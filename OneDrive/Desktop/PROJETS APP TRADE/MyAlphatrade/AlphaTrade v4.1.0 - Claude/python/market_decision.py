from __future__ import annotations

# KB7 — IA décisionnelle, module partagé.
#
# Synthèse pondérée de KB1-KB6 en un score de confiance (0-100), une qualité
# (A+/A/B/C/D) et une probabilité BUY/SELL — reprend directement l'exemple
# donné par Louis (Trend D1/H4/H1, FVG, Order Block, Fibo, Liquidity Grab,
# Momentum/RSI/MACD -> Probabilité BUY 92% / SELL 8%, "Excellent setup").
#
# Pondération décroissante du contexte global vers l'affinage (même logique
# que KB1) : KB1 (multi-timeframe) pèse le plus, KB6 (confirmations) le
# moins — "on part du contexte global, on affine progressivement".
#
# Module pur : prend en entrée un dict de signaux déjà extraits de KB1-KB6
# (pas les objets bruts) — testable isolément, sans dépendance croisée.
#
# Contrat important : kb3_zone_match / kb4_in_golden_zone / kb5_fvg_match /
# kb5_order_block_match / kb5_liquidity_grab_supportive doivent déjà être
# résolus par l'appelant RELATIVEMENT à candidate_direction (ex: "demand"
# pour bullish, "supply" pour bearish) — decision_score() ne les réinterprète
# pas. Seuls kb1_bias_strength, kb2_regime et kb5_last_event sont évalués ici
# en fonction de candidate_direction.

DEFAULT_WEIGHTS = {
    "kb1": 20,  # multi-timeframe (cascade D1->M1)
    "kb2": 15,  # structure (régime)
    "kb3": 10,  # zones (support/résistance/supply/demand/institutionnelles)
    "kb4": 10,  # fibonacci (zone d'achat privilégiée)
    "kb5": 25,  # smart money (BOS/CHOCH + FVG + Order Block + Liquidity Grab)
    "kb6": 20,  # confirmations (EMA/RSI/MACD/Momentum)
}

QUALITY_GRADES = ((85, "A+"), (70, "A"), (55, "B"), (40, "C"), (0, "D"))


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _kb1_subscore(signals: dict, sign: float) -> float:
    bias_strength = signals.get("kb1_bias_strength")
    if bias_strength is None or not signals.get("kb1_usable", True):
        return 0.0
    return _clamp((bias_strength / 100.0) * sign)


def _kb2_subscore(signals: dict, candidate_direction: str) -> float:
    regime = signals.get("kb2_regime")
    if regime == "UPTREND":
        return 1.0 if candidate_direction == "bullish" else -1.0
    if regime == "DOWNTREND":
        return 1.0 if candidate_direction == "bearish" else -1.0
    if regime == "CORRECTION":
        return -0.3
    if regime == "RANGE":
        return -0.5
    return 0.0  # COLLECTING / inconnu


def _kb3_subscore(signals: dict) -> float:
    match = signals.get("kb3_zone_match")
    return {"institutional": 1.0, "supply_demand": 0.5, "opposing": -0.5}.get(match, 0.0)


def _kb4_subscore(signals: dict) -> float:
    return 1.0 if signals.get("kb4_in_golden_zone") is True else 0.0


def _kb5_subscore(signals: dict, candidate_direction: str) -> float:
    parts = []
    event = signals.get("kb5_last_event")
    if event:
        aligned = event.get("direction") == candidate_direction
        if event.get("type") == "BOS":
            parts.append(1.0 if aligned else -1.0)
        elif event.get("type") == "CHOCH":
            parts.append(0.6 if aligned else -0.4)
    if signals.get("kb5_fvg_match"):
        parts.append(0.5)
    if signals.get("kb5_order_block_match"):
        parts.append(0.5)
    if signals.get("kb5_liquidity_grab_supportive"):
        parts.append(0.5)
    return sum(parts) / len(parts) if parts else 0.0


def _kb6_subscore(signals: dict) -> float:
    pct = signals.get("kb6_confirmation_pct")
    if pct is None:
        return 0.0
    return _clamp((pct - 50.0) / 50.0)


def decision_score(signals: dict, candidate_direction: str, weights: dict | None = None,
                    entry_threshold: float = 70.0) -> dict:
    if candidate_direction not in ("bullish", "bearish"):
        raise ValueError("candidate_direction doit etre 'bullish' ou 'bearish'")

    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_weight = sum(w.values()) or 1.0
    sign = 1.0 if candidate_direction == "bullish" else -1.0

    subscores = {
        "kb1": _kb1_subscore(signals, sign),
        "kb2": _kb2_subscore(signals, candidate_direction),
        "kb3": _kb3_subscore(signals),
        "kb4": _kb4_subscore(signals),
        "kb5": _kb5_subscore(signals, candidate_direction),
        "kb6": _kb6_subscore(signals),
    }
    weighted_sum = sum(subscores[k] * w.get(k, 0) for k in subscores)
    score = round(max(0.0, min(100.0, 50 + (weighted_sum / total_weight) * 50)), 1)
    grade = next(g for threshold, g in QUALITY_GRADES if score >= threshold)

    if candidate_direction == "bullish":
        buy_pct, sell_pct = score, round(100 - score, 1)
    else:
        sell_pct, buy_pct = score, round(100 - score, 1)

    return {
        "candidate_direction": candidate_direction,
        "subscores": {k: round(v, 3) for k, v in subscores.items()},
        "weights": w,
        "score": score,
        "grade": grade,
        "probability_buy_pct": buy_pct,
        "probability_sell_pct": sell_pct,
        "entry_authorized": score >= entry_threshold,
        "entry_threshold": entry_threshold,
    }
