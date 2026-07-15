from __future__ import annotations

# KB6 — Confirmations, module partagé.
#
# Contrairement à AlphaTrade AI (où EMA/RSI/MACD/Momentum sont le cœur du
# score de décision), ici ils ne servent qu'à confirmer ou rejeter un signal
# déjà identifié par KB1-KB5 (structure + zones + Fibonacci + Smart Money).
# Chaque indicateur vote simplement "d'accord" / "pas d'accord" avec la
# direction candidate ; `min_confirmations` fixe combien de votes sur 4 sont
# nécessaires pour considérer le signal confirmé.
#
# Module pur : reprend les mêmes formules EMA/RSI qu'AlphaTrade AI
# (alphatrade_engine.ema/rsi) mais dupliquées ici pour rester indépendant de
# MT5 et de l'engine — testable isolément, sans dépendance croisée.


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return values[-1]
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in deltas[-period:]]
    losses = [max(-x, 0) for x in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def confirmations(closes: list[float], candidate_direction: str, min_confirmations: int = 3,
                   rsi_period: int = 14, momentum_lookback: int = 8) -> dict:
    """candidate_direction: "bullish" ou "bearish" (issu de KB1-KB5, ex: direction
    d'un BOS/CHOCH, ou du biais global de la cascade KB1)."""
    if candidate_direction not in ("bullish", "bearish"):
        return {"direction": candidate_direction, "checks": {}, "confirmed_count": 0,
                "total": 4, "confirmation_pct": 0.0, "confirmed": False, "min_confirmations": min_confirmations}

    e9, e21, e50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    rv = rsi(closes, rsi_period)
    macd = ema(closes, 12) - ema(closes, 26)
    lookback = min(momentum_lookback, max(1, len(closes) - 1))
    momentum = closes[-1] - closes[-1 - lookback] if len(closes) > lookback else 0.0

    bullish = candidate_direction == "bullish"
    checks = {
        "ema": (e9 > e21 > e50) if bullish else (e9 < e21 < e50),
        "rsi": (rv > 50) if bullish else (rv < 50),
        "macd": (macd > 0) if bullish else (macd < 0),
        "momentum": (momentum > 0) if bullish else (momentum < 0),
    }
    confirmed_count = sum(1 for v in checks.values() if v)
    total = len(checks)

    return {
        "direction": candidate_direction,
        "checks": checks,
        "values": {"ema9": round(e9, 5), "ema21": round(e21, 5), "ema50": round(e50, 5),
                   "rsi": round(rv, 1), "macd": round(macd, 5), "momentum": round(momentum, 5)},
        "confirmed_count": confirmed_count,
        "total": total,
        "confirmation_pct": round(confirmed_count / total * 100, 1) if total else 0.0,
        "confirmed": confirmed_count >= min_confirmations,
        "min_confirmations": min_confirmations,
    }
