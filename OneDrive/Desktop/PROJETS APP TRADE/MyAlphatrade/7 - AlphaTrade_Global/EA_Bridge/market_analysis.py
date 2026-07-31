"""
Market analysis primitives — real, standard technical-analysis definitions
computed on real candles. No LLM anywhere in this file. These are new
building blocks (no TypeScript original to port) used by engine_scoring.py
to give the previously-narrative engines (Market Structure, Smart Money,
Liquidity, Pattern Recognition) something real to read instead of an
invented LLM description.

Builds on indicators.py's candles/swings — see that file for the base
sma/ema/rsi/atr/find_swings/classify_structure/fibonacci_levels primitives.
"""

from indicators import find_swings, classify_structure, fibonacci_levels


# ── Market Structure: BOS / CHOCH ──────────────────────────────────

def bos_choch(candles, swings):
    """Break of Structure (continuation) vs Change of Character (reversal
    warning), read off the last confirmed swings and the latest close.

    BOS: in an uptrend, close breaks above the last swing high (trend
    continues). In a downtrend, close breaks below the last swing low.
    CHOCH: the opposite — close breaks the swing on the "wrong" side for
    the prevailing trend, the first sign the trend may be turning.
    """
    structure = classify_structure(swings)
    last_close = candles[-1]["close"]
    last_high = next((s for s in reversed(swings) if s["type"] == "high"), None)
    last_low = next((s for s in reversed(swings) if s["type"] == "low"), None)

    if structure["label"] == "uptrend" and last_high and last_close > last_high["price"]:
        return {"event": "BOS", "direction": "bullish", "level": last_high["price"],
                "detail": f"Cassure du dernier plus haut ({last_high['price']:.2f}) — continuation haussière"}
    if structure["label"] == "uptrend" and last_low and last_close < last_low["price"]:
        return {"event": "CHOCH", "direction": "bearish", "level": last_low["price"],
                "detail": f"Cassure du dernier plus bas ({last_low['price']:.2f}) en tendance haussière — signal de retournement"}
    if structure["label"] == "downtrend" and last_low and last_close < last_low["price"]:
        return {"event": "BOS", "direction": "bearish", "level": last_low["price"],
                "detail": f"Cassure du dernier plus bas ({last_low['price']:.2f}) — continuation baissière"}
    if structure["label"] == "downtrend" and last_high and last_close > last_high["price"]:
        return {"event": "CHOCH", "direction": "bullish", "level": last_high["price"],
                "detail": f"Cassure du dernier plus haut ({last_high['price']:.2f}) en tendance baissière — signal de retournement"}
    return {"event": None, "direction": "neutral", "level": None, "detail": f"Pas de cassure — structure {structure['label']}"}


# ── Smart Money: Fair Value Gaps + Order Blocks ────────────────────

def find_fvgs(candles, lookback=80):
    """Fair Value Gap — a 3-candle imbalance: candle[i-1] and candle[i+1]
    don't overlap, leaving a gap the market often revisits. Standard ICT
    definition. `filled` = price has traded back into the zone since."""
    start = max(2, len(candles) - lookback)
    fvgs = []
    for i in range(start, len(candles) - 1):
        prev, nxt = candles[i - 1], candles[i + 1]
        if prev["high"] < nxt["low"]:
            top, bottom = nxt["low"], prev["high"]
            filled = any(c["low"] <= bottom for c in candles[i + 1:])
            fvgs.append({"index": i, "type": "bullish", "top": top, "bottom": bottom, "filled": filled})
        elif prev["low"] > nxt["high"]:
            top, bottom = prev["low"], nxt["high"]
            filled = any(c["high"] >= top for c in candles[i + 1:])
            fvgs.append({"index": i, "type": "bearish", "top": top, "bottom": bottom, "filled": filled})
    return fvgs


def find_order_blocks(candles, atr_series, lookback=80, impulse_mult=1.5):
    """Order Block — the last opposite-colored candle before a strong
    impulsive move that breaks recent structure. Simplified, standard
    retail-ICT definition: an "impulsive" candle is one whose range clears
    `impulse_mult` times the local ATR."""
    start = max(1, len(candles) - lookback)
    blocks = []
    for i in range(start, len(candles)):
        atr_val = atr_series[i]
        if atr_val is None or atr_val <= 0:
            continue
        c = candles[i]
        candle_range = c["high"] - c["low"]
        if candle_range < atr_val * impulse_mult:
            continue
        is_bullish_impulse = c["close"] > c["open"]
        prev = candles[i - 1]
        if is_bullish_impulse and prev["close"] < prev["open"]:
            top, bottom = prev["high"], prev["low"]
            mitigated = any(cc["low"] <= bottom for cc in candles[i + 1:])
            blocks.append({"index": i - 1, "type": "bullish", "top": top, "bottom": bottom, "mitigated": mitigated, "impulse_index": i})
        elif not is_bullish_impulse and prev["close"] > prev["open"]:
            top, bottom = prev["high"], prev["low"]
            mitigated = any(cc["high"] >= top for cc in candles[i + 1:])
            blocks.append({"index": i - 1, "type": "bearish", "top": top, "bottom": bottom, "mitigated": mitigated, "impulse_index": i})
    return blocks


# ── Liquidity: equal highs/lows + sweeps ───────────────────────────

def find_liquidity_zones(swings, tolerance_pct=0.05):
    """Equal highs/lows within `tolerance_pct`% of each other mark a
    liquidity pool — resting stop orders + breakout entries cluster there,
    making it a magnet price often sweeps before reversing."""
    zones = []
    highs = [s for s in swings if s["type"] == "high"]
    lows = [s for s in swings if s["type"] == "low"]
    for group, side in ((highs, "buy_side"), (lows, "sell_side")):
        used = set()
        for i, a in enumerate(group):
            if i in used:
                continue
            cluster = [a]
            for j in range(i + 1, len(group)):
                b = group[j]
                if j in used:
                    continue
                if abs(b["price"] - a["price"]) / a["price"] * 100 <= tolerance_pct:
                    cluster.append(b)
                    used.add(j)
            if len(cluster) >= 2:
                avg_price = sum(s["price"] for s in cluster) / len(cluster)
                zones.append({"side": side, "price": avg_price, "touches": len(cluster), "last_index": max(s["index"] for s in cluster)})
    return zones


def detect_sweep(candles, zones, recent_bars=5):
    """A sweep: a recent candle wicks beyond a liquidity zone then closes
    back on the other side — smart money grabbing stops before reversing,
    the classic precursor to a reversal rather than a breakout."""
    recent = candles[-recent_bars:]
    for zone in zones:
        for c in recent:
            if zone["side"] == "buy_side" and c["high"] > zone["price"] and c["close"] < zone["price"]:
                return {"swept": True, "side": "buy_side", "level": zone["price"], "direction": "bearish",
                        "detail": f"Sweep de liquidité acheteuse à {zone['price']:.2f} — mèche au-dessus, clôture en dessous"}
            if zone["side"] == "sell_side" and c["low"] < zone["price"] and c["close"] > zone["price"]:
                return {"swept": True, "side": "sell_side", "level": zone["price"], "direction": "bullish",
                        "detail": f"Sweep de liquidité vendeuse à {zone['price']:.2f} — mèche en dessous, clôture au-dessus"}
    return {"swept": False, "side": None, "level": None, "direction": "neutral", "detail": "Aucun sweep récent détecté"}


# ── Pattern Recognition: candlesticks ──────────────────────────────

def detect_candlestick_pattern(candles):
    """Reads the last 1-2 real candles for standard reversal patterns.
    Returns the single most recent pattern found, or None."""
    if len(candles) < 2:
        return None
    c, prev = candles[-1], candles[-2]
    body = abs(c["close"] - c["open"])
    candle_range = c["high"] - c["low"]
    if candle_range <= 0:
        return None
    upper_wick = c["high"] - max(c["close"], c["open"])
    lower_wick = min(c["close"], c["open"]) - c["low"]

    prev_body = abs(prev["close"] - prev["open"])
    prev_bearish = prev["close"] < prev["open"]
    prev_bullish = prev["close"] > prev["open"]

    # Engulfing — current body fully engulfs the previous opposite body.
    if prev_bearish and c["close"] > c["open"] and c["open"] <= prev["close"] and c["close"] >= prev["open"] and body > prev_body:
        return {"pattern": "bullish_engulfing", "bias": "bullish", "strength": min(100, round(body / max(prev_body, 1e-9) * 40))}
    if prev_bullish and c["close"] < c["open"] and c["open"] >= prev["close"] and c["close"] <= prev["open"] and body > prev_body:
        return {"pattern": "bearish_engulfing", "bias": "bearish", "strength": min(100, round(body / max(prev_body, 1e-9) * 40))}

    # Pin bar / hammer — small body, long wick on one side rejecting that direction.
    if body > 0 and lower_wick >= body * 2 and upper_wick <= body * 0.5:
        return {"pattern": "bullish_pin_bar", "bias": "bullish", "strength": min(100, round(lower_wick / candle_range * 100))}
    if body > 0 and upper_wick >= body * 2 and lower_wick <= body * 0.5:
        return {"pattern": "bearish_pin_bar", "bias": "bearish", "strength": min(100, round(upper_wick / candle_range * 100))}

    # Doji — indecision, not directional.
    if body <= candle_range * 0.1:
        return {"pattern": "doji", "bias": "neutral", "strength": 20}

    return None
