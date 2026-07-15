from __future__ import annotations

# KB1 — Analyse Multi-Timeframe (cascade hiérarchique), module partagé.
#
# Contrairement à multi_timeframe_context() (agrégation à plat : tous les
# timeframes votent à égalité), la cascade compare chaque niveau au biais du
# plus haut niveau (D1) : un conflit sur D1/H4 casse la cohérence plus qu'un
# conflit sur M5/M1, grâce à une pondération décroissante par niveau.
#
# Module pur : ne dépend pas de MT5, prend en entrée des contextes déjà
# calculés (ex: par timeframe_trend_context()) — testable isolément.

CASCADE_LEVELS = ["D1", "H4", "H1", "M30", "M15", "M5", "M1"]


def _direction(trend: str) -> int:
    if trend == "BULLISH":
        return 1
    if trend == "BEARISH":
        return -1
    return 0


def multi_timeframe_cascade(level_contexts: dict, coherence_threshold_pct: float = 60.0) -> dict:
    """level_contexts: {"D1": {"trend": "BULLISH", ...}, "H4": {...}, ...}"""
    n = len(CASCADE_LEVELS)
    weights = [float(n - i) for i in range(n)]
    total_weight = sum(weights)

    root_ctx = level_contexts.get(CASCADE_LEVELS[0]) or {}
    root_trend = str(root_ctx.get("trend") or "COLLECTING")
    root_dir = _direction(root_trend)

    levels = []
    aligned_count = 0
    weighted_direction_sum = 0.0
    first_break = None

    for i, tf in enumerate(CASCADE_LEVELS):
        ctx = level_contexts.get(tf) or {}
        trend = str(ctx.get("trend") or "COLLECTING")
        direction = _direction(trend)
        weight = weights[i]
        weighted_direction_sum += direction * weight

        if direction == 0 or root_dir == 0:
            # Niveau en range, ou D1 lui-même sans biais exploitable (collecte) :
            # rien à comparer, jamais compté comme aligné (y compris D1 sur lui-même).
            status = "neutral"
        elif direction == root_dir:
            status = "aligned"
        else:
            status = "broken"
            if first_break is None and i > 0:
                first_break = tf

        if status == "aligned":
            aligned_count += 1

        levels.append({"timeframe": tf, "trend": trend, "status": status, "weight": weight})

    coherence_score = round((aligned_count / n) * 100, 1) if n else 0.0
    bias_strength = round((weighted_direction_sum / total_weight) * 100, 1) if total_weight else 0.0
    global_bias = root_trend if root_dir != 0 else "RANGE"

    return {
        "levels": levels,
        "global_bias": global_bias,
        "first_break": first_break,
        "aligned_count": aligned_count,
        "total_levels": n,
        "coherence_score": coherence_score,
        "bias_strength": bias_strength,
        "usable": coherence_score >= float(coherence_threshold_pct),
    }
