"""
Market Regime AI — Module 6 of the professional transformation plan.

Classifies THIS instrument's own current technical regime — trending up,
trending down, ranging, or in transition — plus a separate volatility read
(expansion/compression/normal), from real price action already computed
elsewhere in this codebase (EMA slope, ATR, BOS/CHOCH). Deterministic, no
LLM, single-instrument.

This is a different question from global_market_intelligence.py's own
"regime" (risk-on/risk-off) — that one reads cross-asset macro conditions
(DXY, Nasdaq, Dow) as a weak supplement in market_brain.py. This one reads
THIS symbol's own recent price action, per timeframe, and answers "is this
instrument trending, ranging, or between the two right now?"

Status as of 2026-08-07: classification only, surfaced as CONTEXT on every
decision (see market_brain.analyze()'s "market_regime" field) for
transparency — NOT wired to modulate engine weights or strategy selection
in live decisions. The project's own standing rule (validate before
activating — see the crypto-context lesson in Audit/) applies here too:
any weight modulation by regime needs to be proven on fusion_backtest.py
first. See regime_experiment.py for that test, run but not yet activated.
"""

from indicators import ema, atr, find_swings, classify_structure
from market_analysis import bos_choch

TREND_SLOPE_ATR_THRESHOLD = 1.5  # |EMA50 move over LOOKBACK_BARS| in ATR units, above this = a real trend
LOOKBACK_BARS = 20
VOLATILITY_EXPANSION_RATIO = 1.3  # mirrors engine_scoring.score_volatility's own threshold, for consistency
VOLATILITY_COMPRESSION_RATIO = 0.7


def classify_market_regime(candles):
    """Returns {"regime": "trend_up"|"trend_down"|"range"|"transition",
    "volatility": "expansion"|"compression"|"normal", "details": [str,...]}.

    Needs enough history for EMA50 + a 20-bar-old EMA50 + a 30-bar ATR
    average; returns the least assertive read ("range"/"normal") rather
    than guessing if there isn't enough — same philosophy as every engine
    in engine_scoring.py degrading gracefully instead of crashing or
    fabricating a confident answer from thin data."""
    closes = [c["close"] for c in candles]
    if len(closes) < LOOKBACK_BARS + 51:
        return {"regime": "range", "volatility": "normal", "details": ["Historique insuffisant pour classer le régime"]}

    ema50 = ema(closes, 50)
    atr14 = atr(candles, 14)
    current_atr = atr14[-1]
    if not current_atr or current_atr <= 0:
        return {"regime": "range", "volatility": "normal", "details": ["ATR indisponible"]}

    valid_atr = [a for a in atr14[-30:] if a is not None]
    atr_ratio = (current_atr / (sum(valid_atr) / len(valid_atr))) if len(valid_atr) >= 10 else 1.0
    if atr_ratio > VOLATILITY_EXPANSION_RATIO:
        volatility = "expansion"
    elif atr_ratio < VOLATILITY_COMPRESSION_RATIO:
        volatility = "compression"
    else:
        volatility = "normal"

    e_now, e_then = ema50[-1], ema50[-1 - LOOKBACK_BARS]
    slope_in_atr = (e_now - e_then) / current_atr if (e_now is not None and e_then is not None) else None

    details = [
        f"Pente EMA50 sur {LOOKBACK_BARS} bougies : {slope_in_atr:.2f} ATR" if slope_in_atr is not None else "Pente EMA50 indisponible",
        f"Volatilité : {volatility} (ATR {atr_ratio:.2f}x la moyenne)",
    ]

    # A CHOCH means the market itself just signaled the prevailing trend may
    # be ending — that overrides the (backward-looking) EMA slope read,
    # since bos_choch is always evaluated against the CURRENT last candle,
    # never a stale one.
    swings = find_swings(candles, 3)
    event = bos_choch(candles, swings)
    if event["event"] == "CHOCH":
        details.append(f"CHOCH : {event['detail']}")
        return {"regime": "transition", "volatility": volatility, "details": details}

    if slope_in_atr is None:
        return {"regime": "range", "volatility": volatility, "details": details}
    if slope_in_atr >= TREND_SLOPE_ATR_THRESHOLD:
        return {"regime": "trend_up", "volatility": volatility, "details": details}
    if slope_in_atr <= -TREND_SLOPE_ATR_THRESHOLD:
        return {"regime": "trend_down", "volatility": volatility, "details": details}
    return {"regime": "range", "volatility": volatility, "details": details}


# ── Weight modulation experiment (2026-08-07) ───────────────────────
# A concrete, testable hypothesis: trend-following engines (multi_timeframe,
# market_structure, indicator_fusion — all three read continuation/momentum)
# should matter MORE during a real trend, and LESS during a range, where a
# reversal-oriented engine (fibonacci, which specifically looks for
# retracement bounces) should matter more instead. During "transition" —
# the market itself just signaled uncertainty via a CHOCH — weights are left
# untouched: leaning either way on an acknowledged uncertain regime is a
# second, unproven hypothesis stacked on the first, not a simplification.
#
# This is OPT-IN everywhere (engine_scoring.fuse_direction_and_confidence,
# market_brain.analyze, fusion_backtest.run_fusion_backtest all default to
# no modulation) — it must be proven on fusion_backtest.py across multiple
# real time windows before it's ever turned on by default. See
# regime_experiment.py for that test and its real result.
TREND_BOOST_ENGINES = ("multi_timeframe", "market_structure", "indicator_fusion")
RANGE_BOOST_ENGINES = ("fibonacci",)
BOOST_MULTIPLIER = 1.3
CUT_MULTIPLIER = 0.7


def regime_weight_multipliers(regime):
    """Returns {engine_id: multiplier} — only engines that should change are
    present; engine_scoring.py treats a missing entry as 1.0 (unchanged)."""
    if regime in ("trend_up", "trend_down"):
        multipliers = {eid: BOOST_MULTIPLIER for eid in TREND_BOOST_ENGINES}
        multipliers.update({eid: CUT_MULTIPLIER for eid in RANGE_BOOST_ENGINES})
        return multipliers
    if regime == "range":
        multipliers = {eid: BOOST_MULTIPLIER for eid in RANGE_BOOST_ENGINES}
        multipliers.update({eid: CUT_MULTIPLIER for eid in TREND_BOOST_ENGINES})
        return multipliers
    return {}
