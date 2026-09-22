"""Controle par mutation des points critiques du protocole de l'experience 2
(D1-D7). Pour chaque mutation : copie des modules dans un dossier temporaire,
modification d'UNE ligne, execution des tests concernes. Une mutation est
"tuee" si les tests echouent ; une mutation qui SURVIT revele un trou de
couverture. Ne modifie jamais les fichiers du depot.

Usage : python mutation_check.py      (code de sortie 1 si une mutation survit)
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

S, E, P, D, W, I = ("survival_stats.py", "exp2_protocol.py", "power_design.py", "stability_analysis.py",
                    "data_integrity.py", "import_protocol.py")
T_S, T_E, T_P, T_D, T_W, T_I = ("test_survival_stats", "test_exp2_protocol", "test_power_design",
                                "test_stability_analysis", "test_data_integrity", "test_import_protocol")

MUTATIONS = [
    # (nom, fichier, ancien, nouveau, modules de test)
    ("D2 percentiles : borne haute decalee", S, "975 * (b - 1) // 1000", "975 * b // 1000", [T_S]),
    ("D2 percentiles : borne basse decalee", S, "25 * (b - 1) // 1000", "25 * b // 1000", [T_S]),
    ("D2 flux : l'etiquette n'entre plus dans la graine", S,
     'f"{master_seed}|{label}".encode("utf-8")', 'f"{master_seed}".encode("utf-8")', [T_S]),
    ("D2 flux : le bootstrap par blocs partage le flux i.i.d.", S,
     "rng = derive_rng(label, master_seed)\n    randrange = rng.randrange\n    reps, discarded",
     'rng = derive_rng("H1:iid", master_seed)\n    randrange = rng.randrange\n    reps, discarded', [T_S]),
    ("D2 flux : une etiquette peut etre reutilisee", S, "if label in self._used:", "if False:", [T_S]),
    ("Verdict : retour a 'non soutenue'", S, '"soutenue" if supported else "non concluante"',
     '"soutenue" if supported else "non soutenue"', [T_S]),
    ("tau : le groupe intermediaire n'est plus refuse", E, "if o[\"zone\"] not in TEST_GROUPS:\n            raise ValueError(f\"tau",
     "if False:\n            raise ValueError(f\"tau", [T_E]),
    ("H1 : les deux bootstraps partagent une etiquette", E, 'LABEL_H1_BLOCKS = "H1:blocs"', 'LABEL_H1_BLOCKS = "H1:iid"', [T_E]),
    ("D6 : les bougies posterieures ne sont plus marquees prospectives", E,
     '"prospective": t >= prospective_start', '"prospective": True', [T_E]),
    ("D7 : la censure est reduite comme un temps d'evenement", P,
     "times_r = [factor * u if e else float(tau) for u, e in drawn_range]", "times_r = [factor * u for u, e in drawn_range]", [T_P]),
    ("D7 : comblement exactement a tau traite comme censure", P,
     "e = 1 if (filled and fill_minutes <= tau) else 0", "e = 1 if (filled and fill_minutes < tau) else 0", [T_P]),
    ("D7 : tendance tiree avant range", P,
     "    drawn_range = [pairs[rng.randrange(size)] for _ in range(n_range)]\n"
     "    drawn_tendance = [pairs[rng.randrange(size)] for _ in range(n_tendance)]\n",
     "    drawn_tendance = [pairs[rng.randrange(size)] for _ in range(n_tendance)]\n"
     "    drawn_range = [pairs[rng.randrange(size)] for _ in range(n_range)]\n", [T_P]),
    ("D7 : invariants desactives", P,
     '"""Invariants obligatoires (D7.2e) sur un groupe simule."""\n',
     '"""Invariants obligatoires (D7.2e) sur un groupe simule."""\n    return\n', [T_P]),
    ("D7 : delta mal echelonne", P, "factor = 1.0 - delta_pct / 100.0", "factor = 1.0 - delta_pct / 10.0", [T_P]),
    ("D7 : signe de l'effet vrai inverse", P, "minutes = -delta * s[", "minutes = delta * s[", [T_P]),
    ("D7 : flux de bootstrap identique au flux de donnees", P, 'f"D7:boot:δ=', 'f"D7:data:δ=', [T_P]),
    ("D7 : reservoir non trie", P, "rows.sort(key=lambda r: r[0])", "pass", [T_P]),
    ("D7 : le simulateur accepte des 3-uplets", P, "len(item) != 2", "len(item) < 2", [T_P]),
    ("D4 : frontiere de semestre decalee", D, "1 if int(t_event[5:7]) <= 6 else 2", "1 if int(t_event[5:7]) < 6 else 2", [T_D]),
    ("D4 : population non tronquee a la reference", D,
     "series = reference_series(m15_bars, reference_last_bar)", "series = m15_bars", [T_D]),
    ("D4 : seuil de lisibilite exclusif", D, "counts_for_period[g] >= minimum", "counts_for_period[g] > minimum", [T_D]),
    ("D4 : meme etiquette de flux pour toutes les periodes", D, 'ledger.claim(f"D4:{period}")', 'ledger.claim("D4:x")', [T_D]),
    ("Integrite : la reference exclut sa propre derniere bougie", W, 'b["timestamp"] <= last_bar]', 'b["timestamp"] < last_bar]', [T_W, T_D]),
    # --- D5 / R1 : garde-fou d'import (import_protocol.py) ---
    ("D5 : la bougie partielle n'est plus liee a son OHLC stocke", I,
     'return all(collision["old"].get(f) == KNOWN_PARTIAL_BARS[ts][f] for f in OHLC_FIELDS)', "return True", [T_I]),
    ("D5 : une bougie partielle est admise meme si ce n'est pas la derniere stockee", I,
     "if ts != last_stored_ts or ts not in KNOWN_PARTIAL_BARS:", "if ts not in KNOWN_PARTIAL_BARS:", [T_I]),
    ("D5 : start_date anterieur accepte", I, "if start != last_stored:", "if start > last_stored:", [T_I]),
    ("D5 : start_date posterieur accepte", I, "if start != last_stored:", "if start < last_stored:", [T_I]),
    ("D5 : bougie du lot anterieure a start_date acceptee", I,
     'if canonical_ts(c["timestamp"]) < start:', "if False:", [T_I]),
    ("D5 : le close n'entre plus dans la collision", I,
     "return any(old.get(f) != new.get(f) for f in OHLC_FIELDS)", "return any(old.get(f) != new.get(f) for f in OHLC_FIELDS[:3])", [T_I]),
    ("D5 : le volume et le spread entrent dans la collision", I,
     "return any(old.get(f) != new.get(f) for f in OHLC_FIELDS)",
     "return any(old.get(f) != new.get(f) for f in OHLC_FIELDS + INFORMATIVE_FIELDS)", [T_I]),
    ("D5 : un chevauchement identique est traite comme collision", I, "elif _ohlc_differs(old, c):", "elif True:", [T_I]),
    ("D5 : les anomalies ne bloquent plus", I, 'if result["anomalies"]:', "if False:", [T_I]),
    ("D5 : l'ecrivain est appele avant les controles", I,
     "    plan = plan_import(existing_by_timestamp, candles, start_date)\n    write(plan)\n",
     "    write(None)\n    plan = plan_import(existing_by_timestamp, candles, start_date)\n", [T_I]),
    ("D5 : une serie vide est acceptee", I, "if not existing:", "if False:", [T_I]),
    # --- D5 / durcissement (2026-09-21) : exception 00:45 fermee par construction ---
    ("D5 : la table des bougies partielles redevient mutable", I,
     "KNOWN_PARTIAL_BARS = MappingProxyType({\n"
     '    "2026-09-16T00:45:00Z": MappingProxyType({"open": 28997.4, "high": 29001.9, "low": 28991.9, "close": 28993.65}),\n'
     "})",
     'KNOWN_PARTIAL_BARS = {\n'
     '    "2026-09-16T00:45:00Z": {"open": 28997.4, "high": 29001.9, "low": 28991.9, "close": 28993.65},\n'
     '}', [T_I]),
    ("D5 : plan_import reaccepte un parametre partial_bars generique", I,
     "def plan_import(existing_by_timestamp, candles, start_date):",
     "def plan_import(existing_by_timestamp, candles, start_date, partial_bars=None):\n"
     "    if partial_bars:\n"
     "        globals()['KNOWN_PARTIAL_BARS'] = {**KNOWN_PARTIAL_BARS, **partial_bars}", [T_I]),
]


def run_mutation(name, filename, old, new, tests):
    with tempfile.TemporaryDirectory() as tmp:
        for path in glob.glob(os.path.join(HERE, "*.py")):
            shutil.copy(path, tmp)
        target = os.path.join(tmp, filename)
        with open(target, encoding="utf-8", newline="") as f:
            source = f.read()
        if source.count(old) != 1:
            return "INVALIDE", f"motif trouve {source.count(old)} fois (attendu : 1)"
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(source.replace(old, new))
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run([sys.executable, "-m", "unittest", *tests], cwd=tmp, env=env,
                                capture_output=True, text=True, timeout=600)
        return ("TUEE" if result.returncode != 0 else "SURVIVANTE"), ""


def main():
    survivors = 0
    for name, filename, old, new, tests in MUTATIONS:
        status, detail = run_mutation(name, filename, old, new, tests)
        print(f"{status:11s} {name} ({filename}) {detail}")
        if status != "TUEE":
            survivors += 1
    print(f"\n{len(MUTATIONS) - survivors}/{len(MUTATIONS)} mutations detectees.")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
