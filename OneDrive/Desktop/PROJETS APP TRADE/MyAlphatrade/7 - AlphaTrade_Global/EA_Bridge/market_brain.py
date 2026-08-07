"""
Market Brain — the orchestrator of the modular intelligence system, made
fully deterministic. No LLM anywhere: the direction is derived bottom-up
from real engine votes (engine_scoring.py), never picked first and
justified afterwards. Faithful in spirit to the removed
Dist/base44/functions/marketBrain/entry.ts (same fields, same validated-
strategy-as-supplement rule, same confidence tiers) but every number here
is computed, not guessed by a model.
"""

import logging
import time

import indicators as ind
import engine_scoring as es
import confidence_v2 as cv2
import market_regime
from market_analysis import find_order_blocks, find_fvgs
from local_store import list_entities as _list_entities

# Diagnostic-only logger (Phase A follow-up) — see engine_scoring.py's
# diag_log for the market_structure/indicator_fusion counterparts. Never
# read by any decision logic.
diag_log = logging.getLogger("engine_diagnostics")

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

# Below this, force WAIT regardless of direction. Raised 57 -> 60 on
# 2026-08-07, recalibrated against the REAL 3-asset live watchlist
# (XAUUSD/BTCUSD/ETHUSD) using fusion_backtest.py, right after fixing a
# real dilution bug in engine_scoring.py (volatility/session/economic —
# three engines that never vote a direction by design — were still
# counted in the fusion's denominator, permanently capping confidence).
# That fix alone raised every engine's effective confidence, which
# silently changed what "57" meant — the old value was calibrated against
# the pre-fix, more diluted distribution.
#
# Full 90-day real sweep post-fix (profit factor / total PnL per asset):
#   floor   XAUUSD PF   BTCUSD PF   ETHUSD PF   combined PnL (5000$ each)
#   57      1.32        0.85 (!)    1.04        +160$   <- BTCUSD LOSES money
#   60      1.10        1.20        1.24        +876$   <- all three >= 1.10
#   63      2.80        1.05        1.17        +1388$  <- best $, but only
#                                                            because XAUUSD alone
#                                                            carries BTC/ETH,
#                                                            both under the 1.2
#                                                            validation threshold
#   66      1.70        0.81 (!)    1.55        +433$
#   69      8.46 (n=6)  0.33 (!)    1.20        +256$
#
# 60 chosen over 63 deliberately: it's the only floor where all three
# actively-traded assets are individually sound (PF >= 1.10, two >= 1.20),
# not just the aggregate propped up by XAUUSD's outsized edge — a
# portfolio that only works because one asset carries the other two is a
# concentration risk, not "well-tuned". This is a single GLOBAL threshold
# shared by every symbol; it is a compromise across the current watchlist,
# not a per-asset optimum — any newly added asset should be re-validated
# with fusion_backtest.py before being trusted against this same floor.
CONFIDENCE_FLOOR = 60


def _tier_for(confidence):
    for min_conf, key, label in ACTION_TIERS:
        if confidence >= min_conf:
            return {"key": key, "label": label, "min": min_conf}
    return {"key": "none", "label": "Aucune action", "min": 0}


def _bias_to_decision(bias):
    return {"bullish": "BUY", "bearish": "SELL", "neutral": "WAIT"}[bias]


# --- Global Market Intelligence context — ACTIVATED 2026-08-02 at the
# user's explicit instruction, despite zero accumulated validation history
# in the CryptoIntelSnapshot journal (see Audit/... for the exchange where
# this trade-off was made explicit — the user was told the risk and chose
# to proceed anyway). For BTC/ETH, the real Hyperliquid signal now votes
# directly inside the fusion as the "microstructure" engine (see
# _microstructure_engine_result and ENGINE_WEIGHTS in engine_scoring.py) —
# what's left here is only the weaker, unmeasured cross-asset regime
# hypothesis (e.g. "risk-off favors gold") for everything else. Same
# principle as validated_strategy just below in analyze(): a supplement
# that can reinforce a decision, never turn a WAIT into a BUY/SELL by
# itself. Reads the last snapshot already written by the 10-minute
# background collector (see alphatg_bridge.py) instead of calling
# Hyperliquid live on every analyze() — a live call here would tie every
# single decision's latency (including for symbols with nothing to do
# with crypto) to a third-party API's availability. CRYPTO_CONTEXT_ENABLED
# is a kill switch: flip to False to fully disable without removing code.
CRYPTO_CONTEXT_ENABLED = True
CRYPTO_CONTEXT_MAX_AGE_SEC = 1800  # ignore a snapshot older than this — stale data is worse than none
MACRO_REGIME_BOOST = 5       # smaller effect for the unmeasured cross-asset regime hypothesis


def _crypto_symbol_coin(symbol):
    """BTCUSD/ETHUSD-style MT5 symbols map directly to a Hyperliquid coin —
    same underlying asset, different venue, a directly justified link.
    Everything else (XAUUSD, synthetic indices, ...) falls through to the
    much weaker/unmeasured market_regime hypothesis below."""
    s = (symbol or "").upper()
    if s.startswith("BTC"):
        return "BTC"
    if s.startswith("ETH"):
        return "ETH"
    return None


def _microstructure_engine_result(symbol):
    """Real order-flow data for BTC/ETH (Hyperliquid: OBI, funding, open
    interest — see hyperliquid_connector.py/global_market_intelligence.py)
    as a genuine voting engine, not a post-hoc bonus — see
    ENGINE_WEIGHTS["microstructure"] in engine_scoring.py. Same
    reasoning as apply_global_intelligence_context below for reading the
    last stored snapshot instead of calling Hyperliquid live here. Returns
    None for anything that isn't BTC/ETH, which correctly excludes this
    engine's weight from that symbol's fusion entirely (see
    engine_scoring.run_all_engines) instead of forcing a fake neutral vote."""
    coin = _crypto_symbol_coin(symbol)
    if not coin:
        return None
    snaps = _list_entities("CryptoIntelSnapshot", sort="-created_date", limit=1)
    if not snaps:
        return None
    snapshot = snaps[0]
    if snapshot.get("fetched_at") and (time.time() - snapshot["fetched_at"]) > CRYPTO_CONTEXT_MAX_AGE_SEC:
        return None
    coin_data = (snapshot.get("sources") or {}).get("crypto", {}).get(coin)
    if not coin_data:
        return None
    pressure = coin_data.get("pressure")
    if pressure in (None, "unknown"):
        return None
    coin_score = (snapshot.get("crypto_intelligence_score") or {}).get("per_coin", {}).get(coin, {})
    confidence = coin_score.get("score", 50)
    obi = (coin_data.get("order_book") or {}).get("obi")
    obi_str = f"{obi:.2f}" if obi is not None else "n/d"
    return {
        "id": "microstructure", "bias": pressure, "confidence": confidence,
        "findings": [f"Hyperliquid {coin}: OBI {obi_str}, funding {coin_data.get('funding_rate')}, OI {coin_data.get('open_interest') or 0:.0f}"],
    }


def apply_global_intelligence_context(decision, confidence, symbol, decision_bias):
    if not CRYPTO_CONTEXT_ENABLED or decision == "WAIT":
        return decision, confidence, "none"

    if _crypto_symbol_coin(symbol):
        # Real Hyperliquid data for this symbol already voted as a genuine
        # weighted engine (see _microstructure_engine_result, applied
        # BEFORE fusion) — applying the same signal again here as a bonus
        # would double-count it. Only the macro-regime hypothesis below
        # (for symbols with no direct microstructure engine of their own)
        # still applies as a supplement.
        return decision, confidence, "handled_by_microstructure_engine"

    snaps = _list_entities("CryptoIntelSnapshot", sort="-created_date", limit=1)
    if not snaps:
        return decision, confidence, "no_data"
    snapshot = snaps[0]
    if snapshot.get("fetched_at") and (time.time() - snapshot["fetched_at"]) > CRYPTO_CONTEXT_MAX_AGE_SEC:
        return decision, confidence, "stale"

    # Non-crypto symbol: the cross-asset regime link (e.g. "risk-off favors
    # gold") is a hypothesis, not something measured for this system yet —
    # kept deliberately weaker (smaller boost, never a veto) than the
    # direct same-asset microstructure engine above.
    regime = snapshot.get("market_regime")
    if regime == "risk_off" and decision_bias == "bullish":
        return decision, min(100, confidence + MACRO_REGIME_BOOST), "risk_off_context"
    if regime == "risk_on" and decision_bias == "bearish":
        return decision, min(100, confidence + MACRO_REGIME_BOOST), "risk_on_context"
    return decision, confidence, "neutral"


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
    ctx = es.build_context(candles, symbol=symbol)

    # Market Regime AI (2026-08-07) — this instrument's own current
    # technical regime (trend/range/transition + volatility), computed from
    # the SAME primary-timeframe candles already fetched. Context only: see
    # market_regime.py's module docstring for why this doesn't yet touch
    # engine weights or the decision itself.
    regime = market_regime.classify_market_regime(candles)

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
        per_tf = ", ".join(f"{t['timeframe']}={t['bias']}@{t['current_price']:.2f}" for t in mtf_view["timeframes"])
        diag_log.info(
            "multi_timeframe symbol=%s per_tf=[%s] dominant_bias=%s confidence=%s",
            symbol, per_tf, mtf_engine_result["bias"], mtf_engine_result["confidence"],
        )

    microstructure_result = _microstructure_engine_result(symbol) if CRYPTO_CONTEXT_ENABLED else None
    engine_results = es.run_all_engines(ctx, multi_timeframe_result=mtf_engine_result, microstructure_result=microstructure_result)
    fusion = es.fuse_direction_and_confidence(engine_results)
    breakdown = fusion["breakdown"]

    # --- AI Confidence Engine v2 — comparison mode only, NOT activated. ---
    # Computed in parallel from the same engine_results/ctx, but never fed
    # back into `decision`, `confidence`, the Entry Planner or the
    # Autonomous Trading Engine. Purely observational fields exposed below
    # (confidence_v1/v2, direction_score, setup_quality_score,
    # market_condition_score) so old vs new can be compared live without
    # any behavior change. See confidence_v2.py.
    v2_direction = cv2.calculate_direction_score(engine_results)
    v2_setup = cv2.calculate_setup_quality_score(ctx, engine_results)
    v2_condition = cv2.calculate_market_condition_score(ctx)
    v2_final_confidence = cv2.calculate_final_confidence(
        v2_direction["score"], v2_setup["score"], v2_condition["score"]
    )

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

    decision, confidence, crypto_context = apply_global_intelligence_context(decision, confidence, symbol, fusion["direction"])

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

    # "agree"/"conflict" no longer occur here for BTC/ETH — that signal now
    # votes directly inside the fusion via the microstructure engine (see
    # engine_results/breakdown above), so only the weaker macro-regime
    # supplement (for non-crypto symbols) still needs an explanation note.
    crypto_context_notes = {
        "risk_off_context": f" Régime de marché global risk-off (+{MACRO_REGIME_BOOST}, hypothèse non validée statistiquement).",
        "risk_on_context": f" Régime de marché global risk-on (+{MACRO_REGIME_BOOST}, hypothèse non validée statistiquement).",
    }
    crypto_note = crypto_context_notes.get(crypto_context, "")

    entry_plan_note = ""
    if decision != "WAIT" and pending_zone is not None:
        if entry_type == "immediate":
            entry_plan_note = ""
        elif entry_type == "pending_order":
            entry_plan_note = f" Entrée différée à {ideal_entry:.2f} ({pending_zone['distance_atr']:.1f} ATR du prix actuel) plutôt qu'au marché."
        else:
            entry_plan_note = f" Zone la plus proche à {ideal_entry:.2f} ({pending_zone['distance_atr']:.1f} ATR) — trop loin pour un ordre en attente, en attente que le prix se rapproche."

    if decision == "WAIT":
        reason = "aucun consensus directionnel suffisant entre les moteurs" if confidence < CONFIDENCE_FLOOR else "conflit avec la stratégie validée ou le contexte de marché"
        explanation = f"WAIT — {reason} (confiance fusionnée {confidence}%).{strategy_note}{crypto_note}"
    else:
        engines_favorable = ", ".join(r["findings"][0] for r in supporting[:3]) if supporting else "aucun détail"
        explanation = f"{decision} avec {confidence}% de confiance. Moteurs favorables : {engines_favorable}.{strategy_note}{crypto_note}{entry_plan_note}"

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
        "crypto_context": crypto_context,
        "market_regime": regime,
        "tier": tier,
        "fused_confidence": fusion["confidence"],
        # --- Comparison mode (AI Confidence Engine v2 prep, not active) ---
        "confidence_v1": confidence,
        "confidence_v2": v2_final_confidence,
        "direction_score": v2_direction["score"],
        "setup_quality_score": v2_setup["score"],
        "market_condition_score": v2_condition["score"],
    }
