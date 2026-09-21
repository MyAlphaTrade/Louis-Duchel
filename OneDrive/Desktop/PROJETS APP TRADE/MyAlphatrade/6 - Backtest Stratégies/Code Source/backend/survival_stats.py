"""Statistiques de survie -- experience 2 (D1/D2 verrouilles, 2026-09-19/20).

Implementation du protocole verrouille par Louis (voir
Preregistration_Experience2_ADX_M15 et la conversation de verrouillage) :

D1  Temps de comblement = duree jusqu'a l'evenement "comble". Un temps commun
    tau plafonne l'analyse : une observation non comblee a tau (jamais
    comblee, ou comblee apres tau) est CENSUREE a tau -- aucune duree
    infinie n'est imputee. Critere principal : difference de RMST a tau,
    Delta = RMST_range(tau) - RMST_tendance(tau), avec
    RMST_g(tau) = integrale de 0 a tau de S_g(t) dt (S_g = courbe de survie
    "non comble a t" de Kaplan-Meier). Sensibilite : log-rank bilateral,
    alpha = 0,05.
D2  IC principal : bootstrap percentile bilateral a 95 %, 10 000
    rerechantillonnages avec remise, stratifie par groupe (tailles observees
    conservees), graine maitre 20260918, tau fixe (jamais recalcule par
    rerechantillon). Sensibilite sans poids de decision : bootstrap par
    blocs de semaines ISO.
D2-flux (amendement verrouille, 2026-09-21) : chaque analyse bootstrap recoit
    un flux pseudo-aleatoire deterministe DISTINCT, derive de la graine
    maitre et d'une etiquette explicite (`H1:iid`, `H1:blocs`,
    `D4:2024-S2`, `D7:...`). Une etiquette n'est jamais reutilisee ; aucun
    flux n'est partage entre deux analyses.
D2-percentiles (amendement verrouille, 2026-09-21) : sur les repliques
    triees par ordre croissant (indices a partir de 0), les bornes sont aux
    indices floor(25*(B-1)/1000) et floor(975*(B-1)/1000), sans
    interpolation ; B = nombre de repliques VALIDES (10 000 -> 249 et 9749 ;
    1 000 -> 24 et 974).

Note de verification (D2) : toutes les observations eligibles ont un horizon
reel >= tau, donc AUCUNE censure n'existe avant tau. L'integrale est alors
exactement egale a la moyenne des min(T_i, tau). Le bootstrap utilise cette
identite pour la vitesse ; les tests verifient l'egalite avec le calcul
Kaplan-Meier.

Libelle du verdict (amendement verrouille, 2026-09-21) : un IC principal qui
contient 0 est "non concluante", jamais "non soutenue" -- ce n'est pas la
preuve d'une absence d'effet.

Module pur : aucun acces DB, aucune donnee.
"""
import hashlib
import math
import random
from statistics import median

DEFAULT_SEED = 20260918
DEFAULT_N_BOOT = 10000

READING_CLAUSE = (
    "Le critere RMST repond uniquement a la question : le temps moyen "
    "plafonne a tau differe-t-il entre les deux contextes ? Il ne permet "
    "pas, a lui seul, d'attribuer cette difference a la vitesse typique ou "
    "a la traine."
)


def derive_rng(label, master_seed=DEFAULT_SEED):
    """D2-flux : flux pseudo-aleatoire deterministe derive de la graine maitre
    et d'une etiquette explicite. Graine du generateur = SHA-256 de
    "{graine_maitre}|{etiquette}" (UTF-8), lu comme entier big-endian ; ne
    depend donc pas du traitement interne des graines textuelles de Python."""
    if not isinstance(label, str) or not label:
        raise ValueError("Etiquette de flux obligatoire (chaine non vide).")
    digest = hashlib.sha256(f"{master_seed}|{label}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest, "big"))


class LabelLedger:
    """Garantit qu'aucune etiquette de flux n'est reutilisee au sein d'un
    meme run (D2-flux : jamais de flux partage entre analyses)."""

    def __init__(self):
        self._used = set()

    def claim(self, label):
        if label in self._used:
            raise ValueError(f"Etiquette de flux deja utilisee : {label!r}.")
        self._used.add(label)
        return label


def censor_at_tau(times, events, tau):
    """Toute observation dont le temps depasse tau est censuree a tau."""
    out_t, out_e = [], []
    for t, e in zip(times, events):
        if t > tau:
            out_t.append(tau)
            out_e.append(False)
        else:
            out_t.append(t)
            out_e.append(bool(e))
    return out_t, out_e


def km_curve(times, events):
    """Kaplan-Meier. Retourne [(t, S(t))] : (0, 1) puis un point par temps
    d'evenement distinct (fonction en escalier continue a droite). Les
    censures a un temps t restent a risque a t (convention standard)."""
    data = sorted(zip(times, events))
    at_risk = len(data)
    surv = 1.0
    curve = [(0.0, 1.0)]
    i = 0
    while i < len(data):
        t = data[i][0]
        deaths = censored = 0
        j = i
        while j < len(data) and data[j][0] == t:
            if data[j][1]:
                deaths += 1
            else:
                censored += 1
            j += 1
        if deaths:
            surv *= 1 - deaths / at_risk
            curve.append((t, surv))
        at_risk -= deaths + censored
        i = j
    return curve


def rmst_from_curve(curve, tau):
    """Integrale de 0 a tau de la courbe en escalier."""
    area = 0.0
    prev_t, prev_s = 0.0, 1.0
    for t, s in curve[1:]:
        if t >= tau:
            break
        area += prev_s * (t - prev_t)
        prev_t, prev_s = t, s
    return area + prev_s * (tau - prev_t)


def rmst(times, events, tau):
    t, e = censor_at_tau(times, events, tau)
    return rmst_from_curve(km_curve(t, e), tau)


def km_median(curve):
    """Premier temps ou S(t) <= 0,5 ; None si la courbe n'y descend pas
    (mediane non estimable)."""
    for t, s in curve[1:]:
        if s <= 0.5:
            return t
    return None


def logrank_test(times_a, events_a, times_b, events_b):
    """Log-rank bilateral, 2 groupes, gestion standard des ex aequo
    (variance hypergeometrique). p-valeur du chi2 a 1 ddl :
    erfc(sqrt(chi2 / 2))."""
    all_times = sorted({t for t, e in zip(times_a, events_a) if e} | {t for t, e in zip(times_b, events_b) if e})
    observed_a = expected_a = variance = 0.0
    for t in all_times:
        n_a = sum(1 for x in times_a if x >= t)
        n_b = sum(1 for x in times_b if x >= t)
        d_a = sum(1 for x, e in zip(times_a, events_a) if e and x == t)
        d_b = sum(1 for x, e in zip(times_b, events_b) if e and x == t)
        n, d = n_a + n_b, d_a + d_b
        observed_a += d_a
        expected_a += d * n_a / n
        if n > 1:
            variance += n_a * n_b * d * (n - d) / (n * n * (n - 1))
    if variance <= 0:
        return {"chi2": None, "p_value": None, "significant_at_0_05": None, "estimable": False}
    chi2 = (observed_a - expected_a) ** 2 / variance
    p = math.erfc(math.sqrt(chi2 / 2))
    return {
        "chi2": chi2, "p_value": p, "significant_at_0_05": p < 0.05, "estimable": True,
        "observed_a": observed_a, "expected_a": expected_a, "variance": variance,
    }


def percentile_indices(b):
    """D2-percentiles : indices (a partir de 0) des bornes 2,5 % et 97,5 %
    pour `b` repliques valides, en arithmetique ENTIERE, sans interpolation."""
    if b < 1:
        raise ValueError("Aucune replique : intervalle percentile indefini.")
    return 25 * (b - 1) // 1000, 975 * (b - 1) // 1000


def percentile_interval(values):
    a = sorted(values)
    lo, hi = percentile_indices(len(a))
    return a[lo], a[hi]


def bootstrap_delta_rmst_iid(capped_a, capped_b, label, n_boot=DEFAULT_N_BOOT, master_seed=DEFAULT_SEED):
    """IC principal (D2). `capped_*` = min(T_i, tau) par observation ; le
    groupe a est "range", b "tendance". Stratifie : les tailles des deux
    groupes sont conservees a chaque replique. `label` : etiquette du flux
    (D2-flux), obligatoire -- jamais de flux par defaut partage."""
    rng = derive_rng(label, master_seed)
    randrange = rng.randrange
    na, nb = len(capped_a), len(capped_b)
    if na == 0 or nb == 0:
        raise ValueError("Bootstrap impossible : un groupe est vide.")
    reps = []
    for _ in range(n_boot):
        mean_a = sum(capped_a[randrange(na)] for _ in range(na)) / na
        mean_b = sum(capped_b[randrange(nb)] for _ in range(nb)) / nb
        reps.append(mean_a - mean_b)
    return {"interval": percentile_interval(reps), "n_boot": n_boot, "master_seed": master_seed, "label": label}


def bootstrap_delta_rmst_blocks(blocks, label, n_boot=DEFAULT_N_BOOT, master_seed=DEFAULT_SEED):
    """Sensibilite (D2) : semaines rerechantillonnees avec remise. `blocks` :
    {cle_de_bloc: [("a"|"b", temps_plafonne), ...]}. Les repliques ou un
    groupe est vide sont ecartees ET comptees."""
    keys = sorted(blocks)
    nk = len(keys)
    if nk == 0:
        raise ValueError("Bootstrap par blocs impossible : aucun bloc.")
    rng = derive_rng(label, master_seed)
    randrange = rng.randrange
    reps, discarded = [], 0
    for _ in range(n_boot):
        sum_a = n_a = sum_b = n_b = 0
        for _k in range(nk):
            for group, t in blocks[keys[randrange(nk)]]:
                if group == "a":
                    sum_a += t
                    n_a += 1
                else:
                    sum_b += t
                    n_b += 1
        if n_a == 0 or n_b == 0:
            discarded += 1
            continue
        reps.append(sum_a / n_a - sum_b / n_b)
    return {
        "interval": percentile_interval(reps) if reps else None,
        "n_valid": len(reps), "n_discarded": discarded, "n_blocks": nk, "n_boot": n_boot,
        "master_seed": master_seed, "label": label,
    }


def excludes_zero(interval):
    return interval[0] > 0 or interval[1] < 0


def h1_verdict(primary_interval, block_interval=None):
    """H1 est "soutenue" si l'IC principal exclut 0 (D1) ; sinon "non
    concluante" (amendement verrouille : un IC contenant 0 n'est pas la
    preuve d'une absence d'effet). Si l'IC par blocs inclut 0 alors que le
    principal l'exclut : libelle descriptif de D2, le verdict de H1 restant
    celui du critere principal."""
    supported = excludes_zero(primary_interval)
    note = None
    if supported and block_interval is not None and not excludes_zero(block_interval):
        note = "soutenu, non robuste a la dependance intra-semaine"
    return {"h1_supported": supported, "label": "soutenue" if supported else "non concluante", "sensitivity_note": note}


def describe_group(times, events, tau):
    """Descriptifs sans poids de decision (D1) : RMST, taux de comblement a
    tau, mediane des combles, mediane Kaplan-Meier si estimable, et
    decomposition du RMST entre la part des non-combles a tau et celle des
    combles avant tau (les deux parts somment au RMST)."""
    t, e = censor_at_tau(times, events, tau)
    n = len(t)
    if n == 0:
        raise ValueError("Groupe vide.")
    curve = km_curve(t, e)
    filled_times = [ti for ti, ei in zip(t, e) if ei]
    return {
        "n": n,
        "n_filled_by_tau": len(filled_times),
        "n_not_filled_at_tau": n - len(filled_times),
        "rmst": rmst_from_curve(curve, tau),
        "fill_rate_at_tau": len(filled_times) / n,
        "median_of_filled": median(filled_times) if filled_times else None,
        "km_median": km_median(curve),
        "contribution_filled": sum(filled_times) / n,
        "contribution_not_filled": (n - len(filled_times)) / n * tau,
        "survival_curve": curve,
    }
