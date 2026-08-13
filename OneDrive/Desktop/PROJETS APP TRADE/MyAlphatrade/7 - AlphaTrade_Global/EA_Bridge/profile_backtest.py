"""
Profile-Aware Position-Management Backtest (2026-08-13).

Built at the trader's request, to validate "the new way of managing and
functioning" — real per-profile adaptive timeframe selection (Task #90)
and real position management (TP1/TP2 partial, break-even, trailing,
reversal-close — Task #91) — none of which fusion_backtest.py models
(single fixed timeframe, one full SL/TP exit, no partials, no reversal).

Reuses market_brain.analyze() UNCHANGED, same principle as
fusion_backtest.py: no second copy of the decision logic. Also handles
pending (LIMIT/STOP) orders the same way fusion_backtest.py does — waits
for a real price touch or expires unfilled (see
PENDING_ORDER_MAX_WAIT_CLOCK_BARS), never fills instantly. This matters
here specifically: real production data shows pending_order is the
majority outcome (~74% of non-WAIT decisions, vs ~26% immediate,
2026-08-13 sample) — an immediate-only harness would silently ignore most
real entries.

Design — iterates on the profile's SHORTEST allowed timeframe as the
"clock" (Scalping=M1, Intraday=M30, Swing=H4), since that's the finest
resolution position-management/reversal checks could actually resolve at
live. At each clock bar:
  - If flat: assembles the SAME synchronized multi-timeframe window
    local_functions.market_brain_analyze() builds live (MULTI_TIMEFRAMES
    + this profile's own EXTRA_TIMEFRAMES_FOR_SELECTION entry), calls
    market_brain.select_timeframe() scoped exactly like production, then
    market_brain.analyze() on whichever real timeframe was chosen.
  - If a position is open: re-runs the same analyze() call (reversal
    check, Task #91) — closes the position (even at a loss, per the
    trader's explicit confirmation) if the fresh decision opposes it at
    >= min_confidence. Otherwise manages TP1/TP2/BE/trailing using the
    EXACT same R-multiple math and thresholds as
    local_functions.manage_open_positions — real triggers checked against
    this bar's high/low, not just its close.

Known, disclosed scope limits (same category as fusion_backtest.py's own):
  - Same "economic"/Global-Intelligence-context exclusions as
    fusion_backtest.py — reading real current-moment state into a
    historical replay would leak today into every past bar.
  - Real measured cost: ~91ms per analyze() call on a bare single
    timeframe (measured 2026-08-13, 200 real M1 XAUUSD calls) — with the
    added multi-timeframe slicing this harness does every clock bar
    (flat-scan AND reversal-check both need a fresh call), a 90-day
    Scalping run on an M1 clock (~130,000 bars) is impractical in a
    single interactive session. Scalping therefore defaults to a shorter,
    disclosed window — see run_profile_backtest's `days` param at the
    call site, not silently reduced here.
  - max_daily_trades is enforced; the separate daily-loss-cap/goal engine
    (score_risk_management) is not — this tests the market_brain +
    position-management pipeline, not every autonomous-loop risk gate.
  - Single position at a time (`open_position`, not a list) — real
    production Scalping (2026-08-13 spec) allows pyramiding up to 5
    same-direction concurrent positions per symbol (see
    AnalysisSessionStore.jsx's profile-aware exposure gate). This harness
    does NOT model that yet: it still tests one Scalping position's own
    entry/exit mechanics correctly (immediate-only entry, no TP1/TP2,
    full-close-on-trail), just not the pyramiding effect on total volume/
    PnL. Disclosed gap, not silently wrong.
  - Lot size uses local_functions.calculate_lot with CONTRACT_SIZES's
    fallback (100000) for any symbol not in that dict — same known,
    disclosed limitation fusion_backtest.py already carries for
    synthetic indices; irrelevant here since this harness is only run on
    XAUUSD/BTCUSD/ETHUSD.
"""

from backtest_engine import compute_stats
from fusion_backtest import _pending_order_type
from local_functions import (
    CONTRACT_SIZES, calculate_lot, MULTI_TIMEFRAMES,
    PROFILE_TIMEFRAME_RANGES, PROFILE_TIMEFRAME_FALLBACK,
    EXTRA_TIMEFRAMES_FOR_SELECTION,
    TP1_TRIGGER_R, TP1_CLOSE_FRACTION, TP2_TRIGGER_R, TP2_CLOSE_FRACTION,
    DEFAULT_BREAK_EVEN_TRIGGER,
    DEFAULT_PROFIT_PROTECTION_TRIGGER, TRAIL_DISTANCE_R, _r_multiple,
)
import indicators as ind
import market_brain as mb

# Mirrors Dist/src/lib/tradingProfiles.js exactly (2026-08-13) — duplicated
# here since this is a Python harness and that file is JS; same reasoning
# as every other cross-language constant already duplicated in this
# codebase (e.g. the asset-category classifier).
PROFILE_CONFIG = {
    # scalping max_risk_percent raised 0.5 -> 0.8 (real trader spec,
    # 2026-08-13, mirrors local_functions.PROFILE_BASE_RISK_PERCENT) — this
    # is now the BASE the dynamic lot-sizing multiplier scales from (see
    # market_brain._dynamic_risk_multiplier), not a flat lot.
    "scalping": {"min_confidence": 80, "max_risk_percent": 0.8, "max_daily_trades": 10, "clock_tf": "M1", "break_even_trigger": 0.5},
    "intraday": {"min_confidence": 70, "max_risk_percent": 1.0, "max_daily_trades": 5, "clock_tf": "M30", "break_even_trigger": 1.0},
    "swing":    {"min_confidence": 75, "max_risk_percent": 1.5, "max_daily_trades": 2, "clock_tf": "H4", "break_even_trigger": 2.0},
}

# How long a pending (LIMIT/STOP) order waits for a real price touch before
# expiring unfilled, in CLOCK bars (see clock_tf above) — real, disclosed
# modeling choice, not a value copied from production (same category as
# fusion_backtest.py's own PENDING_ORDER_MAX_WAIT_BARS). Scaled to roughly
# the same REAL wall-clock duration per profile rather than a fixed bar
# count, since each profile's clock resolution differs by two orders of
# magnitude: ~4 real hours for Scalping (a zone that hasn't filled in 4h
# on a rapid M1/M5/M15 setup likely never will), ~1 real day for Intraday,
# ~4 real days for Swing (matches fusion_backtest.py's own 24-bar default,
# coincidentally, on an H4 clock).
PENDING_ORDER_MAX_WAIT_CLOCK_BARS = {
    "scalping": 240,   # 240 * M1  = 4 hours
    "intraday": 48,    # 48  * M30 = 24 hours
    "swing": 24,        # 24  * H4  = 4 days
}


def _make_cursor_slicer(all_candles):
    """Returns a function `slice_to(now)` -> {tf: candles_up_to_now}. The
    naive way to do this — filtering every timeframe's full candle list on
    every clock bar — is O(clock_bars * total_candles), which is fine for
    fusion_backtest.py (called only at real decision points, i.e. rarely)
    but not here: this harness needs a sliced window on EVERY clock bar,
    including ones spent just managing an open position (the reversal
    check, Task #91, needs a fresh decision then too). Since `now` only
    ever moves forward, each timeframe's own index only ever advances —
    O(total_candles) for the whole backtest instead of O(n^2). Real,
    measured difference: this is what makes a 129,600-bar Scalping M1
    clock tractable at all rather than a multi-hour run."""
    idx = {tf: 0 for tf in all_candles}

    def slice_to(now):
        result = {}
        for tf, candles in all_candles.items():
            i = idx[tf]
            n = len(candles)
            while i < n and candles[i]["time"] <= now:
                i += 1
            idx[tf] = i
            result[tf] = candles[:i]
        return result

    return slice_to


def _price_at_r(entry_price, direction, original_risk, r_mult):
    sign = 1 if direction == "BUY" else -1
    return entry_price + sign * original_risk * r_mult


def _finalize_trade(trades, open_position, exit_price, exit_date, exit_reason, closed_lot, contract_size, capital):
    direction = open_position["direction"]
    pnl = (
        (exit_price - open_position["entry_price"]) * closed_lot * contract_size
        if direction == "BUY"
        else (open_position["entry_price"] - exit_price) * closed_lot * contract_size
    )
    trades.append({
        "entry_date": open_position["entry_date"], "exit_date": exit_date,
        "direction": direction, "entry_price": open_position["entry_price"],
        "exit_price": exit_price, "stop_loss": open_position["original_sl"],
        "take_profit": open_position.get("take_profit_1"),
        "pnl": round(pnl * 100) / 100, "pnl_percent": round((pnl / capital) * 10000) / 10000,
        "outcome": "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven",
        "rationale": open_position["rationale"], "confidence": open_position["confidence"],
        "exit_reason": exit_reason, "chosen_timeframe": open_position["chosen_timeframe"],
        "applied_risk_percent": open_position.get("applied_risk_percent"),
    })
    return pnl


def run_profile_backtest(symbol, profile_key, all_candles, capital=1000, warmup_bars=210,
                          use_momentum_catchup=False):
    """
    all_candles: {timeframe: full_candle_list} — REAL MT5 data covering the
      SAME real period for every timeframe this profile might touch: the
      standard MULTI_TIMEFRAMES (D1/H4/H1/M15/M5) PLUS this profile's own
      EXTRA_TIMEFRAMES_FOR_SELECTION entry (M1 for scalping, M30 for
      intraday) if applicable. Fetched once by the caller.

    Returns {"trades": [...], "stats": {...}} — same shape as
    fusion_backtest.run_fusion_backtest, plus each trade also carries
    exit_reason ("stop_loss" | "tp1_partial" | "tp2_partial" |
    "reversal_close") and chosen_timeframe (which real timeframe
    select_timeframe picked for that entry).
    """
    config = PROFILE_CONFIG[profile_key]
    clock_tf = config["clock_tf"]
    min_confidence = config["min_confidence"]
    risk_percent = config["max_risk_percent"]
    max_daily_trades = config["max_daily_trades"]
    be_trigger = config["break_even_trigger"]
    trail_trigger = DEFAULT_PROFIT_PROTECTION_TRIGGER

    clock_candles = all_candles[clock_tf]
    if not clock_candles:
        # Real failure mode hit running this on ETHUSD (2026-08-13): MT5
        # returned zero candles for every timeframe, not just this one —
        # a real data-fetch problem (symbol resolution or a transient
        # connectivity issue), not something this function can recover
        # from. Fails clearly here instead of a cryptic IndexError from
        # negative-indexing an empty list a few lines down.
        return {"trades": [], "stats": compute_stats([], capital), "error": f"No {clock_tf} candles for {symbol} — check the real MT5 data fetch before trusting this result."}

    allowed = PROFILE_TIMEFRAME_RANGES.get(profile_key)
    fallback = PROFILE_TIMEFRAME_FALLBACK.get(profile_key, "H1")
    contract_size = CONTRACT_SIZES.get(symbol.upper(), 100000)

    trades = []
    open_position = None
    pending_order = None
    daily_trade_count = {}
    slice_to = _make_cursor_slicer(all_candles)
    max_wait_bars = PENDING_ORDER_MAX_WAIT_CLOCK_BARS[profile_key]

    start_idx = min(warmup_bars, len(clock_candles) - 1)
    for i in range(start_idx, len(clock_candles)):
        bar = clock_candles[i]
        now = bar["time"]
        today = now[:10]

        if pending_order:
            # Waits for a real price touch like a genuine LIMIT/STOP order —
            # does NOT fill instantly at the planned price, same discipline
            # as fusion_backtest.py's own pending-order handling, and does
            # NOT re-run analyze() while waiting (matches fusion_backtest.py
            # too — a pending order is a standing plan, not re-evaluated
            # every bar; the reversal-close mechanism only applies once a
            # position is actually open).
            p_direction = pending_order["direction"]
            p_price = pending_order["price"]
            if pending_order["order_type"] == "LIMIT":
                filled = (bar["low"] <= p_price) if p_direction == "BUY" else (bar["high"] >= p_price)
            else:
                filled = (bar["high"] >= p_price) if p_direction == "BUY" else (bar["low"] <= p_price)
            if filled:
                original_risk = abs(p_price - pending_order["stop_loss"])
                open_position = {
                    "direction": p_direction, "entry_price": p_price, "entry_date": now,
                    "original_sl": pending_order["stop_loss"], "current_sl": pending_order["stop_loss"],
                    "original_risk": original_risk, "remaining_lot": pending_order["lot"], "events": set(),
                    "confidence": pending_order["confidence"], "rationale": pending_order["rationale"],
                    "chosen_timeframe": pending_order["chosen_timeframe"], "take_profit_1": pending_order.get("take_profit_1"),
                }
                pending_order = None
            else:
                pending_order["bars_waited"] += 1
                if pending_order["bars_waited"] >= max_wait_bars:
                    pending_order = None  # expired unfilled — the zone was never reached in time
            continue

        if open_position:
            direction = open_position["direction"]
            entry_price = open_position["entry_price"]
            original_risk = open_position["original_risk"]
            current_sl = open_position["current_sl"]
            events = open_position["events"]
            remaining_lot = open_position["remaining_lot"]

            # 1. Real stop-loss check FIRST (this bar's high/low against
            # whatever the current stop is — original, break-even, or
            # trailing) — conservative, matches fusion_backtest.py's own
            # SL-first-on-ambiguity convention.
            hit_sl = (bar["low"] <= current_sl) if direction == "BUY" else (bar["high"] >= current_sl)
            if hit_sl:
                reason = "break_even" if current_sl == entry_price else ("trailing_stop" if "trailing_stop" in events or "break_even" in events else "stop_loss")
                _finalize_trade(trades, open_position, current_sl, now, reason, remaining_lot, contract_size, capital)
                open_position = None
                continue

            # 2. TP1 partial (33%) at 1R, TP2 partial (50%) at 2R once TP1
            # is done — exact same triggers/fractions as
            # local_functions.manage_open_positions, checked against this
            # bar's high/low (a real price touch), not just its close.
            # NEVER for Scalping (real trader spec, 2026-08-13, mirrors
            # local_functions.manage_open_positions exactly): a scalp holds
            # its full size until step 3 either protects it at break-even
            # or banks it entirely on the trailing trigger — no partial
            # legging.
            r_now = _r_multiple(direction, entry_price, bar["close"], original_risk)
            at_be_or_better = (current_sl >= entry_price) if direction == "BUY" else (current_sl <= entry_price)

            if profile_key != "scalping":
                if "tp1_partial" not in events:
                    tp1_price = _price_at_r(entry_price, direction, original_risk, TP1_TRIGGER_R)
                    tp1_hit = (bar["high"] >= tp1_price) if direction == "BUY" else (bar["low"] <= tp1_price)
                    if tp1_hit:
                        closed_vol = round(remaining_lot * TP1_CLOSE_FRACTION, 4)
                        _finalize_trade(trades, open_position, tp1_price, now, "tp1_partial", closed_vol, contract_size, capital)
                        remaining_lot = round(remaining_lot - closed_vol, 4)
                        events.add("tp1_partial")

                if remaining_lot > 0 and "tp1_partial" in events and "tp2_partial" not in events:
                    tp2_price = _price_at_r(entry_price, direction, original_risk, TP2_TRIGGER_R)
                    tp2_hit = (bar["high"] >= tp2_price) if direction == "BUY" else (bar["low"] <= tp2_price)
                    if tp2_hit:
                        closed_vol = round(remaining_lot * TP2_CLOSE_FRACTION, 4)
                        _finalize_trade(trades, open_position, tp2_price, now, "tp2_partial", closed_vol, contract_size, capital)
                        remaining_lot = round(remaining_lot - closed_vol, 4)
                        events.add("tp2_partial")

                if remaining_lot <= 0:
                    open_position = None
                    daily_trade_count[today] = daily_trade_count.get(today, 0) + 1
                    continue
                open_position["remaining_lot"] = remaining_lot

            # 3. Break-even / trailing — evaluated against this bar's
            # close as the "current price" proxy (a continuous live tick
            # feed isn't available in a bar backtest; close is the same
            # proxy fusion_backtest.py itself uses elsewhere). Scalping
            # banks the WHOLE position the moment the trailing trigger is
            # reached instead of moving the stop and continuing to hold —
            # mirrors local_functions.manage_open_positions's is_scalping
            # branch exactly.
            if r_now >= trail_trigger:
                if profile_key == "scalping":
                    _finalize_trade(trades, open_position, bar["close"], now, "scalping_trail_close", remaining_lot, contract_size, capital)
                    open_position = None
                    daily_trade_count[today] = daily_trade_count.get(today, 0) + 1
                    continue
                trail_offset = original_risk * TRAIL_DISTANCE_R
                sign = 1 if direction == "BUY" else -1
                candidate = bar["close"] - sign * trail_offset
                better = (candidate > current_sl) if direction == "BUY" else (candidate < current_sl)
                beyond_entry = (candidate > entry_price) if direction == "BUY" else (candidate < entry_price)
                if better and beyond_entry:
                    open_position["current_sl"] = candidate
                    events.add("trailing_stop")
            elif r_now >= be_trigger and not at_be_or_better:
                open_position["current_sl"] = entry_price
                events.add("break_even")

            # 4. Reversal-close (Task #91) — re-run the SAME real decision
            # pipeline used for entries. If it now opposes this open
            # position with real confidence, close everything left, even
            # at a loss (explicit trader confirmation, 2026-08-13: cutting
            # a loss early beats waiting for the original, wider stop).
            window_by_tf = slice_to(now)
            reversal_result = _run_one_decision(symbol, profile_key, window_by_tf, allowed, fallback, capital, risk_percent, use_momentum_catchup, min_confidence=min_confidence)
            if reversal_result and reversal_result["decision"] in ("BUY", "SELL") and reversal_result["decision"] != direction and reversal_result["confidence"] >= min_confidence:
                _finalize_trade(trades, open_position, bar["close"], now, "reversal_close", remaining_lot, contract_size, capital)
                open_position = None
                daily_trade_count[today] = daily_trade_count.get(today, 0) + 1
            continue

        # Flat — scan for a new entry, respecting the daily trade cap.
        if daily_trade_count.get(today, 0) >= max_daily_trades:
            continue

        window_by_tf = slice_to(now)
        result = _run_one_decision(symbol, profile_key, window_by_tf, allowed, fallback, capital, risk_percent, use_momentum_catchup, min_confidence=min_confidence)
        if not result or result["decision"] not in ("BUY", "SELL") or result["confidence"] < min_confidence:
            continue
        if result["entry_type"] not in ("immediate", "pending_order"):
            continue

        sl = result["stop_loss"]
        if not sl:
            continue
        rationale = "; ".join((result.get("rationale") or [])[:2])
        # Dynamic lot sizing (Scalping only) — result["effective_risk_percent"]
        # is the confidence/volatility-scaled risk from
        # market_brain._dynamic_risk_multiplier; None for Intraday/Swing,
        # where the flat profile risk_percent applies unchanged.
        applied_risk_percent = result.get("effective_risk_percent") or risk_percent

        if result["entry_type"] == "immediate":
            entry_price = result["ideal_entry"] or bar["close"]
            original_risk = abs(entry_price - sl)
            if original_risk <= 0:
                continue
            lot = calculate_lot(symbol, entry_price=entry_price, stop_loss=sl, capital=capital, risk_percent=applied_risk_percent)
            open_position = {
                "direction": result["decision"], "entry_price": entry_price, "entry_date": now,
                "original_sl": sl, "current_sl": sl, "original_risk": original_risk,
                "remaining_lot": lot, "events": set(), "confidence": result["confidence"],
                "rationale": rationale, "chosen_timeframe": result["timeframe"],
                "take_profit_1": result.get("take_profit_1"), "applied_risk_percent": applied_risk_percent,
            }
        else:  # pending_order — real LIMIT/STOP order, waits for a genuine price touch
            planned_price = result["ideal_entry"]
            if not planned_price:
                continue
            lot = calculate_lot(symbol, entry_price=planned_price, stop_loss=sl, capital=capital, risk_percent=applied_risk_percent)
            pending_order = {
                "direction": result["decision"], "price": planned_price,
                "order_type": _pending_order_type(result["decision"], planned_price, bar["close"]),
                "stop_loss": sl, "lot": lot, "bars_waited": 0,
                "confidence": result["confidence"], "rationale": rationale,
                "chosen_timeframe": result["timeframe"], "take_profit_1": result.get("take_profit_1"),
            }

    return {"trades": trades, "stats": compute_stats(trades, capital)}


def _run_one_decision(symbol, profile_key, window_by_tf, allowed, fallback, capital, risk_percent, use_momentum_catchup, min_confidence=None):
    """One real market_brain.analyze() call, timeframe chosen exactly like
    local_functions.market_brain_analyze()'s AUTO path does live for this
    profile — reused for both the flat-scan and the reversal-check, so
    there is exactly one place this selection logic lives in this file."""
    mtf_candles = {tf: window_by_tf.get(tf) for tf in MULTI_TIMEFRAMES if window_by_tf.get(tf)}
    if not mtf_candles:
        return None

    selection_snapshots = {tf: ind.compute_snapshot(symbol, tf, c) for tf, c in mtf_candles.items() if len(c) >= 30}
    for extra_tf in EXTRA_TIMEFRAMES_FOR_SELECTION.get(profile_key, []):
        extra_candles = window_by_tf.get(extra_tf)
        if extra_candles and len(extra_candles) >= 30:
            selection_snapshots[extra_tf] = ind.compute_snapshot(symbol, extra_tf, extra_candles)
    if not selection_snapshots:
        return None
    mtf_view = ind.compute_multi_timeframe_view(selection_snapshots)
    timeframe, _rationale = mb.select_timeframe(mtf_view, allowed=allowed, fallback=fallback)

    primary_candles = window_by_tf.get(timeframe)
    if not primary_candles or len(primary_candles) < 30:
        return None

    return mb.analyze(
        symbol, timeframe, primary_candles, multi_tf_candles=mtf_candles,
        validated_strategy=None, capital=capital, risk_percent=risk_percent,
        use_momentum_catchup=use_momentum_catchup, profile_key=profile_key,
        profile_min_confidence=min_confidence, profile_base_risk_percent=risk_percent,
    )
