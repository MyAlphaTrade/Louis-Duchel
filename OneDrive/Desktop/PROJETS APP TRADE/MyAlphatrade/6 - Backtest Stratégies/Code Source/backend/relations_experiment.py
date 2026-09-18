"""Premiere experience relationnelle -- gap de session cash Nasdaq x contexte
RSI/ADX/EMA (M15/H1/H4) x temps de comblement (2026-09-17).

PERIMETRE STRICT, valide par Louis avant implementation (voir
Design_Premiere_Experience_Relations_2026-09-17.html) :
- CETTE experience uniquement -- pas un moteur Relations general.
- Aucune optimisation de seuil, aucun score, aucun signal BUY/SELL, aucun
  ARMING. Les zones RSI/ADX/EMA sont des categories DESCRIPTIVES
  preexistantes (indicators.py), jamais ajustees pour "mieux marcher".
- Reutilise gap_analysis.py et indicators.py tels quels -- ne reimplemente
  rien de ce qui existe deja.

Convention temporelle (Audit_Couche_Relations_2026-09-17.html, section C/F) :
`timestamp` d'une bougie = heure d'OUVERTURE. Une bougie n'est reellement
connue qu'a `timestamp + duree(timeframe)`. Pour un contexte de timeframe
TF a l'instant T : `cutoff = T - duree(TF)`, puis la derniere bougie de TF
dont le timestamp <= cutoff est la derniere bougie CLOTUREE a T -- jamais
une bougie encore en formation.

Discovery / Validation OOS (figee, 2026-09-17) :
Discovery = [2024-01-22, 2025-11-30], OOS = [2025-12-01, 2026-09-16].
Aucune observation ni resultat de l'OOS n'intervient dans la Discovery.

Seuil de lisibilite (fige, 2026-09-17) : n < 30 = echantillon insuffisant,
jamais affiche comme un resultat. S'applique a Discovery et OOS separement
-- jamais de fusion des deux pour depasser artificiellement le seuil.
"""
import bisect
from datetime import datetime, timedelta, timezone
from statistics import mean, median

import gap_analysis
import indicators

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
CONTEXT_TIMEFRAMES = ["M15", "H1", "H4"]

DISCOVERY_START = "2024-01-22T00:00:00Z"
DISCOVERY_END = "2025-11-30T23:59:59Z"
OOS_START = "2025-12-01T00:00:00Z"
# Bornee explicitement a la fin reelle du dataset au moment de la validation
# du protocole (2026-09-17) -- si le dataset s'etend plus tard, ces
# nouvelles donnees ne doivent PAS glisser silencieusement dans l'OOS deja
# valide : elles restent "hors_perimetre" jusqu'a une decision explicite.
OOS_END = "2026-09-16T23:59:59Z"

MIN_SAMPLE_SIZE = 30
GAP_FILL_HORIZON_BARS = 2000  # identique a /research/gap-analysis (main.py)

RSI_PERIOD, ADX_PERIOD, EMA_PERIOD = 14, 14, 21


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _shift_iso(ts, minutes):
    """`ts` (canonique, deja UTC) decale de `minutes` (peut etre negatif),
    reconverti en la meme representation canonique pour rester comparable
    par bissection sur chaines."""
    dt = _parse(ts) - timedelta(minutes=minutes)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_last_closed_bar(sorted_ts, bars_by_ts, t_event, timeframe):
    """Derniere bougie de `timeframe` reellement CLOTUREE a `t_event` --
    jamais une bougie encore en formation. Fonction pure. Retourne None si
    aucune bougie ne precede (debut d'historique) -- jamais approxime."""
    cutoff = _shift_iso(t_event, TIMEFRAME_MINUTES[timeframe])
    idx = bisect.bisect_right(sorted_ts, cutoff) - 1
    if idx < 0:
        return None
    return bars_by_ts[sorted_ts[idx]]


def _rsi_zone(value):
    if value is None:
        return "indisponible"
    return "survente" if value <= 30 else ("surachat" if value >= 70 else "neutre")


def _adx_zone(value):
    if value is None:
        return "indisponible"
    return "range" if value <= 20 else ("tendance" if value >= 25 else "intermediaire")


def _ema_zone(close_price, ema_value):
    if ema_value is None or close_price is None:
        return "indisponible"
    return "au-dessus" if close_price > ema_value else "en-dessous"


class _TimeframeIndicators:
    """Precalcule RSI/ADX/EMA une seule fois pour tout un (symbole,
    timeframe), indexes par timestamp -- evite de tout recalculer par
    evenement."""

    def __init__(self, bars):
        self.bars_by_ts = {b["timestamp"]: b for b in bars}
        self.sorted_ts = [b["timestamp"] for b in bars]
        self.rsi_by_ts = {p["timestamp"]: p["value"] for p in indicators.compute_rsi(bars, RSI_PERIOD)}
        self.adx_by_ts = {p["timestamp"]: p["value"] for p in indicators.compute_adx(bars, ADX_PERIOD)}
        self.ema_by_ts = {p["timestamp"]: p["value"] for p in indicators.compute_ema(bars, EMA_PERIOD)}

    def context_at(self, t_event, timeframe):
        """Retourne {rsi, adx, ema, ema_zone, close, bar_timestamp} pour la
        derniere bougie CLOTUREE a `t_event`, ou tout None si aucune
        bougie ne precede."""
        bar = find_last_closed_bar(self.sorted_ts, self.bars_by_ts, t_event, timeframe)
        if bar is None:
            return {"bar_timestamp": None, "rsi": None, "adx": None, "ema": None, "close": None}
        ts = bar["timestamp"]
        ema_val = self.ema_by_ts.get(ts)
        return {
            "bar_timestamp": ts,
            "rsi": self.rsi_by_ts.get(ts),
            "adx": self.adx_by_ts.get(ts),
            "ema": ema_val,
            "close": bar["close"],
        }


def build_observations(m15_bars, h1_bars, h4_bars, symbol="US Tech 100", horizon_bars=GAP_FILL_HORIZON_BARS):
    """Construit une OBSERVATION par gap de session cash : EVENT (gap) +
    CONTEXT (RSI/ADX/EMA sur M15/H1/H4, causal) + OUTCOME (temps de
    comblement, avec distinction censure horizon/fin de dataset). Fonction
    pure, aucun acces DB ici -- l'appelant charge les bougies."""
    ctx_by_tf = {
        "M15": _TimeframeIndicators(m15_bars),
        "H1": _TimeframeIndicators(h1_bars),
        "H4": _TimeframeIndicators(h4_bars),
    }
    m15_sorted_ts = ctx_by_tf["M15"].sorted_ts

    gaps = gap_analysis.compute_cash_session_gaps(symbol, m15_bars)
    observations = []
    for gap in gaps:
        t_event = gap["timestamp"]

        context = {tf: ctx_by_tf[tf].context_at(t_event, tf) for tf in CONTEXT_TIMEFRAMES}

        idx = bisect.bisect_left(m15_sorted_ts, t_event)
        remaining = len(m15_bars) - idx
        window = m15_bars[idx:idx + horizon_bars]
        outcome = gap_analysis.find_fill_time(gap, window, horizon_bars=horizon_bars)
        censor_reason = None
        if not outcome["filled"]:
            censor_reason = "dataset_end" if remaining < horizon_bars else "horizon_exhausted"

        if DISCOVERY_START <= t_event <= DISCOVERY_END:
            split = "discovery"
        elif OOS_START <= t_event <= OOS_END:
            split = "oos"
        else:
            split = "hors_perimetre"

        observations.append({
            "t_event": t_event,
            "direction": gap["direction"],
            "split": split,
            "context": {
                tf: {
                    "rsi_zone": _rsi_zone(context[tf]["rsi"]),
                    "adx_zone": _adx_zone(context[tf]["adx"]),
                    "ema_zone": _ema_zone(context[tf]["close"], context[tf]["ema"]),
                }
                for tf in CONTEXT_TIMEFRAMES
            },
            "filled": outcome["filled"],
            "fill_minutes": outcome["fill_minutes"],
            "censor_reason": censor_reason,
        })
    return observations


def _stats_for(subset, exclude_dataset_end=True):
    """Statistiques descriptives -- jamais de "meilleur" designe. Exclut
    par defaut les observations tronquees par la fin du dataset (ni
    comblees, ni un vrai negatif -- inconnu)."""
    usable = [o for o in subset if not (exclude_dataset_end and o["censor_reason"] == "dataset_end")]
    n = len(usable)
    n_excluded = len(subset) - n
    if n < MIN_SAMPLE_SIZE:
        return {"n": n, "n_excluded_dataset_end": n_excluded, "insufficient": True}

    filled = [o for o in usable if o["filled"]]
    fill_times = [o["fill_minutes"] for o in filled]
    return {
        "n": n,
        "n_excluded_dataset_end": n_excluded,
        "insufficient": False,
        "filled_pct": round(len(filled) / n * 100, 1),
        "fill_minutes_median": round(median(fill_times), 1) if fill_times else None,
        "fill_minutes_mean": round(mean(fill_times), 1) if fill_times else None,
        "fill_minutes_min": round(min(fill_times), 1) if fill_times else None,
        "fill_minutes_max": round(max(fill_times), 1) if fill_times else None,
        "pct_never_filled_horizon_exhausted": round(
            sum(1 for o in usable if o["censor_reason"] == "horizon_exhausted") / n * 100, 1
        ),
    }


# Perimetre pre-declare -- 24 comparaisons + 1 combinaison illustrative,
# jamais elargi apres inspection des resultats (voir section H du design).
def declared_comparisons(observations_by_split):
    """Retourne, pour chaque split (discovery/oos), les 24+1 comparaisons
    pre-declarees : population A (tous les gaps) vs chaque sous-groupe B."""
    results = {}
    for split, obs in observations_by_split.items():
        population_a = _stats_for(obs)
        comparisons = {"A_population_totale": population_a}

        for tf in CONTEXT_TIMEFRAMES:
            for zone in ("survente", "neutre", "surachat"):
                subset = [o for o in obs if o["context"][tf]["rsi_zone"] == zone]
                comparisons[f"RSI_{tf}_{zone}"] = _stats_for(subset)
            for zone in ("range", "intermediaire", "tendance"):
                subset = [o for o in obs if o["context"][tf]["adx_zone"] == zone]
                comparisons[f"ADX_{tf}_{zone}"] = _stats_for(subset)
            for zone in ("au-dessus", "en-dessous"):
                subset = [o for o in obs if o["context"][tf]["ema_zone"] == zone]
                comparisons[f"EMA_{tf}_{zone}"] = _stats_for(subset)

        # Groupe E -- une seule combinaison illustrative, pas une recherche exhaustive.
        illustrative = [
            o for o in obs
            if o["context"]["H1"]["adx_zone"] == "range" and o["context"]["M15"]["rsi_zone"] == "neutre"
        ]
        comparisons["E_illustratif_ADX_H1_range_ET_RSI_M15_neutre"] = _stats_for(illustrative)

        results[split] = comparisons
    return results
