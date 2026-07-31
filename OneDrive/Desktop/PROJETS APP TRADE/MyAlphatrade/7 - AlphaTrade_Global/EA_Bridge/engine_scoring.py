"""
Deterministic engine scoring — replaces the LLM's job of "reasoning across
20 domains" with real math on real candles. No LLM anywhere in this file.

Each of the weighted engines below returns its OWN read of the market —
{"id", "bias": bullish/bearish/neutral, "confidence": 0-100 (how sure THIS
engine is of ITS bias), "findings": [str, ...]}. The final direction is
never picked first and then justified (that was the old LLM pattern) — it
is derived bottom-up from these votes, weighted by each engine's
importance (see ENGINE_WEIGHTS, mirroring Dist/base44/shared/engines.ts).

Economic Intelligence (news calendar) is left out: there is no data source
for it yet, and inventing one would just reintroduce the original problem
(a plausible-sounding number nobody computed).
"""

from indicators import ema, rsi, macd, atr, bollinger_bands, find_swings, classify_structure, fibonacci_levels, bias_from_snapshot
from market_analysis import bos_choch, find_fvgs, find_order_blocks, find_liquidity_zones, detect_sweep, detect_candlestick_pattern

# Mirrors Dist/base44/shared/engines.ts ANALYSIS_ENGINES weights.
# Economic Intelligence (weight 6) is omitted — no data source yet.
ENGINE_WEIGHTS = {
    "multi_timeframe": 14,
    "market_structure": 14,
    "smart_money": 12,
    "indicator_fusion": 10,
    "liquidity": 8,
    "entry_planner": 8,
    "fibonacci": 7,
    "volume": 7,
    "pattern_recognition": 5,
    "volatility": 5,
    "session": 4,
}


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, round(v)))


def build_context(candles):
    """Everything the per-engine scorers need, computed once."""
    closes = [c["close"] for c in candles]
    swings = find_swings(candles, 3)
    return {
        "candles": candles,
        "closes": closes,
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "rsi14": rsi(closes, 14),
        "macd": macd(closes),
        "atr14": atr(candles, 14),
        "bollinger": bollinger_bands(closes, 20, 2),
        "swings": swings,
        "structure": classify_structure(swings),
    }


def score_market_structure(ctx):
    event = bos_choch(ctx["candles"], ctx["swings"])
    if event["event"] == "BOS":
        return {"id": "market_structure", "bias": event["direction"], "confidence": 75, "findings": [event["detail"]]}
    if event["event"] == "CHOCH":
        return {"id": "market_structure", "bias": event["direction"], "confidence": 55, "findings": [event["detail"]]}
    return {"id": "market_structure", "bias": "neutral", "confidence": 20, "findings": [event["detail"]]}


def score_smart_money(ctx):
    candles, last = ctx["candles"], ctx["candles"][-1]
    price = last["close"]
    atr_val = ctx["atr14"][-1] or 0
    fvgs = [f for f in find_fvgs(candles) if not f["filled"]]
    obs = [o for o in find_order_blocks(candles, ctx["atr14"]) if not o["mitigated"]]
    zones = [{"type": z["type"], "top": z["top"], "bottom": z["bottom"], "index": z.get("index", z.get("impulse_index"))} for z in fvgs + obs]

    nearest_bullish = min(
        (z for z in zones if z["type"] == "bullish" and z["top"] <= price), key=lambda z: price - z["top"], default=None
    )
    nearest_bearish = min(
        (z for z in zones if z["type"] == "bearish" and z["bottom"] >= price), key=lambda z: z["bottom"] - price, default=None
    )

    dist_bull = (price - nearest_bullish["top"]) if nearest_bullish else None
    dist_bear = (nearest_bearish["bottom"] - price) if nearest_bearish else None
    near_atr = atr_val * 1.0 if atr_val else price * 0.002

    if dist_bull is not None and dist_bull <= near_atr and (dist_bear is None or dist_bull < dist_bear):
        conf = _clamp(70 - (dist_bull / near_atr) * 20 + (len(candles) - nearest_bullish["index"] < 30) * 10)
        return {"id": "smart_money", "bias": "bullish", "confidence": conf,
                "findings": [f"Zone de demande non mitigée à {nearest_bullish['top']:.2f}-{nearest_bullish['bottom']:.2f}, prix à proximité"]}
    if dist_bear is not None and dist_bear <= near_atr:
        conf = _clamp(70 - (dist_bear / near_atr) * 20 + (len(candles) - nearest_bearish["index"] < 30) * 10)
        return {"id": "smart_money", "bias": "bearish", "confidence": conf,
                "findings": [f"Zone d'offre non mitigée à {nearest_bearish['bottom']:.2f}-{nearest_bearish['top']:.2f}, prix à proximité"]}
    return {"id": "smart_money", "bias": "neutral", "confidence": 20, "findings": [f"{len(zones)} zones non mitigées repérées, aucune à proximité immédiate du prix"]}


def score_fibonacci(ctx):
    swings = ctx["swings"]
    last_high = next((s for s in reversed(swings) if s["type"] == "high"), None)
    last_low = next((s for s in reversed(swings) if s["type"] == "low"), None)
    if not last_high or not last_low:
        return {"id": "fibonacci", "bias": "neutral", "confidence": 15, "findings": ["Pas assez de swings pour tracer un Fibonacci exploitable"]}

    direction = "down" if last_high["index"] > last_low["index"] else "up"
    fib = fibonacci_levels(last_high["price"], last_low["price"], direction)
    golden_618, golden_786 = fib["levels"]["0.618"], fib["levels"]["0.786"]
    zone_low, zone_high = (golden_618, golden_786) if golden_618 < golden_786 else (golden_786, golden_618)
    c = ctx["candles"][-1]
    in_zone = c["low"] <= zone_high and c["high"] >= zone_low

    if not in_zone:
        return {"id": "fibonacci", "bias": "neutral", "confidence": 15, "findings": [f"Prix hors golden pocket ({zone_low:.2f}-{zone_high:.2f})"]}
    if direction == "up" and c["close"] > c["open"]:
        return {"id": "fibonacci", "bias": "bullish", "confidence": 65, "findings": [f"Rebond confirmé dans le golden pocket ({zone_low:.2f}-{zone_high:.2f}) du swing haussier"]}
    if direction == "down" and c["close"] < c["open"]:
        return {"id": "fibonacci", "bias": "bearish", "confidence": 65, "findings": [f"Rebond confirmé dans le golden pocket ({zone_low:.2f}-{zone_high:.2f}) du swing baissier"]}
    return {"id": "fibonacci", "bias": "neutral", "confidence": 35, "findings": [f"Prix dans le golden pocket ({zone_low:.2f}-{zone_high:.2f}) mais pas encore de bougie de confirmation"]}


def score_indicator_fusion(ctx):
    votes = []
    e50, e200 = ctx["ema50"][-1], ctx["ema200"][-1]
    if e50 is not None and e200 is not None:
        votes.append("bullish" if e50 > e200 else "bearish")
    r = ctx["rsi14"][-1]
    if r is not None:
        votes.append("bullish" if r > 50 else "bearish")
    hist = ctx["macd"]["histogram"][-1]
    if hist is not None:
        votes.append("bullish" if hist > 0 else "bearish")

    if not votes:
        return {"id": "indicator_fusion", "bias": "neutral", "confidence": 10, "findings": ["Historique insuffisant pour les indicateurs"]}
    bulls, bears = votes.count("bullish"), votes.count("bearish")
    total = len(votes)
    if bulls == bears:
        return {"id": "indicator_fusion", "bias": "neutral", "confidence": 25, "findings": [f"Indicateurs partagés ({bulls} haussiers / {bears} baissiers)"]}
    bias = "bullish" if bulls > bears else "bearish"
    agree = max(bulls, bears)
    conf = _clamp(30 + (agree / total) * 55)
    return {"id": "indicator_fusion", "bias": bias, "confidence": conf, "findings": [f"{agree}/{total} indicateurs (EMA50/200, RSI, MACD) s'accordent {bias}"]}


def score_volume(ctx):
    candles = ctx["candles"]
    if len(candles) < 21:
        return {"id": "volume", "bias": "neutral", "confidence": 10, "findings": ["Historique insuffisant"]}
    c = candles[-1]
    window = candles[-21:-1]
    avg_vol = sum(x["tick_volume"] for x in window) / len(window)
    if avg_vol <= 0:
        return {"id": "volume", "bias": "neutral", "confidence": 10, "findings": ["Volume indisponible"]}
    ratio = c["tick_volume"] / avg_vol
    if ratio < 1.2:
        return {"id": "volume", "bias": "neutral", "confidence": 15, "findings": [f"Volume {ratio:.1f}x la moyenne — faible participation, pas de confirmation"]}
    bias = "bullish" if c["close"] > c["open"] else "bearish" if c["close"] < c["open"] else "neutral"
    conf = _clamp(40 + min(ratio - 1.2, 2) * 20)
    return {"id": "volume", "bias": bias, "confidence": conf, "findings": [f"Volume {ratio:.1f}x la moyenne sur une bougie {bias}"]}


def score_liquidity(ctx):
    zones = find_liquidity_zones(ctx["swings"])
    sweep = detect_sweep(ctx["candles"], zones)
    if sweep["swept"]:
        return {"id": "liquidity", "bias": sweep["direction"], "confidence": 65, "findings": [sweep["detail"]]}
    return {"id": "liquidity", "bias": "neutral", "confidence": 20, "findings": [f"{len(zones)} zone(s) de liquidité repérée(s), aucun sweep récent"]}


def score_volatility(ctx):
    atr_series = ctx["atr14"]
    valid = [a for a in atr_series[-30:] if a is not None]
    if len(valid) < 10:
        return {"id": "volatility", "bias": "neutral", "confidence": 15, "findings": ["Historique ATR insuffisant"]}
    current, avg = valid[-1], sum(valid) / len(valid)
    ratio = current / avg if avg > 0 else 1
    if ratio > 1.3:
        return {"id": "volatility", "bias": "neutral", "confidence": 55, "findings": [f"Volatilité en expansion (ATR {ratio:.1f}x la moyenne) — mouvements plus fiables"]}
    if ratio < 0.7:
        return {"id": "volatility", "bias": "neutral", "confidence": 20, "findings": [f"Volatilité comprimée (ATR {ratio:.1f}x la moyenne) — mouvements moins fiables"]}
    return {"id": "volatility", "bias": "neutral", "confidence": 35, "findings": [f"Volatilité normale (ATR {ratio:.1f}x la moyenne)"]}


def score_session(ctx):
    from indicators import detect_session
    s = detect_session()
    if s["kill_zone"] == "london_new_york_overlap":
        return {"id": "session", "bias": "neutral", "confidence": 60, "findings": ["Chevauchement Londres/New York — liquidité maximale"]}
    if s["kill_zone"]:
        return {"id": "session", "bias": "neutral", "confidence": 45, "findings": [f"Kill zone {s['kill_zone']}"]}
    if s["active_sessions"]:
        return {"id": "session", "bias": "neutral", "confidence": 30, "findings": [f"Session(s) active(s): {', '.join(s['active_sessions'])}"]}
    return {"id": "session", "bias": "neutral", "confidence": 10, "findings": ["Aucune session majeure active — faible liquidité"]}


def score_pattern_recognition(ctx):
    pattern = detect_candlestick_pattern(ctx["candles"])
    if not pattern or pattern["bias"] == "neutral":
        label = pattern["pattern"] if pattern else "aucun pattern"
        return {"id": "pattern_recognition", "bias": "neutral", "confidence": 20, "findings": [f"Pattern détecté : {label}"]}
    return {"id": "pattern_recognition", "bias": pattern["bias"], "confidence": _clamp(pattern["strength"]), "findings": [f"Pattern {pattern['pattern']} détecté"]}


def score_entry_planner(ctx):
    """Not "which direction" but "is price at an actionable level right
    now" — reuses the smart-money/fibonacci zones to answer that."""
    sm = score_smart_money(ctx)
    fib = score_fibonacci(ctx)
    candidates = [r for r in (sm, fib) if r["bias"] != "neutral"]
    if not candidates:
        return {"id": "entry_planner", "bias": "neutral", "confidence": 15, "findings": ["Prix hors de toute zone d'entrée propre — pas de configuration actionnable"]}
    best = max(candidates, key=lambda r: r["confidence"])
    return {"id": "entry_planner", "bias": best["bias"], "confidence": best["confidence"], "findings": [f"Configuration d'entrée actionnable ({best['id']})"]}


ENGINE_SCORERS = {
    "market_structure": score_market_structure,
    "smart_money": score_smart_money,
    "fibonacci": score_fibonacci,
    "indicator_fusion": score_indicator_fusion,
    "volume": score_volume,
    "liquidity": score_liquidity,
    "volatility": score_volatility,
    "session": score_session,
    "pattern_recognition": score_pattern_recognition,
    "entry_planner": score_entry_planner,
}


def run_all_engines(ctx, multi_timeframe_result=None):
    """Runs every scorer that only needs a single timeframe's context, plus
    the already-real multi_timeframe result computed upstream (it needs
    several timeframes' snapshots, not just this one)."""
    results = {name: fn(ctx) for name, fn in ENGINE_SCORERS.items()}
    if multi_timeframe_result is not None:
        results["multi_timeframe"] = multi_timeframe_result
    return results


def fuse_direction_and_confidence(engine_results):
    """Derives the final direction bottom-up from engine votes — never picks
    a direction first and justifies it after (that was the old LLM pattern).
    Each engine's vote is weighted by (engine importance × its own
    confidence in its bias), so a loud but unimportant engine can't
    outvote a quiet but important one, and vice versa."""
    weighted_votes = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    total_weight = 0.0
    breakdown = {}

    for engine_id, result in engine_results.items():
        weight = ENGINE_WEIGHTS.get(engine_id, 0)
        if weight <= 0:
            continue
        total_weight += weight
        conf = result.get("confidence", 0)
        bias = result.get("bias", "neutral")
        weighted_votes[bias] += weight * (conf / 100)
        breakdown[engine_id] = {"weight": weight, "bias": bias, "confidence": conf, "findings": result.get("findings", [])}

    if total_weight == 0:
        return {"direction": "neutral", "confidence": 0, "breakdown": breakdown}

    dominant = max(weighted_votes, key=weighted_votes.get)
    confidence = round((weighted_votes[dominant] / total_weight) * 100)
    return {"direction": dominant, "confidence": confidence, "breakdown": breakdown}
