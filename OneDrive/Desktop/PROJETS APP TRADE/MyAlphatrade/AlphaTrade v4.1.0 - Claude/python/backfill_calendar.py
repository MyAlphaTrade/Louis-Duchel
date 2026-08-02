"""AlphaTrade - rattrapage ponctuel du Calendrier.

A executer UNE FOIS pour reconstruire data/calendar_data.json depuis l'historique
complet deja present dans data/alphatrade.db (table `trades`) -- necessaire car
l'ancien calendar_data.json s'etait arrete de se mettre a jour a un moment donne
(19/07/2026 : dernier point trouve le 04/07/2026) alors que la base SQLite, elle,
contient tout l'historique reel jusqu'a aujourd'hui. Sans ce script, seuls les
trades clotures APRES ce rattrapage seraient comptes (voir le garde-fou dans
sync_history()).

Connexion en lecture seule (mode=ro) : le moteur peut tourner en parallele sans
risque d'ecriture concurrente ou de verrou.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import calendar_tracker

DATA_DIR = Path(os.environ.get("ALPHATRADE_DATA_DIR", Path.home() / "AlphaTrade"))
DB_FILE = DATA_DIR / "alphatrade.db"


def main() -> None:
    if not DB_FILE.exists():
        print(f"Base introuvable : {DB_FILE}")
        return
    uri = f"file:{DB_FILE.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cur = conn.execute("SELECT symbol, profit, close_time FROM trades WHERE status='CLOSED'")
    trades = [{"symbol": row[0], "profit": row[1], "close_time": row[2]} for row in cur.fetchall()]
    conn.close()

    data = calendar_tracker.rebuild_from_trades(trades)
    print(f"{len(trades)} trades relus depuis {DB_FILE}")
    print(f"{len(data['daily'])} jours reconstruits, ecrit dans {calendar_tracker.CALENDAR_FILE}")
    print(f"Total : {data['alltime']['trades']} trades, profit {data['alltime']['profit']:.2f} $")


if __name__ == "__main__":
    main()
