from __future__ import annotations

import json
import math
import sqlite3
import time
import urllib.request
from collections import defaultdict, deque
from pathlib import Path


def _number(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def order_book_imbalance(bids, asks, depth=5):
    bid_volume = sum(_number(row[1]) for row in (bids or [])[:depth])
    ask_volume = sum(_number(row[1]) for row in (asks or [])[:depth])
    total = bid_volume + ask_volume
    return 0.0 if total <= 0 else (bid_volume - ask_volume) / total


def order_flow_imbalance(previous, current):
    if not previous or not current:
        return 0.0
    value = current["bid_size"] if current["bid"] >= previous["bid"] else -previous["bid_size"]
    value += -current["ask_size"] if current["ask"] <= previous["ask"] else previous["ask_size"]
    scale = max(1.0, current["bid_size"] + current["ask_size"])
    return max(-1.0, min(1.0, value / scale))


def rolling_kyle_lambda(trades):
    rows = list(trades or [])
    if len(rows) < 3:
        return 0.0
    pairs = []
    for previous, current in zip(rows, rows[1:]):
        volume = _number(current.get("signed_volume"))
        if volume:
            pairs.append((volume, _number(current.get("price")) - _number(previous.get("price"))))
    denominator = sum(volume * volume for volume, _ in pairs)
    return 0.0 if denominator <= 0 else sum(volume * delta for volume, delta in pairs) / denominator


def volume_profile(trades, bins=24):
    rows = [row for row in (trades or []) if _number(row.get("price")) > 0]
    if not rows:
        return {"poc": 0.0, "hvn": [], "lvn": [], "bins": []}
    low = min(_number(row["price"]) for row in rows)
    high = max(_number(row["price"]) for row in rows)
    width = max((high - low) / max(1, bins), max(abs(low), 1.0) * 1e-8)
    buckets = defaultdict(float)
    for row in rows:
        index = min(bins - 1, max(0, int((_number(row["price"]) - low) / width)))
        buckets[index] += max(_number(row.get("size"), 1.0), 0.0)
    profile = [{"price": low + (index + 0.5) * width, "volume": buckets[index]} for index in range(bins)]
    ranked = sorted(profile, key=lambda row: row["volume"], reverse=True)
    return {
        "poc": ranked[0]["price"],
        "hvn": [row["price"] for row in ranked[:3]],
        "lvn": [row["price"] for row in sorted(profile, key=lambda row: row["volume"])[:3]],
        "bins": profile,
    }


class MicrostructureObserver:
    """Moteur d'observation sans aucune méthode d'exécution d'ordre."""

    def __init__(self, data_dir):
        self.db_path = Path(data_dir) / "market_data.db"
        self.books = {}
        self.trades = defaultdict(lambda: deque(maxlen=400))
        self.snapshots = {}
        self.last_error = ""
        with self._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS market_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, venue TEXT,
                asset_class TEXT, symbol TEXT, event_type TEXT, exchange_ts REAL,
                received_ts REAL, bid REAL, ask REAL, bid_size REAL, ask_size REAL,
                price REAL, size REAL, payload TEXT)""")
            conn.execute("""CREATE TABLE IF NOT EXISTS microstructure_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, source TEXT,
                symbol TEXT, obi REAL, ofi REAL, kyle_lambda REAL, poc REAL,
                spread REAL, status TEXT)""")

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=5)

    def observe_book(self, source, venue, asset_class, symbol, bids, asks, exchange_ts=None):
        if not bids or not asks:
            return None
        current = {
            "bid": _number(bids[0][0]), "bid_size": _number(bids[0][1]),
            "ask": _number(asks[0][0]), "ask_size": _number(asks[0][1]),
        }
        if current["bid"] <= 0 or current["ask"] <= 0:
            return None
        previous = self.books.get((source, symbol))
        obi = order_book_imbalance(bids, asks)
        ofi = order_flow_imbalance(previous, current)
        midpoint = (current["bid"] + current["ask"]) / 2
        signed_volume = current["bid_size"] - current["ask_size"]
        history = self.trades[(source, symbol)]
        history.append({"price": midpoint, "size": abs(signed_volume), "signed_volume": signed_volume})
        profile = volume_profile(history)
        kyle = rolling_kyle_lambda(history)
        snapshot = {
            "source": source, "venue": venue, "symbol": symbol,
            "obi": round(obi, 6), "ofi": round(ofi, 6),
            "kyle_lambda": round(kyle, 10), "poc": round(profile["poc"], 6),
            "spread": round(current["ask"] - current["bid"], 8),
            "timestamp": time.time(), "status": "OBSERVATION",
        }
        self.books[(source, symbol)] = current
        self.snapshots[f"{source}:{symbol}"] = snapshot
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO market_events
                (source, venue, asset_class, symbol, event_type, exchange_ts,
                received_ts, bid, ask, bid_size, ask_size, price, size, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (source, venue, asset_class, symbol, "book", exchange_ts or time.time(),
                 time.time(), current["bid"], current["ask"], current["bid_size"],
                 current["ask_size"], midpoint, abs(signed_volume),
                 json.dumps({"obi": obi, "ofi": ofi})),
            )
            conn.execute(
                """INSERT INTO microstructure_snapshots
                (ts, source, symbol, obi, ofi, kyle_lambda, poc, spread, status)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (time.time(), source, symbol, obi, ofi, kyle, profile["poc"],
                 snapshot["spread"], "OBSERVATION"),
            )
        return snapshot

    def observe_mt5_tick(self, symbol, tick):
        bid, ask = _number(getattr(tick, "bid", 0)), _number(getattr(tick, "ask", 0))
        volume = max(_number(getattr(tick, "volume_real", 0)), _number(getattr(tick, "volume", 1)), 1.0)
        return self.observe_book(
            "MT5", "BROKER", "CFD_FOREX", symbol,
            [(bid, volume)], [(ask, volume)],
            _number(getattr(tick, "time_msc", 0)) / 1000 or time.time(),
        )

    def poll_hyperliquid(self, symbols=("BTC", "ETH"), timeout=3):
        for symbol in symbols:
            request = urllib.request.Request(
                "https://api.hyperliquid.xyz/info",
                data=json.dumps({"type": "l2Book", "coin": symbol}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "AlphaTrade/0.2.0"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    payload = json.loads(response.read().decode())
                levels = payload.get("levels") or [[], []]
                bids = [(_number(row.get("px")), _number(row.get("sz"))) for row in levels[0]]
                asks = [(_number(row.get("px")), _number(row.get("sz"))) for row in levels[1]]
                self.observe_book("HYPERLIQUID", "HYPERLIQUID", "CRYPTO", symbol, bids, asks)
                self.last_error = ""
            except Exception as exc:
                self.last_error = str(exc)
        return self.snapshot()

    def snapshot(self):
        return {
            "mode": "OBSERVATION_ONLY",
            "execution_authorized": False,
            "snapshots": dict(self.snapshots),
            "last_error": self.last_error,
            "database": str(self.db_path),
            "timestamp": time.time(),
        }
