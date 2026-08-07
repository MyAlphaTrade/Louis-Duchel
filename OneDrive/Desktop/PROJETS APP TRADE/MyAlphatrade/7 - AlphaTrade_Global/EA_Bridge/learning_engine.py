"""
AI Trade Memory — Module 3 of the professional transformation plan.

Turns LearningData from a write-only box into a real per-trade analysis.
Before this file: every closed trade wrote outcome + a generic conditions
list, with "errors"/"lessons"/"accuracy_delta" hard-coded empty/zero,
forever — the professional audit (2026-08-06) found this was the only
consumer of LearningData too (score_ai_learning(), a raw win-rate display,
never fed back into anything). This module answers the actually useful
question: which engines agreed with the trade that was taken, and what
conditions (market regime) surrounded it — per trade, then aggregated.

Status as of 2026-08-07: analysis and aggregation only. pattern_win_rates()
is a read/diagnostic, exactly like score_ai_learning() before it — NOT
wired into market_brain.analyze() to influence confidence, strategy
selection, or risk. Same principle as market_regime.py: a pattern needs
proof on fusion_backtest.py before it's allowed to change a live decision,
and with only a few hundred trades logged so far, nothing here has
anywhere near enough sample size to trust blindly regardless.
"""

from local_store import list_entities

MIN_PATTERN_SAMPLES = 20  # same statistical bar as strategy_validator.DEFAULT_THRESHOLDS' min_trades


def _dominant_engines(engine_results, direction):
    """Engines that actually agreed with the direction taken, ranked by
    confidence — the same ranking principle market_brain.py already uses
    for its `rationale` field, just kept alongside the trade instead of
    discarded once the decision is made."""
    if not engine_results:
        return []
    bias = "bullish" if direction == "BUY" else "bearish"
    agreeing = [(eid, r) for eid, r in engine_results.items() if r.get("bias") == bias]
    agreeing.sort(key=lambda kv: kv[1].get("confidence", 0), reverse=True)
    return [eid for eid, _r in agreeing[:4]]


def _opposing_engines(engine_results, direction):
    if not engine_results:
        return []
    bias = "bearish" if direction == "BUY" else "bullish"
    return [eid for eid, r in engine_results.items() if r.get("bias") == bias]


def analyze_trade(trade, signal, outcome):
    """trade: the closed Trade entity. signal: the Signal entity that
    triggered it, or None — a manually-opened position discovered by
    reconciliation never went through autoExecute() and has no Signal to
    look at, which is itself worth recording, not silently skipped.
    outcome: "win"/"loss"/"breakeven".

    Returns the LearningData fields this trade should be recorded with.
    Never persists anything itself — the caller (trade_manager_close_trade)
    still owns that, same as before this module existed."""
    engine_results = (signal or {}).get("engine_results") or {}
    direction = trade.get("direction")
    regime_info = (signal or {}).get("market_regime") or {}
    regime = regime_info.get("regime")

    dominant = _dominant_engines(engine_results, direction)
    opposing = _opposing_engines(engine_results, direction)

    patterns_detected = [f"dominant:{eid}" for eid in dominant]
    if regime:
        patterns_detected.append(f"regime:{regime}")

    lessons, successful_conditions, failed_conditions = [], [], []
    if outcome == "win":
        if dominant:
            successful_conditions.append(f"Moteurs dominants alignés : {', '.join(dominant)}")
            lessons.append(f"Gagné avec {', '.join(dominant)} alignés" + (f", régime {regime}" if regime else ""))
        if opposing:
            lessons.append(f"Gagné malgré {', '.join(opposing)} en désaccord au moment de l'entrée — à surveiller si ça se reproduit souvent")
    elif outcome == "loss":
        if opposing:
            failed_conditions.append(f"Moteurs en désaccord ignorés à l'entrée : {', '.join(opposing)}")
            lessons.append(f"Perdu avec {', '.join(opposing)} déjà en désaccord au moment de l'entrée")
        elif dominant:
            failed_conditions.append(f"Perdu malgré l'accord de : {', '.join(dominant)}")
            lessons.append(f"Perdu malgré {', '.join(dominant)} alignés" + (f", régime {regime}" if regime else "") + " — le signal seul ne suffit pas toujours")
        if regime:
            failed_conditions.append(f"Régime au moment de l'entrée : {regime}")

    if not signal:
        lessons.append("Aucun Signal lié à ce trade — position ouverte manuellement ou par un EA externe, découverte par réconciliation ; analyse limitée aux données du Trade lui-même.")

    return {
        "patterns_detected": patterns_detected,
        "lessons": lessons,
        "successful_conditions": successful_conditions,
        "failed_conditions": failed_conditions,
    }


def pattern_win_rates(min_samples=MIN_PATTERN_SAMPLES):
    """Aggregates every LearningData record's patterns_detected tags into a
    per-pattern win rate — e.g. {"dominant:smart_money": {"trades": 34,
    "win_rate": 61.8}} — only for tags that have reached min_samples, so a
    2-trade fluke never masquerades as a real pattern. Read-only
    diagnostic, like score_ai_learning() — see this module's docstring for
    why it isn't fed back into any live decision yet."""
    records = list_entities("LearningData", sort="-created_date", limit=1000)
    counts = {}
    for r in records:
        outcome = r.get("outcome")
        if outcome not in ("win", "loss"):
            continue
        for tag in (r.get("patterns_detected") or []):
            c = counts.setdefault(tag, {"trades": 0, "wins": 0})
            c["trades"] += 1
            if outcome == "win":
                c["wins"] += 1
    return {
        tag: {"trades": c["trades"], "win_rate": round(c["wins"] / c["trades"] * 100, 1)}
        for tag, c in counts.items()
        if c["trades"] >= min_samples
    }
