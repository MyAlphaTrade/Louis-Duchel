"""
Fusion Engine Validation — Module 5 of the 2026-08-06 professional
transformation plan, built ahead of Module 4 (Auto Optimization Lab)
because that one needs this harness to measure whether a change is an
improvement at all.

Real gap this closes: backtest_engine.py validates 4 standalone coded
strategies (Trend Following, Mean Reversion, Breakout Structure, Smart
Money+Fibonacci) — none of which is what actually decides in production.
The real decision-maker is market_brain.analyze(), the weighted fusion of
13 engines (engine_scoring.py), and until this file, it had never been
replayed over historical data as a whole system — only the fusion FORMULA
and the confidence FLOOR were calibrated manually, once, on a single
90-day XAUUSD H1 window (see Audit/Replay_Reel_XAUUSD_...).

This module reuses market_brain.analyze() UNCHANGED — the exact function
that runs in production — bar by bar, rather than re-implementing the
decision logic. If analyze() changes, this backtest automatically reflects
that change; there is no second copy of the fusion logic to keep in sync.

Known, disclosed scope limits — not silently ignored:
  - "economic" is excluded from the fusion for the whole backtest run.
    score_economic() reads real calendar proximity to *right now* — replaying
    it historically would leak today's actual news calendar into every past
    bar. Its weight (6) is simply absent from total_weight, the same way
    "microstructure" is already correctly absent for non-crypto symbols in
    production (see engine_scoring.py's own comment on that).
  - The Global Market Intelligence context (crypto regime / macro risk-on-off
    supplement) is force-disabled for the duration of the run — it reads the
    single most recent CryptoIntelSnapshot in the local DB, not a historical
    one, which is the same kind of leak.
  - validated_strategy is never passed (always None) — this harness tests
    the 12-engine fusion on its own merits, not the additional supplement
    from a separately-validated Strategy record.
  - Not thread-safe against a concurrently-running live analysis session:
    both temporarily mutate the same module-level state (ENGINE_SCORERS,
    CRYPTO_CONTEXT_ENABLED) for the duration of the run. Don't run a fusion
    backtest while the app's own autonomous session is active.
"""

import engine_scoring as es
import market_brain
from backtest_engine import compute_stats
from local_functions import CONTRACT_SIZES, calculate_lot

MULTI_TIMEFRAMES = ["D1", "H4", "H1", "M15", "M5"]

# A pending order that never gets touched shouldn't wait forever — real
# trading has the same expectation (the frontend's own Signal.expires_at is
# 30 minutes; MT5 pending orders are typically given a GTC-but-monitored
# lifetime, not literally infinite). No exact rule exists in the live code
# to mirror here, so this is a disclosed modeling choice, not a value
# copied from production: ~1 trading day on an hourly primary timeframe.
PENDING_ORDER_MAX_WAIT_BARS = 24


def _slice_up_to(candles, cutoff_time):
    """Every candle with time <= cutoff_time — what would genuinely have
    been visible at that moment. String comparison is safe here: every
    timestamp in this codebase is ISO-8601, which sorts lexicographically
    in chronological order."""
    return [c for c in candles if c["time"] <= cutoff_time]


def _pending_order_type(direction, pending_price, price_at_placement):
    """Mirrors alphatg_bridge.py's /send_pending_order classification
    exactly: LIMIT waits for a BETTER price than when planned, STOP waits
    for a BREAKOUT past a worse one."""
    if direction == "BUY":
        return "LIMIT" if pending_price < price_at_placement else "STOP"
    return "LIMIT" if pending_price > price_at_placement else "STOP"


def run_fusion_backtest(symbol, primary_timeframe, primary_candles, mtf_candles=None,
                         capital=1000, risk_percent=1, warmup_bars=210, use_regime_modulation=False):
    """Replays the real market_brain.analyze() pipeline bar by bar.

    primary_candles: full historical candle list for `primary_timeframe`,
      oldest→newest, real MT5 data.
    mtf_candles: optional {timeframe: candles} covering the SAME real period
      (see MULTI_TIMEFRAMES) — omit to run without the multi_timeframe
      engine (its weight is then absent from the fusion for this run,
      same principle as "economic" above, rather than a fake neutral vote).
    warmup_bars: bars used only as history before the first decision point —
      EMA200/swing-detection need real lookback to mean anything; too small
      a warmup just wastes cycles on bars that would score low-confidence
      WAIT anyway, it doesn't affect correctness (every engine already
      degrades gracefully — lower confidence, explicit "historique
      insuffisant" findings — rather than crashing on too little history).
    use_regime_modulation: OFF by default — passed straight through to
      market_brain.analyze(). This is the exact harness used to run the
      real walk-forward comparison (commit 7a6108f, 2026-08-07): net -37%
      PnL with modulation on, across 3 real assets x 3 real 90-day windows.
      Stays False in every live/default call site.

    Returns {"trades": [...], "stats": {...}} — same shape as
    backtest_engine.run_backtest(), stats now include expectancy.
    """
    original_economic = es.ENGINE_SCORERS.pop("economic", None)
    original_kill_switch = market_brain.CRYPTO_CONTEXT_ENABLED
    market_brain.CRYPTO_CONTEXT_ENABLED = False
    try:
        contract_size = CONTRACT_SIZES.get(symbol.upper(), 100000)
        trades = []
        open_position = None
        pending_order = None  # {direction, price, order_type, stop_loss, take_profit, lot, bars_waited, confidence, rationale}

        for i in range(min(warmup_bars, len(primary_candles) - 1), len(primary_candles)):
            window = primary_candles[: i + 1]
            bar = primary_candles[i]

            if open_position:
                direction = open_position["direction"]
                sl, tp = open_position["stop_loss"], open_position["take_profit"]
                hit_sl = bar["low"] <= sl if direction == "BUY" else bar["high"] >= sl
                hit_tp = bar["high"] >= tp if direction == "BUY" else bar["low"] <= tp
                if hit_sl or hit_tp:
                    # SL-first on an ambiguous same-bar hit — the same
                    # conservative convention as backtest_engine.py, for the
                    # same reason: OHLC bars can't tell us which was
                    # actually touched first intrabar.
                    exit_price = sl if hit_sl else tp
                    lot = open_position["lot"]
                    pnl = (
                        (exit_price - open_position["entry_price"]) * lot * contract_size
                        if direction == "BUY"
                        else (open_position["entry_price"] - exit_price) * lot * contract_size
                    )
                    trades.append({
                        "entry_date": open_position["entry_date"],
                        "exit_date": bar["time"],
                        "direction": direction,
                        "entry_price": open_position["entry_price"],
                        "exit_price": exit_price,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "pnl": round(pnl * 100) / 100,
                        "pnl_percent": round((pnl / capital) * 10000) / 10000,
                        "outcome": "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven",
                        "rationale": open_position["rationale"],
                        "confidence": open_position["confidence"],
                    })
                    open_position = None
                continue  # one position at a time, same discipline as backtest_engine.py

            if pending_order:
                # A pending_order decision does NOT fill instantly at the
                # planned price on the same bar it was decided — that would
                # silently assume a perfect fill and inflate results exactly
                # the way a naive backtest is accused of doing. It waits like
                # a real LIMIT/STOP order until price actually reaches it, or
                # expires unfilled.
                direction = pending_order["direction"]
                price = pending_order["price"]
                if pending_order["order_type"] == "LIMIT":
                    filled = bar["low"] <= price if direction == "BUY" else bar["high"] >= price
                else:
                    filled = bar["high"] >= price if direction == "BUY" else bar["low"] <= price
                if filled:
                    open_position = {
                        "direction": direction, "entry_price": price, "entry_date": bar["time"],
                        "stop_loss": pending_order["stop_loss"], "take_profit": pending_order["take_profit"],
                        "lot": pending_order["lot"], "confidence": pending_order["confidence"],
                        "rationale": pending_order["rationale"],
                    }
                    pending_order = None
                else:
                    pending_order["bars_waited"] += 1
                    if pending_order["bars_waited"] >= PENDING_ORDER_MAX_WAIT_BARS:
                        pending_order = None  # expired unfilled — the zone was never reached in time
                continue

            window_mtf = None
            if mtf_candles:
                window_mtf = {tf: _slice_up_to(c, bar["time"]) for tf, c in mtf_candles.items()}
                window_mtf = {tf: c for tf, c in window_mtf.items() if c}

            result = market_brain.analyze(
                symbol, primary_timeframe, window,
                multi_tf_candles=window_mtf, validated_strategy=None,
                capital=capital, risk_percent=risk_percent,
                use_regime_modulation=use_regime_modulation,
            )

            decision = result["decision"]
            entry_type = result["entry_type"]
            if decision == "WAIT" or entry_type not in ("immediate", "pending_order"):
                continue

            sl = result["stop_loss"]
            tp = result["take_profit_1"]
            if not sl or not tp:
                continue
            rationale = "; ".join((result.get("rationale") or [])[:2])

            if entry_type == "immediate":
                entry_price = result["ideal_entry"] or bar["close"]
                lot = calculate_lot(symbol, entry_price=entry_price, stop_loss=sl, capital=capital, risk_percent=risk_percent)
                open_position = {
                    "direction": decision, "entry_price": entry_price, "entry_date": bar["time"],
                    "stop_loss": sl, "take_profit": tp, "lot": lot,
                    "confidence": result["confidence"], "rationale": rationale,
                }
            else:  # pending_order
                planned_price = result["ideal_entry"]
                if not planned_price:
                    continue
                lot = calculate_lot(symbol, entry_price=planned_price, stop_loss=sl, capital=capital, risk_percent=risk_percent)
                pending_order = {
                    "direction": decision, "price": planned_price,
                    "order_type": _pending_order_type(decision, planned_price, bar["close"]),
                    "stop_loss": sl, "take_profit": tp, "lot": lot, "bars_waited": 0,
                    "confidence": result["confidence"], "rationale": rationale,
                }

        return {"trades": trades, "stats": compute_stats(trades, capital)}
    finally:
        market_brain.CRYPTO_CONTEXT_ENABLED = original_kill_switch
        if original_economic is not None:
            es.ENGINE_SCORERS["economic"] = original_economic
