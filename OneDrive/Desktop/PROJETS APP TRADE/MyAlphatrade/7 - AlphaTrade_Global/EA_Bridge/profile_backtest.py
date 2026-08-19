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
  - FIXED 2026-08-18 (was: single position at a time, disclosed gap since
    2026-08-13) — `run_profile_backtest` now takes `max_concurrent_positions`
    (default 1, so every prior result in this session stays reproducible
    unchanged) and tracks a real list of open positions, mirroring
    AnalysisSessionStore.jsx's own exposure gate (up to 5 same-direction
    for Scalping, 2 for Intraday/Swing in production) instead of silently
    understating real live throughput.
  - FIXED 2026-08-19 (was: Scalping trades only ever checked stop_loss
    for an exit, never take_profit — a real, undisclosed modeling gap
    found while investigating Louis's own observation about a real 48$
    Scalping TP) — Scalping positions now also check a real touch of
    take_profit_1 (see the "1b." step in run_profile_backtest's loop),
    matching the real resting "tp" order /send_order sets at MT5, which
    manage_open_positions() never modifies after entry. Every PRIOR
    Scalping result in this session was produced WITHOUT this check —
    re-running the exact same inputs after this fix can shift $ figures
    (a trade that used to only ever exit via SL/BE/quick-lock can now also
    exit at take_profit_1), disclosed here rather than silently.
  - Lot size uses local_functions.calculate_lot with CONTRACT_SIZES's
    fallback (100000) for any symbol not in that dict — same known,
    disclosed limitation fusion_backtest.py already carries for
    synthetic indices; irrelevant here since this harness is only run on
    XAUUSD/BTCUSD/ETHUSD.
"""

import math

from backtest_engine import compute_stats
from fusion_backtest import _pending_order_type
from local_functions import (
    calculate_lot, resolve_contract_size, MULTI_TIMEFRAMES,
    PROFILE_TIMEFRAME_RANGES, PROFILE_TIMEFRAME_FALLBACK,
    EXTRA_TIMEFRAMES_FOR_SELECTION,
    TP1_TRIGGER_R, TP1_CLOSE_FRACTION, TP2_TRIGGER_R, TP2_CLOSE_FRACTION,
    DEFAULT_BREAK_EVEN_TRIGGER,
    DEFAULT_PROFIT_PROTECTION_TRIGGER, TRAIL_DISTANCE_R, _r_multiple,
    BREAK_EVEN_TRIGGER_USD, BREAK_EVEN_BUFFER_USD,
    QUICK_PROFIT_LOCK_USD, QUICK_PROFIT_TRAIL_DISTANCE_R,
)
import indicators as ind
import market_brain as mb

# 2026-08-15 — testing candidate (Louis's proposal): the "dead zone"
# between BREAK_EVEN_TRIGGER_USD (1.5$) and QUICK_PROFIT_LOCK_USD (15$)
# locks the stop ONCE at entry+BREAK_EVEN_BUFFER_USD and leaves it flat no
# matter how much further real profit builds before a pullback — a trade
# that reaches 10$ then reverses still only banks 0.5$. Sound reasoning,
# but REAL RESULT (XAUUSD Scalping, ~4.5 real M1 days, same session as
# the widened quick-lock above): pnl 78.80 -> 31.91 (-59%), avg_win 2.54
# -> 1.67, ratio 0.62 -> 0.41, trades reaching quick_profit_lock 7 -> 1.
# INVALIDATED — raising the stop this early, even gradually, gives real
# trades less room to breathe before reaching the (now-widened) 15$
# lock zone; most get stopped out by ordinary noise before they can
# develop into the bigger wins the flat BE + wide lock combo allows.
# Same verdict class as RSI-for-gold and abstention-for-ETH the same day:
# intuitive, invalidated by real data. Stays False; kept as a tested,
# documented, inactive capability — never mirrored into local_functions.py.
BE_RATCHET_ENABLED = False
BE_RATCHET_STEP_USD = 2.0       # every extra $2 of real profit past the BE trigger...
BE_RATCHET_LOCK_FRACTION = 0.5  # ...locks in half of that extra step (monotonic, never moves back down)

# 2026-08-15 — second variant of the same idea, per Louis's own clarified
# example: "si le prix va de 10$ à 20$... au lieu de reprendre 1.5$ à
# cause du BE initial, on pourrait prendre 10$" — a CONTINUOUS fraction of
# the real peak profit reached, not the discrete $2 steps above (which
# were shown to tighten too early/too often and cut trades short before
# they could grow). This locks proportionally to whatever peak is
# actually reached — a 20$ peak locks 10$ (50%), an 8$ peak locks 4$ —
# while never tightening MORE aggressively than that single ratio,
# unlike the stepped version. Still gated separately (BE_RATCHET_ENABLED
# must stay False when this is True — see the loop below) so both can be
# A/B tested independently. Not yet proven — test before trusting.
BE_TRAIL_PEAK_ENABLED = False
BE_TRAIL_PEAK_FRACTION = 0.5    # lock this fraction of the real peak profit reached, continuously

# Mirrors Dist/src/lib/tradingProfiles.js exactly (2026-08-13) — duplicated
# here since this is a Python harness and that file is JS; same reasoning
# as every other cross-language constant already duplicated in this
# codebase (e.g. the asset-category classifier).
PROFILE_CONFIG = {
    # scalping max_risk_percent raised 0.5 -> 0.8 (real trader spec,
    # 2026-08-13, mirrors local_functions.PROFILE_BASE_RISK_PERCENT) — this
    # is now the BASE the dynamic lot-sizing multiplier scales from (see
    # market_brain._dynamic_risk_multiplier), not a flat lot.
    # max_daily_trades: None for scalping (2026-08-14, real trader spec —
    # Louis: "pas de limite pour le mode scalping, l'objectif par jour est
    # le gain plafonné") — no trade-count cap; the real daily governor is
    # the $ daily-goal engine (score_risk_management/dailyGoalStatus),
    # which this harness doesn't model either (see this file's own
    # disclosed scope-limit comment above). None is handled explicitly
    # below (no comparison against it), never silently treated as 0.
    "scalping": {"min_confidence": 80, "max_risk_percent": 0.8, "max_daily_trades": None, "clock_tf": "M1", "break_even_trigger": 0.5},
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
        "max_favorable_r": round(open_position.get("max_favorable_r", 0.0), 3),
    })
    return pnl


def run_profile_backtest(symbol, profile_key, all_candles, capital=1000, warmup_bars=210,
                          use_momentum_catchup=False, max_concurrent_positions=1, scalping_tp_mult=None):
    """
    scalping_tp_mult: None (default, unchanged 3.0/5.0 ATR TP multiples) |
      (tp1_mult, tp2_mult) tuple — forwarded to market_brain.analyze(), see
      its own docstring. 2026-08-19 real test (Louis): the Scalping TP was
      never profile-tuned like break-even/quick-profit-lock were, and a
      real live trade showed a 48$ TP1 — far past QUICK_PROFIT_LOCK_USD
      (15$), which in practice already tightens the stop first. Combined
      with the take_profit-touch check added to this harness the same day
      (see the "1b." step below), this lets a tighter TP be A/B tested on
      equal footing against the current default.

    all_candles: {timeframe: full_candle_list} — REAL MT5 data covering the
      SAME real period for every timeframe this profile might touch: the
      standard MULTI_TIMEFRAMES (D1/H4/H1/M15/M5) PLUS this profile's own
      EXTRA_TIMEFRAMES_FOR_SELECTION entry (M1 for scalping, M30 for
      intraday) if applicable. Fetched once by the caller.

    max_concurrent_positions: 2026-08-18, real request (Louis) — the live
      app already pyramids same-direction positions (AnalysisSessionStore.jsx,
      Task #98/#103: up to 5 for Scalping, 2 for Intraday/Swing), re-
      confirming each addition with a fresh >= min_confidence decision, but
      this backtest harness stayed single-position (disclosed limitation
      since its creation, 2026-08-13) — every $/day figure produced by it
      therefore UNDERSTATES real live throughput. Defaults to 1 (byte-
      identical to the old single-position behavior) so every existing
      call site and every already-validated result in this session is
      unaffected unless a caller explicitly asks for more. Mirrors the
      live exposure gate exactly: a same-direction signal is added if
      the count of open same-direction positions is still under this
      limit; an OPPOSING signal blocks entirely (no reversal-close for
      Scalping — see the module-level comment near BE_RATCHET_ENABLED —
      so it just waits for the existing position(s) to close on their own
      stop/BE/TP first, exactly like live).

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
    contract_size = resolve_contract_size(symbol)

    trades = []
    open_positions = []  # list, not a single dict — see max_concurrent_positions above
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
                open_positions.append({
                    "direction": p_direction, "entry_price": p_price, "entry_date": now,
                    "original_sl": pending_order["stop_loss"], "current_sl": pending_order["stop_loss"],
                    "original_risk": original_risk, "remaining_lot": pending_order["lot"], "events": set(),
                    "confidence": pending_order["confidence"], "rationale": pending_order["rationale"],
                    "chosen_timeframe": pending_order["chosen_timeframe"], "take_profit_1": pending_order.get("take_profit_1"),
                    "max_favorable_r": 0.0,
                })
                pending_order = None
            else:
                pending_order["bars_waited"] += 1
                if pending_order["bars_waited"] >= max_wait_bars:
                    pending_order = None  # expired unfilled — the zone was never reached in time
            continue

        # Manage every open position independently (0..max_concurrent_positions
        # of them). With max_concurrent_positions=1 this loop body runs at
        # most once per bar — byte-identical outcome to the old single-
        # position code it replaces.
        still_open = []
        reversal_result = None  # computed at most once per bar, shared across positions (same symbol/profile)
        reversal_checked = False
        for pos in open_positions:
            direction = pos["direction"]
            entry_price = pos["entry_price"]
            original_risk = pos["original_risk"]
            current_sl = pos["current_sl"]
            events = pos["events"]
            remaining_lot = pos["remaining_lot"]
            closed = False

            # 0. Max favorable excursion (diagnostic only) — see original
            # rationale, unchanged, just per-position now.
            favorable_r_this_bar = _r_multiple(direction, entry_price, bar["high"] if direction == "BUY" else bar["low"], original_risk)
            if favorable_r_this_bar > pos["max_favorable_r"]:
                pos["max_favorable_r"] = favorable_r_this_bar

            # 1. Real stop-loss check FIRST — unchanged.
            hit_sl = (bar["low"] <= current_sl) if direction == "BUY" else (bar["high"] >= current_sl)
            if hit_sl:
                if "quick_profit_lock" in events:
                    reason = "quick_profit_lock"
                elif "trailing_stop" in events:
                    reason = "trailing_stop"
                elif "break_even" in events:
                    reason = "break_even"
                else:
                    reason = "stop_loss"
                _finalize_trade(trades, pos, current_sl, now, reason, remaining_lot, contract_size, capital)
                closed = True

            # 1b. Real broker-side take-profit touch — Scalping only.
            # 2026-08-19, real gap found (Louis's own observation about a
            # real 48$ Scalping TP): this harness used to check ONLY the
            # stop-loss for Scalping trades, never the take_profit — but in
            # live trading /send_order DOES set a real resting "tp" on the
            # broker (see alphatg_bridge.py), and manage_open_positions()
            # only ever modifies stop_loss, never take_profit, so that wide
            # ATR-based level stays live at MT5 for the trade's whole life.
            # A backtest that never checks it silently overstated how often
            # Scalping trades "ride the trailing stop" vs. actually banking
            # at the far TP — this closes that gap so scalping_tp_mult (see
            # run_profile_backtest) can be tested on equal footing against
            # the CURRENT (untuned) 3.0/5.0 ATR default, not against a
            # baseline that was never modeling the real broker-side order.
            if not closed and profile_key == "scalping" and pos.get("take_profit_1"):
                tp_price = pos["take_profit_1"]
                tp_hit = (bar["high"] >= tp_price) if direction == "BUY" else (bar["low"] <= tp_price)
                if tp_hit:
                    _finalize_trade(trades, pos, tp_price, now, "take_profit", remaining_lot, contract_size, capital)
                    daily_trade_count[today] = daily_trade_count.get(today, 0) + 1
                    closed = True

            # 2. TP1/TP2 partials — NEVER for Scalping, unchanged rationale.
            if not closed and profile_key != "scalping":
                if "tp1_partial" not in events:
                    tp1_price = _price_at_r(entry_price, direction, original_risk, TP1_TRIGGER_R)
                    tp1_hit = (bar["high"] >= tp1_price) if direction == "BUY" else (bar["low"] <= tp1_price)
                    if tp1_hit:
                        closed_vol = round(remaining_lot * TP1_CLOSE_FRACTION, 4)
                        _finalize_trade(trades, pos, tp1_price, now, "tp1_partial", closed_vol, contract_size, capital)
                        remaining_lot = round(remaining_lot - closed_vol, 4)
                        events.add("tp1_partial")

                if remaining_lot > 0 and "tp1_partial" in events and "tp2_partial" not in events:
                    tp2_price = _price_at_r(entry_price, direction, original_risk, TP2_TRIGGER_R)
                    tp2_hit = (bar["high"] >= tp2_price) if direction == "BUY" else (bar["low"] <= tp2_price)
                    if tp2_hit:
                        closed_vol = round(remaining_lot * TP2_CLOSE_FRACTION, 4)
                        _finalize_trade(trades, pos, tp2_price, now, "tp2_partial", closed_vol, contract_size, capital)
                        remaining_lot = round(remaining_lot - closed_vol, 4)
                        events.add("tp2_partial")

                if remaining_lot <= 0:
                    daily_trade_count[today] = daily_trade_count.get(today, 0) + 1
                    closed = True
                else:
                    pos["remaining_lot"] = remaining_lot

            # 3. Break-even / trailing / quick-profit-lock — unchanged logic,
            # per-position.
            if not closed:
                favorable_price = bar["high"] if direction == "BUY" else bar["low"]
                at_be_or_better = (current_sl >= entry_price) if direction == "BUY" else (current_sl <= entry_price)
                sign = 1 if direction == "BUY" else -1

                if profile_key == "scalping":
                    profit_usd = (
                        (favorable_price - entry_price) * remaining_lot * contract_size
                        if direction == "BUY"
                        else (entry_price - favorable_price) * remaining_lot * contract_size
                    )
                    if profit_usd >= QUICK_PROFIT_LOCK_USD:
                        tight_offset = original_risk * QUICK_PROFIT_TRAIL_DISTANCE_R
                        candidate = favorable_price - sign * tight_offset
                        better = (candidate > current_sl) if direction == "BUY" else (candidate < current_sl)
                        if better:
                            pos["current_sl"] = candidate
                            events.add("quick_profit_lock")
                    elif profit_usd >= BREAK_EVEN_TRIGGER_USD and remaining_lot > 0:
                        if BE_TRAIL_PEAK_ENABLED:
                            locked_profit_usd = max(BREAK_EVEN_BUFFER_USD, profit_usd * BE_TRAIL_PEAK_FRACTION)
                            offset = locked_profit_usd / (remaining_lot * contract_size)
                            candidate = entry_price + sign * offset
                            better = (candidate > current_sl) if direction == "BUY" else (candidate < current_sl)
                            if better:
                                pos["current_sl"] = candidate
                                events.add("break_even_trail_peak")
                        elif BE_RATCHET_ENABLED:
                            steps = math.floor((profit_usd - BREAK_EVEN_TRIGGER_USD) / BE_RATCHET_STEP_USD)
                            locked_profit_usd = BREAK_EVEN_BUFFER_USD + max(0, steps) * BE_RATCHET_STEP_USD * BE_RATCHET_LOCK_FRACTION
                            offset = locked_profit_usd / (remaining_lot * contract_size)
                            candidate = entry_price + sign * offset
                            better = (candidate > current_sl) if direction == "BUY" else (candidate < current_sl)
                            if better:
                                pos["current_sl"] = candidate
                                events.add("break_even_ratchet" if steps > 0 else "break_even")
                        elif not at_be_or_better:
                            buffer_offset = BREAK_EVEN_BUFFER_USD / (remaining_lot * contract_size)
                            pos["current_sl"] = entry_price + sign * buffer_offset
                            events.add("break_even")
                    # Scalping never reversal-closes (real live spec,
                    # 2026-08-15 — mirrors AnalysisSessionStore.jsx's own
                    # `profile.key !== 'scalping'` gate exactly): no
                    # analyze() call needed here at all, pure price math.
                else:
                    r_now = _r_multiple(direction, entry_price, favorable_price, original_risk)
                    if r_now >= trail_trigger:
                        trail_offset = original_risk * TRAIL_DISTANCE_R
                        candidate = favorable_price - sign * trail_offset
                        better = (candidate > current_sl) if direction == "BUY" else (candidate < current_sl)
                        beyond_entry = (candidate > entry_price) if direction == "BUY" else (candidate < entry_price)
                        if better and beyond_entry:
                            pos["current_sl"] = candidate
                            events.add("trailing_stop")
                    elif r_now >= be_trigger and not at_be_or_better:
                        pos["current_sl"] = entry_price
                        events.add("break_even")

                    # 4. Reversal-close (Task #91) — one fresh decision per
                    # bar covers every open position on this symbol (they're
                    # all the same instrument/profile), computed once and
                    # reused rather than once per position.
                    if not reversal_checked:
                        reversal_checked = True
                        reversal_result = _run_one_decision(symbol, profile_key, slice_to(now), allowed, fallback, capital, risk_percent, use_momentum_catchup, min_confidence=min_confidence, scalping_tp_mult=scalping_tp_mult)
                    if reversal_result and reversal_result["decision"] in ("BUY", "SELL") and reversal_result["decision"] != direction and reversal_result["confidence"] >= min_confidence:
                        _finalize_trade(trades, pos, bar["close"], now, "reversal_close", remaining_lot, contract_size, capital)
                        daily_trade_count[today] = daily_trade_count.get(today, 0) + 1
                        closed = True

            if not closed:
                still_open.append(pos)

        open_positions = still_open

        # Scan for a new entry — always attempted (not just when flat), so
        # a same-direction reinforcement can be added on top of already-open
        # positions, exactly like live. Still respects the daily trade cap.
        if max_daily_trades is not None and daily_trade_count.get(today, 0) >= max_daily_trades:
            continue

        window_by_tf = slice_to(now)
        result = _run_one_decision(symbol, profile_key, window_by_tf, allowed, fallback, capital, risk_percent, use_momentum_catchup, min_confidence=min_confidence, scalping_tp_mult=scalping_tp_mult)
        if not result or result["decision"] not in ("BUY", "SELL") or result["confidence"] < min_confidence:
            continue
        if result["entry_type"] not in ("immediate", "pending_order"):
            continue

        # Exposure gate — mirrors AnalysisSessionStore.jsx's `alreadyExposed`
        # exactly: an OPPOSING open position blocks entirely (Scalping never
        # reversal-closes anymore, so it just waits for the existing
        # position(s) to close on their own); same-direction is allowed
        # until max_concurrent_positions is reached. A pending order on this
        # symbol also blocks (never stacks a plan on top of a plan).
        same_direction_count = sum(1 for p in open_positions if p["direction"] == result["decision"])
        opposing_count = len(open_positions) - same_direction_count
        if opposing_count > 0 or same_direction_count >= max_concurrent_positions or pending_order:
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
            open_positions.append({
                "direction": result["decision"], "entry_price": entry_price, "entry_date": now,
                "original_sl": sl, "current_sl": sl, "original_risk": original_risk,
                "remaining_lot": lot, "events": set(), "confidence": result["confidence"],
                "rationale": rationale, "chosen_timeframe": result["timeframe"],
                "take_profit_1": result.get("take_profit_1"), "applied_risk_percent": applied_risk_percent,
                "max_favorable_r": 0.0,
            })
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


def _run_one_decision(symbol, profile_key, window_by_tf, allowed, fallback, capital, risk_percent, use_momentum_catchup, min_confidence=None, scalping_tp_mult=None):
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
        use_momentum_catchup=use_momentum_catchup,
        use_zone_only_fusion=True,  # mirrors the real live call site (local_functions.market_brain_analyze) —
        # XAUUSD + BTCUSD, see market_brain.analyze's docstring. Kept in sync so this harness never silently
        # diverges from what the live app actually does.
        profile_key=profile_key,
        profile_min_confidence=min_confidence, profile_base_risk_percent=risk_percent,
        scalping_tp_mult=scalping_tp_mult,
    )
