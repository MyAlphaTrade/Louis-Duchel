"""Indicateurs de marche -- Research Lab (2026-09-16/17).

Louis (16/09/2026) : avant tout critere d'ARMING, enrichir la capacite
D'OBSERVATION du Research Lab -- RSI, ADX, EMA traites comme des
INDICATEURS DE MARCHE (statistiques descriptives sur des donnees reelles),
PAS comme des regles BUY/SELL, PAS comme un score de confiance. Rien ici ne
produit de signal ni de decision -- seulement des observations mesurees.

Conventions de calcul (deliberement le standard le plus repandu -- "RSI(14)"
Wilder, "ADX(14)" Wilder, EMA classique -- documente explicitement plutot
que suppose) :

RSI -- Wilder (1978), periode par defaut 14. Moyenne des gains/pertes
lissee par la methode de Wilder (pas une simple moyenne mobile) :
premiere moyenne = moyenne arithmetique des `period` premieres variations,
puis moyenne[i] = (moyenne[i-1] * (period-1) + valeur[i]) / period.
Necessite au moins `period + 1` cloture pour produire une seule valeur.
Convention explicite si perte moyenne nulle : RSI = 100 (jamais de division
par zero silencieuse) ; si gain ET perte moyens nuls (aucun mouvement) :
RSI = 50.

ADX -- Wilder (1978), periode par defaut 14. +DM/-DM/TR lisses par la meme
methode de Wilder (somme glissante lissee), DX = 100 * |+DI - -DI| / (+DI +
-DI) (DX = 0 par convention si +DI + -DI = 0, jamais de division par
zero), ADX = moyenne de Wilder des DX. Necessite au moins `2*period + 1`
bougies pour produire une seule valeur ADX (period pour lisser +DM/-DM/TR,
period supplementaires pour la premiere moyenne de DX).

EMA -- moyenne mobile exponentielle classique, multiplicateur
2/(period+1), amorcee par la moyenne arithmetique simple des `period`
premieres clotures (convention standard, jamais une valeur inventee).
Necessite au moins `period` clotures.

Toute serie avec moins de bougies que le minimum requis retourne une liste
vide et le champ `insufficient_data: true` dans les statistiques associees
-- jamais une valeur approximee ou extrapolee.
"""
from statistics import mean, median


def _closes(bars):
    return [b["close"] for b in bars]


# ── RSI (Wilder) ─────────────────────────────────────────────────────────

def compute_rsi(bars: list, period: int = 14) -> list:
    """Fonction pure. `bars` : liste de dicts {timestamp, close, ...} triee
    chronologiquement. Retourne une liste de {timestamp, value} -- une valeur
    de moins que le nombre de bougies utilisees pour la lisser (la toute
    premiere bougie n'a pas de variation precedente)."""
    closes = _closes(bars)
    if len(closes) < period + 1:
        return []

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]

    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])
    out = []

    def _rsi_from_averages(ag, al):
        if ag == 0 and al == 0:
            return 50.0
        if al == 0:
            return 100.0
        rs = ag / al
        return 100 - 100 / (1 + rs)

    out.append({"timestamp": bars[period]["timestamp"], "value": round(_rsi_from_averages(avg_gain, avg_loss), 4)})

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append({"timestamp": bars[i + 1]["timestamp"], "value": round(_rsi_from_averages(avg_gain, avg_loss), 4)})

    return out


def summarize_rsi(rsi_series: list, overbought: float = 70, oversold: float = 30) -> dict:
    """Statistiques DESCRIPTIVES uniquement -- 70/30 sont les seuils
    conventionnels utilises pour NOMMER les zones de surachat/survente d'un
    RSI (terminologie universelle de l'indicateur lui-meme), jamais une
    regle de declenchement."""
    if not rsi_series:
        return {"insufficient_data": True}
    values = [p["value"] for p in rsi_series]
    n = len(values)
    overbought_n = sum(1 for v in values if v >= overbought)
    oversold_n = sum(1 for v in values if v <= oversold)
    return {
        "insufficient_data": False,
        "count": n,
        "mean": round(mean(values), 2),
        "median": round(median(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "last": round(values[-1], 2),
        "pct_overbought": round(overbought_n / n * 100, 1),
        "pct_oversold": round(oversold_n / n * 100, 1),
        "pct_neutral": round((n - overbought_n - oversold_n) / n * 100, 1),
        "overbought_threshold": overbought,
        "oversold_threshold": oversold,
    }


# ── ADX (Wilder) ─────────────────────────────────────────────────────────

def compute_adx(bars: list, period: int = 14) -> list:
    """Fonction pure. `bars` : liste de dicts {timestamp, high, low, close}
    triee chronologiquement. Retourne une liste de {timestamp, value, plus_di,
    minus_di}."""
    if len(bars) < 2 * period + 1:
        return []

    tr, plus_dm, minus_dm = [], [], []
    for i in range(1, len(bars)):
        high, low, prev_high, prev_low, prev_close = (
            bars[i]["high"], bars[i]["low"], bars[i - 1]["high"], bars[i - 1]["low"], bars[i - 1]["close"],
        )
        up_move = high - prev_high
        down_move = prev_low - low
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0)
        tr.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    def _wilder_smooth_running(raw, period):
        smoothed = [sum(raw[:period])]
        for v in raw[period:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
        return smoothed

    s_tr = _wilder_smooth_running(tr, period)
    s_plus_dm = _wilder_smooth_running(plus_dm, period)
    s_minus_dm = _wilder_smooth_running(minus_dm, period)

    dx = []
    plus_di_series, minus_di_series = [], []
    for stt, spd, smd in zip(s_tr, s_plus_dm, s_minus_dm):
        plus_di = 100 * spd / stt if stt else 0
        minus_di = 100 * smd / stt if stt else 0
        plus_di_series.append(plus_di)
        minus_di_series.append(minus_di)
        denom = plus_di + minus_di
        dx.append(100 * abs(plus_di - minus_di) / denom if denom else 0)

    if len(dx) < period:
        return []

    adx_values = [mean(dx[:period])]
    for v in dx[period:]:
        adx_values.append((adx_values[-1] * (period - 1) + v) / period)

    # dx[k] correspond a la bougie d'indice (period + k) dans `bars` (le
    # premier `tr`/`dm` porte sur bars[1], et le premier smoothed sur
    # bars[period]) ; adx_values[0] utilise dx[0..period-1], donc porte sur
    # la meme bougie que dx[period-1] -> bars[period + (period-1)] = bars[2*period-1].
    out = []
    for i, v in enumerate(adx_values):
        bar_index = 2 * period - 1 + i
        out.append({
            "timestamp": bars[bar_index]["timestamp"],
            "value": round(v, 4),
            "plus_di": round(plus_di_series[period - 1 + i], 4),
            "minus_di": round(minus_di_series[period - 1 + i], 4),
        })
    return out


def summarize_adx(adx_series: list, trending_threshold: float = 25, ranging_threshold: float = 20) -> dict:
    """25/20 sont les seuils conventionnels utilises pour NOMMER les zones
    "tendance"/"range" d'un ADX (terminologie universelle de l'indicateur),
    jamais une regle de declenchement."""
    if not adx_series:
        return {"insufficient_data": True}
    values = [p["value"] for p in adx_series]
    n = len(values)
    trending_n = sum(1 for v in values if v >= trending_threshold)
    ranging_n = sum(1 for v in values if v <= ranging_threshold)
    return {
        "insufficient_data": False,
        "count": n,
        "mean": round(mean(values), 2),
        "median": round(median(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "last": round(values[-1], 2),
        "pct_trending": round(trending_n / n * 100, 1),
        "pct_ranging": round(ranging_n / n * 100, 1),
        "trending_threshold": trending_threshold,
        "ranging_threshold": ranging_threshold,
    }


# ── EMA ──────────────────────────────────────────────────────────────────

def compute_ema(bars: list, period: int = 21) -> list:
    """Fonction pure. Amorcee par la SMA des `period` premieres clotures
    (convention standard) -- la premiere valeur EMA porte donc sur la bougie
    d'indice `period - 1`."""
    closes = _closes(bars)
    if len(closes) < period:
        return []

    multiplier = 2 / (period + 1)
    ema = mean(closes[:period])
    out = [{"timestamp": bars[period - 1]["timestamp"], "value": round(ema, 6)}]
    for i in range(period, len(closes)):
        ema = (closes[i] - ema) * multiplier + ema
        out.append({"timestamp": bars[i]["timestamp"], "value": round(ema, 6)})
    return out


def summarize_ema(bars: list, ema_series: list, period: int) -> dict:
    """Statistiques descriptives sur la relation prix/EMA -- jamais un
    signal de croisement. `bars` doit couvrir au moins la meme plage que
    `ema_series` (les `period-1` premieres bougies n'ont pas d'EMA)."""
    if not ema_series:
        return {"insufficient_data": True}
    aligned_closes = [b["close"] for b in bars[period - 1:]]
    values = [p["value"] for p in ema_series]
    n = len(values)
    above = sum(1 for c, e in zip(aligned_closes, values) if c > e)
    below = sum(1 for c, e in zip(aligned_closes, values) if c < e)
    rising = sum(1 for i in range(1, n) if values[i] > values[i - 1])
    crossings = sum(
        1 for i in range(1, n)
        if (aligned_closes[i] - values[i]) * (aligned_closes[i - 1] - values[i - 1]) < 0
    )
    return {
        "insufficient_data": False,
        "count": n,
        "last": round(values[-1], 4),
        "pct_price_above": round(above / n * 100, 1),
        "pct_price_below": round(below / n * 100, 1),
        "pct_rising": round(rising / max(n - 1, 1) * 100, 1),
        "crossings": crossings,
        "period": period,
    }
