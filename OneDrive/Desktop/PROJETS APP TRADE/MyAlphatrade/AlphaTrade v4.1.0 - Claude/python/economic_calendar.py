"""Economic Calendar (v5.1.0) -- risque d'evenement macro a fort impact,
porte depuis AlphaTrade Global (EA_Bridge/economic_calendar.py), adapte a
urllib (pas de dependance requests supplementaire dans ce projet).

Flux public, sans cle API -- le meme que le widget calendrier de
ForexFactory. Verifie accessible directement (200 OK, JSON propre).

Comme Risk Manager, ceci est un agent de CONDITION, pas de direction : le
timing d'une publication ne dit rien sur BUY/SELL, seulement "s'attendre a
de la volatilite/des gaps". Ne recommande donc jamais autre chose que WAIT
-- ne peut jamais etre choisi comme gagnant par caio_decide() (qui filtre
les WAIT), mais peut bloquer une entree en CRITICAL + any_rejected, comme
le fait deja Risk Manager pour un lot rejete."""
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from agent_report import AgentReport, make_agent_report

log = logging.getLogger("economic_calendar")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
REQUEST_TIMEOUT = 5
CACHE_TTL_SEC = 900  # un calendrier hebdomadaire n'a pas besoin d'etre re-fetch a chaque cycle

_cache: dict = {"data": None, "fetched_at": 0.0}

# Quelle devise influence reellement un symbole donne -- XAUUSD reagit
# fortement aux publications macro americaines (NFP, CPI, Fed).
SYMBOL_CURRENCIES = {"XAUUSD": ["USD"]}
DEFAULT_CURRENCIES = ["USD"]


def _fetch_calendar() -> list:
    now = time.time()
    if _cache["data"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SEC:
        return _cache["data"]
    try:
        request = urllib.request.Request(CALENDAR_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            _cache["data"] = json.loads(response.read().decode("utf-8"))
        _cache["fetched_at"] = now
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        log.warning("[ECONOMIC_CALENDAR] fetch failed: %s", e)
        if _cache["data"] is None:
            _cache["data"] = []
    return _cache["data"]


def _currencies_for_symbol(symbol: str | None) -> list:
    return SYMBOL_CURRENCIES.get((symbol or "").upper(), DEFAULT_CURRENCIES)


def economic_calendar_report(
    symbol: str = "XAUUSD",
    block_hours: float = 2.0,
    near_hours: float = 24.0,
    now: datetime | None = None,
) -> AgentReport:
    """v5.1.0 -- formalise score_economic() (porte de Global) en AgentReport.
    `block_hours` (parametrable, DEFAULT_PARAMS['economic_calendar_block_hours'])
    determine la fenetre CRITICAL + any_rejected=True qui bloque une entree
    via caio_decide() -- le meme mecanisme deja utilise par Risk Manager pour
    un lot rejete, aucune nouvelle branche d'arbitrage requise."""
    now = now or datetime.now(timezone.utc)
    events = _fetch_calendar()
    currencies = _currencies_for_symbol(symbol)
    now_ts = now.timestamp()

    upcoming_high = []
    for e in events:
        if e.get("impact") != "High" or e.get("country") not in currencies:
            continue
        try:
            event_ts = datetime.fromisoformat(e["date"]).timestamp()
        except (ValueError, KeyError, TypeError):
            continue
        delta_hours = (event_ts - now_ts) / 3600
        if -0.5 <= delta_hours <= near_hours:  # inclut les evenements tout juste publies (volatilite post-release)
            upcoming_high.append((delta_hours, e))

    if not upcoming_high:
        return make_agent_report(
            "economic_calendar", status="OK", confidence=15, priority="LOW",
            recommendation={"action": "WAIT"},
            arguments=[f"Aucun evenement a fort impact ({'/'.join(currencies)}) dans les prochaines {near_hours:.0f}h."],
            ttl_seconds=CACHE_TTL_SEC, now=now,
        )

    upcoming_high.sort(key=lambda x: abs(x[0]))
    delta_hours, nearest = upcoming_high[0]
    timing = "vient de se produire" if delta_hours < 0 else f"dans {delta_hours:.1f}h"
    title = str(nearest.get("title") or "Evenement")
    country = str(nearest.get("country") or "")

    if delta_hours <= block_hours:
        return make_agent_report(
            "economic_calendar", status="OK", confidence=75, priority="CRITICAL",
            recommendation={"action": "WAIT", "any_rejected": True},
            risks=[f"{title} ({country}, fort impact) {timing} -- entree bloquee, risque d'evenement imminent."],
            ttl_seconds=CACHE_TTL_SEC, now=now,
        )
    return make_agent_report(
        "economic_calendar", status="OK", confidence=40, priority="MEDIUM",
        recommendation={"action": "WAIT"},
        arguments=[f"{title} ({country}, fort impact) {timing} -- volatilite accrue a prevoir, pas encore bloquant."],
        ttl_seconds=CACHE_TTL_SEC, now=now,
    )
