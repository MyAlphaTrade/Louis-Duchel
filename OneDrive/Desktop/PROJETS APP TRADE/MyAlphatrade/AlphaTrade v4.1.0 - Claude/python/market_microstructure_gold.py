"""Gold Microstructure Engine (v5.1.1, chantier 2 de la feuille de route
post-Scenario-Engine). Distinct du module existant `market_microstructure.py`
(OBI/Kyle lambda, order book -- pensé crypto/DOM, confirmé "dashboard
uniquement" par l'audit du 04/08/2026, jamais utilisé dans une décision).

Correction de Louis (04/08/2026) : pas d'order book crypto pour l'or -- ce
qui compte, c'est le comportement des bougies elles-mêmes : vitesse,
accélération, taille, rejet de mèche. Exemple donné : un prix qui descend
mais dont la vitesse baisse, dont les bougies rétrécissent et qui rejette le
bas = probabilité de rebond en hausse, même si le score directionnel dit
encore SELL.

Module pur, aucune dépendance MT5/réseau -- reçoit une liste de bougies déjà
chargées (même format {"open","high","low","close"} que le reste du Scenario
Engine), testable isolément."""
from __future__ import annotations


def candle_velocity(candles: list[dict]) -> float:
    """Vitesse de variation du prix sur la derniere bougie (points), signee
    (positif = hausse, negatif = baisse)."""
    if len(candles) < 2:
        return 0.0
    return float(candles[-1]["close"]) - float(candles[-2]["close"])


def candle_acceleration(candles: list[dict], lookback: int = 5) -> float:
    """Variation de la vitesse (derivee seconde) sur les dernieres bougies --
    positif = le mouvement s'accelere, negatif = il ralentit. Un ralentissement
    du mouvement CONTRAIRE a un scenario est le signe precoce d'epuisement que
    decrit l'exemple de Louis, avant meme un retournement visible du prix."""
    if len(candles) < lookback + 1:
        return 0.0
    recent = candles[-lookback:]
    velocities = [float(recent[i]["close"]) - float(recent[i - 1]["close"]) for i in range(1, len(recent))]
    if len(velocities) < 2:
        return 0.0
    return velocities[-1] - velocities[0]


def candle_size_trend(candles: list[dict], lookback: int = 5) -> float:
    """Ratio (taille moyenne recente) / (taille moyenne anterieure), high-low.
    <1 = les bougies retrecissent (essoufflement), >1 = elles grossissent
    (impulsion). 1.0 (neutre) si pas assez de bougies pour comparer."""
    if len(candles) < lookback * 2:
        return 1.0
    recent = candles[-lookback:]
    prior = candles[-lookback * 2:-lookback]
    recent_avg = sum(float(c["high"]) - float(c["low"]) for c in recent) / len(recent)
    prior_avg = sum(float(c["high"]) - float(c["low"]) for c in prior) / len(prior)
    if prior_avg <= 0:
        return 1.0
    return recent_avg / prior_avg


def rejection_score(candles: list[dict], direction: str, lookback: int = 3) -> float:
    """Detecte un rejet de meche (queue longue opposee au corps, cloture pres
    de l'autre extreme) sur les dernieres bougies -- signe qu'un niveau vient
    d'etre teste et refuse. 0-100, 0 = aucun rejet observe."""
    if not candles:
        return 0.0
    recent = candles[-lookback:]
    scores = []
    for c in recent:
        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        rng = h - l
        if rng <= 0:
            continue
        if direction == "BUY":
            wick = min(o, cl) - l  # rejet bas : meche basse longue
        else:
            wick = h - max(o, cl)  # rejet haut : meche haute longue
        scores.append(max(0.0, min(100.0, (wick / rng) * 100)))
    return sum(scores) / len(scores) if scores else 0.0


def gold_microstructure_score(candles: list[dict], direction: str) -> dict:
    """Assemble vitesse/acceleration/taille/rejet en un score composite 0-100
    (plus haut = comportement des bougies plus favorable a `direction`) +
    detail brut pour tracabilite (confluences). Poids internes fixes et
    documentes -- meme statut que SCENARIO_WEIGHTS (algorithme, pas reglage
    utilisateur).

    Logique de l'exemple de Louis : un mouvement CONTRAIRE a `direction` qui
    decelere (ralentit son propre elan) est un bon signe pour `direction`,
    pas un mauvais -- distinct de la vitesse brute, qui elle regarderait
    seulement "le prix baisse" sans voir que la baisse s'essouffle."""
    velocity = candle_velocity(candles)
    acceleration = candle_acceleration(candles)
    size_trend = candle_size_trend(candles)
    rejection = rejection_score(candles, direction)

    move_direction = "BUY" if velocity > 0 else "SELL" if velocity < 0 else None
    if move_direction is not None and move_direction != direction:
        # Le marche vient de bouger contre notre scenario -- une deceleration
        # de CE mouvement contraire (acceleration qui s'oppose a son propre
        # sens) est un bon signe pour nous.
        opposing_accel = acceleration if move_direction == "BUY" else -acceleration
        decel_signal = 70.0 if opposing_accel < 0 else 30.0
    else:
        decel_signal = 50.0  # mouvement neutre ou deja dans notre sens -- pas d'info discriminante ici

    exhaustion_signal = 70.0 if size_trend < 0.85 else 30.0 if size_trend > 1.15 else 50.0

    score = 0.4 * rejection + 0.3 * decel_signal + 0.3 * exhaustion_signal
    return {
        "score": round(max(0.0, min(100.0, score)), 1),
        "velocity": round(velocity, 4),
        "acceleration": round(acceleration, 4),
        "size_trend": round(size_trend, 3),
        "rejection": round(rejection, 1),
    }
