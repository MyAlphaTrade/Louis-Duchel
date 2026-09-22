"""Protocole d'import des donnees prospectives -- D5 (verrouille, 2026-09-20).

Regles verrouillees, codees ici sous forme de fonctions PURES :
- US Tech 100, M15 uniquement.
- Bornes obligatoires, jamais les valeurs par defaut du code :
  `start_date` = horodatage de la derniere bougie stockee (incluse), jamais
  anterieur ; `end_date` = ouverture de la derniere bougie CLOTUREE (heure
  UTC arrondie au quart d'heure inferieur, moins 15 min). Raison : le code
  d'import actuel prend `date_to = maintenant` (bougie en formation
  incluse) et, sans `start_date`, re-telecharge depuis l'an 2000.
- Collision (D5, tranchee le 2026-09-21, R1 -- arret strict) : meme
  horodatage deja present ET OHLC different (comparaison EXACTE, aucune
  tolerance numerique). Un chevauchement a OHLC identique est `unchanged` :
  aucune ecriture. Volume et spread ne determinent pas la collision ; ils
  sont rapportes a titre informatif.
- `start_date` doit etre EGAL a la derniere bougie actuellement stockee ; un
  `start_date` different (anterieur ou posterieur), ou une bougie du lot
  anterieure a `start_date`, refuse l'import AVANT toute ecriture.
- Une collision n'est admise que sur la derniere bougie stockee, et
  seulement si elle est explicitement identifiee comme partielle
  (`KNOWN_PARTIAL_BARS` : horodatage ET OHLC partiel constate a l'attestation
  D6). Exception de premier import : la bougie 2026-09-16T00:45:00Z. Des
  qu'elle est remplacee par sa version cloturee, elle n'est plus identifiee
  comme partielle : toute collision ulterieure sur elle est une anomalie.
- Toute autre collision (bougie deja cloturee ou anterieure) est une ANOMALIE
  BLOQUANTE : arret avant toute ecriture, aucun ecrasement, rapport de
  l'ancien et du nouvel OHLC. Le rapport est adresse a Louis, qui decide de la
  suite.
- Un import produit une entree de journal append-only (contenu ci-dessous),
  commitee a chaque import (decision de commit : hors de ce module).

PROCEDURE D'ORCHESTRATION PREVUE (a implementer plus tard, sur demande
explicite mois par mois ; le garde-fou du endpoint d'import de main.py est
explicitement differe) :
  1. fenetre = compute_import_window(derniere_bougie_stockee, maintenant)
  2. recuperer les bougies MT5 dans cette fenetre
  3. `_merge_market_data` (fonction pure de main.py) -> collisions AVANT
     toute ecriture
  4. preflight_check(...) : si anomalie, ABANDON avant d'ecrire quoi que ce soit
  5. ecriture, puis verify_reference + journal + commit.
Le controle 3-4 est volontairement AVANT l'ecriture : detecter une
anomalie apres l'ecriture serait trop tard, l'historique aurait deja ete
ecrase. `plan_import` (pure) porte tous les controles ; `guarded_import`
n'appelle l'ecrivain fourni QU'APRES un plan valide. Le endpoint
/market-data/import de main.py n'est PAS modifie et n'est pas protege : un
import du protocole doit passer par `guarded_import`.

Module pur : aucun acces DB ni MT5.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

MAX_INTERVAL_REPORT_MINUTES = 60  # liste des intervalles > 60 min (D5)
OHLC_FIELDS = ("open", "high", "low", "close")          # seuls champs qui determinent une collision
INFORMATIVE_FIELDS = ("volume", "spread")               # rapportes, jamais determinants

# Bougie UNIQUE, explicitement identifiee comme partielle (horodatage ET OHLC
# partiel constate a l'attestation D6). DURCISSEMENT (2026-09-21) : cette
# exception historique est fermee par construction, pas seulement par
# convention -- aucune fonction de ce module n'accepte de parametre pour
# l'etendre ou la remplacer, et la table elle-meme est IMMUABLE
# (MappingProxyType : toute tentative d'ajout/modification leve TypeError).
# Reconnaitre une AUTRE bougie comme partielle exige de modifier ce module et
# releve d'un amendement date, jamais d'un argument d'appel ni d'une mutation
# a chaud de cette table.
KNOWN_PARTIAL_BARS = MappingProxyType({
    "2026-09-16T00:45:00Z": MappingProxyType({"open": 28997.4, "high": 29001.9, "low": 28991.9, "close": 28993.65}),
})


class ImportAnomaly(Exception):
    """Import refuse AVANT toute ecriture (collision non admise, `start_date`
    incorrect, ...). `details` porte le rapport structure."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def _to_utc(dt):
    if dt.tzinfo is None:
        raise ValueError("Datetime naif refuse : un import doit etre borne en UTC explicite.")
    return dt.astimezone(timezone.utc)


def to_canonical(dt) -> str:
    return _to_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def last_closed_bar_open(now_utc):
    """Ouverture de la derniere bougie M15 entierement CLOTUREE a `now_utc` :
    heure arrondie au quart d'heure inferieur, moins 15 min."""
    now = _to_utc(now_utc)
    floored = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    return floored - timedelta(minutes=15)


def compute_import_window(last_stored_ts, now_utc):
    """Bornes OBLIGATOIRES d'un import (D5). Retourne `start_date` et
    `end_date` au format ISO avec offset explicite (+00:00), utilisables tels
    quels par l'API d'import. Leve ValueError s'il n'y a rien a importer."""
    start = _parse(last_stored_ts)
    end = last_closed_bar_open(now_utc)
    if end < start:
        raise ValueError(
            f"Rien a importer : derniere bougie cloturee {to_canonical(end)} "
            f"anterieure a la derniere bougie stockee {last_stored_ts}."
        )
    return {"start_date": start.astimezone(timezone.utc).isoformat(), "end_date": end.isoformat()}


def canonical_ts(raw) -> str:
    """Instant UTC canonique `YYYY-MM-DDTHH:MM:SSZ` d'un horodatage ISO 8601
    (meme regle que la couche de fusion de main.py : un horodatage naif est
    suppose UTC)."""
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ohlc_differs(old, new):
    return any(old.get(f) != new.get(f) for f in OHLC_FIELDS)


def _snapshot(data):
    return {f: data.get(f) for f in OHLC_FIELDS + INFORMATIVE_FIELDS}


def classify_candles(existing_by_canonical, candles):
    """Classe chaque bougie du lot, SANS aucune regle de protocole :
    absente -> `to_insert` ; presente a OHLC identique -> `unchanged` ;
    presente a OHLC different -> `collisions` (ancien et nouvel etat).
    Meme semantique que `_merge_market_data` de main.py (test de parite)."""
    to_insert, collisions, unchanged = [], [], 0
    for c in candles:
        ts = canonical_ts(c["timestamp"])
        old = existing_by_canonical.get(ts)
        if old is None:
            to_insert.append({**c, "timestamp": ts})
        elif _ohlc_differs(old, c):
            collisions.append({"timestamp": ts, "old": _snapshot(old), "new": _snapshot(c), "candle": {**c, "timestamp": ts}})
        else:
            unchanged += 1
    return to_insert, collisions, unchanged


def _is_identified_partial(collision, last_stored_ts):
    """Reconnaissance de LA bougie partielle unique -- source unique
    `KNOWN_PARTIAL_BARS`, jamais parametrable par l'appelant."""
    ts = collision["timestamp"]
    if ts != last_stored_ts or ts not in KNOWN_PARTIAL_BARS:
        return False
    return all(collision["old"].get(f) == KNOWN_PARTIAL_BARS[ts][f] for f in OHLC_FIELDS)


def classify_collisions(collisions, last_stored_ts):
    """R1 : seule est ATTENDUE une collision sur la derniere bougie stockee
    explicitement identifiee comme partielle (horodatage et OHLC partiel
    stocke, `KNOWN_PARTIAL_BARS`). Toute autre collision est une ANOMALIE."""
    expected = [c for c in collisions if _is_identified_partial(c, last_stored_ts)]
    anomalies = [c for c in collisions if not _is_identified_partial(c, last_stored_ts)]
    return {"expected": expected, "anomalies": anomalies}


def _describe(collision):
    old, new = collision["old"], collision["new"]
    ohlc = ", ".join(f"{f} {old[f]} -> {new[f]}" for f in OHLC_FIELDS)
    info = ", ".join(f"{f} {old[f]} -> {new[f]}" for f in INFORMATIVE_FIELDS)
    return f"{collision['timestamp']} : {ohlc} (informatif : {info})"


def preflight_check(collisions, last_stored_ts):
    """A appeler AVANT toute ecriture. Leve ImportAnomaly (avec rapport de
    l'ancien et du nouvel OHLC) pour toute collision non admise par R1."""
    result = classify_collisions(collisions, last_stored_ts)
    if result["anomalies"]:
        raise ImportAnomaly(
            "Collision non admise (seule la derniere bougie stockee, explicitement identifiee comme "
            f"partielle, peut etre mise a jour ; derniere bougie stockee : {last_stored_ts}) : "
            + " ; ".join(_describe(c) for c in result["anomalies"])
            + ". Import abandonne avant ecriture, aucun ecrasement.",
            {"anomalies": [{k: c[k] for k in ("timestamp", "old", "new")} for c in result["anomalies"]]},
        )
    return result


def plan_import(existing_by_timestamp, candles, start_date):
    """Decision COMPLETE d'un import du protocole (D5, R1), sans aucun acces
    base : leve ImportAnomaly AVANT toute ecriture, sinon retourne le plan.
    `existing_by_timestamp` : {horodatage ISO quelconque : donnees de la bougie}
    ; `candles` : dicts `timestamp/open/high/low/close[/volume/spread]`.
    Aucun parametre pour designer une bougie partielle : source unique
    `KNOWN_PARTIAL_BARS`."""
    existing = {canonical_ts(ts): data for ts, data in existing_by_timestamp.items()}
    if not existing:
        raise ImportAnomaly("Aucune bougie stockee : un import du protocole prolonge une serie existante. "
                            "Import refuse avant ecriture.")
    last_stored = max(existing)
    start = canonical_ts(start_date)
    if start != last_stored:
        raise ImportAnomaly(
            f"start_date {start} different de la derniere bougie stockee {last_stored} : import refuse avant ecriture.",
            {"start_date": start, "last_stored": last_stored},
        )
    for c in candles:
        if canonical_ts(c["timestamp"]) < start:
            raise ImportAnomaly(
                f"Bougie {canonical_ts(c['timestamp'])} du lot anterieure a start_date {start} : import refuse avant ecriture.",
                {"start_date": start, "candle": canonical_ts(c["timestamp"])},
            )
    to_insert, collisions, unchanged = classify_candles(existing, candles)
    classified = preflight_check(collisions, last_stored)
    return {
        "start_date": start,
        "last_stored": last_stored,
        "to_insert": to_insert,
        "to_update": [c["candle"] for c in classified["expected"]],
        "unchanged": unchanged,
        "expected_collisions": [c["timestamp"] for c in classified["expected"]],
    }


def guarded_import(existing_by_timestamp, candles, start_date, write):
    """Import garde : `write(plan)` n'est appele QU'APRES un plan valide. Toute
    anomalie leve ImportAnomaly sans que `write` soit jamais invoque."""
    plan = plan_import(existing_by_timestamp, candles, start_date)
    write(plan)
    return plan


def interval_report(bars, threshold_minutes=MAX_INTERVAL_REPORT_MINUTES):
    """Plus grand intervalle entre deux bougies consecutives et liste des
    intervalles > seuil (revue humaine, non bloquant). `bars` tries."""
    max_gap = None
    over = []
    for prev, cur in zip(bars, bars[1:]):
        minutes = int((_parse(cur["timestamp"]) - _parse(prev["timestamp"])).total_seconds() // 60)
        if max_gap is None or minutes > max_gap:
            max_gap = minutes
        if minutes > threshold_minutes:
            over.append((prev["timestamp"], cur["timestamp"], minutes))
    return {"max_interval_minutes": max_gap, "intervals_over_threshold": over, "threshold_minutes": threshold_minutes}


def format_journal_entry(*, import_datetime_utc, symbol, timeframe, requested_start, requested_end,
                         inserted, updated, unchanged, collision_timestamps, first_bar, last_bar,
                         series_n, series_sha256, reference_check, intervals):
    """Entree de journal (D5) : champs dans un ordre fixe, texte LF."""
    over = intervals["intervals_over_threshold"]
    lines = [
        "=== IMPORT ===",
        f"import_datetime_utc: {import_datetime_utc}",
        f"symbol: {symbol}",
        f"timeframe: {timeframe}",
        f"requested_start: {requested_start}",
        f"requested_end: {requested_end}",
        f"inserted: {inserted}",
        f"updated: {updated}",
        f"unchanged: {unchanged}",
        f"collisions: {len(collision_timestamps)} [{', '.join(collision_timestamps)}]",
        f"first_stored_bar: {first_bar}",
        f"last_stored_bar: {last_bar}",
        f"series_n: {series_n}",
        f"series_sha256: {series_sha256}",
        f"reference_ok: {str(reference_check['ok']).lower()}",
        f"reference_sha256: {reference_check['sha256']}",
        f"max_interval_minutes: {intervals['max_interval_minutes']}",
        f"intervals_over_{intervals['threshold_minutes']}min: {len(over)}",
    ]
    lines += [f"  - {a} -> {b} ({m} min)" for a, b, m in over]
    return "\n".join(lines) + "\n\n"


def append_journal_entry(path, entry_text):
    """Ajout SEUL a la fin du journal : jamais de reecriture ni de
    troncature. Refuse un journal existant qui ne se termine pas par un
    saut de ligne (etat ambigu) et tout retour chariot."""
    if "\r" in entry_text or not entry_text.endswith("\n"):
        raise ValueError("Entree invalide : fins de ligne LF exigees, terminee par un saut de ligne.")
    p = Path(path)
    if p.exists() and p.stat().st_size > 0:
        with open(p, "rb") as f:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                raise ValueError("Journal existant ne se terminant pas par un saut de ligne : ajout refuse.")
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(entry_text)
