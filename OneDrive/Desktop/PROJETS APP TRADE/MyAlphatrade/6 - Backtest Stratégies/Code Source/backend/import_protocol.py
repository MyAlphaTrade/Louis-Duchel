"""Protocole d'import des donnees prospectives -- D5 (verrouille, 2026-09-20).

Regles verrouillees, codees ici sous forme de fonctions PURES :
- US Tech 100, M15 uniquement.
- Bornes obligatoires, jamais les valeurs par defaut du code :
  `start_date` = horodatage de la derniere bougie stockee (incluse), jamais
  anterieur ; `end_date` = ouverture de la derniere bougie CLOTUREE (heure
  UTC arrondie au quart d'heure inferieur, moins 15 min). Raison : le code
  d'import actuel prend `date_to = maintenant` (bougie en formation
  incluse) et, sans `start_date`, re-telecharge depuis l'an 2000.
- Collisions : au plus UNE attendue -- la derniere bougie precedemment
  stockee, si elle etait partielle. Toute collision sur une bougie
  anterieure est une ANOMALIE : arret et rapport avant tout autre calcul.
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
ecrase.

Module pur : aucun acces DB ni MT5.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_INTERVAL_REPORT_MINUTES = 60  # liste des intervalles > 60 min (D5)


class ImportAnomaly(Exception):
    """Collision sur une bougie anterieure a la derniere bougie stockee."""


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


def classify_collisions(collision_timestamps, last_stored_ts):
    """Separe la collision attendue (derniere bougie stockee) des anomalies
    (toute autre bougie)."""
    expected = [t for t in collision_timestamps if t == last_stored_ts]
    anomalies = [t for t in collision_timestamps if t != last_stored_ts]
    return {"expected": expected, "anomalies": anomalies}


def preflight_check(collision_timestamps, last_stored_ts):
    """A appeler AVANT toute ecriture. Leve ImportAnomaly si une bougie
    anterieure serait ecrasee."""
    result = classify_collisions(collision_timestamps, last_stored_ts)
    if result["anomalies"]:
        raise ImportAnomaly(
            "Collision sur une bougie anterieure a la derniere bougie stockee "
            f"({last_stored_ts}) : {result['anomalies']}. Import abandonne avant ecriture."
        )
    return result


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
