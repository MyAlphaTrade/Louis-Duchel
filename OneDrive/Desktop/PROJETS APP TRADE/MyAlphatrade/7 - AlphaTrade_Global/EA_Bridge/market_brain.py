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
import hyperliquid_connector
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

# Task #96 — momentum catch-up for entry_type, opt-in (use_momentum_catchup
# =False everywhere, testing in progress). Real finding, 2026-08-13: replayed
# real production decisions and found XAUUSD BUY targeting a pending zone at
# 4356.84 while price ran continuously AWAY from it for hours (4360 -> 4364
# -> 4358 -> 4394 -> 4413 -> 4422 -> 4433, ~5 real ATRs of net displacement)
# — the zone-only logic above has no fallback: a real, sustained, in-favor
# move that never pulls back to the ideal zone just gets re-targeted forever,
# never taken. MOMENTUM_DISPLACEMENT_LOOKBACK/MIN_ATR below define a second,
# independent path to "immediate": real recent price displacement in the
# decision's own direction, regardless of distance to any zone — the move
# itself is treated as the validation a clean setup would otherwise provide.
#
# MIN_ATR=3.0 (not the original 1.5, see analyze()'s own docstring for the
# real walk-forward numbers behind this choice): 1.5 fired too often and
# came back net negative, same pattern as the three invalidated experiments
# elsewhere in this file; 3.0 — closer to the real incident's ~5 ATR
# magnitude, a genuinely rare and decisive signal — came back net positive
# on real H1 data, though modest and uneven across symbols/windows.
MOMENTUM_DISPLACEMENT_LOOKBACK = 10
MOMENTUM_DISPLACEMENT_MIN_ATR = 3.0

# Dynamic lot sizing for Scalping (2026-08-13, real trader spec — Louis,
# explicit: "je ne voudrais pas que ce soit un lot fixe"). The lot must NOT
# be a flat fraction of capital: it scales UP when confidence is genuinely
# high AND the instrument is in a real volatility expansion (more real $ per
# pip available to capture on a fast move), and scales DOWN otherwise.
# Different application from use_regime_modulation above (which modulates
# ENGINE CONFIDENCE WEIGHTS and was invalidated, -37% PnL, 2026-08-07) — this
# modulates POSITION SIZE only, the decision/confidence itself is never
# touched by it. ACTIVE for Scalping only (profile_key="scalping"), not an
# opt-in experiment flag like the ones above — real trader spec. Not yet
# walk-forward tested at the time this was written; validate via
# profile_backtest.py before treating the exact multiplier values as final,
# same discipline as everything else in this file.
DYNAMIC_LOT_CONFIDENCE_MIN_MULT = 0.7   # at the profile's own min_confidence floor
DYNAMIC_LOT_CONFIDENCE_MAX_MULT = 1.6   # at confidence = 100
# Reuses market_regime.py's own volatility classification (same
# VOLATILITY_EXPANSION_RATIO/COMPRESSION_RATIO thresholds already tested
# there) — applied here to position size instead of engine weights.
DYNAMIC_LOT_VOLATILITY_MULT = {"expansion": 1.3, "normal": 1.0, "compression": 0.7}


def _dynamic_risk_multiplier(confidence, min_confidence, volatility):
    """confidence/min_confidence in the same 0-100 scale as everywhere else
    in this file. Returns a multiplier to apply to a profile's own BASE
    risk_percent — never the risk_percent itself, so a caller with no
    dynamic-sizing concept can still ignore this and use the flat base."""
    span = max(1, 100 - min_confidence)
    conf_frac = max(0.0, min(1.0, (confidence - min_confidence) / span))
    conf_mult = DYNAMIC_LOT_CONFIDENCE_MIN_MULT + conf_frac * (DYNAMIC_LOT_CONFIDENCE_MAX_MULT - DYNAMIC_LOT_CONFIDENCE_MIN_MULT)
    vol_mult = DYNAMIC_LOT_VOLATILITY_MULT.get(volatility, 1.0)
    return conf_mult * vol_mult

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

# Microstructure engine confidence (2026-08-14, real investigation, Louis:
# "pourquoi les positions sur SOL/BTC ne se déclenchent presque jamais").
# This used to read confidence from CryptoIntelSnapshot's
# crypto_intelligence_score.per_coin[coin].score — a composite 0-100 "how
# EXTREME is the current condition" reading from global_market_intelligence.py.
# That module's own docstring says explicitly: "OBSERVATION ONLY... does
# not touch decision.confidence... stays observational until measured
# against real outcomes" — its normalizers are calibrated against
# genuinely extreme reference points (e.g. a 5%+ daily move counted as
# "maximal" momentum), so under normal conditions it naturally sits low
# REGARDLESS of whether the directional read itself is real. Confirmed on
# 319 real BTC snapshots: median score 16, max ever recorded 47 — while
# `pressure` (the actual bias this engine votes) was directionally
# non-neutral 79% of the time in the same sample. Using that score as this
# engine's own confidence dragged BTC/ETH's fused confidence down
# structurally for a reason unrelated to real signal quality — this is the
# highest-weighted engine of all (15, engine_scoring.ENGINE_WEIGHTS).
#
# Fixed: confidence now comes directly from the SAME real order-book
# imbalance (OBI) that `pressure` itself is derived from
# (hyperliquid_connector.OBI_PRESSURE_THRESHOLD=0.15 is the bare minimum
# |OBI| for a directional read at all) — scaled linearly from that
# threshold (base confidence) to a fully one-sided book, |OBI|=1.0 (max
# confidence). A genuine measure of how strongly the order book leans
# right now, not how extreme today's broader market conditions are.
MICROSTRUCTURE_CONFIDENCE_BASE = 35
MICROSTRUCTURE_CONFIDENCE_MAX = 85


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
    obi = (coin_data.get("order_book") or {}).get("obi")
    if obi is None:
        # pressure was derived from this same obi (hyperliquid_connector.
        # _pressure_from_obi) — if it's now missing, the pressure read
        # itself isn't trustworthy either; don't vote on stale/partial data.
        return None
    threshold = hyperliquid_connector.OBI_PRESSURE_THRESHOLD
    span = max(1e-9, 1.0 - threshold)
    frac = max(0.0, min(1.0, (abs(obi) - threshold) / span))
    confidence = round(MICROSTRUCTURE_CONFIDENCE_BASE + frac * (MICROSTRUCTURE_CONFIDENCE_MAX - MICROSTRUCTURE_CONFIDENCE_BASE))
    obi_str = f"{obi:.2f}"
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


def select_timeframe(multi_tf_view, allowed=None, fallback="H1"):
    """Deterministic replacement for the old LLM timeframe picker: choose
    the timeframe whose own bias agrees with the dominant multi-timeframe
    bias (real confluence), preferring the most reactive (shortest) one
    among ties so entries aren't needlessly delayed.

    allowed: optional ordered list restricting the candidate timeframes to
    a profile's real scope (Task #90 — audit found Scalping/Intraday/Swing
    never got adaptive selection at all, always a single hardcoded
    default_timeframe; only the separate "Auto" profile ever called this
    function). None (unchanged) keeps the full real range — exact prior
    behavior for the "auto" profile, which stays unscoped.
    fallback: timeframe returned when there's no multi-timeframe data, or
    none of `allowed` confirms the dominant bias. Defaults to "H1"
    (unchanged prior behavior) — callers that scope `allowed` should also
    pass their own profile's proven-safe default here instead.
    """
    order = list(allowed) if allowed else ["M5", "M15", "H1", "H4", "D1"]
    if not multi_tf_view or multi_tf_view["timeframes_analyzed"] == 0:
        return fallback, f"Aucune donnée multi-timeframe — repli sur {fallback} par défaut."
    dominant = multi_tf_view["dominant_bias"]
    agreeing = [t["timeframe"] for t in multi_tf_view["timeframes"] if t["bias"] == dominant and t["timeframe"] in order]
    if not agreeing:
        return fallback, f"Aucun timeframe autorisé ({', '.join(order)}) ne confirme le biais dominant {dominant} — repli sur {fallback}."
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


def analyze(symbol, timeframe, candles, multi_tf_candles=None, validated_strategy=None, capital=1000, risk_percent=1,
            use_regime_modulation=False, use_category_modulation=False, use_abstention_exclusion=False,
            use_momentum_catchup=False, profile_key=None, profile_min_confidence=None,
            profile_base_risk_percent=None):
    """
    candles: primary-timeframe candle list (oldest→newest, real MT5 data)
    multi_tf_candles: {timeframe: candles} for confluence (D1/H4/H1/M15/M5)
    validated_strategy: {"strategy_name": str, "signal": {"direction","rationale"}|None,
                          "stats": {...}} or None — the live-evaluated active Strategy
    profile_min_confidence / profile_base_risk_percent: the CALLING profile's
      own real config (see local_functions.PROFILE_MIN_CONFIDENCE /
      PROFILE_BASE_RISK_PERCENT) — only consumed by the dynamic lot-sizing
      formula below (Scalping only); unrelated to the legacy risk_percent
      param above, which this function has never used for any computation.
    profile_key: None (default, unchanged behavior) | "scalping" | "intraday" | "swing".
      ACTIVE, not an experiment flag — real trader spec, 2026-08-13: Scalping
      never plans a pending (LIMIT/STOP) order, ever. Intraday/Swing are fine
      waiting for price to reach a real zone; Scalping's whole point is
      maximizing DIRECT entries — an analysis validated live, right now, or
      nothing this cycle. See the pending_zone branch below: for
      profile_key="scalping" the "close enough to plan a pending order"
      branch is skipped entirely, falling through to wait_confirmation
      instead (re-evaluated fresh next cycle, exactly like the "too far"
      case already did for every profile).
    use_regime_modulation: OFF by default everywhere in the real decision
      path. Tested via fusion_backtest.py in a real walk-forward comparison
      (commit 7a6108f, 2026-08-07): net -37% PnL across 9 real (symbol,
      window) cells vs the current unmodulated behavior — the hypothesis
      doesn't generalize (helps XAUUSD, consistently hurts BTCUSD/ETHUSD).
      Stays False; kept as a tested, documented, inactive capability.
    use_category_modulation: OFF by default everywhere (Task #89/Q6). Tested
      via fusion_backtest.py walk-forward (2026-08-12): confirmed zero effect
      on XAUUSD/BTCUSD/ETHUSD (9/9 windows byte-identical, as designed —
      see engine_scoring.category_weight_multipliers's docstring), but the
      hypothesis itself (cut smart_money/liquidity/volume, boost
      pattern_recognition/indicator_fusion/volatility for Deriv synthetic
      indices) came back NEGATIVE on real Boom 1000 Index data across all 3
      tested windows. Stays False; kept as a tested, documented, inactive
      capability, same treatment as use_regime_modulation.
    use_abstention_exclusion: OFF by default everywhere (Task #95, testing
      in progress). Real finding, 2026-08-12: replaying real BTCUSD decisions
      during a regime-classifier-confirmed real trend_down showed confidence
      capped ~42-53% even with several engines in genuine, persistent
      bearish agreement (indicator_fusion/entry_planner/smart_money) —
      because "setup-dependent" engines (market_structure/fibonacci/volume/
      pattern_recognition) correctly sit at low-confidence neutral most of
      the time absent a clean zone/pattern, and their weight still dilutes
      the fusion denominator even though they contribute to neither side.
      See engine_scoring.fuse_direction_and_confidence's exclude_abstentions
      param for the mechanism and its own docstring's module-level comment
      for the real result: tested via fusion_backtest.py walk-forward
      (2026-08-12), net -442 PnL across 9 real windows — INVALIDATED, same
      verdict as use_regime_modulation and use_category_modulation. Nearly
      doubled trade count (94->160) with degraded quality on XAUUSD in
      particular. Stays False; kept as a tested, documented, inactive
      capability.
    use_momentum_catchup: OFF by default everywhere (Task #96, testing in
      progress, tentatively promising but not yet proven). Real finding,
      2026-08-13: replayed real production decisions and found a real
      XAUUSD BUY targeting a pending zone for hours while price ran
      continuously away from it (~5 real ATRs of net displacement, never
      taken) — the zone-only entry_type logic below has no fallback for a
      real, sustained, in-favor move that never pulls back. See
      MOMENTUM_DISPLACEMENT_LOOKBACK/MIN_ATR above for the mechanism.
      Tested via fusion_backtest.py walk-forward (2026-08-13), H1 only, 9
      real windows on XAUUSD/BTCUSD/ETHUSD: a loose 1.5 ATR threshold was
      net NEGATIVE (-213 PnL, more trades, worse quality — same pattern as
      the three invalidated experiments above); tightened to
      MOMENTUM_DISPLACEMENT_MIN_ATR=3.0 (closer to the real incident's ~5
      ATR magnitude — a rarer, more decisive signal) came back net POSITIVE
      but modest and uneven (+34.51 PnL, +3 trades; a real +146 swing on
      XAUUSD's first window, a real -60 swing on ETHUSD's — not a clean win
      everywhere). Stays False pending broader validation (real per-profile
      timeframes M1/M5/M15/M30/H4/D1, not just H1) — kept as a tested,
      documented, tentatively-promising-but-inactive capability.
    """
    snapshot = ind.compute_snapshot(symbol, timeframe, candles)
    ctx = es.build_context(candles, symbol=symbol)

    # Market Regime AI (2026-08-07) — this instrument's own current
    # technical regime (trend/range/transition + volatility), computed from
    # the SAME primary-timeframe candles already fetched. Context only: see
    # market_regime.py's module docstring for why this doesn't yet touch
    # engine weights or the decision itself, except behind the
    # use_regime_modulation experiment flag above.
    regime = market_regime.classify_market_regime(candles)
    regime_multipliers = market_regime.regime_weight_multipliers(regime["regime"]) if use_regime_modulation else {}
    category_multipliers = es.category_weight_multipliers(symbol) if use_category_modulation else {}
    if regime_multipliers or category_multipliers:
        # Key-wise product, not override: if a future combination of both
        # experiments is ever tested together, each engine's weight should
        # reflect BOTH active effects, not whichever flag happened to be
        # applied last. Today only one of these is ever True in practice.
        weight_multipliers = {}
        for engine_id in set(regime_multipliers) | set(category_multipliers):
            weight_multipliers[engine_id] = regime_multipliers.get(engine_id, 1.0) * category_multipliers.get(engine_id, 1.0)
    else:
        weight_multipliers = None

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
    fusion = es.fuse_direction_and_confidence(engine_results, weight_multipliers=weight_multipliers, exclude_abstentions=use_abstention_exclusion)
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

    # Dynamic lot sizing (Scalping only, see _dynamic_risk_multiplier above)
    # — computed on the FINAL confidence (after validated-strategy/global-
    # intelligence adjustments above), using this instrument's own real
    # current volatility read (regime, computed earlier in this function).
    effective_risk_percent = None
    if profile_key == "scalping" and decision != "WAIT" and profile_base_risk_percent:
        risk_multiplier = _dynamic_risk_multiplier(
            confidence, profile_min_confidence or CONFIDENCE_FLOOR, regime["volatility"],
        )
        effective_risk_percent = round(profile_base_risk_percent * risk_multiplier, 3)

    entry_type, entry_zone_low, entry_zone_high, ideal_entry = "wait_confirmation", None, None, None
    stop_loss = take_profit_1 = take_profit_2 = break_even = None
    decision_bias = fusion["direction"]

    pending_zone = None
    if decision != "WAIT":
        zone_engine, zone = _find_actionable_zone(breakdown, decision_bias)
        pending_zone = _find_pending_entry_zone(ctx, atr_val, decision_bias)

        # Task #96 (opt-in) — a real, sustained move in the decision's own
        # direction is validation enough to enter now, even with no clean
        # zone nearby (or one price already left behind): compares current
        # price to MOMENTUM_DISPLACEMENT_LOOKBACK bars ago, in ATR units.
        # Deliberately overrides the zone-distance branches below rather
        # than being a 4th tier — the real finding (Task #96) was price
        # running AWAY from a pending zone for hours while the zone-only
        # logic kept re-targeting it forever, never taking the move.
        momentum_override = False
        if use_momentum_catchup and atr_val and len(candles) > MOMENTUM_DISPLACEMENT_LOOKBACK:
            reference_price = candles[-1 - MOMENTUM_DISPLACEMENT_LOOKBACK]["close"]
            displacement = (current_price - reference_price) if decision_bias == "bullish" else (reference_price - current_price)
            if (displacement / atr_val) >= MOMENTUM_DISPLACEMENT_MIN_ATR:
                momentum_override = True

        if momentum_override or pending_zone is None or pending_zone["distance_atr"] <= IMMEDIATE_ENTRY_MAX_ATR:
            # No real zone to plan around, price is already there, or a real
            # sustained move validates entering now — an immediate entry is
            # the honest read of the situation.
            ideal_entry = current_price
            entry_type = "immediate"
        elif profile_key != "scalping" and pending_zone["distance_atr"] <= PENDING_ORDER_MAX_ATR:
            # A real order block, FVG or golden pocket sits close enough to
            # be worth waiting for — plan the entry there instead of paying
            # the current, worse price. The bridge classifies this as a
            # LIMIT or STOP order on its own by comparing this price to the
            # current one (see alphatg_bridge.py send_pending_order).
            # Never taken for Scalping (see analyze()'s own docstring) — it
            # falls through to the wait_confirmation branch just below,
            # exactly like a zone that's too far to plan around at all.
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
        elif profile_key == "scalping":
            entry_plan_note = f" Zone la plus proche à {ideal_entry:.2f} ({pending_zone['distance_atr']:.1f} ATR) — le Scalping n'attend jamais un ordre en attente, réévaluation en direct au prochain cycle."
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
        "effective_risk_percent": effective_risk_percent,
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
