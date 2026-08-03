"""
Hyperliquid connector — real crypto microstructure data (order book
imbalance, funding rate, open interest), OBSERVATION ONLY.

Uses Hyperliquid's public /info REST API — no API key or wallet needed for
market data (verified against the official hyperliquid-python-sdk source
and gitbook docs): https://hyperliquid.gitbook.io/hyperliquid-docs

This module is never imported by market_brain.py and never feeds
decision.confidence, ENGINE_WEIGHTS, or any BUY/SELL/WAIT decision. Same
caution as the finding in Audit/ — AlphaTrade v4.1.0 already has an
equivalent microstructure module (Order Book Imbalance + Kyle's lambda)
that turned out to be wired into a display panel only, never into any real
decision. This module exists so a future Global Market Intelligence layer
has real data to observe and validate BEFORE anything gets activated —
not to repeat that same "computed but unused" mistake in reverse (used
without being validated first).

Liquidation data is deliberately NOT included: Hyperliquid does not expose
a simple public REST endpoint for recent liquidations — that data requires
subscribing to the WebSocket trade feed and filtering for liquidation-
tagged fills, a meaningfully bigger integration than this module's scope.
"""
import logging
import time

import requests

log = logging.getLogger("hyperliquid_connector")

BASE_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_COINS = ["BTC", "ETH"]
REQUEST_TIMEOUT = 5
OBI_DEPTH = 10  # top N price levels on each side of the book
OBI_PRESSURE_THRESHOLD = 0.15  # |OBI| below this counts as "neutral"


def _post(payload):
    resp = requests.post(BASE_URL, json=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_l2_book(coin):
    """Real order book snapshot. Never raises — this is observation-only
    and a failed fetch must not be able to break any caller."""
    try:
        data = _post({"type": "l2Book", "coin": coin})
        levels = data.get("levels") or [[], []]
        bids, asks = (levels + [[], []])[:2]
        return {"coin": coin, "time": data.get("time"), "bids": bids, "asks": asks}
    except Exception as e:
        log.warning("[HYPERLIQUID] l2Book failed for %s: %s", coin, e)
        return None


def order_book_imbalance(book, depth=OBI_DEPTH):
    """OBI = (bid_volume - ask_volume) / (bid_volume + ask_volume) over the
    top `depth` price levels on each side. +1 = pure buy-side pressure,
    -1 = pure sell-side pressure, 0 = balanced book."""
    if not book or (not book["bids"] and not book["asks"]):
        return None
    bid_vol = sum(float(lvl["sz"]) for lvl in book["bids"][:depth])
    ask_vol = sum(float(lvl["sz"]) for lvl in book["asks"][:depth])
    total = bid_vol + ask_vol
    if total <= 0:
        return None
    return {
        "obi": round((bid_vol - ask_vol) / total, 4),
        "bid_volume": round(bid_vol, 4),
        "ask_volume": round(ask_vol, 4),
        "best_bid": float(book["bids"][0]["px"]) if book["bids"] else None,
        "best_ask": float(book["asks"][0]["px"]) if book["asks"] else None,
    }


def get_asset_contexts():
    """Funding rate, open interest and mark price for every perp, in one
    call. Never raises."""
    try:
        meta, ctxs = _post({"type": "metaAndAssetCtxs"})
        universe = meta.get("universe", [])
        by_coin = {}
        for asset, ctx in zip(universe, ctxs):
            by_coin[asset["name"]] = {
                "funding": float(ctx.get("funding") or 0),
                "open_interest": float(ctx.get("openInterest") or 0),
                "mark_price": float(ctx["markPx"]) if ctx.get("markPx") else None,
                "day_volume": float(ctx.get("dayNtlVlm") or 0),
                "prev_day_price": float(ctx["prevDayPx"]) if ctx.get("prevDayPx") else None,
            }
        return by_coin
    except Exception as e:
        log.warning("[HYPERLIQUID] metaAndAssetCtxs failed: %s", e)
        return {}


def _pressure_from_obi(obi):
    if obi is None:
        return "unknown"
    if obi > OBI_PRESSURE_THRESHOLD:
        return "bullish"
    if obi < -OBI_PRESSURE_THRESHOLD:
        return "bearish"
    return "neutral"


def get_crypto_intelligence(coins=None):
    """Single entry point: real order book pressure + funding/open interest
    for each coin. Observation-only — not consumed by market_brain.py or
    any decision path anywhere in this codebase."""
    coins = coins or DEFAULT_COINS
    asset_ctxs = get_asset_contexts()
    result = {}
    for coin in coins:
        book = get_l2_book(coin)
        obi_data = order_book_imbalance(book)
        ctx = asset_ctxs.get(coin, {})
        day_change_pct = None
        if ctx.get("prev_day_price") and ctx.get("mark_price"):
            day_change_pct = round((ctx["mark_price"] - ctx["prev_day_price"]) / ctx["prev_day_price"] * 100, 2)
        result[coin] = {
            "order_book": obi_data,
            "pressure": _pressure_from_obi(obi_data["obi"] if obi_data else None),
            "funding_rate": ctx.get("funding"),
            "open_interest": ctx.get("open_interest"),
            "mark_price": ctx.get("mark_price"),
            "day_change_pct": day_change_pct,
            "day_volume": ctx.get("day_volume"),
        }
    return {"coins": result, "fetched_at": time.time()}
