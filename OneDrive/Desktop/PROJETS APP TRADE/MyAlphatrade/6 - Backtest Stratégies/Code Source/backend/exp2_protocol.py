"""Protocole de l'experience 2 -- ADX(M15) x temps de comblement des gaps de
session cash Nasdaq (D1/D2/D3 verrouilles, 2026-09-19/20).

Ce module code UNIQUEMENT ce qui est verrouille :
- eligibilite et maturite (horizon complet observe), horizon reel, tau (D1) ;
- compteur AVEUGLE des effectifs eligibles et regle de declenchement (D3) ;
- liste canonique des observations eligibles et son SHA-256 (D3) ;
- registre de declenchement (D3, contenu ; creation du DatasetVersion, commit
  et push restent des actions explicites, jamais executees ici) ;
- analyse principale one-shot (D1/D2), sur une liste d'observations fournie.

Hors perimetre (non verrouille) : analyse de stabilite (D4), estimation de
puissance (D7). Ne modifie aucune donnee ; n'importe pas main.py.

Regles verrouillees rappelees ici :
- tau = plus petit horizon reel parmi les observations eligibles des SEULS
  groupes range et tendance ; le groupe "intermediaire" n'y entre jamais
  (regle D2/tau, verrouillee 2026-09-21 ; tau_hist = 42 765 min).
- horizon reel = duree entre T_event et l'horodatage de la derniere bougie
  de sa fenetre de 2000 bougies M15 (verrouille, D1).
- Etiquettes des flux bootstrap de l'analyse principale : `H1:iid` et
  `H1:blocs` (D2-flux).
"""
import bisect
import re
from datetime import datetime

import gap_analysis
from data_integrity import sha256_lf_normalized, verify_reference
from relations_experiment import _TimeframeIndicators, _adx_zone
from survival_stats import (
    DEFAULT_N_BOOT, DEFAULT_SEED, READING_CLAUSE, bootstrap_delta_rmst_blocks,
    bootstrap_delta_rmst_iid, describe_group, h1_verdict, logrank_test,
)

SYMBOL = "US Tech 100"
PROSPECTIVE_START = "2026-09-17T00:00:00Z"
HORIZON_BARS = 2000
TRIGGER_MIN_PER_GROUP = 60
TEST_GROUPS = ("range", "tendance")
LABEL_H1_IID = "H1:iid"
LABEL_H1_BLOCKS = "H1:blocs"
_CANONICAL_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _minutes_between(ts_a, ts_b):
    seconds = (_parse(ts_b) - _parse(ts_a)).total_seconds()
    if seconds % 60:
        raise ValueError(f"Ecart non entier en minutes entre {ts_a} et {ts_b}.")
    return int(seconds // 60)


def list_observations(m15_bars, symbol=SYMBOL, horizon_bars=HORIZON_BARS):
    """Evenements (gaps de session cash), zone ADX(M15) au dernier instant
    causalement disponible, maturite et horizon reel. N'utilise QUE les
    bougies : aucune issue (comblement) n'est calculee ni lue ici."""
    ind = _TimeframeIndicators(m15_bars)
    ts = ind.sorted_ts
    observations = []
    for gap in gap_analysis.compute_cash_session_gaps(symbol, m15_bars):
        t_event = gap["timestamp"]
        zone = _adx_zone(ind.context_at(t_event, "M15")["adx"])
        idx = bisect.bisect_left(ts, t_event)
        mature = idx + horizon_bars <= len(ts)
        observations.append({
            "t_event": t_event,
            "zone": zone,
            "mature": mature,
            "horizon_min": _minutes_between(ts[idx], ts[idx + horizon_bars - 1]) if mature else None,
            "_gap": gap,
        })
    return observations


def select_eligible(observations, prospective_only=True, prospective_start=PROSPECTIVE_START):
    """Eligible = horizon complet observe, contexte disponible, groupe range
    ou tendance (et, en mode prospectif, T_event >= debut prospectif)."""
    return [
        o for o in observations
        if o["mature"] and o["zone"] in TEST_GROUPS
        and (not prospective_only or o["t_event"] >= prospective_start)
    ]


def trigger_condition(n_range, n_tendance, minimum=TRIGGER_MIN_PER_GROUP):
    """D3 : les DEUX groupes comptent chacun au moins `minimum` observations
    eligibles (>= : 60 atteint suffit)."""
    return n_range >= minimum and n_tendance >= minimum


def blind_counts(m15_bars, prospective_start=PROSPECTIVE_START, horizon_bars=HORIZON_BARS,
                 minimum=TRIGGER_MIN_PER_GROUP, symbol=SYMBOL):
    """COMPTEUR AVEUGLE (D3) : uniquement des effectifs. Ne calcule ni
    n'expose aucun temps de comblement, aucun comble/non comble."""
    prospective = [o for o in list_observations(m15_bars, symbol, horizon_bars) if o["t_event"] >= prospective_start]
    n = {g: sum(1 for o in prospective if o["mature"] and o["zone"] == g) for g in TEST_GROUPS}
    return {
        "prospective_start": prospective_start,
        "eligible_range": n["range"],
        "eligible_tendance": n["tendance"],
        "intermediaire_mature": sum(1 for o in prospective if o["mature"] and o["zone"] == "intermediaire"),
        "context_unavailable": sum(1 for o in prospective if o["zone"] == "indisponible"),
        "not_mature": sum(1 for o in prospective if not o["mature"]),
        "minimum_per_group": minimum,
        "trigger_reached": trigger_condition(n["range"], n["tendance"], minimum),
        "last_bar": m15_bars[-1]["timestamp"] if m15_bars else None,
    }


def compute_tau(eligible):
    """tau = plus petit horizon reel (minutes) parmi les observations
    eligibles, calcule a partir des bougies uniquement (D1). Regle
    verrouillee : seules les observations des groupes range et tendance y
    entrent ; une observation d'un autre groupe (intermediaire, contexte
    indisponible) ou sans horizon complet est REFUSEE, jamais ignoree."""
    if not eligible:
        raise ValueError("Aucune observation eligible : tau non defini.")
    for o in eligible:
        if o["zone"] not in TEST_GROUPS:
            raise ValueError(f"tau : groupe non admis {o['zone']!r} (seuls range et tendance).")
        if isinstance(o["horizon_min"], bool) or not isinstance(o["horizon_min"], int):
            raise ValueError("tau : horizon reel entier obligatoire (observation mature).")
    return min(o["horizon_min"] for o in eligible)


def serialize_eligible(eligible) -> bytes:
    """Serialisation canonique (D3) : lignes `T_event|groupe|horizon_min`
    triees par T_event ; UTF-8 ; T_event en UTC normalise ; horizon_min
    entier ; separateur de ligne LF ; aucun champ facultatif."""
    lines = []
    for o in sorted(eligible, key=lambda x: x["t_event"]):
        if not _CANONICAL_TS.match(o["t_event"]):
            raise ValueError(f"T_event non canonique : {o['t_event']!r}")
        if o["zone"] not in TEST_GROUPS:
            raise ValueError(f"Groupe non eligible dans la liste : {o['zone']!r}")
        h = o["horizon_min"]
        if isinstance(h, bool) or not isinstance(h, int):
            raise ValueError(f"horizon_min doit etre un entier : {h!r}")
        lines.append(f"{o['t_event']}|{o['zone']}|{h}\n")
    return "".join(lines).encode("utf-8")


def eligible_list_sha256(eligible) -> str:
    return sha256_lf_normalized(serialize_eligible(eligible))


def attest_reference_state(m15_bars, prospective_start=PROSPECTIVE_START):
    """Attestation (D6, formulation corrigee le 2026-09-21). Distingue
    explicitement :
    - la derniere bougie de REFERENCE cloturee (`REFERENCE_LAST_BAR`) et
      l'empreinte de la serie jusqu'a elle (`reference`) ;
    - les bougies POSTERIEURES a la reference (`later_bars`), listees une a
      une sans interpretation -- par exemple la bougie de 00:45 du 16/09,
      stockee partielle a 00:47:17 : elle EXISTE dans la base, est hors
      reference et hors toute serie d'analyse, et sera ecrasee par le
      premier import (collision attendue, D5). Chacune est marquee
      prospective (T >= debut prospectif) ou anterieure a ce debut ;
    - la serie effectivement UTILISEE par les analyses historiques
      (D4/D7) : les bougies <= reference uniquement (`series_used`).
    Aucune affirmation « aucune bougie posterieure n'existe » n'est faite :
    seul l'inventaire l'est."""
    ref = verify_reference(m15_bars)
    last = ref["expected_last_bar"]
    later = [b["timestamp"] for b in m15_bars if b["timestamp"] > last]
    return {
        "reference": ref,
        "last_closed_reference_bar": last,
        "series_used": {"up_to": last, "n": ref["n"], "sha256": ref["sha256"]},
        "later_bars": [{"timestamp": t, "prospective": t >= prospective_start} for t in later],
        "n_later_bars": len(later),
        "n_prospective_bars": sum(1 for t in later if t >= prospective_start),
        "prospective_start": prospective_start,
    }


def attach_outcomes(eligible, m15_bars, horizon_bars=HORIZON_BARS):
    """Calcule le comblement des observations eligibles. A n'appeler qu'une
    fois le declenchement atteint et le registre commite (D3)."""
    ts = [b["timestamp"] for b in m15_bars]
    out = []
    for o in eligible:
        idx = bisect.bisect_left(ts, o["t_event"])
        fill = gap_analysis.find_fill_time(o["_gap"], m15_bars[idx:idx + horizon_bars], horizon_bars=horizon_bars)
        out.append({**o, "filled": fill["filled"], "fill_minutes": fill["fill_minutes"]})
    return out


def _time_and_event(o, tau):
    """Une observation comblee a t <= tau est un evenement a t ; sinon
    (jamais comblee, ou comblee apres tau) elle est censuree a tau."""
    if o["filled"] and o["fill_minutes"] <= tau:
        return float(o["fill_minutes"]), True
    return float(tau), False


def run_primary_analysis(observations_with_outcomes, tau, n_boot=DEFAULT_N_BOOT, master_seed=DEFAULT_SEED):
    """Analyse principale (D1/D2). Entree : observations eligibles avec
    `zone`, `t_event`, `filled`, `fill_minutes`. Sortie : tout ce qui est
    pre-enregistre, le verdict ne dependant QUE du critere principal."""
    groups = {g: [o for o in observations_with_outcomes if o["zone"] == g] for g in TEST_GROUPS}
    for g, obs in groups.items():
        if not obs:
            raise ValueError(f"Groupe vide : {g}")
    te = {g: [_time_and_event(o, tau) for o in obs] for g, obs in groups.items()}
    times = {g: [t for t, _ in te[g]] for g in TEST_GROUPS}
    events = {g: [e for _, e in te[g]] for g in TEST_GROUPS}

    desc = {g: describe_group(times[g], events[g], tau) for g in TEST_GROUPS}
    delta = desc["range"]["rmst"] - desc["tendance"]["rmst"]

    primary = bootstrap_delta_rmst_iid(times["range"], times["tendance"], LABEL_H1_IID, n_boot=n_boot, master_seed=master_seed)

    blocks = {}
    for g, tag in (("range", "a"), ("tendance", "b")):
        for o, (t, _) in zip(groups[g], te[g]):
            iso = _parse(o["t_event"]).isocalendar()
            blocks.setdefault((iso[0], iso[1]), []).append((tag, t))
    block = bootstrap_delta_rmst_blocks(blocks, LABEL_H1_BLOCKS, n_boot=n_boot, master_seed=master_seed)

    return {
        "tau_minutes": tau,
        "bootstrap_streams": {"primary": primary["label"], "blocks": block["label"]},
        "delta_rmst_range_minus_tendance": delta,
        "primary_ci_95": primary["interval"],
        "verdict": h1_verdict(primary["interval"], block["interval"]),
        "sensitivity_block_bootstrap": block,
        "sensitivity_logrank": logrank_test(times["range"], events["range"], times["tendance"], events["tendance"]),
        "descriptive": {
            g: {
                **desc[g],
                "n_filled_after_tau": sum(1 for o in groups[g] if o["filled"] and o["fill_minutes"] > tau),
                "n_never_filled_in_horizon": sum(1 for o in groups[g] if not o["filled"]),
            }
            for g in TEST_GROUPS
        },
        "delta_decomposition": {
            "not_filled_at_tau": desc["range"]["contribution_not_filled"] - desc["tendance"]["contribution_not_filled"],
            "filled_before_tau": desc["range"]["contribution_filled"] - desc["tendance"]["contribution_filled"],
        },
        "reading_clause": READING_CLAUSE,
    }


def build_trigger_record(*, import_datetime_utc, data_state_last_bar, series_n, series_sha256,
                         counts, tau, eligible_sha256, code_commit, journal_sha256,
                         reference_check, seed=DEFAULT_SEED, n_boot=DEFAULT_N_BOOT):
    """Contenu du registre de declenchement (D3), texte LF, champs dans un
    ordre fixe. A commiter AVANT tout calcul d'issue. La creation du
    DatasetVersion (frozen=true), le commit et le push sont des actions
    separees, avec accord explicite : rien n'est ecrit ici."""
    ref = reference_check
    fields = [
        ("registre", "declenchement experience 2 ADX(M15)"),
        ("import_datetime_utc", import_datetime_utc),
        ("data_state_last_bar", data_state_last_bar),
        ("series_m15_n", series_n),
        ("series_m15_sha256", series_sha256),
        ("reference_ok", str(ref["ok"]).lower()),
        ("reference_n", ref["n"]),
        ("reference_last_bar", ref["last_bar"]),
        ("reference_sha256", ref["sha256"]),
        ("eligible_range", counts["eligible_range"]),
        ("eligible_tendance", counts["eligible_tendance"]),
        ("prospective_start", counts["prospective_start"]),
        ("tau_minutes", tau),
        ("eligible_list_sha256", eligible_sha256),
        ("import_journal_sha256", journal_sha256),
        ("code_commit", code_commit),
        ("bootstrap_seed", seed),
        ("bootstrap_n", n_boot),
    ]
    return "".join(f"{k}: {v}\n" for k, v in fields)
