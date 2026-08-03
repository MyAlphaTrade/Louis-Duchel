"""
Economic Intelligence — real economic-calendar event risk, replacing the
long-standing zero-weight stub (engine_scoring.py originally documented:
"Economic Intelligence (news calendar) is left out: there is no data
source for it yet"). It has one now: a public, no-key-required calendar
feed used widely by retail trading tools (the same feed ForexFactory's own
calendar widget serves) — verified reachable directly with `requests`,
200 OK, clean JSON, no auth.

Like Volatility/Session, this is a CONDITION engine, not a directional
one: news timing says nothing about direction, so bias is always neutral.
Confidence reflects how much high-impact event risk is imminent right now
for the traded symbol's currency — a big scheduled release nearby means
"expect volatility/gaps", not "buy" or "sell".
"""
import logging
import time
from datetime import datetime

import requests

log = logging.getLogger("economic_calendar")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
REQUEST_TIMEOUT = 5
CACHE_TTL_SEC = 900  # a weekly calendar doesn't need refetching every analyze() cycle

_cache = {"data": None, "fetched_at": 0.0}

# Which currency's news actually moves a given traded symbol. USD is the
# default for anything unmapped — it dominates most CFDs/crypto pairs.
SYMBOL_CURRENCIES = {
    "XAUUSD": ["USD"],
    "BTCUSD": ["USD"],
    "ETHUSD": ["USD"],
}
DEFAULT_CURRENCIES = ["USD"]

IMMINENT_WINDOW_HOURS = 2
NEAR_WINDOW_HOURS = 24


def _fetch_calendar():
    now = time.time()
    if _cache["data"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SEC:
        return _cache["data"]
    try:
        resp = requests.get(CALENDAR_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        _cache["data"] = resp.json()
        _cache["fetched_at"] = now
    except Exception as e:
        log.warning("[ECONOMIC_CALENDAR] fetch failed: %s", e)
        if _cache["data"] is None:
            _cache["data"] = []
    return _cache["data"]


def _currencies_for_symbol(symbol):
    return SYMBOL_CURRENCIES.get((symbol or "").upper(), DEFAULT_CURRENCIES)


def score_economic(symbol=None):
    events = _fetch_calendar()
    currencies = _currencies_for_symbol(symbol)
    now = time.time()

    upcoming_high = []
    for e in events:
        if e.get("impact") != "High" or e.get("country") not in currencies:
            continue
        try:
            event_time = datetime.fromisoformat(e["date"]).timestamp()
        except (ValueError, KeyError, TypeError):
            continue
        delta_hours = (event_time - now) / 3600
        if -0.5 <= delta_hours <= NEAR_WINDOW_HOURS:  # include just-released events too (post-release volatility)
            upcoming_high.append((delta_hours, e))

    if not upcoming_high:
        return {"id": "economic", "bias": "neutral", "confidence": 15,
                "findings": [f"Aucun événement à fort impact ({'/'.join(currencies)}) dans les prochaines {NEAR_WINDOW_HOURS}h"]}

    upcoming_high.sort(key=lambda x: abs(x[0]))
    delta_hours, nearest = upcoming_high[0]
    if delta_hours <= IMMINENT_WINDOW_HOURS:
        confidence = 75
        timing = "vient de se produire" if delta_hours < 0 else f"dans {delta_hours:.1f}h"
    else:
        confidence = 40
        timing = f"dans {delta_hours:.1f}h"
    return {
        "id": "economic", "bias": "neutral", "confidence": confidence,
        "findings": [f"{nearest['title']} ({nearest['country']}, fort impact) {timing} — risque d'événement élevé"],
    }
