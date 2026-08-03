"""
Deterministic technical analysis — real math on real candles.

Faithful Python port of Dist/base44/shared/indicators.ts. No LLM involved
anywhere in this file — this is what the (now-deterministic) decision
engines reason from instead of asking a model to invent numbers.

Candle shape (matches alphatg_bridge.py's /rates endpoint):
    {"time": iso8601 str, "open": float, "high": float, "low": float,
     "close": float, "tick_volume": int, "spread": int}
"""

import math
from datetime import datetime, timezone


def sma(values, period):
    out = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def ema(values, period):
    out = [None] * len(values)
    k = 2 / (period + 1)
    prev = None
    for i in range(len(values)):
        if i == period - 1:
            seed = sum(values[:period]) / period
            prev = seed
            out[i] = seed
        elif i >= period and prev is not None:
            prev = values[i] * k + prev * (1 - k)
            out[i] = prev
    return out


def rsi(closes, period=14):
    """Wilder's smoothing (the original RSI formula, not a plain SMA of gains/losses)."""
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out

    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            avg_gain += delta
        else:
            avg_loss -= delta
    avg_gain /= period
    avg_loss /= period
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = delta if delta > 0 else 0
        loss = -delta if delta < 0 else 0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def macd(closes, fast=12, slow=26, signal_period=9):
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [
        (ema_fast[i] - ema_slow[i]) if ema_fast[i] is not None and ema_slow[i] is not None else None
        for i in range(len(closes))
    ]
    macd_values = [v if v is not None else 0 for v in macd_line]
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), -1)
    signal_line = [None] * len(closes)
    if first_valid != -1:
        signal_raw = ema(macd_values[first_valid:], signal_period)
        for i, v in enumerate(signal_raw):
            signal_line[first_valid + i] = v
    histogram = [
        (macd_line[i] - signal_line[i]) if macd_line[i] is not None and signal_line[i] is not None else None
        for i in range(len(closes))
    ]
    return {"macd_line": macd_line, "signal_line": signal_line, "histogram": histogram}


def atr(candles, period=14):
    out = [None] * len(candles)
    if len(candles) < period + 1:
        return out

    true_ranges = []
    for i in range(1, len(candles)):
        c = candles[i]
        prev_close = candles[i - 1]["close"]
        true_ranges.append(max(
            c["high"] - c["low"],
            abs(c["high"] - prev_close),
            abs(c["low"] - prev_close),
        ))

    avg = sum(true_ranges[:period]) / period
    out[period] = avg
    for i in range(period, len(true_ranges)):
        avg = (avg * (period - 1) + true_ranges[i]) / period
        out[i + 1] = avg
    return out


def bollinger_bands(closes, period=20, std_dev_mult=2):
    middle = sma(closes, period)
    upper = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        mid = middle[i]
        window = closes[i - period + 1:i + 1]
        variance = sum((v - mid) ** 2 for v in window) / period
        std_dev = math.sqrt(variance)
        upper[i] = mid + std_dev_mult * std_dev
        lower[i] = mid - std_dev_mult * std_dev
    return {"middle": middle, "upper": upper, "lower": lower}


def find_swings(candles, lookback=3):
    """A swing high/low is a local extreme relative to `lookback` candles on each side."""
    swings = []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback:i + lookback + 1]
        is_high = all(candles[i]["high"] >= c["high"] for c in window)
        is_low = all(candles[i]["low"] <= c["low"] for c in window)
        if is_high:
            swings.append({"index": i, "type": "high", "price": candles[i]["high"], "time": candles[i]["time"]})
        elif is_low:
            swings.append({"index": i, "type": "low", "price": candles[i]["low"], "time": candles[i]["time"]})
    return swings


def classify_structure(swings):
    """Classic HH/HL vs LH/LL read on the last 4 confirmed swings."""
    highs = [s for s in swings if s["type"] == "high"][-2:]
    lows = [s for s in swings if s["type"] == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return {"label": "ranging", "detail": "Pas assez de swings confirmés pour classifier la structure."}

    higher_highs = highs[1]["price"] > highs[0]["price"]
    higher_lows = lows[1]["price"] > lows[0]["price"]
    if higher_highs and higher_lows:
        return {
            "label": "uptrend",
            "detail": f"HH {highs[0]['price']:.2f}→{highs[1]['price']:.2f}, HL {lows[0]['price']:.2f}→{lows[1]['price']:.2f}",
        }
    if not higher_highs and not higher_lows:
        return {
            "label": "downtrend",
            "detail": f"LH {highs[0]['price']:.2f}→{highs[1]['price']:.2f}, LL {lows[0]['price']:.2f}→{lows[1]['price']:.2f}",
        }
    return {"label": "ranging", "detail": "Structure mixte — pas de séquence HH/HL ou LH/LL claire."}


def fibonacci_levels(swing_high, swing_low, direction):
    rng = swing_high - swing_low
    ratios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.618]
    levels = {}
    for r in ratios:
        levels[str(r)] = (swing_high - rng * r) if direction == "up" else (swing_low + rng * r)
    return {"swing_high": swing_high, "swing_low": swing_low, "direction": direction, "levels": levels}


def detect_session(now_utc=None):
    """Standard forex session windows in UTC. Kill zones and overlaps are
    derived, not guessed — session identity is a fact of the clock, never
    an LLM call."""
    now_utc = now_utc or datetime.now(timezone.utc)
    hour = now_utc.hour
    active = []
    if hour >= 22 or hour < 7:
        active.append("sydney")
    if 0 <= hour < 9:
        active.append("tokyo")
    if 8 <= hour < 17:
        active.append("london")
    if 13 <= hour < 22:
        active.append("new_york")

    overlaps = []
    if "london" in active and "new_york" in active:
        overlaps.append("london_new_york")
    if "tokyo" in active and "london" in active:
        overlaps.append("tokyo_london")

    if "london_new_york" in overlaps:
        kill_zone = "london_new_york_overlap"
    elif "london" in active and hour < 10:
        kill_zone = "london_open"
    elif "new_york" in active and hour < 15:
        kill_zone = "new_york_open"
    else:
        kill_zone = None

    return {"hour_utc": hour, "active_sessions": active, "overlaps": overlaps, "kill_zone": kill_zone}


def compute_snapshot(symbol, timeframe, candles):
    closes = [c["close"] for c in candles]
    last = len(closes) - 1

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_series = rsi(closes, 14)
    macd_result = macd(closes)
    atr_series = atr(candles, 14)
    bb = bollinger_bands(closes, 20, 2)
    swings = find_swings(candles, 3)
    structure = classify_structure(swings)
    last_high = next((s for s in reversed(swings) if s["type"] == "high"), None)
    last_low = next((s for s in reversed(swings) if s["type"] == "low"), None)

    fibonacci = None
    if last_high and last_low:
        direction = "down" if last_high["index"] > last_low["index"] else "up"
        fibonacci = fibonacci_levels(last_high["price"], last_low["price"], direction)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_count": len(candles),
        "current_price": closes[last],
        "last_candle_time": candles[last]["time"],
        "ema20": ema20[last],
        "ema50": ema50[last],
        "ema200": ema200[last],
        "rsi14": rsi_series[last],
        "macd": {"line": macd_result["macd_line"][last], "signal": macd_result["signal_line"][last], "histogram": macd_result["histogram"][last]},
        "atr14": atr_series[last],
        "bollinger": {"middle": bb["middle"][last], "upper": bb["upper"][last], "lower": bb["lower"][last]},
        "structure": structure,
        "last_swing_high": last_high,
        "last_swing_low": last_low,
        "fibonacci": fibonacci,
        "session": detect_session(),
    }


def bias_from_snapshot(snapshot):
    """A single timeframe's directional read, from data already computed for it.
    EMA50/200 gives the macro trend; structure gives the more reactive swing
    read. When they agree, that's the bias; when only one is available, use
    it; when they conflict, call it neutral rather than picking a side."""
    if not snapshot:
        return "neutral"
    ema_bias = None
    if snapshot["ema50"] is not None and snapshot["ema200"] is not None:
        ema_bias = "bullish" if snapshot["ema50"] > snapshot["ema200"] else "bearish"
    structure_label = snapshot["structure"]["label"]
    structure_bias = "bullish" if structure_label == "uptrend" else "bearish" if structure_label == "downtrend" else "neutral"
    if ema_bias and ema_bias == structure_bias:
        return ema_bias
    if ema_bias and structure_bias == "neutral":
        return ema_bias
    if not ema_bias:
        return structure_bias
    return "neutral"  # ema and structure disagree — no real reason to pick a side


# Mirrors engine_scoring.FUSION_BASE (not imported directly — indicators.py
# is imported BY engine_scoring.py, so importing back would be circular).
# Same reasoning: a pure agreement ratio (round(agreeing/total*100)) meant
# alignment_score could never exceed 60 with only 3/5 timeframes agreeing,
# and never dropped below 40 with 2/5 — confirmed live, this engine only
# ever emitted exactly 40 or 60 regardless of symbol (see
# Audit/Audit_PhaseA_Distribution_Moteurs_Directionnels). Base+additive
# gives partial agreement real room to move instead of two fixed values.
_MTF_BASE = 25


def compute_multi_timeframe_view(snapshots_by_timeframe):
    """Real confluence across timeframes — each one's bias comes from its own
    real candles, computed above."""
    timeframes = []
    for tf, s in snapshots_by_timeframe.items():
        if s is None:
            continue
        timeframes.append({
            "timeframe": tf,
            "bias": bias_from_snapshot(s),
            "current_price": s["current_price"],
            "ema50": s["ema50"],
            "ema200": s["ema200"],
            "structure": s["structure"]["label"],
        })

    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for t in timeframes:
        counts[t["bias"]] += 1

    total = len(timeframes)
    dominant_bias = max(counts.items(), key=lambda kv: kv[1])[0] if total > 0 else "neutral"
    agreement_ratio = (counts[dominant_bias] / total) if total > 0 else 0
    alignment_score = round(_MTF_BASE + agreement_ratio * (100 - _MTF_BASE)) if total > 0 else 0

    return {
        "timeframes": timeframes,
        "dominant_bias": dominant_bias,
        "alignment_score": alignment_score,
        "timeframes_analyzed": total,
    }
