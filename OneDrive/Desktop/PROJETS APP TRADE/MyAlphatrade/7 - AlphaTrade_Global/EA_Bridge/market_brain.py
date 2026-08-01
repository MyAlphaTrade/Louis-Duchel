"""
Market Brain — the orchestrator of the modular intelligence system, made
fully deterministic. No LLM anywhere: the direction is derived bottom-up
from real engine votes (engine_scoring.py), never picked first and
justified afterwards. Faithful in spirit to the removed
Dist/base44/functions/marketBrain/entry.ts (same fields, same validated-
strategy-as-supplement rule, same confidence tiers) but every number here
is computed, not guessed by a model.
"""

import indicators as ind
import engine_scoring as es
from market_analysis import find_order_blocks, find_fvgs

# Beyond this many ATRs from the nearest real zone, a pending order isn't
# worth placing — price may never come back, and it wouldn't be a plan
# grounded in structure anymore, just a guess.
PENDING_ORDER_MAX_ATR = 1.5
# Below this, price is already close enough that waiting only risks paying
# a worse price than acting now — treat it as "there", not "approaching".
IMMEDIATE_ENTRY_MAX_ATR = 0.15

ACTION_TIERS = [
    (90, "premium", "Configuration premium"),
    (75, "potential", "Signal potentiel"),
    (60, "observation", "Observation"),
    (0, "none", "Aucune action"),
]

CONFIDENCE_FLOOR = 60  # below this, force WAIT regardless of direction — mirrors the old resolveDecision()


def _tier_for(confidence):
    for min_conf, key, label in ACTION_TIERS:
        if confidence >= min_conf:
            return {"key": key, "label": label, "min": min_conf}
    return {"key": "none", "label": "Aucune action", "min": 0}


def _bias_to_decision(bias):
    return {"bullish": "BUY", "bearish": "SELL", "neutral": "WAIT"}[bias]


def select_timeframe(multi_tf_view):
    """Deterministic replacement for the old LLM timeframe picker: choose
    the timeframe whose own bias agrees with the dominant multi-timeframe
    bias (real confluence), preferring the most reactive (shortest) one
    among ties so entries aren't needlessly delayed."""
    if not multi_tf_view or multi_tf_view["timeframes_analyzed"] == 0:
        return "H1", "Aucune donnée multi-timeframe — repli sur H1 par défaut."
    dominant = multi_tf_view["dominant_bias"]
    order = ["M5", "M15", "H1", "H4", "D1"]
    agreeing = [t["timeframe"] for t in multi_tf_view["timeframes"] if t["bias"] == dominant]
    if not agreeing:
        return "H1", "Aucun timeframe ne confirme un biais dominant clair — repli sur H1."
    chosen = next((tf for tf in order if tf in agreeing), agreeing[0])
    return chosen, f"Timeframe {chosen} choisi — confirme le biais dominant {dominant} ({multi_tf_view['alignment_score']}% d'alignement)."


def _find_pending_entry_zone(ctx, atr_val, decision_bias):
    """Where would a professional trader place a resting order instead of
    paying the current price? Looks at the same real zones Smart Money and
    Fibonacci already compute, but — unlike those engines' own confidence
    scoring — does NOT require price to already be at the zone. Distance is
    exactly what this function exists to measure, in ATR multiples, so
    analyze() can decide immediate vs pending vs "too far to plan around".
    Kept fully separate from engine_scoring.py: this never touches the
    weighted vote or confidence math, only which price to enter at once a
    direction is already decided."""
    candles = ctx["candles"]
    price = candles[-1]["close"]
    kind = "bullish" if decision_bias == "bullish" else "bearish" if decision_bias == "bearish" else None
    if kind is None or not atr_val:
        return None

    fvgs = [f for f in find_fvgs(candles) if not f["filled"] and f["type"] == kind]
    obs = [o for o in find_order_blocks(candles, ctx["atr14"]) if not o["mitigated"] and o["type"] == kind]
    candidates = []
    for z in fvgs + obs:
        # The edge closest to current price — top of a demand zone below
        # price, bottom of a supply zone above it — is the level that would
        # actually get filled first, not the far edge of the zone.
        edge = z["top"] if kind == "bullish" else z["bottom"]
        if (kind == "bullish" and edge <= price) or (kind == "bearish" and edge >= price):
            candidates.append(edge)

    swings = ctx["swings"]
    last_high = next((s for s in reversed(swings) if s["type"] == "high"), None)
    last_low = next((s for s in reversed(swings) if s["type"] == "low"), None)
    if last_high and last_low:
        direction = "down" if last_high["index"] > last_low["index"] else "up"
        fib = ind.fibonacci_levels(last_high["price"], last_low["price"], direction)
        golden = fib["levels"]["0.618"]
        if (kind == "bullish" and golden <= price) or (kind == "bearish" and golden >= price):
            candidates.append(golden)

    if not candidates:
        return None
    nearest = min(candidates, key=lambda p: abs(price - p))
    return {"price": nearest, "distance_atr": abs(price - nearest) / atr_val}


def _find_actionable_zone(breakdown, decision_bias):
    """Reuses the smart_money/fibonacci reads already computed for
    entry_planner to decide immediate vs pending-order entry."""
    for engine_id in ("smart_money", "fibonacci"):
        r = breakdown.get(engine_id)
        if r and r["bias"] == decision_bias and r["confidence"] >= 50:
            return engine_id, r
    return None, None


def analyze(symbol, timeframe, candles, multi_tf_candles=None, validated_strategy=None, capital=1000, risk_percent=1):
    """
    candles: primary-timeframe candle list (oldest→newest, real MT5 data)
    multi_tf_candles: {timeframe: candles} for confluence (D1/H4/H1/M15/M5)
    validated_strategy: {"strategy_name": str, "signal": {"direction","rationale"}|None,
                          "stats": {...}} or None — the live-evaluated active Strategy
    """
    snapshot = ind.compute_snapshot(symbol, timeframe, candles)
    ctx = es.build_context(candles)

    mtf_view = None
    if multi_tf_candles:
        snapshots = {tf: ind.compute_snapshot(symbol, tf, c) for tf, c in multi_tf_candles.items() if c}
        mtf_view = ind.compute_multi_timeframe_view(snapshots)

    mtf_engine_result = None
    if mtf_view:
        mtf_engine_result = {
            "bias": mtf_view["dominant_bias"],
            "confidence": mtf_view["alignment_score"],
            "findings": [f"{mtf_view['timeframes_analyzed']} timeframes analysés, {mtf_view['alignment_score']}% alignés sur {mtf_view['dominant_bias']}"],
        }

    engine_results = es.run_all_engines(ctx, multi_timeframe_result=mtf_engine_result)
    fusion = es.fuse_direction_and_confidence(engine_results)
    breakdown = fusion["breakdown"]

    decision = _bias_to_decision(fusion["direction"])
    confidence = fusion["confidence"]
    if confidence < CONFIDENCE_FLOOR:
        decision = "WAIT"

    # The validated strategy is a supplement, never the sole trigger: it can
    # only reinforce a decision the engines already reached, or veto one
    # they got wrong — it never turns a WAIT into a BUY/SELL by itself.
    strategy_agreement = "none"
    if validated_strategy:
        signal = validated_strategy.get("signal")
        if not signal:
            strategy_agreement = "no_signal"
        elif decision != "WAIT" and signal["direction"] == decision:
            strategy_agreement = "agree"
            confidence = min(100, confidence + 5)
        elif decision != "WAIT" and signal["direction"] != decision:
            strategy_agreement = "conflict"
            confidence = min(confidence, 40)
            decision = "WAIT"

    tier = _tier_for(confidence)
    current_price = snapshot["current_price"]
    atr_val = snapshot["atr14"] or (current_price * 0.001)

    entry_type, entry_zone_low, entry_zone_high, ideal_entry = "wait_confirmation", None, None, None
    stop_loss = take_profit_1 = take_profit_2 = break_even = None
    decision_bias = fusion["direction"]

    pending_zone = None
    if decision != "WAIT":
        zone_engine, zone = _find_actionable_zone(breakdown, decision_bias)
        pending_zone = _find_pending_entry_zone(ctx, atr_val, decision_bias)

        if pending_zone is None or pending_zone["distance_atr"] <= IMMEDIATE_ENTRY_MAX_ATR:
            # No real zone to plan around, or price is already there — an
            # immediate entry is the honest read of the situation.
            ideal_entry = current_price
            entry_type = "immediate"
        elif pending_zone["distance_atr"] <= PENDING_ORDER_MAX_ATR:
            # A real order block, FVG or golden pocket sits close enough to
            # be worth waiting for — plan the entry there instead of paying
            # the current, worse price. The bridge classifies this as a
            # LIMIT or STOP order on its own by comparing this price to the
            # current one (see alphatg_bridge.py send_pending_order).
            ideal_entry = pending_zone["price"]
            entry_type = "pending_order"
        else:
            # The only real zone is too far to plan around honestly — an
            # order placed there might never fill, and entering now would
            # mean ignoring the very structure that justified the decision.
            # Keep the directional call (BUY/SELL) and the planned level for
            # the record (entry_type, not ideal_entry, is what gates whether
            # the frontend actually sends an order), but send nothing this
            # cycle; next cycle re-evaluates as price moves.
            ideal_entry = pending_zone["price"]
            entry_type = "wait_confirmation"

        sl_mult, tp1_mult, tp2_mult = 1.5, 3.0, 5.0
        if decision == "BUY":
            stop_loss = ideal_entry - atr_val * sl_mult
            take_profit_1 = ideal_entry + atr_val * tp1_mult
            take_profit_2 = ideal_entry + atr_val * tp2_mult
            break_even = ideal_entry + (take_profit_1 - ideal_entry) * 0.5
        else:
            stop_loss = ideal_entry + atr_val * sl_mult
            take_profit_1 = ideal_entry - atr_val * tp1_mult
            take_profit_2 = ideal_entry - atr_val * tp2_mult
            break_even = ideal_entry - (ideal_entry - take_profit_1) * 0.5
        entry_zone_low, entry_zone_high = min(ideal_entry, stop_loss), max(ideal_entry, take_profit_1)

    # Explanation assembled from real findings, ranked by (engine weight × confidence).
    supporting = sorted(
        (r for r in breakdown.values() if r["bias"] == decision_bias and decision_bias != "neutral"),
        key=lambda r: r["weight"] * r["confidence"], reverse=True,
    )
    rationale = [f for r in supporting[:4] for f in r["findings"][:1]]
    if not rationale:
        rationale = [f for r in sorted(breakdown.values(), key=lambda r: r["weight"], reverse=True)[:3] for f in r["findings"][:1]]

    strategy_note = ""
    if validated_strategy:
        vs_name = validated_strategy["strategy_name"]
        if strategy_agreement == "agree":
            strategy_note = f" La stratégie validée « {vs_name} » confirme cette direction (+5 de confiance)."
        elif strategy_agreement == "conflict":
            strategy_note = f" La stratégie validée « {vs_name} » contredit ce signal — décision ramenée à WAIT par prudence."
        elif strategy_agreement == "no_signal":
            strategy_note = f" La stratégie validée « {vs_name} » n'émet aucun signal sur cette bougie."

    entry_plan_note = ""
    if decision != "WAIT" and pending_zone is not None:
        if entry_type == "immediate":
            entry_plan_note = ""
        elif entry_type == "pending_order":
            entry_plan_note = f" Entrée différée à {ideal_entry:.2f} ({pending_zone['distance_atr']:.1f} ATR du prix actuel) plutôt qu'au marché."
        else:
            entry_plan_note = f" Zone la plus proche à {ideal_entry:.2f} ({pending_zone['distance_atr']:.1f} ATR) — trop loin pour un ordre en attente, en attente que le prix se rapproche."

    if decision == "WAIT":
        reason = "aucun consensus directionnel suffisant entre les moteurs" if confidence < CONFIDENCE_FLOOR else "conflit avec la stratégie validée"
        explanation = f"WAIT — {reason} (confiance fusionnée {confidence}%).{strategy_note}"
    else:
        engines_favorable = ", ".join(r["findings"][0] for r in supporting[:3]) if supporting else "aucun détail"
        explanation = f"{decision} avec {confidence}% de confiance. Moteurs favorables : {engines_favorable}.{strategy_note}{entry_plan_note}"

    invalidation = None
    if decision != "WAIT" and stop_loss is not None:
        invalidation = f"Scénario invalidé si le prix clôture au-delà du stop ({stop_loss:.2f})."

    scenario_label = "Continuation" if decision != "WAIT" else "Attente"
    scenarios = [{
        "label": scenario_label,
        "probability": confidence,
        "direction": decision,
        "description": explanation,
    }]

    opposing_ids = [eid for eid, r in breakdown.items() if r["bias"] not in ("neutral", decision_bias)] if decision_bias != "neutral" else []
    conflicts = []
    if opposing_ids:
        conflicts.append({
            "engines": opposing_ids,
            "description": f"{len(opposing_ids)} moteur(s) en désaccord avec la décision {decision_bias}.",
            "resolution": f"Direction retenue par poids×confiance cumulés ({decision_bias} l'emporte).",
        })

    return {
        "symbol": symbol,
        "decision": decision,
        "confidence": confidence,
        "current_price": current_price,
        "timeframe": timeframe,
        "entry_type": entry_type,
        "entry_zone_low": entry_zone_low,
        "entry_zone_high": entry_zone_high,
        "ideal_entry": ideal_entry,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "break_even": break_even,
        "explanation": explanation,
        "probable_scenario": explanation,
        "invalidation": invalidation,
        "rationale": rationale,
        "scenarios": scenarios,
        "engine_results": {eid: {"confidence": r["confidence"], "bias": r["bias"], "findings": r["findings"]} for eid, r in breakdown.items()},
        "conflicts": [{"engines": [r0["id"] if False else eid for eid in [e]], "description": "", "resolution": ""} for e in []],
        "multi_timeframe_view": mtf_view,
        "validated_strategy_agreement": strategy_agreement,
        "tier": tier,
        "fused_confidence": fusion["confidence"],
    }
