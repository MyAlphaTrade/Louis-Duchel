"""
AI Confidence Engine v2 — preparation only, NOT activated.

Implements the 3-layer architecture validated (with adjustments) in
Audit/Transformation_3Couches_ParMoteur_2026-08-01.html and
Audit/Proposition_Architecture_3Couches_AIConfidenceEngine_2026-08-01.html:

  1. Direction Score   — "which way": Multi-Timeframe, Market Structure,
     Indicator Fusion only (same weighted-vote formula as
     engine_scoring.fuse_direction_and_confidence, restricted to these 3).
  2. Setup Quality Score — "is there a clean zone to enter": Smart Money,
     Fibonacci, Liquidity, Pattern Recognition. Entry Planner is
     deliberately EXCLUDED here per the validated adjustment — it stays a
     downstream gate (MARKET/LIMIT/STOP/skip) in market_brain.py, not a
     weighted contributor to this score.
  3. Market Condition Score (named "Market Risk Score" in the original
     proposal, renamed per the validated adjustment) — "how reliable is
     this market right now": Volatility, Volume, Session.

Final confidence recombination (kept for comparison only):
    final = direction_score * (setup_quality_score/100)**0.5 * (market_condition_score/100)**0.3

This module is entirely additive and read-only with respect to production
behavior: it is called from market_brain.py in "comparison mode" only,
never used to compute decision.confidence, never referenced by the
Autonomous Trading Engine or the Entry Planner. Nothing here changes
ENGINE_WEIGHTS, CONFIDENCE_FLOOR, or any trading threshold.
"""

from market_analysis import find_fvgs, find_order_blocks
from engine_scoring import FUSION_BASE

DIRECTION_WEIGHTS = {"multi_timeframe": 37, "market_structure": 37, "indicator_fusion": 26}
SETUP_WEIGHTS = {"smart_money": 35, "fibonacci": 24, "liquidity": 23, "pattern_recognition": 18}
CONDITION_WEIGHTS = {"volatility": 40, "volume": 35, "session": 25}


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, round(v)))


def calculate_direction_score(engine_results):
    """Same weighted-vote mechanics as fuse_direction_and_confidence
    (including its base+additive final mapping, see FUSION_BASE), but
    restricted to the 3 engines that actually vote on market direction."""
    votes = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    total_weight = 0
    for engine_id, weight in DIRECTION_WEIGHTS.items():
        r = engine_results.get(engine_id)
        if not r:
            continue
        conf = r.get("confidence", 0)
        bias = r.get("bias", "neutral")
        votes[bias] += weight * (conf / 100)
        total_weight += weight

    if total_weight == 0:
        return {"score": 0, "direction": "neutral"}

    scores = {bias: FUSION_BASE + (vote / total_weight) * (100 - FUSION_BASE) for bias, vote in votes.items()}
    dominant = max(scores, key=scores.get)
    score = round(scores[dominant])
    return {"score": score, "direction": dominant}


def _smart_money_zone_distance_atr(ctx):
    """Nearest unmitigated order block / FVG to current price, in ATR
    multiples — same zone lists and "nearest" definition as
    engine_scoring.score_smart_money, just exposing the raw distance instead
    of folding it into a bias+confidence pair. Returns None if no zone
    exists on either side."""
    candles = ctx["candles"]
    price = candles[-1]["close"]
    atr_val = ctx["atr14"][-1] or 0

    fvgs = [f for f in find_fvgs(candles) if not f["filled"]]
    obs = [o for o in find_order_blocks(candles, ctx["atr14"]) if not o["mitigated"]]
    zones = [{"type": z["type"], "top": z["top"], "bottom": z["bottom"]} for z in fvgs + obs]

    nearest_bullish = min(
        (z for z in zones if z["type"] == "bullish" and z["top"] <= price), key=lambda z: price - z["top"], default=None
    )
    nearest_bearish = min(
        (z for z in zones if z["type"] == "bearish" and z["bottom"] >= price), key=lambda z: z["bottom"] - price, default=None
    )
    dist_bull = (price - nearest_bullish["top"]) if nearest_bullish else None
    dist_bear = (nearest_bearish["bottom"] - price) if nearest_bearish else None
    candidates = [d for d in (dist_bull, dist_bear) if d is not None]
    if not candidates:
        return None

    denom = atr_val if atr_val else price * 0.002
    if not denom:
        return None
    return min(candidates) / denom


def _setup_quality_smart_money(ctx):
    distance_atr = _smart_money_zone_distance_atr(ctx)
    if distance_atr is None:
        return 0
    return _clamp(100 - distance_atr * 60)


def _setup_quality_fibonacci(engine_results):
    """Maps score_fibonacci's existing confidence values (65=confirmed
    rebound in golden pocket, 35=in zone unconfirmed, 15=outside/no swings)
    onto a quality score — reuses its zone logic rather than recomputing
    it, per the validated proposal."""
    r = engine_results.get("fibonacci")
    if not r:
        return 15
    conf = r.get("confidence", 15)
    if conf >= 65:
        return 100
    if conf >= 35:
        return 50
    return 15


def _setup_quality_liquidity(engine_results):
    r = engine_results.get("liquidity")
    if not r:
        return 20
    return 100 if r.get("bias", "neutral") != "neutral" else 20


def _setup_quality_pattern(engine_results):
    """score_pattern_recognition's confidence already IS the pattern's
    strength magnitude regardless of direction (20 when no pattern) — no
    recomputation needed."""
    r = engine_results.get("pattern_recognition")
    if not r:
        return 20
    return _clamp(r.get("confidence", 20))


def calculate_setup_quality_score(ctx, engine_results):
    components = {
        "smart_money": _setup_quality_smart_money(ctx),
        "fibonacci": _setup_quality_fibonacci(engine_results),
        "liquidity": _setup_quality_liquidity(engine_results),
        "pattern_recognition": _setup_quality_pattern(engine_results),
    }
    total_weight = sum(SETUP_WEIGHTS.values())
    weighted_sum = sum(components[eid] * w for eid, w in SETUP_WEIGHTS.items())
    score = round(weighted_sum / total_weight) if total_weight else 0
    return {"score": score, "components": components}


def _market_condition_volatility(ctx):
    """Same ATR-ratio thresholds as score_volatility (>1.3 expansion,
    <0.7 compression) but with the NEW output values from the validated
    proposal (80/40/15 instead of 55/35/20) — this layer measures
    reliability, not a directional vote, so it gets its own scale."""
    atr_series = ctx["atr14"]
    valid = [a for a in atr_series[-30:] if a is not None]
    if len(valid) < 10:
        return 15
    current, avg = valid[-1], sum(valid) / len(valid)
    ratio = current / avg if avg > 0 else 1
    if ratio > 1.3:
        return 80
    if ratio < 0.7:
        return 15
    return 40


def _market_condition_volume(ctx):
    candles = ctx["candles"]
    if len(candles) < 21:
        return 15
    c = candles[-1]
    window = candles[-21:-1]
    avg_vol = sum(x["tick_volume"] for x in window) / len(window)
    if avg_vol <= 0:
        return 15
    ratio = c["tick_volume"] / avg_vol
    return _clamp(min(100, ratio * 50))


def _market_condition_session():
    from indicators import detect_session
    s = detect_session()
    if s["kill_zone"] == "london_new_york_overlap":
        return 90
    if s["kill_zone"]:
        return 60
    if s["active_sessions"]:
        return 35
    return 10


def calculate_market_condition_score(ctx):
    components = {
        "volatility": _market_condition_volatility(ctx),
        "volume": _market_condition_volume(ctx),
        "session": _market_condition_session(),
    }
    total_weight = sum(CONDITION_WEIGHTS.values())
    weighted_sum = sum(components[eid] * w for eid, w in CONDITION_WEIGHTS.items())
    score = round(weighted_sum / total_weight) if total_weight else 0
    return {"score": score, "components": components}


def calculate_final_confidence(direction_score, setup_quality_score, market_condition_score):
    """Direction is the ceiling; Setup Quality and Market Condition can only
    attenuate it (exponents < 1), never push it above the raw direction
    score. See §0 of Transformation_3Couches_ParMoteur_2026-08-01.html."""
    return round(
        direction_score
        * ((setup_quality_score / 100) ** 0.5)
        * ((market_condition_score / 100) ** 0.3)
    )
