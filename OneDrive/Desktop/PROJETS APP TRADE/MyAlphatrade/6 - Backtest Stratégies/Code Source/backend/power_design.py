"""Etude de conception de puissance -- D7 (verrouillee, 2026-09-21).

Etude de CONCEPTION, realisee avant la v0.2 et avant tout registre de
declenchement. Elle ne teste PAS H1 et ne calcule aucune issue prospective.

Mecanisme (D7.2), tel que verrouille :
- Reservoir : les observations de la population historique D4.2, reduites a
  (u_i, e_i) avec u_i = min(T_i, tau_hist), e_i = 1 si comblee a t <= tau_hist,
  sinon 0 ; toute observation e = 0 vaut EXACTEMENT tau_hist ; aucune
  information au-dela de tau_hist ; le groupe n'est pas conserve.
- Ordre canonique : tri par T_event croissant ; empreinte SHA-256 des lignes
  UTF-8 LF `T_event|u|e`. T_event ne sert qu'a cet ordre, en amont : le
  simulateur ne recoit que des paires (u, e).
- Tirage : uniforme avec remise depuis le meme reservoir poole, n_range
  indices puis n_tendance indices.
- Transformation : tendance inchangee ; range : si e = 1, u' = (1 - delta) * u
  et e' = 1 ; si e = 0, u' = tau_hist et e' = 0. Aucune transformation de
  censure, aucun arrondi ; delta = 0 est l'identite.
- Effet reel : Delta_vrai(delta) = -delta * C, C = contribution moyenne des
  seuls comblements du reservoir. delta est le parametre NOMINAL, pas l'effet.
- Portee : le scenario accelere uniquement les comblements observables avant
  tau_hist ; il ne modifie ni la proportion de comblements ni la queue
  (hypothese CONSERVATRICE sur la queue).
- tau_hist est le plafond et l'unique point de censure simule.
- Critere : IC principal de D1/D2 (bootstrap i.i.d. stratifie, percentiles
  D2), exclusion de 0 ; flux D2-flux dedies, une etiquette par jeu et par
  role, jamais reutilisee.

Statut de la puissance simulee : propriete CONDITIONNELLE du scenario de
conception. Ce n'est ni une estimation de la puissance reelle de H1, ni une
probabilite de detection. Limites : observations supposees independantes,
dependance intra-semaine non modelisee, mecanisme conservateur sur la queue.

Le module n'importe que la bibliotheque standard et survival_stats : aucun
acces DB, aucune notion de groupe dans le simulateur.
"""
import hashlib
import re
from statistics import median

from survival_stats import DEFAULT_SEED, LabelLedger, bootstrap_delta_rmst_iid, derive_rng, rmst

DELTAS_PCT = (0, 5, 10, 15, 20, 30)
SCENARIOS = ((60, 102), (80, 136), (100, 170))
N_SIMS = 1000
N_BOOT = 1000
INVARIANT_TOLERANCE = 1e-9   # relative, sur l'egalite RMST Kaplan-Meier = moyenne des temps

_CANONICAL_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

LIMITS = (
    "Observations supposees independantes (tirage i.i.d. dans le reservoir).",
    "Dependance intra-semaine non modelisee ; elle reduirait la puissance reelle.",
    "Mecanisme conservateur sur la queue : seuls les comblements observables avant tau_hist sont acceleres.",
    "tau_hist est une hypothese de conception : le tau prospectif sera calcule sur la population prospective.",
    "Difference avec l'analyse reelle : B = 1000 par simulation (10 000 dans l'analyse reelle) ; "
    "la sensibilite par blocs et le log-rank ne sont pas simules.",
)
POWER_STATEMENT = (
    "La puissance simulee est une propriete conditionnelle du scenario de conception "
    "(reservoir poole historique, acceleration des seuls comblements observables avant tau_hist, "
    "censure administrative a tau_hist, observations independantes, effectifs supposes). Elle n'est "
    "ni une estimation de la puissance reelle de H1, ni une probabilite de detection."
)


class InvariantViolation(Exception):
    """Un invariant obligatoire de D7.2 est viole : la simulation s'arrete."""


# --------------------------------------------------------------------------
# Reservoir (amont : seule etape qui connait T_event ; aucun groupe utilise)
# --------------------------------------------------------------------------

def build_reservoir(population_with_outcomes, tau):
    """Reservoir canonique [(T_event, u, e)] trie par T_event. N'utilise que
    `t_event`, `filled` et `fill_minutes` de chaque observation : le groupe
    n'est ni lu ni conserve."""
    if isinstance(tau, bool) or not isinstance(tau, int) or tau <= 0:
        raise ValueError("tau_hist doit etre un entier de minutes strictement positif.")
    rows = []
    seen = set()
    for o in population_with_outcomes:
        t_event = o["t_event"]
        if not _CANONICAL_TS.match(t_event):
            raise ValueError(f"T_event non canonique : {t_event!r}")
        if t_event in seen:
            raise ValueError(f"T_event duplique dans le reservoir : {t_event}")
        seen.add(t_event)
        filled, fill_minutes = o["filled"], o["fill_minutes"]
        if filled:
            # Les durees de comblement sont des multiples entiers de bougies M15, stockes en flottant
            # (ex. 2070.0) : un flottant ENTIER est accepte et ramene a l'entier ; tout autre est refuse.
            if isinstance(fill_minutes, float) and fill_minutes.is_integer():
                fill_minutes = int(fill_minutes)
            if isinstance(fill_minutes, bool) or not isinstance(fill_minutes, int) or fill_minutes < 0:
                raise ValueError(f"fill_minutes invalide pour {t_event} : {fill_minutes!r}")
        e = 1 if (filled and fill_minutes <= tau) else 0
        u = fill_minutes if e else tau
        rows.append((t_event, u, e))
    rows.sort(key=lambda r: r[0])
    return tuple(rows)


def reservoir_bytes(reservoir):
    """Serialisation canonique : lignes `T_event|u|e`, LF, UTF-8."""
    return "".join(f"{t}|{u}|{e}\n" for t, u, e in reservoir).encode("utf-8")


def reservoir_sha256(reservoir):
    return hashlib.sha256(reservoir_bytes(reservoir)).hexdigest()


def to_pairs(reservoir):
    """Ce que le simulateur recoit : uniquement (u, e)."""
    return tuple((u, e) for _, u, e in reservoir)


# --------------------------------------------------------------------------
# Simulateur : ne connait que des paires (u, e)
# --------------------------------------------------------------------------

def _validate_pairs(pairs, tau):
    if not pairs:
        raise ValueError("Reservoir vide.")
    for item in pairs:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ValueError("Le simulateur n'accepte que des paires (u, e).")
        u, e = item
        if e not in (0, 1) or isinstance(e, bool):
            raise ValueError(f"e doit valoir 0 ou 1 : {e!r}")
        if not (0 <= u <= tau):
            raise ValueError(f"u hors de [0, tau_hist] : {u!r}")
        if e == 0 and u != tau:
            raise ValueError("Toute observation e = 0 doit valoir exactement tau_hist.")


def pooled_summary(pairs, tau):
    """Sorties poolees autorisees : N, part censuree, RMST poole, C."""
    _validate_pairs(pairs, tau)
    n = len(pairs)
    n_censored = sum(1 for _, e in pairs if e == 0)
    return {
        "n": n,
        "n_censored": n_censored,
        "censored_share": n_censored / n,
        "rmst_pooled": sum(u for u, _ in pairs) / n,
        "c_filled_contribution": sum(u for u, e in pairs if e == 1) / n,
    }


def true_effect(pairs, tau, delta_pct):
    """Delta_vrai(delta) = -delta * C, en minutes et en % du RMST poole."""
    s = pooled_summary(pairs, tau)
    delta = delta_pct / 100.0
    minutes = -delta * s["c_filled_contribution"]
    return {"delta_true_minutes": minutes, "delta_true_pct_of_pooled_rmst": 100.0 * minutes / s["rmst_pooled"]}


def data_label(delta_pct, n_range, n_tendance, k):
    return f"D7:data:δ={delta_pct}:n={n_range}/{n_tendance}:sim={k}"


def boot_label(delta_pct, n_range, n_tendance, k):
    return f"D7:boot:δ={delta_pct}:n={n_range}/{n_tendance}:sim={k}"


def all_labels(deltas=DELTAS_PCT, scenarios=SCENARIOS, n_sims=N_SIMS):
    return [
        f(d, nr, nt, k)
        for d in deltas for nr, nt in scenarios for k in range(n_sims) for f in (data_label, boot_label)
    ]


def check_group(times, events, source_events, tau, event_time_cap):
    """Invariants obligatoires (D7.2e) sur un groupe simule."""
    if len(times) != len(events) or len(events) != len(source_events):
        raise InvariantViolation("Longueurs incoherentes.")
    for t, e, e0 in zip(times, events, source_events):
        if bool(e) != bool(e0):
            raise InvariantViolation("L'indicateur d'evenement a ete modifie.")
        if t > tau:
            raise InvariantViolation(f"Temps superieur a tau_hist : {t!r}")
        if not e and t != tau:
            raise InvariantViolation(f"Observation censuree hors de tau_hist exactement : {t!r}")
        if e and not (0 <= t <= event_time_cap):
            raise InvariantViolation(f"Temps d'evenement hors bornes : {t!r}")
    mean = sum(times) / len(times)
    km = rmst(times, events, tau)
    if abs(km - mean) > INVARIANT_TOLERANCE * max(1.0, abs(mean)):
        raise InvariantViolation(f"RMST Kaplan-Meier {km!r} != moyenne des temps {mean!r}.")


def draw_dataset(pairs, n_range, n_tendance, delta_pct, rng, tau):
    """Un jeu simule : n_range indices puis n_tendance indices, tirage
    uniforme avec remise dans le reservoir poole ; transformation du seul
    groupe range. Retourne (times_range, events_range, times_tendance,
    events_tendance)."""
    if n_range < 1 or n_tendance < 1:
        raise ValueError("Effectifs strictement positifs requis.")
    size = len(pairs)
    factor = 1.0 - delta_pct / 100.0
    drawn_range = [pairs[rng.randrange(size)] for _ in range(n_range)]
    drawn_tendance = [pairs[rng.randrange(size)] for _ in range(n_tendance)]
    times_r = [factor * u if e else float(tau) for u, e in drawn_range]
    events_r = [bool(e) for _, e in drawn_range]
    times_t = [float(u) for u, _ in drawn_tendance]
    events_t = [bool(e) for _, e in drawn_tendance]
    check_group(times_r, events_r, [bool(e) for _, e in drawn_range], tau, factor * tau)
    check_group(times_t, events_t, [bool(e) for _, e in drawn_tendance], tau, float(tau))
    return times_r, events_r, times_t, events_t


def simulate_cell(pairs, tau, delta_pct, n_range, n_tendance, n_sims=N_SIMS, n_boot=N_BOOT, master_seed=DEFAULT_SEED):
    """Une cellule de la grille : `n_sims` jeux, chacun avec son flux de
    donnees et son flux de bootstrap (etiquettes uniques). Sorties : voir D7.5."""
    _validate_pairs(pairs, tau)
    ledger = LabelLedger()
    n_excl = n_neg = n_pos = 0
    half_widths, deltas_hat = [], []
    for k in range(n_sims):
        rng = derive_rng(ledger.claim(data_label(delta_pct, n_range, n_tendance, k)), master_seed)
        times_r, _, times_t, _ = draw_dataset(pairs, n_range, n_tendance, delta_pct, rng, tau)
        boot = bootstrap_delta_rmst_iid(
            times_r, times_t, ledger.claim(boot_label(delta_pct, n_range, n_tendance, k)),
            n_boot=n_boot, master_seed=master_seed,
        )
        lo, hi = boot["interval"]
        half_widths.append((hi - lo) / 2)
        deltas_hat.append(sum(times_r) / len(times_r) - sum(times_t) / len(times_t))
        if hi < 0:
            n_excl += 1
            n_neg += 1
        elif lo > 0:
            n_excl += 1
            n_pos += 1
    effect = true_effect(pairs, tau, delta_pct)
    return {
        "delta_pct": delta_pct, "n_range": n_range, "n_tendance": n_tendance,
        "n_sims": n_sims, "n_boot": n_boot,
        "n_excluding_zero": n_excl,
        "rate_excluding_zero": n_excl / n_sims,
        "n_excluding_negative_side": n_neg,
        "n_excluding_positive_side": n_pos,
        # bon signe = cote de Delta_vrai (negatif : range plus rapide) ; sans objet pour delta = 0
        "share_correct_sign_among_exclusions": (n_neg / n_excl) if (delta_pct > 0 and n_excl) else None,
        "median_ci_half_width": median(half_widths),
        "median_delta_hat": median(deltas_hat),
        **effect,
    }


def _cell_task(args):
    pairs, tau, delta_pct, n_range, n_tendance, n_sims, n_boot, master_seed = args
    return simulate_cell(pairs, tau, delta_pct, n_range, n_tendance, n_sims, n_boot, master_seed)


def run_grid(pairs, tau, deltas=DELTAS_PCT, scenarios=SCENARIOS, n_sims=N_SIMS, n_boot=N_BOOT,
             master_seed=DEFAULT_SEED, map_fn=map):
    """Grille complete, cellules dans l'ordre fixe scenario puis delta.
    `map_fn` permet de repartir les cellules sur plusieurs processus sans
    changer le moindre resultat (chaque cellule est deterministe)."""
    tasks = [
        (pairs, tau, d, nr, nt, n_sims, n_boot, master_seed)
        for nr, nt in scenarios for d in deltas
    ]
    return list(map_fn(_cell_task, tasks))
