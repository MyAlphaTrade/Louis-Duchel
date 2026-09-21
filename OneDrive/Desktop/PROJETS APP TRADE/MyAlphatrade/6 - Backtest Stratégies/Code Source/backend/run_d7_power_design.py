"""Execution unique de l'etude de conception D7 sur le reservoir historique.

Parametres FIGES (aucun argument ne peut les modifier) : ceux de
`power_design`. Lecture seule de la base (URI mode=ro). N'importe pas main.py.
Sorties poolees uniquement : N, part censuree, RMST poole, C -- jamais de
statistique par groupe (D7.9).

Usage :
    python run_d7_power_design.py            execution complete + fichier de resultat
    python run_d7_power_design.py --smoke    controle rapide, N'ECRIT RIEN, non probant

Le fichier de resultat consigne : graine maitre, parametres exacts,
empreinte du reservoir, etat du code (HEAD + empreinte SHA-256 de chaque
fichier source, dirty = vrai tant que le code n'est pas commite), resultats
par cellule, limites. Il n'est jamais ecrase.
"""
import hashlib
import json
import multiprocessing
import os
import platform
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

import exp2_protocol as p
import power_design as pd
import stability_analysis as sa
from data_integrity import REFERENCE_N, REFERENCE_LAST_BAR, reference_series, sha256_lf_normalized, verify_reference
from survival_stats import DEFAULT_SEED, percentile_indices

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "data", "strategylab.db")
RESULT_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "Pre-registrations"))
SYMBOL, TIMEFRAME = "US Tech 100", "M15"
EXPECTED_POPULATION = 511      # D4.2 : population historique verrouillee
EXPECTED_EXCLUDED = 22         # D4.2 : evenements non matures a la reference
EXPECTED_TAU_HIST = 42765      # regle de tau (range + tendance), donnees de reference
CODE_FILES = (
    "survival_stats.py", "power_design.py", "data_integrity.py", "exp2_protocol.py",
    "stability_analysis.py", "relations_experiment.py", "gap_analysis.py", "indicators.py",
    "run_d7_power_design.py",
)
_CANONICAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def load_bars():
    """Bougies M15 US Tech 100, lecture seule, timestamps canoniques."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        users = conn.execute(
            "SELECT user_id, COUNT(*) FROM entities WHERE entity_type='MarketData' "
            "AND json_extract(data,'$.symbol')=? AND json_extract(data,'$.timeframe')=? GROUP BY user_id",
            (SYMBOL, TIMEFRAME),
        ).fetchall()
        if len(users) != 1:
            raise SystemExit(f"ABANDON : {len(users)} comptes possedent {SYMBOL} {TIMEFRAME} (attendu : 1) : {users}")
        rows = conn.execute(
            "SELECT data FROM entities WHERE user_id=? AND entity_type='MarketData' "
            "AND json_extract(data,'$.symbol')=? AND json_extract(data,'$.timeframe')=? "
            "ORDER BY json_extract(data,'$.timestamp')",
            (users[0][0], SYMBOL, TIMEFRAME),
        ).fetchall()
    finally:
        conn.close()
    bars = []
    for (raw,) in rows:
        bar = json.loads(raw)
        bar["timestamp"] = bar["timestamp"].replace("+00:00", "Z")
        if not _CANONICAL.match(bar["timestamp"]):
            raise SystemExit(f"ABANDON : horodatage non canonique {bar['timestamp']!r}")
        bars.append(bar)
    return bars


def git(*args):
    return subprocess.run(["git", "-C", HERE, *args], capture_output=True, text=True, check=True).stdout.strip()


def code_state():
    files = {}
    for name in CODE_FILES:
        with open(os.path.join(HERE, name), "rb") as f:
            files[name] = sha256_lf_normalized(f.read())
    dirty = git("status", "--porcelain", "--", *CODE_FILES)
    return {
        "head_commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "code_files_dirty": bool(dirty),
        "code_files_sha256_lf": files,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "note": ("Le code est execute depuis l'arbre de travail. Tant que `code_files_dirty` est vrai, le "
                 "commit qui le contient n'existe pas encore : il est identifie apres coup en verifiant que "
                 "le SHA-256 (LF) de chaque fichier commite egale la valeur ci-dessus."),
    }


def build_inputs():
    bars = load_bars()
    ref = verify_reference(bars)
    if not ref["ok"]:
        raise SystemExit(f"ABANDON : reference historique alteree : {ref}")
    run = sa.historical_population(bars)
    population = run["population"]
    if len(population) != EXPECTED_POPULATION or len(run["excluded_not_mature"]) != EXPECTED_EXCLUDED:
        raise SystemExit(f"ABANDON : population {len(population)} / exclus {len(run['excluded_not_mature'])} "
                         f"differe du verrou ({EXPECTED_POPULATION} / {EXPECTED_EXCLUDED}).")
    tau = sa.tau_hist(population)
    if tau != EXPECTED_TAU_HIST:
        raise SystemExit(f"ABANDON : tau_hist = {tau} differe du verrou ({EXPECTED_TAU_HIST}).")
    series = reference_series(bars)
    with_outcomes = p.attach_outcomes(population, series)
    reservoir = pd.build_reservoir(with_outcomes, tau)
    return {
        "tau": tau,
        "reservoir": reservoir,
        "pairs": pd.to_pairs(reservoir),
        "reference": {"n": ref["n"], "last_bar": ref["last_bar"], "sha256": ref["sha256"]},
    }


def main(argv):
    smoke = "--smoke" in argv
    unknown = [a for a in argv if a != "--smoke"]
    if unknown:
        raise SystemExit(f"Argument non admis : {unknown} (les parametres de D7 sont figes).")
    started = time.time()
    inputs = build_inputs()
    tau, pairs, reservoir = inputs["tau"], inputs["pairs"], inputs["reservoir"]
    pooled = pd.pooled_summary(pairs, tau)
    print(f"reservoir : n={pooled['n']} censures={pooled['n_censored']} sha256={pd.reservoir_sha256(reservoir)}")
    print(f"tau_hist={tau} rmst_poole={pooled['rmst_pooled']:.3f} C={pooled['c_filled_contribution']:.3f}")

    if smoke:
        # graine maitre distincte : le controle rapide ne consomme AUCUNE etiquette de flux de l'execution reelle
        cell = pd.simulate_cell(pairs, tau, 10, 60, 102, n_sims=3, n_boot=50, master_seed=0)
        print("SMOKE (non probant, rien n'est ecrit) :", json.dumps(cell, ensure_ascii=False))
        return 0

    executed_at = datetime.now(timezone.utc)
    stamp = executed_at.strftime("%Y-%m-%d")
    path = os.path.join(RESULT_DIR, f"D7_RESULT_{stamp}.json")
    if os.path.exists(path):
        raise SystemExit(f"ABANDON : {path} existe deja (un resultat n'est jamais ecrase).")
    state = code_state()

    workers = min(multiprocessing.cpu_count(), len(pd.DELTAS_PCT) * len(pd.SCENARIOS))
    with multiprocessing.Pool(workers) as pool:
        cells = pd.run_grid(pairs, tau, master_seed=DEFAULT_SEED, map_fn=lambda f, xs: pool.map(f, xs, chunksize=1))

    result = {
        "titre": "D7 - etude de conception de puissance (resultat d'execution)",
        "executed_at_utc": executed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": round(time.time() - started, 1),
        "workers": workers,
        "master_seed": DEFAULT_SEED,
        "labels": {
            "scheme": "D7:data:δ={δ}:n={n_range}/{n_tendance}:sim={k} et D7:boot:... (δ en pourcent entier, k = 0..999)",
            "derivation": "random.Random(int.from_bytes(SHA-256(UTF-8('{graine_maitre}|{etiquette}')), 'big'))",
            "n_labels": len(pd.all_labels()),
        },
        "parameters": {
            "deltas_pct": list(pd.DELTAS_PCT),
            "scenarios_n_range_n_tendance": [list(s) for s in pd.SCENARIOS],
            "n_sims_per_cell": pd.N_SIMS,
            "n_boot_per_simulation": pd.N_BOOT,
            "percentile_indices_for_B_1000": list(percentile_indices(pd.N_BOOT)),
            "invariant_tolerance_relative": pd.INVARIANT_TOLERANCE,
        },
        "reference_state": {**inputs["reference"], "expected_n": REFERENCE_N, "expected_last_bar": REFERENCE_LAST_BAR},
        "reservoir": {
            "n": pooled["n"],
            "sha256_lines_T_event_u_e": pd.reservoir_sha256(reservoir),
            "tau_hist_minutes": tau,
            "pooled_outputs": pooled,
        },
        "cells": cells,
        "code_state": state,
        "power_statement": pd.POWER_STATEMENT,
        "limits": list(pd.LIMITS),
        "threshold_rule": ("Le seuil minimal reste 60/60 (D3). Aucun relevement automatique : un relevement a 80 ou 100 "
                           "est une decision explicite de Louis (delai supplementaire ~ +3,3 mois pour 80, ~ +6,5 mois "
                           "pour 100). Aucun abaissement sous 60."),
    }
    os.makedirs(RESULT_DIR, exist_ok=True)
    text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with open(path + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write(f"{digest}  {os.path.basename(path)}\n")
    print(f"resultat : {path}\nsha256 : {digest}\nduree : {result['duration_seconds']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
