from __future__ import annotations

# KB2 — Structure du marché, module partagé.
#
# Détecte les points de swing (fractals haut/bas), les classe en
# Higher High / Lower High / Higher Low / Lower Low, puis en déduit un
# régime de marché : tendance haussière/baissière, range, correction
# (pullback qui ne casse pas la structure dominante), retournement
# (cassure confirmée des deux côtés).
#
# Module pur : ne dépend pas de MT5, prend en entrée une liste de bougies
# ({"high": float, "low": float}, ordre chronologique) — testable isolément.
# Le détecteur de swing (detect_swings) sera réutilisé par KB4 (Fibonacci).


def detect_swings(candles: list[dict], lookback: int = 2) -> list[dict]:
    """Fractal simple : un swing high/low est l'extrême strict sur une fenêtre
    de `lookback` bougies de chaque côté. Swings consécutifs du même type
    fusionnés en ne gardant que le plus extrême (évite les doublons de bruit)."""
    n = len(candles)
    raw = []
    for i in range(lookback, n - lookback):
        window = candles[i - lookback:i + lookback + 1]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        if candles[i]["high"] == max(highs) and highs.count(candles[i]["high"]) == 1:
            raw.append({"index": i, "type": "high", "price": candles[i]["high"]})
        if candles[i]["low"] == min(lows) and lows.count(candles[i]["low"]) == 1:
            raw.append({"index": i, "type": "low", "price": candles[i]["low"]})
    raw.sort(key=lambda s: s["index"])

    merged: list[dict] = []
    for s in raw:
        if merged and merged[-1]["type"] == s["type"]:
            if s["type"] == "high" and s["price"] > merged[-1]["price"]:
                merged[-1] = s
            elif s["type"] == "low" and s["price"] < merged[-1]["price"]:
                merged[-1] = s
        else:
            merged.append(s)
    return merged


def classify_swings(swings: list[dict]) -> list[dict]:
    """Ajoute le label HH/LH (highs) ou HL/LL (lows) par rapport au swing
    précédent du même type. Premier swing de chaque type : label None."""
    labeled = []
    last_high = None
    last_low = None
    for s in swings:
        if s["type"] == "high":
            label = None if last_high is None else ("HH" if s["price"] > last_high else "LH")
            last_high = s["price"]
        else:
            label = None if last_low is None else ("HL" if s["price"] > last_low else "LL")
            last_low = s["price"]
        labeled.append({**s, "label": label})
    return labeled


def market_structure(candles: list[dict], lookback: int = 2) -> dict:
    swings = detect_swings(candles, lookback)
    labeled = classify_swings(swings)

    regime = "RANGE"
    confirmed_trend = None  # dernière tendance UPTREND/DOWNTREND confirmée (ignore RANGE/CORRECTION)
    last_high_label = None
    last_low_label = None
    reversal_index = None
    reversal_direction = None

    for s in labeled:
        if s["label"] is None:
            continue
        if s["type"] == "high":
            last_high_label = s["label"]
        else:
            last_low_label = s["label"]

        if last_high_label == "HH" and last_low_label == "HL":
            regime = "UPTREND"
        elif last_high_label == "LH" and last_low_label == "LL":
            regime = "DOWNTREND"
        elif last_high_label == "HH" and last_low_label == "LL":
            regime = "CORRECTION" if confirmed_trend == "UPTREND" else "RANGE"
        elif last_high_label == "LH" and last_low_label == "HL":
            regime = "CORRECTION" if confirmed_trend == "DOWNTREND" else "RANGE"
        else:
            regime = "RANGE"

        if regime in ("UPTREND", "DOWNTREND"):
            if confirmed_trend is not None and confirmed_trend != regime:
                reversal_index = s["index"]
                reversal_direction = regime
            confirmed_trend = regime

    return {
        "swings": labeled,
        "regime": regime,
        "last_high_label": last_high_label,
        "last_low_label": last_low_label,
        "reversal_index": reversal_index,
        "reversal_direction": reversal_direction,
        "swing_count": len(labeled),
    }
