"""AlphaTrade - persistance du calendrier (Dashboard mobile + Calendrier desktop).

Écrit/relit data/calendar_data.json — agrégats journaliers (clé UTC YYYY-MM-DD),
jamais purgés. Port du module équivalent côté KB1000 (engine/calendar_tracker.py),
réduit à `record_trade()` — AlphaTrade n'a pas de concept de spike/crash à
enregistrer séparément, seulement des trades XAUUSD réels clôturés.

Ce module ne fait que collecter et sauvegarder — aucune stratégie, aucune
décision, aucun ordre.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("ALPHATRADE_DATA_DIR", Path.home() / "AlphaTrade"))
CALENDAR_FILE = DATA_DIR / "calendar_data.json"


def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _empty_day() -> dict:
    # Forme lue par electron/renderer.js::calendarStats() (persisted.trades/.profit/
    # .wins/.losses) -- garder ces 4 clés au niveau du jour, pas seulement dans
    # "symbols", sinon le Calendrier desktop retombe sur ses trades en mémoire au
    # lieu du résumé persistant pour les jours hors fenêtre récente.
    return {"trades": 0, "profit": 0.0, "wins": 0, "losses": 0, "symbols": {}}


def _empty_alltime() -> dict:
    return {"trades": 0, "wins": 0, "losses": 0, "profit": 0.0, "gross_win": 0.0, "gross_loss": 0.0}


def _load() -> dict:
    try:
        with open(CALENDAR_FILE, encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("daily", {})
            data.setdefault("alltime", _empty_alltime())
            return data
    except Exception:
        return {"daily": {}, "alltime": _empty_alltime()}


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = str(CALENDAR_FILE) + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_file, CALENDAR_FILE)


def _day_bucket(data: dict, day_key: str) -> dict:
    return data["daily"].setdefault(day_key, _empty_day())


def record_trade(symbol: str, profit: float) -> None:
    """Enregistre un VRAI trade clôturé. Appelé une seule fois par trade — voir le
    garde-fou `SELECT 1 FROM trades WHERE id=?` dans sync_history() avant l'appel,
    car sync_history() rescanne plusieurs jours de deals MT5 à chaque tick."""
    data = _load()
    day = _day_bucket(data, _today_key())
    day["trades"] = int(day.get("trades", 0)) + 1
    day["profit"] = round(float(day.get("profit", 0.0)) + float(profit), 2)
    if profit > 0:
        day["wins"] = int(day.get("wins", 0)) + 1
    else:
        day["losses"] = int(day.get("losses", 0)) + 1
    day["symbols"].setdefault(symbol, {"trades": 0, "profit": 0.0})
    day["symbols"][symbol]["trades"] = int(day["symbols"][symbol].get("trades", 0)) + 1
    day["symbols"][symbol]["profit"] = round(float(day["symbols"][symbol].get("profit", 0.0)) + float(profit), 2)

    at = data.setdefault("alltime", _empty_alltime())
    at["trades"] = int(at.get("trades", 0)) + 1
    at["profit"] = round(float(at.get("profit", 0.0)) + float(profit), 2)
    if profit > 0:
        at["wins"] = int(at.get("wins", 0)) + 1
        at["gross_win"] = round(float(at.get("gross_win", 0.0)) + float(profit), 2)
    else:
        at["losses"] = int(at.get("losses", 0)) + 1
        at["gross_loss"] = round(float(at.get("gross_loss", 0.0)) + abs(float(profit)), 2)

    _save(data)


def rebuild_from_trades(trades: list[dict]) -> dict:
    """Reconstruit calendar_data.json en entier depuis une liste de trades
    {symbol, profit, close_time (ISO)} -- source de verite = table SQLite `trades`,
    bien plus complete que l'ancien calendar_data.json (qui s'etait arrete de se
    mettre a jour a un moment donne). Ecrase le fichier existant : ne pas appeler
    en cours de fonctionnement normal, seulement pour un rattrapage ponctuel
    (voir python/backfill_calendar.py)."""
    data = {"daily": {}, "alltime": _empty_alltime()}
    for t in trades:
        close_time = str(t.get("close_time") or "")
        day_key = close_time[:10]
        if not day_key:
            continue
        symbol = str(t.get("symbol") or "?")
        profit = float(t.get("profit") or 0.0)

        day = _day_bucket(data, day_key)
        day["trades"] = int(day.get("trades", 0)) + 1
        day["profit"] = round(float(day.get("profit", 0.0)) + profit, 2)
        if profit > 0:
            day["wins"] = int(day.get("wins", 0)) + 1
        else:
            day["losses"] = int(day.get("losses", 0)) + 1
        day["symbols"].setdefault(symbol, {"trades": 0, "profit": 0.0})
        day["symbols"][symbol]["trades"] = int(day["symbols"][symbol].get("trades", 0)) + 1
        day["symbols"][symbol]["profit"] = round(float(day["symbols"][symbol].get("profit", 0.0)) + profit, 2)

        at = data["alltime"]
        at["trades"] = int(at.get("trades", 0)) + 1
        at["profit"] = round(float(at.get("profit", 0.0)) + profit, 2)
        if profit > 0:
            at["wins"] = int(at.get("wins", 0)) + 1
            at["gross_win"] = round(float(at.get("gross_win", 0.0)) + profit, 2)
        else:
            at["losses"] = int(at.get("losses", 0)) + 1
            at["gross_loss"] = round(float(at.get("gross_loss", 0.0)) + abs(profit), 2)

    _save(data)
    return data
