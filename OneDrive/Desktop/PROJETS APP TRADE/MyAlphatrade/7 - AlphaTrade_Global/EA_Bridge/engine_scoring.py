"""
Deterministic engine scoring — replaces the LLM's job of "reasoning across
20 domains" with real math on real candles. No LLM anywhere in this file.

Each of the weighted engines below returns its OWN read of the market —
{"id", "bias": bullish/bearish/neutral, "confidence": 0-100 (how sure THIS
engine is of ITS bias), "findings": [str, ...]}. The final direction is
never picked first and then justified (that was the old LLM pattern) — it
is derived bottom-up from these votes, weighted by each engine's
importance (see ENGINE_WEIGHTS, mirroring Dist/base44/shared/engines.ts).

Economic Intelligence now has a real source (economic_calendar.py, a
public no-key calendar feed) — restored at its originally-documented
weight of 6, after being a zero-weight stub since this file's creation.
"""

import logging
import re

from indicators import ema, rsi, macd, atr, bollinger_bands, find_swings, classify_structure, fibonacci_levels, bias_from_snapshot, chaikin_money_flow, session_vwap
from market_analysis import bos_choch, find_fvgs, find_order_blocks, find_liquidity_zones, detect_sweep, detect_candlestick_pattern
from economic_calendar import score_economic

# Diagnostic-only logger (Phase A follow-up): confirms whether market_structure
# and indicator_fusion actually see fresh candle data between two analyze()
# cycles, or are stuck on stale inputs. Purely additive — never read by any
# decision logic, safe to ignore or filter out by logger name.
diag_log = logging.getLogger("engine_diagnostics")

# Mirrors Dist/base44/shared/engines.ts ANALYSIS_ENGINES weights, plus
# "microstructure" (new, real order-flow data via Hyperliquid — see
# market_brain.py's _microstructure_engine_result). Not in ENGINE_SCORERS
# below: like multi_timeframe, it needs data beyond a single symbol's
# candles (Hyperliquid's own order book), so it's injected into
# engine_results externally by market_brain.py, only for symbols where
# real data exists (BTCUSD/ETHUSD) — absent entirely for everything else,
# which correctly excludes its weight from total_weight for those symbols
# rather than forcing a fake "neutral" vote.
ENGINE_WEIGHTS = {
    "multi_timeframe": 14,
    "market_structure": 14,
    "smart_money": 12,
    "indicator_fusion": 10,
    "microstructure": 15,
    "liquidity": 8,
    "entry_planner": 8,
    "economic": 6,
    "fibonacci": 7,
    "volume": 7,
    "pattern_recognition": 5,
    "volatility": 5,
    "session": 4,
}


def _infer_asset_category(raw):
    """Mirrors local_functions._infer_asset_category / portfolio_risk.py's
    own copy exactly (duplicated, not imported, same reasoning as
    portfolio_risk.py's own comment: keep this leaf module import-independent)."""
    s = re.sub(r"\s+", "", (raw or "").upper())
    # search (not ^match) — see local_functions._infer_asset_category's
    # comment (2026-08-14): Multi Step/Skew Step don't start with STEP.
    if re.search(r"(BOOM|CRASH|STEP|VOLATILITY|JUMP|RANGEBREAK|VOLOVER|SPOTUP)", s) or re.search(r"VIX\d", s):
        return "synthetic"
    if "INDEX" in s:
        return "indices"
    if re.match(r"^(BTC|ETH|SOL|XRP|ADA|DOGE|BNB|LTC|AVAX|LINK|DOT|MATIC|ATOM|TRX|NEAR|APT|FIL|ICP|ARB|OP|INJ|SUI|TIA|RNDR|FTM)", s):
        return "crypto"
    if re.match(r"^X(AU|AG|PT|PD)", s):
        return "metals"
    if re.search(r"(OIL|GAS|COPPER|WHEAT|CORN|SOY|COFFEE|SUGAR|COCOA)", s):
        return "commodities"
    return "forex"


# Task #89 (Q6) — modulation par catégorie d'actif, opt-in (use_category_modulation
# param sur market_brain.analyze(), défaut False partout, TESTÉE ET INVALIDÉE).
# Même mécanique que market_regime.regime_weight_multipliers (BOOST/CUT sur
# ENGINE_WEIGHTS avant fusion), même discipline : jamais activé sans preuve.
#
# Hypothèse testée : les indices synthétiques Deriv (Boom/Crash/Step) sont des
# processus purement algorithmiques sans carnet d'ordres institutionnel réel —
# donc smart_money (order blocks/FVG suppose une empreinte institutionnelle
# réelle), liquidity (sweeps suppose de vraies zones de liquidité) et volume
# (le volume broker sur un synthétique est un proxy de ticks, pas un vrai
# volume de marché) devraient être moins fiables pour cette catégorie, au
# profit de pattern_recognition/indicator_fusion/volatility (purement
# statistiques/techniques).
#
# Résultat réel (fusion_backtest.py, walk-forward, 2026-08-12) :
# - Non-régression : XAUUSD/BTCUSD/ETHUSD, 3 fenêtres réelles de 30j chacune
#   (9 cellules) — résultat BYTE-IDENTIQUE modulation ON vs OFF dans les 9,
#   confirmé : category_weight_multipliers retourne {} pour metals/crypto/
#   forex/indices/commodities, donc ce flag ne peut structurellement pas les
#   affecter, quelle que soit sa valeur.
# - Boom 1000 Index, 3 fenêtres réelles de 30j (seul instrument où {} n'est
#   PAS retourné) : modulation négative dans les 3 — PnL relatif -12.7%,
#   -9.4%, -3.3% ; profit factor et win rate en baisse à chaque fenêtre.
#   Hypothèse invalidée, comme l'expérience de régime (commit 7a6108f) : la
#   théorie ne se vérifie pas sur données réelles. (Les montants PnL absolus
#   de ce backtest sont hors échelle — fusion_backtest.py utilise encore le
#   contract_size par défaut de CONTRACT_SIZES, incomplet pour les
#   synthétiques — mais la comparaison RELATIVE base vs modulé, qui utilise
#   la même valeur erronée des deux côtés, reste valide.)
# Reste désactivé partout ; conservé comme capacité testée, documentée,
# inactive — même traitement que market_regime.py.
#
# Toutes les catégories (forex/metals/crypto/indices/commodities/synthetic) :
# {} — cette modulation n'est donc active nulle part par défaut.
SYNTHETIC_CUT_ENGINES = ("smart_money", "liquidity", "volume")
SYNTHETIC_BOOST_ENGINES = ("pattern_recognition", "indicator_fusion", "volatility")
CATEGORY_CUT_MULTIPLIER = 0.7
CATEGORY_BOOST_MULTIPLIER = 1.3


def category_weight_multipliers(symbol):
    """Returns a {engine_name: multiplier} dict to apply on top of
    ENGINE_WEIGHTS before fusion, or {} for categories left untouched.
    Mirrors market_regime.regime_weight_multipliers's contract exactly so
    market_brain.py can combine both key-wise."""
    category = _infer_asset_category(symbol)
    if category != "synthetic":
        return {}
    multipliers = {}
    for name in SYNTHETIC_CUT_ENGINES:
        multipliers[name] = CATEGORY_CUT_MULTIPLIER
    for name in SYNTHETIC_BOOST_ENGINES:
        multipliers[name] = CATEGORY_BOOST_MULTIPLIER
    return multipliers


# Zone-only fusion (2026-08-14, real-trader spec — Louis) — ACTIVE for
# XAUUSD, unlike every other modulation experiment in this file (all
# stayed False/inactive). Restricts the fusion to smart_money (FVG+Order
# Blocks) and liquidity (S/R zones + sweeps) only, every other engine's
# weight zeroed out — the question tested was literally "what if we only
# used FVG/OB/S/R and let those set the confidence".
#
# Real result (fusion_backtest.py walk-forward, 2026-08-14, 6 independent
# real ~30-day H1 windows, ~9 real months of XAUUSD): baseline 690.36$
# (110 trades) -> restricted 1328.82$ (182 trades), +638.46 (+92%), 4/6
# windows improved and the gains dwarf the 2 losing windows (+153/+53/
# +318/+192 vs -37/-41). First mechanism this session to survive a real
# walk-forward test — regime modulation (-37%), category modulation
# (invalidated), abstention exclusion (-442) all failed the same test.
#
# First same-day single-window test on BTCUSD/ETHUSD (not walk-forward)
# was mixed — BTCUSD +99, ETHUSD -267. Re-tested properly (2026-08-14,
# 6 real ~30-day H1 windows, ~7 real months, Jan-Aug 2026):
#   BTCUSD: baseline 69.67$ (112 trades) -> restricted 344.50$ (193
#     trades), +274.83 (~5x), 4/6 windows improved (+174/+102/+48/+132 vs
#     -109/-1) — same distributed-gain profile as XAUUSD. ACTIVATED.
#   ETHUSD: baseline 59.85$ -> restricted -197.50$, -257.35 — confirms
#     the first single-window result, clearly bad. Stays OFF for ETHUSD.
#
# BTCUSD additionally keeps "microstructure" active (real Hyperliquid
# order-book data, weight 15, the highest of any engine, fixed this same
# day — see MICROSTRUCTURE_CONFIDENCE_BASE/MAX above) — Louis asked
# directly (2026-08-14) to combine it with FVG+OB+S/R for BTC specifically.
# NOT re-validated in combination via fusion_backtest.py: that harness
# force-disables microstructure for its entire run (CRYPTO_CONTEXT_ENABLED
# = False) because it only ever reads the SINGLE MOST RECENT real
# Hyperliquid snapshot — no genuine historical order-book series is
# stored to replay bar-by-bar, so "backtesting" it would leak today's
# live snapshot into every past bar (same disclosed reason "economic" is
# excluded — see fusion_backtest.py's own module docstring). Kept active
# for BTC on the strength of its OWN prior real validation instead (79%
# real directional accuracy of `pressure` on 319 real BTC snapshots,
# 2026-08-14, documented above this file's MICROSTRUCTURE_CONFIDENCE_BASE)
# — not re-proven in this specific combination, disclosed as such.
ZONE_ONLY_CONFIG = {
    "XAUUSD": {"smart_money", "liquidity"},
    "BTCUSD": {"smart_money", "liquidity", "microstructure"},
}
ZONE_ONLY_CUT_MULTIPLIER = 0.0


def zone_only_weight_multipliers(symbol):
    """Returns a {engine_name: multiplier} dict to apply on top of
    ENGINE_WEIGHTS before fusion, or {} for symbols left untouched. Mirrors
    category_weight_multipliers's contract exactly. Derives the cut list
    from ENGINE_WEIGHTS itself (not a hardcoded name list) so a future new
    weighted engine is automatically zeroed out too, never silently left
    active by omission."""
    keep = ZONE_ONLY_CONFIG.get((symbol or "").upper())
    if keep is None:
        return {}
    return {name: ZONE_ONLY_CUT_MULTIPLIER for name in ENGINE_WEIGHTS if name not in keep}


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, round(v)))


def build_context(candles, symbol=None):
    """Everything the per-engine scorers need, computed once. `symbol` is
    optional (defaults to None, backward compatible with every existing
    caller) — only score_economic uses it, to pick which currency's news
    calendar is relevant."""
    closes = [c["close"] for c in candles]
    swings = find_swings(candles, 3)
    return {
        "candles": candles,
        "symbol": symbol,
        "closes": closes,
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema200": ema(closes, 200),
        "rsi14": rsi(closes, 14),
        "macd": macd(closes),
        "atr14": atr(candles, 14),
        "bollinger": bollinger_bands(closes, 20, 2),
        "swings": swings,
        "structure": classify_structure(swings),
        "cmf20": chaikin_money_flow(candles, 20),
        "vwap": session_vwap(candles),
    }


def score_market_structure(ctx):
    event = bos_choch(ctx["candles"], ctx["swings"])
    last_swing = ctx["swings"][-1] if ctx["swings"] else None
    candle_time = ctx["candles"][-1]["time"] if ctx["candles"] else None
    if event["event"] == "BOS":
        result = {"id": "market_structure", "bias": event["direction"], "confidence": 75, "findings": [event["detail"]]}
    elif event["event"] == "CHOCH":
        result = {"id": "market_structure", "bias": event["direction"], "confidence": 55, "findings": [event["detail"]]}
    else:
        # No fresh break on THIS candle -- true most of the time by
        # definition (a break is a one-off event, not a continuous state).
        # Previously this fell through to flat neutral/20 regardless of
        # what the underlying HH/HL vs LH/LL structure actually showed,
        # discarding real information on ~2/3 of all candles (see
        # Audit/Audit_PhaseA_Distribution_Moteurs_Directionnels). A trend
        # that hasn't just broken out is still a trend.
        structure = ctx["structure"]
        if structure["label"] == "uptrend":
            result = {"id": "market_structure", "bias": "bullish", "confidence": 45, "findings": [structure["detail"]]}
        elif structure["label"] == "downtrend":
            result = {"id": "market_structure", "bias": "bearish", "confidence": 45, "findings": [structure["detail"]]}
        else:
            result = {"id": "market_structure", "bias": "neutral", "confidence": 20, "findings": [structure["detail"]]}
    diag_log.info(
        "market_structure candle_time=%s event=%s last_swing=%s bias=%s confidence=%s",
        candle_time, event["event"],
        f"{last_swing['type']}@{last_swing['price']:.2f}" if last_swing else None,
        result["bias"], result["confidence"],
    )
    return result


def score_smart_money(ctx):
    candles, last = ctx["candles"], ctx["candles"][-1]
    price = last["close"]
    atr_val = ctx["atr14"][-1] or 0
    fvgs = [f for f in find_fvgs(candles) if not f["filled"]]
    obs = [o for o in find_order_blocks(candles, ctx["atr14"]) if not o["mitigated"]]
    zones = [{"type": z["type"], "top": z["top"], "bottom": z["bottom"], "index": z.get("index", z.get("impulse_index"))} for z in fvgs + obs]

    nearest_bullish = min(
        (z for z in zones if z["type"] == "bullish" and z["top"] <= price), key=lambda z: price - z["top"], default=None
    )
    nearest_bearish = min(
        (z for z in zones if z["type"] == "bearish" and z["bottom"] >= price), key=lambda z: z["bottom"] - price, default=None
    )

    dist_bull = (price - nearest_bullish["top"]) if nearest_bullish else None
    dist_bear = (nearest_bearish["bottom"] - price) if nearest_bearish else None
    near_atr = atr_val * 1.0 if atr_val else price * 0.002

    if dist_bull is not None and dist_bull <= near_atr and (dist_bear is None or dist_bull < dist_bear):
        conf = _clamp(70 - (dist_bull / near_atr) * 20 + (len(candles) - nearest_bullish["index"] < 30) * 10)
        return {"id": "smart_money", "bias": "bullish", "confidence": conf,
                "findings": [f"Zone de demande non mitigée à {nearest_bullish['top']:.2f}-{nearest_bullish['bottom']:.2f}, prix à proximité"]}
    if dist_bear is not None and dist_bear <= near_atr:
        conf = _clamp(70 - (dist_bear / near_atr) * 20 + (len(candles) - nearest_bearish["index"] < 30) * 10)
        return {"id": "smart_money", "bias": "bearish", "confidence": conf,
                "findings": [f"Zone d'offre non mitigée à {nearest_bearish['bottom']:.2f}-{nearest_bearish['top']:.2f}, prix à proximité"]}
    return {"id": "smart_money", "bias": "neutral", "confidence": 20, "findings": [f"{len(zones)} zones non mitigées repérées, aucune à proximité immédiate du prix"]}


def score_fibonacci(ctx):
    swings = ctx["swings"]
    last_high = next((s for s in reversed(swings) if s["type"] == "high"), None)
    last_low = next((s for s in reversed(swings) if s["type"] == "low"), None)
    if not last_high or not last_low:
        return {"id": "fibonacci", "bias": "neutral", "confidence": 15, "findings": ["Pas assez de swings pour tracer un Fibonacci exploitable"]}

    direction = "down" if last_high["index"] > last_low["index"] else "up"
    fib = fibonacci_levels(last_high["price"], last_low["price"], direction)
    golden_618, golden_786 = fib["levels"]["0.618"], fib["levels"]["0.786"]
    zone_low, zone_high = (golden_618, golden_786) if golden_618 < golden_786 else (golden_786, golden_618)
    c = ctx["candles"][-1]
    in_zone = c["low"] <= zone_high and c["high"] >= zone_low

    if not in_zone:
        return {"id": "fibonacci", "bias": "neutral", "confidence": 15, "findings": [f"Prix hors golden pocket ({zone_low:.2f}-{zone_high:.2f})"]}
    if direction == "up" and c["close"] > c["open"]:
        return {"id": "fibonacci", "bias": "bullish", "confidence": 65, "findings": [f"Rebond confirmé dans le golden pocket ({zone_low:.2f}-{zone_high:.2f}) du swing haussier"]}
    if direction == "down" and c["close"] < c["open"]:
        return {"id": "fibonacci", "bias": "bearish", "confidence": 65, "findings": [f"Rebond confirmé dans le golden pocket ({zone_low:.2f}-{zone_high:.2f}) du swing baissier"]}
    return {"id": "fibonacci", "bias": "neutral", "confidence": 35, "findings": [f"Prix dans le golden pocket ({zone_low:.2f}-{zone_high:.2f}) mais pas encore de bougie de confirmation"]}


def score_indicator_fusion(ctx):
    votes = []
    e50, e200 = ctx["ema50"][-1], ctx["ema200"][-1]
    if e50 is not None and e200 is not None:
        votes.append("bullish" if e50 > e200 else "bearish")
    r = ctx["rsi14"][-1]
    if r is not None:
        votes.append("bullish" if r > 50 else "bearish")
    hist = ctx["macd"]["histogram"][-1]
    if hist is not None:
        votes.append("bullish" if hist > 0 else "bearish")

    candle_time = ctx["candles"][-1]["time"] if ctx["candles"] else None

    if not votes:
        result = {"id": "indicator_fusion", "bias": "neutral", "confidence": 10, "findings": ["Historique insuffisant pour les indicateurs"]}
    else:
        bulls, bears = votes.count("bullish"), votes.count("bearish")
        total = len(votes)
        if bulls == bears:
            result = {"id": "indicator_fusion", "bias": "neutral", "confidence": 25, "findings": [f"Indicateurs partagés ({bulls} haussiers / {bears} baissiers)"]}
        else:
            bias = "bullish" if bulls > bears else "bearish"
            agree = max(bulls, bears)
            conf = _clamp(30 + (agree / total) * 55)
            result = {"id": "indicator_fusion", "bias": bias, "confidence": conf, "findings": [f"{agree}/{total} indicateurs (EMA50/200, RSI, MACD) s'accordent {bias}"]}

    diag_log.info(
        "indicator_fusion candle_time=%s ema50=%s ema200=%s rsi14=%s macd_hist=%s bias=%s confidence=%s",
        candle_time,
        f"{e50:.2f}" if e50 is not None else None,
        f"{e200:.2f}" if e200 is not None else None,
        f"{r:.1f}" if r is not None else None,
        f"{hist:.4f}" if hist is not None else None,
        result["bias"], result["confidence"],
    )
    return result


def score_volume(ctx):
    candles = ctx["candles"]
    if len(candles) < 21:
        return {"id": "volume", "bias": "neutral", "confidence": 10, "findings": ["Historique insuffisant"]}
    c = candles[-1]
    window = candles[-21:-1]
    avg_vol = sum(x["tick_volume"] for x in window) / len(window)
    if avg_vol <= 0:
        return {"id": "volume", "bias": "neutral", "confidence": 10, "findings": ["Volume indisponible"]}
    ratio = c["tick_volume"] / avg_vol
    if ratio < 1.2:
        return {"id": "volume", "bias": "neutral", "confidence": 15, "findings": [f"Volume {ratio:.1f}x la moyenne — faible participation, pas de confirmation"]}
    bias = "bullish" if c["close"] > c["open"] else "bearish" if c["close"] < c["open"] else "neutral"
    conf = _clamp(40 + min(ratio - 1.2, 2) * 20)
    return {"id": "volume", "bias": bias, "confidence": conf, "findings": [f"Volume {ratio:.1f}x la moyenne sur une bougie {bias}"]}


def score_order_flow(ctx):
    """OBSERVATION-ONLY engine (2026-08-14, real-trader spec — Louis asked
    for a flux-based read of the market using free data we already have,
    after a trader he follows recommended calibrating on proven formulas
    instead of stacking generic indicators). Combines Chaikin Money Flow
    (real buy/sell pressure from OHLCV, decades-old formula) with price's
    position relative to the session VWAP (institutional fair-value
    reference). Deliberately absent from ENGINE_WEIGHTS — computed and
    logged every cycle, visible in the breakdown, contributes 0 to the
    live decision until validated against real historical data (same
    discipline as Task #89/#95: never trusted without proof).

    Hypothesis being tested: does this flip direction EARLIER than
    market_structure/indicator_fusion (which only react to closed candles)
    — i.e. does it address the "late entry" complaint (XAUUSD entering
    after the move already validated) that #104/#105 only partially cover
    (those cancel stale orders after the fact; this would improve the
    entry signal itself).

    First real test (2026-08-14, XAUUSD M15, ~1500 real candles / 3.5
    weeks, isolated directional-accuracy of non-neutral calls over the
    next 8 bars): order_flow 47.7% (811 calls) vs market_structure 41.8%
    (594) vs indicator_fusion 51.4% (1132) — INCONCLUSIVE/NEGATIVE, no
    edge shown, stays disabled. Note market_structure itself (already
    live, weight 14) scored worse than order_flow on this same isolated
    metric — a reminder that single-engine isolated hit-rate isn't the
    same as an engine's real contribution once fused+confidence-weighted,
    so this result doesn't fully indict the concept, but it does not
    clear the bar to activate it either. Sample is narrow (one symbol,
    one 3.5-week window) — same caveat as the confidence-threshold test
    earlier this session. Do not re-enable without a wider, real
    walk-forward test first."""
    candles = ctx["candles"]
    cmf = ctx["cmf20"][-1] if ctx["cmf20"] else None
    vwap = ctx["vwap"]["vwap"][-1] if ctx["vwap"]["vwap"] else None
    price = candles[-1]["close"] if candles else None
    candle_time = candles[-1]["time"] if candles else None

    if cmf is None or vwap is None or price is None:
        result = {"id": "order_flow", "bias": "neutral", "confidence": 10,
                   "findings": ["Historique insuffisant pour le flux d'ordres (CMF/VWAP)"]}
    else:
        # +-0.05 threshold is Chaikin's own published rule of thumb, not
        # invented here.
        cmf_bias = "bullish" if cmf > 0.05 else "bearish" if cmf < -0.05 else "neutral"
        price_bias = "bullish" if price > vwap else "bearish" if price < vwap else "neutral"
        if cmf_bias == "neutral":
            result = {"id": "order_flow", "bias": "neutral", "confidence": 20,
                       "findings": [f"CMF(20)={cmf:.2f} — pression acheteuse/vendeuse insuffisante pour trancher"]}
        elif cmf_bias == price_bias:
            conf = _clamp(45 + min(abs(cmf), 0.3) / 0.3 * 35)
            side = "au-dessus" if price_bias == "bullish" else "en-dessous"
            result = {"id": "order_flow", "bias": cmf_bias, "confidence": conf,
                       "findings": [f"CMF(20)={cmf:.2f} et prix {side} du VWAP journalier — flux et prix s'accordent {cmf_bias}"]}
        else:
            conf = _clamp(25 + min(abs(cmf), 0.3) / 0.3 * 15)
            result = {"id": "order_flow", "bias": cmf_bias, "confidence": conf,
                       "findings": [f"CMF(20)={cmf:.2f} {cmf_bias} mais prix du côté opposé au VWAP — signal contradictoire, confiance réduite"]}

    diag_log.info(
        "order_flow candle_time=%s cmf20=%s vwap=%s price=%s bias=%s confidence=%s",
        candle_time,
        f"{cmf:.3f}" if cmf is not None else None,
        f"{vwap:.2f}" if vwap is not None else None,
        f"{price:.2f}" if price is not None else None,
        result["bias"], result["confidence"],
    )
    return result


def score_liquidity(ctx):
    zones = find_liquidity_zones(ctx["swings"])
    sweep = detect_sweep(ctx["candles"], zones)
    if sweep["swept"]:
        return {"id": "liquidity", "bias": sweep["direction"], "confidence": 65, "findings": [sweep["detail"]]}
    return {"id": "liquidity", "bias": "neutral", "confidence": 20, "findings": [f"{len(zones)} zone(s) de liquidité repérée(s), aucun sweep récent"]}


def score_volatility(ctx):
    atr_series = ctx["atr14"]
    valid = [a for a in atr_series[-30:] if a is not None]
    if len(valid) < 10:
        return {"id": "volatility", "bias": "neutral", "confidence": 15, "findings": ["Historique ATR insuffisant"]}
    current, avg = valid[-1], sum(valid) / len(valid)
    ratio = current / avg if avg > 0 else 1
    if ratio > 1.3:
        return {"id": "volatility", "bias": "neutral", "confidence": 55, "findings": [f"Volatilité en expansion (ATR {ratio:.1f}x la moyenne) — mouvements plus fiables"]}
    if ratio < 0.7:
        return {"id": "volatility", "bias": "neutral", "confidence": 20, "findings": [f"Volatilité comprimée (ATR {ratio:.1f}x la moyenne) — mouvements moins fiables"]}
    return {"id": "volatility", "bias": "neutral", "confidence": 35, "findings": [f"Volatilité normale (ATR {ratio:.1f}x la moyenne)"]}


def score_session(ctx):
    from indicators import detect_session
    s = detect_session()
    if s["kill_zone"] == "london_new_york_overlap":
        return {"id": "session", "bias": "neutral", "confidence": 60, "findings": ["Chevauchement Londres/New York — liquidité maximale"]}
    if s["kill_zone"]:
        return {"id": "session", "bias": "neutral", "confidence": 45, "findings": [f"Kill zone {s['kill_zone']}"]}
    if s["active_sessions"]:
        return {"id": "session", "bias": "neutral", "confidence": 30, "findings": [f"Session(s) active(s): {', '.join(s['active_sessions'])}"]}
    return {"id": "session", "bias": "neutral", "confidence": 10, "findings": ["Aucune session majeure active — faible liquidité"]}


def score_pattern_recognition(ctx):
    pattern = detect_candlestick_pattern(ctx["candles"])
    if not pattern or pattern["bias"] == "neutral":
        label = pattern["pattern"] if pattern else "aucun pattern"
        return {"id": "pattern_recognition", "bias": "neutral", "confidence": 20, "findings": [f"Pattern détecté : {label}"]}
    return {"id": "pattern_recognition", "bias": pattern["bias"], "confidence": _clamp(pattern["strength"]), "findings": [f"Pattern {pattern['pattern']} détecté"]}


def score_entry_planner(ctx):
    """Not "which direction" but "is price at an actionable level right
    now" — reuses the smart-money/fibonacci zones to answer that."""
    sm = score_smart_money(ctx)
    fib = score_fibonacci(ctx)
    candidates = [r for r in (sm, fib) if r["bias"] != "neutral"]
    if not candidates:
        return {"id": "entry_planner", "bias": "neutral", "confidence": 15, "findings": ["Prix hors de toute zone d'entrée propre — pas de configuration actionnable"]}
    best = max(candidates, key=lambda r: r["confidence"])
    return {"id": "entry_planner", "bias": best["bias"], "confidence": best["confidence"], "findings": [f"Configuration d'entrée actionnable ({best['id']})"]}


ENGINE_SCORERS = {
    "market_structure": score_market_structure,
    "smart_money": score_smart_money,
    "fibonacci": score_fibonacci,
    "indicator_fusion": score_indicator_fusion,
    "volume": score_volume,
    "order_flow": score_order_flow,  # observation-only, absent from ENGINE_WEIGHTS (see score_order_flow docstring)
    "liquidity": score_liquidity,
    "volatility": score_volatility,
    "session": score_session,
    "pattern_recognition": score_pattern_recognition,
    "entry_planner": score_entry_planner,
    "economic": lambda ctx: score_economic(ctx.get("symbol")),
}


def run_all_engines(ctx, multi_timeframe_result=None, microstructure_result=None):
    """Runs every scorer that only needs a single timeframe's context, plus
    externally-computed results that need more than that (multi_timeframe
    needs several timeframes' snapshots; microstructure needs Hyperliquid's
    real order-book/funding data, only available for BTCUSD/ETHUSD)."""
    results = {name: fn(ctx) for name, fn in ENGINE_SCORERS.items()}
    if multi_timeframe_result is not None:
        results["multi_timeframe"] = multi_timeframe_result
    if microstructure_result is not None:
        results["microstructure"] = microstructure_result
    return results


# Confidence floor for whichever side ends up dominant. A trader forming a
# view rarely starts from "zero conviction, must be earned back to 100" —
# and neither should this formula. The previous version computed
# `weighted_votes[dominant] / total_weight`, a pure consensus RATIO: any
# disagreement between engines (including engines voting neutral) directly
# divided the winning side's score down, so a real but non-unanimous
# majority (e.g. 60% of weighted opinion agreeing) produced a low score
# (~60% of 100 only if literally everyone agreed). Replayed against 90 days
# of real XAUUSD H1 data, that ratio never once reached the 60 decision
# floor — zero trades in 90 days of a real, tradeable downtrend. Below,
# each side's score starts at FUSION_BASE and only ADDS what engines
# contribute to it — mirroring how AlphaTrade's own (non-LLM) scoring
# works (buy/sell both start at 25, confirmations add points, see
# `alphatrade_engine.py:1009-1058` in the sibling project) — so one side's
# score is never dragged down by how much weight the other side or neutral
# engines accumulated. Still fully deterministic, still no LLM: same
# weighted-vote inputs as before, only the final mapping from vote to
# confidence changed.
FUSION_BASE = 25

# Structurally-neutral engines (2026-08-07 finding): score_volatility,
# score_session and score_economic NEVER return a directional bias — it's
# not that they usually don't, it's written into every branch of their code
# (score_economic's own docstring: "news timing says nothing about
# direction, so bias is always neutral"). Counting their weight in
# total_weight anyway means they can only ever pad the denominator, never
# the numerator — permanently diluting confidence on every single decision,
# on every symbol, forever. Confirmed on 500 real recent AIDecision records:
# median fused confidence was 42%, only 1.4% of decisions ever reached the
# 57 floor. Replaying the SAME 500 real decisions with these three excluded
# from the vote (context/findings still shown, just not weighed) raised
# that to 5.6% — a real, measured effect, not a guess. This is the exact
# same principle already applied to "microstructure" for non-crypto symbols
# above: an engine with nothing to contribute to a side should be absent
# from the vote, not forced into the denominator as a fake "neutral".
STRUCTURALLY_NEUTRAL_ENGINES = {"volatility", "session", "economic"}

# Task #95 — abstention-based confidence, opt-in (exclude_abstentions=False
# everywhere in the live decision path, TESTING IN PROGRESS, not yet proven).
#
# Real finding (2026-08-12, investigating why BTCUSD real confidence stayed
# capped ~42-53% during a genuine, regime-classifier-confirmed trend_down):
# several engines (market_structure, fibonacci, volume, pattern_recognition)
# are "setup-dependent" by design — they need a clean zone/pattern to have
# just formed to express real confidence, and correctly sit at low-confidence
# neutral otherwise. Confirmed on real BTCUSD data (Aug 8-12, 1239 decisions):
# market_structure neutral 83% of the time, fibonacci 90%, volume 96%,
# pattern_recognition 85%. Unlike STRUCTURALLY_NEUTRAL_ENGINES (which can
# NEVER vote directionally, excluded above since 2026-08-07), these engines
# CAN vote directionally and sometimes do — but when they don't, their full
# weight still inflates total_weight (the denominator) without helping
# either side, capping confidence even when the engines that DO have a
# genuine, persistent directional opinion (indicator_fusion bearish 78% of
# the time in the same real window, entry_planner bearish 73%, smart_money
# bearish 71%) agree.
#
# Hypothesis: treat a neutral vote from any (non-structurally-neutral)
# engine as an ABSTENTION for the bullish/bearish ratio specifically — its
# weight stops diluting the side that DOES have an opinion. Guarded by
# MIN_PARTICIPATION_FRACTION: only trust a ratio computed among a minority
# of the total weight if a real majority of it actually voted; below that,
# falls back to today's exact behavior (full total_weight denominator) —
# never lets one or two loud engines dominate just because everything else
# stayed quiet. "neutral"'s own score is untouched either way, so WAIT
# remains exactly as viable an outcome as today when genuinely nothing has
# conviction — this only reshapes bullish vs bearish, never adds false
# direction where none exists.
#
# Résultat réel (fusion_backtest.py, walk-forward, 2026-08-12, 9 fenêtres
# réelles de 30j sur XAUUSD/BTCUSD/ETHUSD) : PnL total -442 (472,07 baseline
# vs 30,09 modulé) — INVALIDÉE au global, même verdict que les deux
# expériences précédentes (régime, catégorie). Le nombre de trades a
# quasiment doublé (94→160, +70%) avec une qualité souvent dégradée (ex.
# XAUUSD fenêtre 90→60j : taux de réussite 71,4%→14,3%). Effet mitigé par
# actif — hausse nette sur BTCUSD (+15) et ETHUSD (+99), forte baisse sur
# XAUUSD (-320) — mais l'augmentation du volume de trades n'est en soi pas
# un signe positif : plus de trades ouverts n'a pas voulu dire plus de
# vraies opportunités captées, surtout visible dans la baisse du taux de
# réussite. Reste désactivée partout ; conservée comme capacité testée,
# documentée, inactive — même traitement que les deux précédentes.
EXCLUDE_ABSTENTIONS_MIN_PARTICIPATION = 0.4


def fuse_direction_and_confidence(engine_results, weight_multipliers=None, exclude_abstentions=False):
    """Derives the final direction bottom-up from engine votes — never picks
    a direction first and justifies it after (that was the old LLM pattern).
    Each engine's vote is weighted by (engine importance × its own
    confidence in its bias), so a loud but unimportant engine can't
    outvote a quiet but important one, and vice versa.

    weight_multipliers: optional {engine_id: float}, defaults to None (every
    engine's weight is used exactly as ENGINE_WEIGHTS defines it — today's
    live behavior, unchanged). Only market_regime.py's experiment (opt-in,
    see its own module docstring) ever passes a real dict here — this
    stays None everywhere in the normal decision path until that
    experiment is actually proven on fusion_backtest.py.

    exclude_abstentions: OFF by default everywhere (Task #95, testing in
    progress). See the module-level comment above EXCLUDE_ABSTENTIONS_MIN_PARTICIPATION
    for the real finding and reasoning behind this."""
    weight_multipliers = weight_multipliers or {}
    weighted_votes = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    total_weight = 0.0
    breakdown = {}

    for engine_id, result in engine_results.items():
        weight = ENGINE_WEIGHTS.get(engine_id, 0)
        conf = result.get("confidence", 0)
        bias = result.get("bias", "neutral")
        # Still shown in breakdown (findings are real, useful context — e.g.
        # "volatilité en expansion" — even when they carry no directional
        # weight) — only excluded from the vote itself. breakdown reports
        # the BASE weight, not the (experimental) modulated one, so the UI
        # never shows a number that silently depends on an unproven flag.
        # Also how an observation-only engine (absent from ENGINE_WEIGHTS
        # entirely, e.g. order_flow, 2026-08-14) stays VISIBLE in the Journal
        # Global breakdown while contributing 0 to the fused decision — same
        # discipline as Task #89/#95: computed and exposed, never silently
        # influential without proof. Previously weight<=0 skipped breakdown
        # too, which would have hidden order_flow entirely — moved the
        # weight<=0 check below breakdown[] instead.
        breakdown[engine_id] = {"weight": weight, "bias": bias, "confidence": conf, "findings": result.get("findings", [])}
        if weight <= 0 or engine_id in STRUCTURALLY_NEUTRAL_ENGINES:
            continue
        effective_weight = weight * weight_multipliers.get(engine_id, 1.0)
        total_weight += effective_weight
        weighted_votes[bias] += effective_weight * (conf / 100)

    if total_weight == 0:
        return {"direction": "neutral", "confidence": 0, "breakdown": breakdown}

    scores = {
        bias: FUSION_BASE + (vote / total_weight) * (100 - FUSION_BASE)
        for bias, vote in weighted_votes.items()
    }

    if exclude_abstentions:
        # participating_weight = total_weight minus whatever weight sits on
        # engines currently voting neutral — the denominator only, not the
        # numerator. Each engine's own (weight × confidence) contribution to
        # weighted_votes[bullish/bearish] is untouched, so an engine that is
        # only 67% confident still can't singlehandedly push the fused score
        # to 100 just because nothing opposed it — first version of this
        # formula divided by (bullish+bearish) instead of participating_weight
        # and did exactly that (5 real engines, all 80%-confident, zero
        # opposition -> fused to 100%, overstating every individual engine's
        # own certainty). Dividing by participating_weight instead makes this
        # a strict generalization of the existing formula: when there are no
        # abstentions at all (neutral_weight=0), participating_weight equals
        # total_weight and the result is mathematically identical to today's
        # behavior — confirmed by test, not just reasoned.
        neutral_weight = sum(
            (weight_multipliers.get(eid, 1.0) * ENGINE_WEIGHTS.get(eid, 0))
            for eid, r in engine_results.items()
            if eid not in STRUCTURALLY_NEUTRAL_ENGINES and r.get("bias", "neutral") == "neutral"
        )
        participating_weight = total_weight - neutral_weight
        if participating_weight > 0 and participating_weight >= total_weight * EXCLUDE_ABSTENTIONS_MIN_PARTICIPATION:
            for bias in ("bullish", "bearish"):
                scores[bias] = FUSION_BASE + (weighted_votes[bias] / participating_weight) * (100 - FUSION_BASE)
        # Below the participation floor: deliberately falls through to the
        # standard total_weight-based scores computed above — never trusts a
        # ratio computed among a small, unrepresentative minority of the
        # total weight.

    dominant = max(scores, key=scores.get)
    confidence = round(scores[dominant])
    return {"direction": dominant, "confidence": confidence, "breakdown": breakdown}
