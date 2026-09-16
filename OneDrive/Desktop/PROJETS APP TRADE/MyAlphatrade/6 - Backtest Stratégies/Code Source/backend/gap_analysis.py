"""Analyse des gaps d'ouverture -- Research Lab (2026-09-16).

Module GENERIQUE (parametre par symbole, aucun branchement specifique a
un actif dans la logique elle-meme) -- repond a la demande de Louis :
Strategy Lab doit pouvoir analyser, POUR N'IMPORTE QUEL ACTIF, comment le
marche se comporte apres chaque ouverture de journee et apres un
week-end : le gap est-il comble, sur quelle echelle de temps, min/max.

Deux definitions du "gap", toutes les deux demandees explicitement par
Louis plutot que d'en choisir une seule a sa place :

1. GAP DE BOUGIE D1 -- open de la bougie journaliere vs close de la
   bougie journaliere precedente. Disponible pour N'IMPORTE QUEL actif
   deja backfille (aucun calendrier de session requis).

2. GAP DE SESSION CASH -- pour les actifs ou une session boursiere
   reelle et bien definie existe (ex. NYSE 9h30-16h00 heure de New York
   pour les indices actions US). Necessite un calendrier explicite,
   PAS invente au cas par cas : voir CASH_SESSION_HOURS_ET ci-dessous.
   Absent de ce dict = non calcule pour ce symbole (jamais une heure
   devinee).

Toute mesure de "temps de comblement" utilise M15 (la plus fine
resolution partagee par tous les actifs actuellement backfilles) et
respecte le principe de coherence multi-timeframe deja pose (Phase 3) :
la mesure ne porte que sur la fenetre ou M15 est reellement disponible,
jamais extrapolee au-dela.

Aucune valeur n'est jamais inventee : un gap qui ne se comble pas dans
l'horizon d'analyse est marque explicitement `filled: False`, jamais
associe a un faux temps de comblement.
"""
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

NY_TZ = ZoneInfo("America/New_York")

# Heures de session cash connues, en heure de New York -- explicite,
# jamais devine. Un symbole absent de ce dict n'a simplement pas de
# gap de session cash calcule (le gap D1 reste toujours calcule).
CASH_SESSION_HOURS_ET = {
    # NYSE -- indices actions US (ex. NASDAQ / "US Tech 100" chez Deriv).
    "US Tech 100": {"open": (9, 30), "close": (16, 0)},
}
CASH_SESSION_TOLERANCE_MINUTES = 60  # marge pour trouver la bougie M15 la plus proche


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ── 1) Gaps de bougie D1 (tout actif) ───────────────────────────────────────

def compute_d1_gaps(d1_bars: list) -> list:
    """Fonction pure. `d1_bars` : liste de dicts {timestamp, open, high, low,
    close} deja triee chronologiquement. Retourne un enregistrement par gap
    (un par bougie D1 sauf la premiere)."""
    gaps = []
    for i in range(1, len(d1_bars)):
        prev, cur = d1_bars[i - 1], d1_bars[i]
        prev_close = prev["close"]
        open_price = cur["open"]
        gap = open_price - prev_close
        prev_dt = _parse_ts(prev["timestamp"])
        cur_dt = _parse_ts(cur["timestamp"])
        calendar_days = (cur_dt.date() - prev_dt.date()).days
        gaps.append({
            "timestamp": cur["timestamp"],
            "prev_close": prev_close,
            "open": open_price,
            "gap": gap,
            "gap_pct": (gap / prev_close * 100) if prev_close else None,
            "direction": "up" if gap > 0 else ("down" if gap < 0 else "flat"),
            # >1 jour calendaire entre deux bougies D1 consecutives = un
            # week-end (ou un jour ferie) a ete saute -- jamais suppose,
            # deduit directement de l'ecart reel entre les deux timestamps.
            "is_weekend_or_holiday_gap": calendar_days > 1,
            "calendar_days_since_prev": calendar_days,
        })
    return gaps


# ── 2) Gaps de session cash (actifs listes dans CASH_SESSION_HOURS_ET) ─────

def _closest_bar_at_or_after(bars_by_ts: dict, sorted_ts: list, target_dt: datetime, tolerance_minutes: int):
    """Bougie dont l'instant est >= target_dt et le plus proche de
    target_dt, dans la tolerance -- ne regarde jamais dans le futur au-dela
    de la tolerance (reste causal/local a l'instant vise)."""
    import bisect
    target_iso = target_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    idx = bisect.bisect_left(sorted_ts, target_iso)
    if idx >= len(sorted_ts):
        return None
    candidate_ts = sorted_ts[idx]
    candidate_dt = _parse_ts(candidate_ts)
    if (candidate_dt - target_dt).total_seconds() > tolerance_minutes * 60:
        return None
    return bars_by_ts[candidate_ts]


def _closest_bar_at_or_before(bars_by_ts: dict, sorted_ts: list, target_dt: datetime, tolerance_minutes: int):
    import bisect
    target_iso = target_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    idx = bisect.bisect_right(sorted_ts, target_iso) - 1
    if idx < 0:
        return None
    candidate_ts = sorted_ts[idx]
    candidate_dt = _parse_ts(candidate_ts)
    if (target_dt - candidate_dt).total_seconds() > tolerance_minutes * 60:
        return None
    return bars_by_ts[candidate_ts]


def compute_cash_session_gaps(symbol: str, m15_bars: list) -> list:
    """Fonction pure. Necessite `symbol` dans CASH_SESSION_HOURS_ET -- leve
    ValueError sinon (jamais un calcul silencieux avec une heure devinee).
    `m15_bars` : {timestamp, open, high, low, close} tries chronologiquement."""
    if symbol not in CASH_SESSION_HOURS_ET:
        raise ValueError(
            f"Aucune heure de session cash connue pour '{symbol}' -- "
            "ajouter explicitement a CASH_SESSION_HOURS_ET plutot que deviner."
        )
    hours = CASH_SESSION_HOURS_ET[symbol]
    bars_by_ts = {b["timestamp"]: b for b in m15_bars}
    sorted_ts = [b["timestamp"] for b in m15_bars]
    if not sorted_ts:
        return []

    first_day = _parse_ts(sorted_ts[0]).astimezone(NY_TZ).date()
    last_day = _parse_ts(sorted_ts[-1]).astimezone(NY_TZ).date()

    gaps = []
    prev_close_bar = None
    prev_close_day = None
    day = first_day
    while day <= last_day:
        close_dt_ny = datetime(day.year, day.month, day.day, hours["close"][0], hours["close"][1], tzinfo=NY_TZ)
        close_bar = _closest_bar_at_or_before(bars_by_ts, sorted_ts, close_dt_ny, CASH_SESSION_TOLERANCE_MINUTES)

        open_dt_ny = datetime(day.year, day.month, day.day, hours["open"][0], hours["open"][1], tzinfo=NY_TZ)
        open_bar = _closest_bar_at_or_after(bars_by_ts, sorted_ts, open_dt_ny, CASH_SESSION_TOLERANCE_MINUTES)

        if open_bar is not None and prev_close_bar is not None:
            prev_close = prev_close_bar["close"]
            open_price = open_bar["open"]
            gap = open_price - prev_close
            calendar_days = (day - prev_close_day).days
            gaps.append({
                "timestamp": open_bar["timestamp"],
                "prev_close": prev_close,
                "open": open_price,
                "gap": gap,
                "gap_pct": (gap / prev_close * 100) if prev_close else None,
                "direction": "up" if gap > 0 else ("down" if gap < 0 else "flat"),
                "is_weekend_or_holiday_gap": calendar_days > 1,
                "calendar_days_since_prev": calendar_days,
            })

        if close_bar is not None:
            prev_close_bar = close_bar
            prev_close_day = day
        day += timedelta(days=1)

    return gaps


# ── 3) Temps de comblement (commun aux deux definitions de gap) ────────────

def find_fill_time(gap: dict, m15_bars_after: list, horizon_bars: int = 2000):
    """Fonction pure. `m15_bars_after` : bougies M15 A PARTIR de l'instant du
    gap (incluse), triees chronologiquement -- typiquement une tranche deja
    filtree par l'appelant. `horizon_bars` (defaut 2000 ~ 3 semaines en M15)
    limite la recherche -- au-dela, `filled=False`, JAMAIS suppose comble ni
    laisse chercher indefiniment.

    Comblement = le prix retouche `gap["prev_close"]` (low<=prev_close pour
    un gap haussier, high>=prev_close pour un gap baissier)."""
    prev_close = gap["prev_close"]
    is_up = gap["direction"] == "up"
    gap_dt = _parse_ts(gap["timestamp"])

    for bar in m15_bars_after[:horizon_bars]:
        bar_dt = _parse_ts(bar["timestamp"])
        if bar_dt < gap_dt:
            continue
        touched = (bar["low"] <= prev_close) if is_up else (bar["high"] >= prev_close)
        if touched:
            fill_minutes = (bar_dt - gap_dt).total_seconds() / 60
            return {"filled": True, "filled_at": bar["timestamp"], "fill_minutes": fill_minutes}

    return {"filled": False, "filled_at": None, "fill_minutes": None}


# ── 4) Agregation ───────────────────────────────────────────────────────────

def aggregate_gap_stats(enriched_gaps: list) -> dict:
    """Fonction pure. `enriched_gaps` : gaps (de compute_d1_gaps ou
    compute_cash_session_gaps) fusionnes avec le resultat de find_fill_time
    (meme dict, cles `filled`/`filled_at`/`fill_minutes` ajoutees)."""
    def _stats_for(subset):
        n = len(subset)
        filled = [g for g in subset if g["filled"]]
        fill_times = [g["fill_minutes"] for g in filled]
        return {
            "count": n,
            "filled_count": len(filled),
            "filled_pct": round(len(filled) / n * 100, 1) if n else None,
            "fill_minutes_min": round(min(fill_times), 1) if fill_times else None,
            "fill_minutes_max": round(max(fill_times), 1) if fill_times else None,
            "fill_minutes_median": round(median(fill_times), 1) if fill_times else None,
            "fill_minutes_mean": round(mean(fill_times), 1) if fill_times else None,
        }

    weekday_gaps = [g for g in enriched_gaps if not g["is_weekend_or_holiday_gap"]]
    weekend_gaps = [g for g in enriched_gaps if g["is_weekend_or_holiday_gap"]]
    up_gaps = [g for g in enriched_gaps if g["direction"] == "up"]
    down_gaps = [g for g in enriched_gaps if g["direction"] == "down"]

    return {
        "all": _stats_for(enriched_gaps),
        "weekday_gaps": _stats_for(weekday_gaps),
        "weekend_or_holiday_gaps": _stats_for(weekend_gaps),
        "up_gaps": _stats_for(up_gaps),
        "down_gaps": _stats_for(down_gaps),
    }
