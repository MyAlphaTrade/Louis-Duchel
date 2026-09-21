"""Analyse de stabilite historique -- D4 (verrouillee, 2026-09-21).

Analyse SEPAREE, etiquetee "stabilite -- non probante" et jamais
"validation" : elle reutilise des donnees qui ont servi a choisir
l'hypothese. Elle mesure seulement si l'ecart range/tendance observe sur
l'historique se concentre dans une periode ; elle ne teste pas H1.

Regles verrouillees codees ici :
D4.2  Population figee : observations eligibles au sens D1 (horizon complet,
      ADX(M15) disponible, groupe range ou tendance), calculees sur la serie
      TRONQUEE a REFERENCE_LAST_BAR. Aucun import ulterieur ne la modifie.
      Les evenements NON MATURES a la reference (22 au 2026-09-16) sont
      exclus de D4 et de H1, definitivement : leur horizon n'est pas complet
      (issue censuree par la fin des donnees, non observee) et ils ne sont
      pas prospectifs (T_event < debut prospectif, debut d'issue deja visible
      dans les donnees de reference).
D4.3  Six periodes figees, semestres civils UTC selon T_event.
D4.4  Une periode est lisible si CHAQUE groupe compte >= 30 observations ;
      sinon seuls les effectifs sont produits, AUCUNE statistique. Ce seuil
      est une regle de lisibilite, jamais un critere de selection.
D4.5  Un seul tau_hist pour toutes les periodes (plus petit horizon reel
      parmi la population, range + tendance).
D4.6  Sorties par periode lisible : n, RMST(tau_hist) par groupe, Delta,
      IC 95 % bootstrap i.i.d. stratifie (D2, etiquette `D4:<periode>`),
      taux de comblement a tau_hist, decomposition du Delta, comblements
      apres tau et jamais combles dans l'horizon. RIEN d'autre : ni
      log-rank, ni p-valeur, ni bootstrap par blocs, ni mediane.
D4.7  Aucune agregation entre periodes (ni comptage de signes, ni moyenne).
D4.8  Pare-feu : aucun resultat ne modifie H1, D1-D3, tau, seuils, horizon.
D4.9  Execution une seule fois, APRES le commit de la preinscription, avec le
      code reference par ce commit.

Ce module ne s'execute PAS sur des issues avant ce commit : il ne contient
aucun acces DB.
"""
import exp2_protocol as p
from data_integrity import REFERENCE_LAST_BAR, reference_series
from survival_stats import (
    DEFAULT_N_BOOT, DEFAULT_SEED, READING_CLAUSE, LabelLedger, bootstrap_delta_rmst_iid, describe_group,
)

PERIODS = ("2024-S1", "2024-S2", "2025-S1", "2025-S2", "2026-S1", "2026-S2")
MIN_N_PER_GROUP = 30
GROUPS = p.TEST_GROUPS


def period_of(t_event):
    """Semestre civil UTC de `t_event` (ISO canonique). Refuse toute date hors
    des six periodes figees."""
    if not p._CANONICAL_TS.match(t_event):
        raise ValueError(f"T_event non canonique : {t_event!r}")
    label = f"{t_event[:4]}-S{1 if int(t_event[5:7]) <= 6 else 2}"
    if label not in PERIODS:
        raise ValueError(f"Periode hors du perimetre fige de D4 : {label} ({t_event}).")
    return label


def historical_population(m15_bars, reference_last_bar=REFERENCE_LAST_BAR, prospective_start=p.PROSPECTIVE_START,
                          horizon_bars=p.HORIZON_BARS):
    """Population de D4.2, calculee sur les bougies uniquement (aucune issue).
    Retourne `population` (eligibles historiques), `excluded_not_mature`
    (evenements non matures a la reference, avec leur groupe : a lister dans la
    preinscription), et des effectifs de controle."""
    series = reference_series(m15_bars, reference_last_bar)
    observations = p.list_observations(series, horizon_bars=horizon_bars)
    if any(o["t_event"] >= prospective_start for o in observations):
        raise ValueError("Evenement prospectif dans la serie tronquee : reference incoherente.")
    population = p.select_eligible(observations, prospective_only=False)
    not_mature = [o for o in observations if not o["mature"]]
    return {
        "population": population,
        "excluded_not_mature": [{"t_event": o["t_event"], "zone": o["zone"]} for o in not_mature],
        "n_series": len(series),
        "last_bar": series[-1]["timestamp"] if series else None,
        "n_events": len(observations),
        "n_context_unavailable_mature": sum(1 for o in observations if o["mature"] and o["zone"] == "indisponible"),
        "n_intermediaire_mature": sum(1 for o in observations if o["mature"] and o["zone"] == "intermediaire"),
    }


def tau_hist(population):
    """D4.5 : tau historique unique (regle de tau : range + tendance seuls)."""
    return p.compute_tau(population)


def period_counts(population):
    """Effectifs par periode et par groupe (comptage seul), les six periodes
    toujours presentes."""
    counts = {period: {g: 0 for g in GROUPS} for period in PERIODS}
    for o in population:
        counts[period_of(o["t_event"])][o["zone"]] += 1
    return counts


def is_readable(counts_for_period, minimum=MIN_N_PER_GROUP):
    return all(counts_for_period[g] >= minimum for g in GROUPS)


def run_stability_analysis(population_with_outcomes, tau, n_boot=DEFAULT_N_BOOT, master_seed=DEFAULT_SEED,
                           minimum=MIN_N_PER_GROUP, prospective_start=p.PROSPECTIVE_START):
    """D4.6. Entree : observations de la population historique AVEC issues
    (`filled`, `fill_minutes`). Sortie : un resultat par periode, sans aucune
    agregation entre periodes et sans p-valeur."""
    if any(o["t_event"] >= prospective_start for o in population_with_outcomes):
        raise ValueError("D4 refuse toute observation prospective.")
    counts = period_counts(population_with_outcomes)
    ledger = LabelLedger()
    results = {}
    for period in PERIODS:
        c = counts[period]
        if not is_readable(c, minimum):
            results[period] = {"readable": False, "n_range": c["range"], "n_tendance": c["tendance"]}
            continue
        obs = {g: [o for o in population_with_outcomes if o["zone"] == g and period_of(o["t_event"]) == period]
               for g in GROUPS}
        te = {g: [p._time_and_event(o, tau) for o in obs[g]] for g in GROUPS}
        times = {g: [t for t, _ in te[g]] for g in GROUPS}
        events = {g: [e for _, e in te[g]] for g in GROUPS}
        desc = {g: describe_group(times[g], events[g], tau) for g in GROUPS}
        boot = bootstrap_delta_rmst_iid(times["range"], times["tendance"], ledger.claim(f"D4:{period}"),
                                        n_boot=n_boot, master_seed=master_seed)
        results[period] = {
            "readable": True,
            "n_range": c["range"], "n_tendance": c["tendance"],
            "delta_rmst_range_minus_tendance": desc["range"]["rmst"] - desc["tendance"]["rmst"],
            "ci_95": boot["interval"], "label": boot["label"],
            "delta_decomposition": {
                "not_filled_at_tau": desc["range"]["contribution_not_filled"] - desc["tendance"]["contribution_not_filled"],
                "filled_before_tau": desc["range"]["contribution_filled"] - desc["tendance"]["contribution_filled"],
            },
            "descriptive": {
                g: {
                    "rmst": desc[g]["rmst"], "fill_rate_at_tau": desc[g]["fill_rate_at_tau"],
                    "n_filled_after_tau": sum(1 for o in obs[g] if o["filled"] and o["fill_minutes"] > tau),
                    "n_never_filled_in_horizon": sum(1 for o in obs[g] if not o["filled"]),
                }
                for g in GROUPS
            },
        }
    return {
        "label": "stabilite -- non probante",
        "tau_hist_minutes": tau,
        "periods": results,
        "reading_clause": READING_CLAUSE,
    }
