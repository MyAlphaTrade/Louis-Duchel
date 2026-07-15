from __future__ import annotations

# KB5 — Smart Money Concepts, module partagé.
#
# S'appuie sur la structure (KB2 : detect_swings/classify_swings) et complète
# KB3/KB4. Sept concepts, chacun une fonction pure indépendante :
#
# - FVG (Fair Value Gap) : déséquilibre 3 bougies (gap entre bougie 1 et 3).
# - Order Blocks : dernière bougie contraire avant un mouvement impulsif
#   (même logique de mouvement moyen que KB3, à l'échelle bougie).
# - BOS / CHOCH : dérivés directement des labels HH/LH/HL/LL de KB2 — seuls
#   HH et LL "cassent" réellement un extrême précédent. BOS si la cassure va
#   dans le sens de la tendance déjà confirmée (ou l'établit) ; CHOCH si elle
#   va contre une tendance déjà confirmée (premier signal d'alerte).
# - Liquidity Grab : mèche qui dépasse un swing puis clôture à l'intérieur
#   (chasse aux stops sans cassure confirmée — différent d'un BOS).
# - Equal Highs / Equal Lows : swings du même type très proches en prix
#   (zone de liquidité probable).
# - Premium / Discount : position du prix actuel dans le dernier range
#   significatif (même range que le Fibonacci de KB4).
#
# Module pur : ne dépend pas de MT5 — testable isolément.


def detect_fvg(candles: list[dict]) -> list[dict]:
    gaps = []
    for i in range(1, len(candles) - 1):
        prev_high, prev_low = candles[i - 1]["high"], candles[i - 1]["low"]
        next_high, next_low = candles[i + 1]["high"], candles[i + 1]["low"]
        if prev_high < next_low:
            gaps.append({"type": "bullish", "index": i, "top": next_low, "bottom": prev_high})
        elif prev_low > next_high:
            gaps.append({"type": "bearish", "index": i, "top": prev_low, "bottom": next_high})
    return gaps


def detect_order_blocks(candles: list[dict], impulse_multiplier: float = 2.0, lookahead: int = 3) -> list[dict]:
    if len(candles) < lookahead + 2:
        return []
    ranges = [c["high"] - c["low"] for c in candles]
    avg_range = sum(ranges) / len(ranges) if ranges else 0.0
    if avg_range <= 0:
        return []

    blocks = []
    for i in range(len(candles) - lookahead):
        c = candles[i]
        future = candles[i + 1:i + 1 + lookahead]
        move_up = max(f["high"] for f in future) - c["close"]
        move_down = c["close"] - min(f["low"] for f in future)
        if c["close"] < c["open"] and move_up >= impulse_multiplier * avg_range:
            blocks.append({"type": "bullish", "index": i, "top": c["high"], "bottom": c["low"]})
        elif c["close"] > c["open"] and move_down >= impulse_multiplier * avg_range:
            blocks.append({"type": "bearish", "index": i, "top": c["high"], "bottom": c["low"]})
    return blocks


def detect_bos_choch(labeled_swings: list[dict]) -> list[dict]:
    events = []
    confirmed_trend = None
    for s in labeled_swings:
        if s["label"] == "HH":
            event_type = "BOS" if confirmed_trend in (None, "UPTREND") else "CHOCH"
            events.append({"type": event_type, "direction": "bullish", "index": s["index"]})
            confirmed_trend = "UPTREND"
        elif s["label"] == "LL":
            event_type = "BOS" if confirmed_trend in (None, "DOWNTREND") else "CHOCH"
            events.append({"type": event_type, "direction": "bearish", "index": s["index"]})
            confirmed_trend = "DOWNTREND"
        # LH et HL ne cassent aucun extreme precedent : pas d'evenement.
    return events


def detect_liquidity_grabs(candles: list[dict], swings: list[dict]) -> list[dict]:
    swing_highs = [s for s in swings if s["type"] == "high"]
    swing_lows = [s for s in swings if s["type"] == "low"]
    grabs = []
    for i, c in enumerate(candles):
        for sh in swing_highs:
            if sh["index"] < i and c["high"] > sh["price"] and c["close"] < sh["price"]:
                grabs.append({"type": "bearish", "index": i, "level": sh["price"], "swing_index": sh["index"]})
        for sl in swing_lows:
            if sl["index"] < i and c["low"] < sl["price"] and c["close"] > sl["price"]:
                grabs.append({"type": "bullish", "index": i, "level": sl["price"], "swing_index": sl["index"]})
    return grabs


def detect_equal_levels(swings: list[dict], tolerance_pct: float = 0.05) -> dict:
    def find_equals(points):
        groups = []
        used = set()
        pts = sorted(points, key=lambda s: s["price"])
        for i, p in enumerate(pts):
            if i in used:
                continue
            group = [p]
            for j in range(i + 1, len(pts)):
                if j in used:
                    continue
                if abs(pts[j]["price"] - p["price"]) / p["price"] * 100 <= tolerance_pct:
                    group.append(pts[j])
                    used.add(j)
            if len(group) >= 2:
                groups.append(group)
                used.add(i)
        return groups

    highs = [s for s in swings if s["type"] == "high"]
    lows = [s for s in swings if s["type"] == "low"]
    return {"equal_highs": find_equals(highs), "equal_lows": find_equals(lows)}


def premium_discount(swing_low: float, swing_high: float, current_price: float) -> dict:
    if swing_high <= swing_low:
        return {"zone": None, "position_pct": None}
    position_pct = (current_price - swing_low) / (swing_high - swing_low) * 100
    if position_pct > 50:
        zone = "PREMIUM"
    elif position_pct < 50:
        zone = "DISCOUNT"
    else:
        zone = "EQUILIBRIUM"
    return {"zone": zone, "position_pct": round(position_pct, 1)}
