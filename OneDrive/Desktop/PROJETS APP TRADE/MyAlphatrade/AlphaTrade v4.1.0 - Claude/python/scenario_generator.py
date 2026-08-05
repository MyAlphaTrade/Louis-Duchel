"""Scenario Generator + Scenario Validator (v5.1.1, Phase 2 -- Market Scenario
Engine). Toujours dans le meme perimetre de version que la Phase 1 (correction
de Louis, 04/08/2026 : pas de decoupage artificiel en v5.1.2 -- tout appartient
a v5.1.1, la calibration statistique reelle est une extension future du meme
Scenario Engine, pas une version separee).

Module pur, aucune dependance MT5 : recoit des `AgentReport` deja calcules
(Structure/Smart Money/Risk/Economic Calendar) et des bougies, ne fait aucun
appel reseau lui-meme -- meme discipline que caio_decide() (arbitre des
rapports, ne les produit pas).

Regle d'integration (Louis, 04/08/2026) : aucun module ne doit rester isole
apres ses tests unitaires. Ces fonctions sont appelees depuis
auto_trade_step() (alphatrade_engine.py) a chaque cycle, derriere le flag
`scenario_engine_enabled` (defaut False), en mode observation uniquement --
aucune position reelle n'est ouverte a partir d'un scenario en Phase 2. Ca
reste la responsabilite du CAIO scenario (Phase 3, non commencee)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_report import AgentReport
from scenario import Scenario, make_scenario
from market_microstructure_gold import gold_microstructure_score

# Poids du score composite (section 8, Architecture_ScenarioEngine_v5.1.1.html) --
# constante d'algorithme documentee, pas un reglage utilisateur (meme statut que
# PRIORITY_ORDER dans agent_report.py). Ajustable plus tard par un Learning
# Manager dedie au Scenario Engine, une fois scenario_log.jsonl assez fourni --
# c'est l'"extension future de calibration" dont parle l'architecture, toujours
# v5.1.1, pas une version separee.
SCENARIO_WEIGHTS = {
    "structure": 0.25,
    "smart_money": 0.25,
    "zone_history": 0.15,
    "volatility": 0.15,
    "momentum": 0.05,
    "session": 0.05,
    # Gold Microstructure Engine (05/08/2026, chantier 2 post-Scenario-Engine) --
    # vitesse/acceleration/taille de bougie/rejet de meche, remplace l'order
    # book crypto pour l'or. Rebalance : momentum et session redescendent de
    # 0.10 a 0.05 chacun pour liberer ce nouveau facteur (somme = 1.00 inchangee).
    "microstructure": 0.10,
}

# Qualite indicative par session (connaissance de marche documentee, pas un
# risque a regler par l'utilisateur -- meme statut que STRATEGY_PROFILES).
SESSION_QUALITY = {
    "asian": 40.0,
    "london": 80.0,
    "london_ny_overlap": 100.0,
    "new_york": 80.0,
    "off_hours": 20.0,
}


def _direction_of(action: str) -> str | None:
    if action.startswith("BUY"):
        return "BUY"
    if action.startswith("SELL"):
        return "SELL"
    return None


def session_label(now: datetime | None = None) -> str:
    """Session de marche a partir de l'heure UTC -- convention documentee
    (Londres 07-13h, chevauchement Londres/New York 13-16h, New York 16-21h,
    Asie 00-07h, sinon creux)."""
    now = now or datetime.now(timezone.utc)
    hour = now.hour
    if 13 <= hour < 16:
        return "london_ny_overlap"
    if 7 <= hour < 13:
        return "london"
    if 16 <= hour < 21:
        return "new_york"
    if 0 <= hour < 7:
        return "asian"
    return "off_hours"


def simple_atr(candles: list[dict], period: int = 14) -> float:
    """ATR simplifie (moyenne des ranges high-low, sans gap true range) --
    suffisant pour dimensionner une zone et normaliser la volatilite. Ne
    remplace pas la logique de risque du Risk Manager (max_position_loss,
    stop-loss broker), qui reste inchangee et prioritaire."""
    if not candles:
        return 0.0
    recent = candles[-period:]
    ranges = [float(c.get("high", 0)) - float(c.get("low", 0)) for c in recent]
    ranges = [r for r in ranges if r > 0]
    return sum(ranges) / len(ranges) if ranges else 0.0


def volatility_score(candles: list[dict], period: int = 14, baseline_period: int = 50) -> float:
    """Volatilite courante relative a sa propre baseline -- se normalise
    seule, evite un seuil fixe arbitraire. 50 = volatilite dans la norme
    recente, au-dessus = expansion, en-dessous = compression."""
    atr_now = simple_atr(candles, period)
    atr_baseline = simple_atr(candles, baseline_period)
    if atr_baseline <= 0:
        return 50.0
    ratio = atr_now / atr_baseline
    return max(0.0, min(100.0, ratio * 50.0))


def scenario_confidence_score(
    structure_report: AgentReport,
    smart_money_report: AgentReport,
    *,
    zone_history_score: float = 50.0,
    volatility: float,
    momentum: float,
    session: float,
    microstructure: float = 50.0,
    weights: dict[str, float] | None = None,
) -> float:
    """Score composite pondere -- niveau 1 (section 8) : confiance
    analytique, jamais appelee 'probability' (correction explicite de
    Louis). `zone_history_score` par defaut a 50 (neutre) tant que
    scenario_log.jsonl n'a pas assez d'historique pour une vraie mesure de
    reussite passee sur cette zone -- se calibrera de lui-meme une fois les
    donnees disponibles, sans changer cette fonction.

    `microstructure` (v5.1.1, chantier 2, 05/08/2026) : score du Gold
    Microstructure Engine (vitesse/acceleration/taille de bougie/rejet de
    meche) -- defaut 50 (neutre) si non fourni.

    `weights` optionnel (v5.1.1, branchement Phase 5, 05/08/2026) : par
    defaut None -> utilise SCENARIO_WEIGHTS (constante figee). Permet a
    l'appelant (alphatrade_engine.py) d'injecter scenario_learned_weights.json
    sans que ce module pur n'ait besoin de connaitre DATA_DIR/le systeme de
    fichiers -- reste un module sans dependance MT5/reseau/disque."""
    w = weights or SCENARIO_WEIGHTS
    score = (
        w["structure"] * structure_report.confidence
        + w["smart_money"] * smart_money_report.confidence
        + w["zone_history"] * zone_history_score
        + w["volatility"] * volatility
        + w["momentum"] * momentum
        + w["session"] * session
        + w.get("microstructure", 0.0) * microstructure
    )
    return max(0.0, min(100.0, score))


def _composite_confidence(
    structure_report: AgentReport,
    smart_money_report: AgentReport,
    candles: list[dict],
    analysis: dict[str, Any],
    now: datetime,
    weights: dict[str, float] | None = None,
    direction: str | None = None,
) -> float:
    """Score composite pondere (section 8), factorise pour etre appele a la
    fois a la creation du scenario (devient `scenario_confidence`, fige) et
    en continu tant qu'il est actif (devient `scenario_health`, vivant --
    Phase 4, Dynamic Position Manager). 7 facteurs -- `weights` optionnel
    (defaut None -> SCENARIO_WEIGHTS), voir scenario_confidence_score().
    `direction` requis pour le facteur microstructure (rejet de meche/
    deceleration s'evaluent par rapport a un sens ; neutre a 50 si absent)."""
    institutional_zones = int((structure_report.metadata or {}).get("institutional_zones", 0) or 0)
    zone_history_score = max(0.0, min(100.0, institutional_zones * 25.0)) or 50.0
    vol_score = volatility_score(candles)
    momentum = max(0.0, min(100.0, float(analysis.get("score_gap") or 0.0)))
    session = SESSION_QUALITY.get(session_label(now), 50.0)
    microstructure = gold_microstructure_score(candles, direction)["score"] if direction else 50.0
    return scenario_confidence_score(
        structure_report, smart_money_report, microstructure=microstructure,
        zone_history_score=zone_history_score, volatility=vol_score, momentum=momentum, session=session,
        weights=weights,
    )


def evaluate_scenario_health(
    scenario: Scenario,
    structure_report: AgentReport,
    smart_money_report: AgentReport,
    candles: list[dict],
    analysis: dict[str, Any] | None = None,
    now: datetime | None = None,
    weights: dict[str, float] | None = None,
) -> float:
    """Dynamic Position Manager (Phase 4) -- recalcule `scenario_health` avec
    des donnees fraiches, meme formule que `scenario_confidence` a la
    creation mais jamais la meme valeur figee. C'est la difference que
    Louis a demandee explicitement (point 3 de sa relecture du 04/08) :
    'le prix est encore a 4086 mais l'idee est deja mauvaise' -- la
    confiance de depart ne bouge plus, la sante si. `weights` optionnel,
    voir scenario_confidence_score()."""
    now = now or datetime.now(timezone.utc)
    analysis = analysis or {}
    if not structure_report.is_trustworthy(now) or not smart_money_report.is_trustworthy(now):
        # Rapports perimes/indisponibles -- pas d'information nouvelle, la
        # sante ne peut pas etre reevaluee ce cycle, on garde la derniere
        # valeur connue plutot que d'inventer une degradation.
        return scenario.scenario_health if scenario.scenario_health is not None else scenario.scenario_confidence
    smart_direction = _direction_of(smart_money_report.recommendation.get("action", ""))
    if smart_direction is not None and smart_direction != scenario.direction:
        # Le Smart Money Analyst penche maintenant dans le sens oppose --
        # signal de retournement fort, plafonne la sante independamment du
        # score composite (qui ne "voit" pas directement la contradiction).
        base = _composite_confidence(structure_report, smart_money_report, candles, analysis, now, weights, scenario.direction)
        return min(base, 35.0)
    return _composite_confidence(structure_report, smart_money_report, candles, analysis, now, weights, scenario.direction)


def evaluate_scalp_opportunity(
    scenario: Scenario,
    current_price: float,
    risk_report: AgentReport,
    analysis: dict[str, Any] | None = None,
    *,
    momentum_min: float = 30.0,
    microstructure_min: float = 60.0,
    now: datetime | None = None,
    candles: list[dict] | None = None,
) -> dict[str, bool]:
    """CAIO mode (b) -- Dynamic Position Manager, Phase 4 (section 9,
    correction de Louis du point 6 : plus un renfort directionnel, une
    exploitation de scenario a 4 conditions, toutes requises). N'ouvre
    AUCUNE position reelle (meme garde d'observation que caio_decide_scenario)
    -- journalise seulement l'opportunite detectee (`simulated_scalp_count`).

    `micro_opportunity` (v5.1.1, chantier 2, 05/08/2026) : utilise le Gold
    Microstructure Engine (vitesse/acceleration/rejet de meche sur `candles`)
    si fourni -- remplace l'ancien proxy `analysis["score_gap"]` (issu du
    pipeline classique) par un signal propre au comportement des bougies,
    demande explicitement par Louis. Retombe sur l'ancien proxy si `candles`
    absent (retrocompatibilite)."""
    now = now or datetime.now(timezone.utc)
    analysis = analysis or {}
    atr = float((scenario.market_context or {}).get("atr") or 0.0)
    buffer = atr * 0.25

    scenario_active = scenario.status == "ACTIVE" and scenario.scalp_allowed
    zone_favorable = (scenario.zone["low"] - buffer) <= current_price <= (scenario.zone["high"] + buffer)
    risk_panier_ok = risk_report.is_trustworthy(now) and not (
        risk_report.priority == "CRITICAL" and risk_report.recommendation.get("any_rejected")
    )
    if candles:
        micro_opportunity = gold_microstructure_score(candles, scenario.direction)["score"] >= microstructure_min
    else:
        momentum = max(0.0, min(100.0, float(analysis.get("score_gap") or 0.0)))
        micro_opportunity = momentum >= momentum_min

    return {
        "scenario_active": scenario_active,
        "zone_favorable": zone_favorable,
        "risk_panier_ok": risk_panier_ok,
        "micro_opportunity": micro_opportunity,
    }


def scenario_learning_stats(entries: list[dict[str, Any]], min_samples: int = 20) -> dict[str, Any]:
    """Phase 5 (Learning). Agrege le winrate par facteur categoriel a partir
    de scenarios deja RESOLUS (outcome WIN_SIMULATED/LOSS_SIMULATED
    uniquement -- un scenario EXPIRED sans avoir jamais ete active n'a jamais
    ete mis a l'epreuve, rien a en apprendre). Meme discipline que
    trading_coach_observe() : jamais de constat sur un echantillon trop
    petit -- chaque case (session/tendance/volatilite) doit atteindre
    `min_samples` pour apparaitre dans le resultat."""
    resolved = [e for e in entries if e.get("outcome") in ("WIN_SIMULATED", "LOSS_SIMULATED")]

    def _bucket(key_fn) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[bool]] = {}
        for e in resolved:
            key = key_fn(e)
            if key is None:
                continue
            groups.setdefault(str(key), []).append(e["outcome"] == "WIN_SIMULATED")
        return {
            k: {"samples": len(v), "winrate": round(sum(v) / len(v) * 100, 1)}
            for k, v in groups.items() if len(v) >= min_samples
        }

    overall_winrate = (
        round(sum(1 for e in resolved if e["outcome"] == "WIN_SIMULATED") / len(resolved) * 100, 1)
        if resolved else 0.0
    )
    return {
        "n_resolved": len(resolved),
        "overall_winrate": overall_winrate,
        "by_session": _bucket(lambda e: (e.get("market_context") or {}).get("session")),
        "by_trend": _bucket(lambda e: (e.get("market_context") or {}).get("trend")),
        "by_volatility": _bucket(lambda e: (e.get("market_context") or {}).get("volatility")),
        "by_direction": _bucket(lambda e: e.get("direction")),
    }


def scenario_weight_adjustments(
    stats: dict[str, Any], base_weights: dict[str, float], *, max_delta: float = 0.05,
) -> dict[str, float]:
    """Traduit les ecarts de winrate observes en ajustements BORNES des poids
    du score composite -- meme discipline que learning_manager_apply() :
    bornes (+/- max_delta), justifies (ecart pondere par le nombre
    d'echantillons), reversibles (ne remplace jamais SCENARIO_WEIGHTS,
    seulement propose un jeu de poids alternatif persiste separement -- voir
    run_scenario_learning() dans alphatrade_engine.py).

    Heuristique v1 (niveau 1, section 8 de l'architecture) : edge de la
    MEILLEURE categorie (celle qui a le plus de succes, avec assez
    d'echantillons) par rapport a la moyenne globale. Pas une regression
    statistique -- ca, c'est l'extension future (niveau 2) une fois
    scenario_log.jsonl assez fourni pour un vrai modele.

    Piege corrige (trouve par mes propres tests, 04/08/2026) : une moyenne
    ponderee des ecarts de TOUTES les categories d'une partition complete
    (ex: chaque scenario a exactement une session) s'annule TOUJOURS
    exactement a zero -- propriete mathematique de la moyenne, pas un signal
    absent. Le signal utile est l'edge de la meilleure categorie seule
    (ex: "Londres reussit a 72%, la moyenne globale est 55%" -> +17 pts),
    pas une comparaison entre categories qui se neutralisent par definition."""
    overall = stats.get("overall_winrate", 0.0)
    adjustments = dict.fromkeys(base_weights, 0.0)

    def _signal(bucket: dict[str, dict[str, Any]]) -> float:
        if not bucket:
            return 0.0
        best_winrate = max(b["winrate"] for b in bucket.values())
        return best_winrate - overall

    session_signal = _signal(stats.get("by_session", {}))
    trend_signal = _signal(stats.get("by_trend", {}))
    volatility_signal = _signal(stats.get("by_volatility", {}))

    if "session" in adjustments:
        adjustments["session"] = max(-max_delta, min(max_delta, session_signal / 200))
    if "structure" in adjustments:
        adjustments["structure"] = max(-max_delta, min(max_delta, trend_signal / 200))
    if "volatility" in adjustments:
        adjustments["volatility"] = max(-max_delta, min(max_delta, volatility_signal / 200))

    return {k: round(base_weights[k] + v, 4) for k, v in adjustments.items()}


def generate_scenario(
    symbol_key: str,
    candles: list[dict],
    current_price: float,
    structure_report: AgentReport,
    smart_money_report: AgentReport,
    analysis: dict[str, Any] | None = None,
    *,
    maximum_validity_min: int = 45,
    now: datetime | None = None,
    weights: dict[str, float] | None = None,
    block_correction_regime: bool = True,
) -> Scenario | None:
    """Scenario Generator (Phase 2). Retourne None si aucune hypothese
    exploitable (agents indisponibles, directions contradictoires, ou aucun
    agent directionnel) -- meme philosophie que caio_decide() : l'absence de
    scenario est un resultat legitime, pas une erreur. `weights` optionnel
    (branchement Phase 5, 05/08/2026), voir scenario_confidence_score().

    `block_correction_regime` (05/08/2026, analyse du Scenario Replay 58j sur
    949 scenarios resolus) : le regime CORRECTION a une esperance negative
    (-0,13R/scenario, winrate 38,5% quelle que soit la direction BUY/SELL) --
    signature d'un marche indecis (les pertes mettent en moyenne PLUS longtemps
    a se resoudre que les gains, l'inverse du schema sain observe en UPTREND/
    DOWNTREND). Coherent avec trading_style_engine.py, qui traite deja
    CORRECTION comme un contexte "mixte" a prudence -- ici, on va plus loin :
    aucun scenario n'est genere du tout tant que le regime reste CORRECTION,
    plutot que d'en generer un et esperer qu'un seuil de confiance plus haut
    suffise (la confiance moyenne en CORRECTION, 68,2, n'etait deja pas plus
    haute que dans les autres regimes -- ce n'est pas un probleme de score)."""
    now = now or datetime.now(timezone.utc)
    analysis = analysis or {}

    if block_correction_regime and (structure_report.metadata or {}).get("regime") == "CORRECTION":
        return None

    usable = [r for r in (structure_report, smart_money_report) if r.is_trustworthy(now)]
    directional = [r for r in usable if _direction_of(r.recommendation.get("action", "")) is not None]
    if not directional:
        return None
    directions = {_direction_of(r.recommendation["action"]) for r in directional}
    if len(directions) > 1:
        return None  # contradiction -- pas de scenario exploitable ce cycle

    winner = max(directional, key=lambda r: r.confidence)
    direction = _direction_of(winner.recommendation["action"])
    entry_price = float(winner.recommendation.get("price") or current_price)

    atr = simple_atr(candles)
    half_width = max(atr * 0.5, current_price * 0.0005)  # plancher minuscule si ATR indisponible
    zone = {"low": round(entry_price - half_width, 5), "high": round(entry_price + half_width, 5)}

    invalidation_buffer = max(atr * 0.5, half_width * 0.5)
    if direction == "BUY":
        invalidation_price = round(zone["low"] - invalidation_buffer, 5)
        target_distance = max(atr, half_width * 2)
        targets = [
            {"price": round(entry_price + target_distance, 5), "label": "extension 1x ATR"},
            {"price": round(entry_price + target_distance * 2, 5), "label": "extension 2x ATR"},
        ]
    else:
        invalidation_price = round(zone["high"] + invalidation_buffer, 5)
        target_distance = max(atr, half_width * 2)
        targets = [
            {"price": round(entry_price - target_distance, 5), "label": "extension 1x ATR"},
            {"price": round(entry_price - target_distance * 2, 5), "label": "extension 2x ATR"},
        ]

    confluences = list(winner.arguments)
    for r in directional:
        if r is not winner:
            confluences.extend(r.arguments)
    micro = gold_microstructure_score(candles, direction)
    if micro["rejection"] >= 60.0:
        confluences.append(f"Microstructure : rejet de meche détecté ({micro['rejection']:.0f}/100).")
    if micro["size_trend"] < 0.85:
        confluences.append("Microstructure : bougies en contraction (essoufflement du mouvement contraire).")

    confidence = _composite_confidence(structure_report, smart_money_report, candles, analysis, now, weights, direction)
    vol_score = volatility_score(candles)

    scenario_id = f"{symbol_key}_{now.strftime('%Y%m%d%H%M%S')}"
    return make_scenario(
        scenario_id, symbol_key, direction, zone,
        confluences=confluences,
        scenario_confidence=confidence,
        market_context={
            "trend": (structure_report.metadata or {}).get("regime"),
            "volatility": "high" if vol_score >= 65 else "low" if vol_score <= 35 else "medium",
            "atr": round(atr, 4),
            "session": session_label(now),
            "timeframe_alignment": {str((structure_report.metadata or {}).get("timeframe", "?")): (structure_report.metadata or {}).get("regime")},
        },
        invalidation_price=invalidation_price,
        targets=targets,
        anchor_plan={"entry": entry_price, "sl": invalidation_price, "tp": targets[0]["price"]},
        maximum_validity_min=maximum_validity_min,
        now=now,
    )


def _price_beyond_final_target(scenario: Scenario, current_price: float) -> bool:
    """True si le marche a deja depasse la derniere cible du scenario --
    l'idee a deja entierement joue (dans le bon sens) sans jamais avoir ete
    validee/activee. Continuer a l'attendre jusqu'a expiration (jusqu'a 45
    min) n'a plus de sens : le rejouer plus tard collerait un plan d'ancrage
    perime (entree tres loin du prix reel) et retarderait inutilement la
    generation d'un nouveau scenario pertinent (05/08/2026, demande de
    Louis : 'il ne doit pas attendre 45 min, il doit refaire l'analyse
    immediatement')."""
    if not scenario.targets:
        return False
    final_price = scenario.targets[-1]["price"]
    if scenario.direction == "BUY":
        return current_price >= final_price
    return current_price <= final_price


def validate_scenario(
    scenario: Scenario,
    current_price: float,
    smart_money_report: AgentReport,
    risk_report: AgentReport,
    economic_report: AgentReport | None,
    *,
    now: datetime | None = None,
    reaction_confidence_min: float = 60.0,
) -> dict[str, bool]:
    """Scenario Validator (Phase 2, point 4 de la relecture de Louis) -- 4
    verifications independantes, toutes requises. Ne decide rien : ecrit le
    resultat dans `scenario.last_validation` et fait transitionner
    CANDIDATE -> VALIDATED seulement si les 4 sont vraies. Le CAIO (Phase 3)
    choisira ensuite parmi les scenarios VALIDATED, jamais parmi les
    CANDIDATE."""
    now = now or datetime.now(timezone.utc)

    zone_touched_now = scenario.zone["low"] <= current_price <= scenario.zone["high"]
    # v5.1.1 -- 05/08/2026, bug trouve en observation reelle : un scenario BUY
    # dont le prix a fortement depasse la zone (ex: cree a 4128, prix rendu a
    # 4140+ quelques minutes plus tard) restait bloque en CANDIDATE avec
    # zone_touched=False en permanence -- alors meme que la zone AVAIT ete
    # touchee, litteralement au moment de la creation (le prix d'entree est
    # toujours a l'interieur de la zone a cet instant). Le probleme : l'ancien
    # `zone_touched` etait un instantane (prix DANS la zone MAINTENANT), pas
    # un souvenir -- des que le prix quittait la zone (souvent tres vite si le
    # mouvement est franc, exactement le cas qu'on veut recompenser), le check
    # repassait a False et ne remontait plus jamais a True, empechant les 4
    # conditions de jamais s'aligner. `reaction_count` (deja incremente plus
    # bas a chaque touche reelle) sert desormais de memoire : une fois touchee
    # au moins une fois, la zone reste consideree "touchee" pour le reste de
    # la vie du scenario.
    zone_touched = zone_touched_now or scenario.reaction_count > 0

    smart_direction = _direction_of(smart_money_report.recommendation.get("action", ""))
    reaction = (
        smart_money_report.is_trustworthy(now)
        and smart_direction == scenario.direction
        and smart_money_report.confidence >= reaction_confidence_min
    )

    risk_ok = risk_report.is_trustworthy(now) and not (
        risk_report.priority == "CRITICAL" and risk_report.recommendation.get("any_rejected")
    )

    market_ok = economic_report is None or not (
        economic_report.priority == "CRITICAL" and economic_report.recommendation.get("any_rejected")
    )

    checks = {"zone_touched": zone_touched, "reaction": reaction, "risk_ok": risk_ok, "market_ok": market_ok}
    scenario.last_validation = dict(checks)

    if zone_touched_now:
        scenario.record_reaction()  # increment sur une touche fraiche uniquement, pas a chaque cycle sticky

    if scenario.status in ("CANDIDATE", "VALIDATED") and _price_beyond_final_target(scenario, current_price):
        # Priorite sur la validation normale : si le prix a deja depasse la
        # derniere cible, activer maintenant n'aurait plus de sens (l'ancrage
        # est perime) -- voir _price_beyond_final_target().
        scenario.transition(
            "EXPIRED",
            "Marche a depasse la derniere cible sans jamais valider -- scenario perime, nouvelle analyse immediate.",
            now=now,
        )
    elif all(checks.values()) and scenario.status == "CANDIDATE":
        scenario.transition(
            "VALIDATED",
            f"Validation reussie: {sum(checks.values())}/4 conditions.",
            now=now,
        )
    elif scenario.status in ("CANDIDATE", "VALIDATED") and scenario.is_expired(now):
        # Corrige un bug trouve par le Scenario Replay (Louis, 04/08/2026) :
        # un scenario VALIDATED dont la confiance reste sous caio_min_confidence
        # (donc jamais active par le CAIO) restait bloque indefiniment --
        # aucun chemin d'expiration ne couvrait ce statut, ce qui empechait
        # tout nouveau scenario d'etre genere ensuite (CURRENT_SCENARIO ne
        # redevient jamais None). L'expiration couvre desormais les deux
        # statuts non-actifs, pas seulement CANDIDATE.
        scenario.transition("EXPIRED", "Delai de validite depasse sans activation.", now=now)

    return checks
