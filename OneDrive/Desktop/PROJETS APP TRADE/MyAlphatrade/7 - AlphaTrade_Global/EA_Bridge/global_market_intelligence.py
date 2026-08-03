"""
Global Market Intelligence — aggregates the Hyperliquid crypto connector
(and, as more sources come online, MT5/macro context) into a single
observation snapshot: market regime, crypto pressure, liquidity state,
volatility state.

OBSERVATION ONLY, same discipline as hyperliquid_connector.py: not
imported by market_brain.py, does not touch ENGINE_WEIGHTS,
decision.confidence, or any BUY/SELL/WAIT decision anywhere in this
codebase. The thresholds below are explicitly first-pass heuristics, not
statistically validated — per the agreed plan this stays observational
until measured against real outcomes, and only then (if it demonstrably
helps) considered for activation. Skipping that step is exactly the
mistake found in AlphaTrade v4.1.0's own microstructure module (built,
plausible-looking, never validated, never actually used) — the goal here
is not to repeat it in the other direction (used before it's validated).

Sources: Hyperliquid (BTC/ETH order book, funding, open interest) plus
macro context (DXY, Nasdaq, Dow via MT5) — confirmed available on the
connected broker (DXYUSD, "US Tech 100", "Wall Street 30" all returned
real historical H1 bars) and wired in via `get_macro_snapshot`.
"""
import hyperliquid_connector

VOLATILITY_HIGH_PCT = 3.0
VOLATILITY_LOW_PCT = 1.0
SPREAD_THIN_PCT = 0.05
SPREAD_DEEP_PCT = 0.02

# Broker-specific symbol names for the macro branch — verified live against
# the connected MT5 account. day_change_pct is approximated the same way
# as the crypto side (first vs. last close over a ~1-day H1 window), not a
# calendar-day close-to-close figure — disclosed, not hidden.
MACRO_SYMBOLS = {"DXY": "DXYUSD", "NASDAQ": "US Tech 100", "DOW": "Wall Street 30"}
MACRO_WINDOW_BARS = 24
MACRO_MOVE_SIGNIFICANT_PCT = 0.3  # below this, a symbol's move is treated as noise, not a signal

# Crypto Intelligence Score — composite 0-100 "how strong/hot is the
# current condition" reading (not a directional signal): each component
# contributes 0..weight based on how extreme it currently is, regardless
# of which side. Weights sum to 100. Interpretation bands as specified:
# 0-30 faible, 30-60 neutre, 60-80 favorable, 80+ euphorie/risque.
SCORE_WEIGHTS = {"obi": 25, "funding": 15, "open_interest": 20, "momentum": 25, "volatility": 15}
MOMENTUM_NORMALIZER_PCT = 5.0   # day_change_pct magnitude counted as "maximal" momentum
FUNDING_NORMALIZER = 0.001      # 0.1% funding rate counted as "maximal" crowding
OI_NORMALIZER_PCT = 5.0         # open-interest change vs previous snapshot counted as "maximal"


def _score_band(score):
    if score >= 80:
        return "euphorie_risque"
    if score >= 60:
        return "favorable"
    if score >= 30:
        return "neutre"
    return "faible"


def calculate_crypto_score(coin, previous_oi=None):
    """Per-coin 0-100 composite. `previous_oi` is the coin's open_interest
    value from the last stored snapshot (see record_snapshot below) — the
    Open Interest component is 0 until a previous value exists, since a
    single snapshot alone can't show whether OI is rising or falling."""
    components = {}

    obi = (coin.get("order_book") or {}).get("obi")
    components["obi"] = round(SCORE_WEIGHTS["obi"] * min(abs(obi), 1.0), 1) if obi is not None else 0.0

    funding = coin.get("funding_rate")
    components["funding"] = round(SCORE_WEIGHTS["funding"] * min(abs(funding or 0) / FUNDING_NORMALIZER, 1.0), 1) if funding is not None else 0.0

    momentum = coin.get("day_change_pct")
    components["momentum"] = round(SCORE_WEIGHTS["momentum"] * min(abs(momentum or 0) / MOMENTUM_NORMALIZER_PCT, 1.0), 1) if momentum is not None else 0.0

    oi = coin.get("open_interest")
    if oi is not None and previous_oi:
        oi_change_pct = abs(oi - previous_oi) / previous_oi * 100
        components["open_interest"] = round(SCORE_WEIGHTS["open_interest"] * min(oi_change_pct / OI_NORMALIZER_PCT, 1.0), 1)
    else:
        components["open_interest"] = 0.0  # no prior snapshot yet — can't measure a delta

    # Volatility here reuses the same day_change magnitude as momentum by
    # design choice (a single-snapshot proxy, disclosed) — a real
    # multi-sample realized-volatility measure needs the observation
    # history this module is now building (see record_snapshot).
    components["volatility"] = round(SCORE_WEIGHTS["volatility"] * min(abs(momentum or 0) / MOMENTUM_NORMALIZER_PCT, 1.0), 1) if momentum is not None else 0.0

    total = round(sum(components.values()))
    return {"score": total, "band": _score_band(total), "components": components}


def _crypto_pressure(coins):
    pressures = {c.get("pressure") for c in coins.values() if c.get("pressure") not in (None, "unknown")}
    if not pressures:
        return "unknown"
    if len(pressures) == 1:
        return next(iter(pressures))
    return "mixed"


def _volatility_state(coins):
    changes = [abs(c["day_change_pct"]) for c in coins.values() if c.get("day_change_pct") is not None]
    if not changes:
        return "unknown"
    avg = sum(changes) / len(changes)
    if avg >= VOLATILITY_HIGH_PCT:
        return "high"
    if avg <= VOLATILITY_LOW_PCT:
        return "low"
    return "normal"


def _liquidity_state(coins):
    """Relative bid/ask spread as a simple proxy for book depth — a wider
    spread relative to price suggests a thinner book. Crude on purpose:
    disclosed as a heuristic, not a calibrated model."""
    spreads = []
    for c in coins.values():
        book = c.get("order_book")
        if not book or not book.get("best_bid") or not book.get("best_ask"):
            continue
        mid = (book["best_bid"] + book["best_ask"]) / 2
        if mid > 0:
            spreads.append((book["best_ask"] - book["best_bid"]) / mid * 100)
    if not spreads:
        return "unknown"
    avg_spread = sum(spreads) / len(spreads)
    if avg_spread >= SPREAD_THIN_PCT:
        return "thin"
    if avg_spread <= SPREAD_DEEP_PCT:
        return "deep"
    return "normal"


def get_macro_snapshot(fetch_candles_fn):
    """`fetch_candles_fn(symbol, timeframe, count)` must match
    alphatg_bridge.fetch_candles_direct's signature/return shape:
    (candles, resolved_symbol, error). Returns {} entirely if MT5 isn't
    connected or a symbol isn't available — never raises, this is
    observation-only and a failed fetch must not break any caller."""
    macro = {}
    for key, symbol in MACRO_SYMBOLS.items():
        try:
            candles, resolved, error = fetch_candles_fn(symbol, "H1", MACRO_WINDOW_BARS)
        except Exception as e:
            log_msg = f"[GLOBAL_INTEL] macro fetch failed for {symbol}: {e}"
            import logging
            logging.getLogger("global_market_intelligence").warning(log_msg)
            continue
        if not candles or len(candles) < 2:
            continue
        first_close, last_close = candles[0]["close"], candles[-1]["close"]
        change_pct = round((last_close - first_close) / first_close * 100, 2) if first_close else None
        macro[key] = {"symbol": resolved or symbol, "price": last_close, "day_change_pct": change_pct}
    return macro


def _macro_risk_signal(macro):
    """Classic cross-asset risk read: equities up + dollar down = risk-on
    confirmation; equities down + dollar up = risk-off confirmation.
    Returns True/False/None (None = no clear macro signal either way)."""
    dxy = (macro or {}).get("DXY", {}).get("day_change_pct")
    nasdaq = (macro or {}).get("NASDAQ", {}).get("day_change_pct")
    if dxy is None or nasdaq is None:
        return None
    if nasdaq > MACRO_MOVE_SIGNIFICANT_PCT and dxy < -MACRO_MOVE_SIGNIFICANT_PCT / 2:
        return True
    if nasdaq < -MACRO_MOVE_SIGNIFICANT_PCT and dxy > MACRO_MOVE_SIGNIFICANT_PCT / 2:
        return False
    return None


def _market_regime(crypto_pressure, volatility_state, score_band, macro=None):
    """Combines crypto (primary signal) with the macro risk read (fallback/
    confirmation) — still a first-pass heuristic, not a measured model."""
    if crypto_pressure == "mixed" or volatility_state == "high" or score_band == "euphorie_risque":
        return "uncertain"
    macro_risk_on = _macro_risk_signal(macro)
    if crypto_pressure == "bullish":
        return "risk_on"
    if crypto_pressure == "bearish":
        return "risk_off"
    if macro_risk_on is True:
        return "risk_on"
    if macro_risk_on is False:
        return "risk_off"
    return "neutral"


def get_global_market_intelligence(coins=None, previous_oi=None, macro=None):
    """`previous_oi`: optional {coin: open_interest} from the last stored
    snapshot, used only to compute the Open Interest scoring component
    (see calculate_crypto_score). `macro`: optional dict from
    get_macro_snapshot — pass None to fall back to crypto-only regime
    logic (e.g. when MT5 isn't connected)."""
    crypto = hyperliquid_connector.get_crypto_intelligence(coins)
    coin_data = crypto["coins"]
    previous_oi = previous_oi or {}
    macro = macro or {}

    scores = {coin: calculate_crypto_score(data, previous_oi.get(coin)) for coin, data in coin_data.items()}
    avg_score = round(sum(s["score"] for s in scores.values()) / len(scores)) if scores else 0

    crypto_pressure = _crypto_pressure(coin_data)
    volatility_state = _volatility_state(coin_data)
    liquidity_state = _liquidity_state(coin_data)
    dominant_band = _score_band(avg_score)
    market_regime = _market_regime(crypto_pressure, volatility_state, dominant_band, macro)
    return {
        "market_regime": market_regime,
        "crypto_pressure": crypto_pressure,
        "liquidity_state": liquidity_state,
        "volatility_state": volatility_state,
        "crypto_intelligence_score": {"average": avg_score, "band": dominant_band, "per_coin": scores},
        "sources": {"crypto": coin_data, "macro": macro},
        "fetched_at": crypto["fetched_at"],
        "action_recommended": "none",  # deliberately always "none" — observation only, see record_snapshot
        "methodology_note": (
            "Heuristiques de premier jet (seuils simples sur OBI/spread/variation "
            "journalière, régime macro basé sur Nasdaq/DXY), pas encore validées "
            "statistiquement."
        ),
    }


def record_snapshot(fetch_candles_fn=None):
    """Journal d'observation — persists one snapshot as a CryptoIntelSnapshot
    entity (same generic local_store used for Trade/Signal/AppLog), reusing
    the PREVIOUS snapshot's open_interest to compute this one's OI delta
    component. Called on a timer (see alphatg_bridge.py) so weeks of real
    observation history accumulate whether or not any UI is open — the
    explicit precondition before this data is ever considered for
    activation in a real decision. `fetch_candles_fn`: pass
    alphatg_bridge.fetch_candles_direct to include the macro branch, or
    None to skip it (e.g. MT5 not connected)."""
    from local_store import create_entity, list_entities

    previous = list_entities("CryptoIntelSnapshot", sort="-created_date", limit=1)
    previous_oi = {}
    if previous:
        prev_coins = (previous[0].get("sources") or {}).get("crypto") or {}
        previous_oi = {coin: data.get("open_interest") for coin, data in prev_coins.items() if data.get("open_interest") is not None}

    macro = get_macro_snapshot(fetch_candles_fn) if fetch_candles_fn else None
    snapshot = get_global_market_intelligence(previous_oi=previous_oi, macro=macro)
    create_entity("CryptoIntelSnapshot", snapshot)
    return snapshot
