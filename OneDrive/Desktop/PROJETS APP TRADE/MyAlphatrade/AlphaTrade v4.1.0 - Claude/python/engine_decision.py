"""Decision Engine (v1.1.5, Phase 1, 06/08/2026 -- demande explicite de
Louis : "je ferais comme Global, mais sans casser Gold. Creer un nouveau
module engine_decision.py [...] Mais au debut il ne trade pas. Il observe
seulement.").

Module pur, aucune dependance MT5/reseau -- meme discipline que
scenario_generator.py/agent_report.py. Ne reinvente PAS un nouveau format
de rapport d'agent : reutilise le contrat AgentReport deja existant
(agent_report.py, `recommendation["action"]` + `confidence`) -- exactement
ce que la reconstruction du 06/08/2026 recommandait ("le format
{bias, confidence, justification} est deja proche d'AgentReport,
existant").

Phase Shadow (Phase 2 de la demande de Louis, PAS ENCORE CABLEE ici --
cette phase-ci reste Phase 1, observation pure) : chaque fusion sera
comparee apres coup a la vraie decision du pipeline actuel, sur plusieurs
centaines de decisions, avant de laisser ce moteur influencer un seul
trade reel (voir wiring dans auto_trade_step(), qui n'appelle JAMAIS
open_position()/place_order() depuis ce module)."""
from __future__ import annotations

from typing import Any


def _direction_of(action: str) -> str | None:
    if action.startswith("BUY"):
        return "BUY"
    if action.startswith("SELL"):
        return "SELL"
    return None


def fuse_agent_reports(
    agent_scores: dict[str, dict[str, Any]],
    *,
    agent_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Fusion pure (Phase 1, 06/08/2026, demande de Louis -- exemple donne :
    "BUY = 0.78 + 0.65 + 0.81 / SELL = 0.52 / Resultat: BUY / Confiance: 74%").

    `agent_scores` : {nom_agent: {"action": "BUY"/"SELL"/"WAIT"/"BUY_MARKET"/...,
    "confidence": 0-100}} -- accepte directement `recommendation` d'un
    AgentReport (meme forme).

    BUY = somme des confidences (ponderees) des agents ayant vote BUY, SELL
    = somme des agents ayant vote SELL (pas de somme melangee) -- direction
    retenue = la somme la plus haute. WAIT si aucune direction n'a de voix
    OU en cas d'egalite stricte (jamais un depart age au hasard sur une
    decision de trading). La confiance finale est la MOYENNE (ponderee) des
    agents ayant vote la direction gagnante -- pas la somme, qui grandirait
    artificiellement avec le nombre d'agents consultes et perdrait son sens
    0-100.

    `agent_weights` (06/08/2026, demande de Louis : "un edge tres solide",
    point 3 -- ponderer les agents par fiabilite prouvee plutot que par
    poids egal par defaut) : {nom_agent: poids >= 0}. None (defaut) ->
    poids 1.0 pour tous, comportement EXACTEMENT identique a avant --
    aucune regression tant qu'aucun poids appris n'existe. Voir
    compute_agent_reliability_weights()."""
    weights = agent_weights or {}
    buy_confidences: list[float] = []
    sell_confidences: list[float] = []
    buy_weighted_sum = 0.0
    sell_weighted_sum = 0.0
    for name, score in agent_scores.items():
        direction = _direction_of(str((score or {}).get("action") or "WAIT"))
        confidence = max(0.0, min(100.0, float((score or {}).get("confidence") or 0)))
        weight = max(0.0, float(weights.get(name, 1.0)))
        if direction == "BUY":
            buy_confidences.append(confidence)
            buy_weighted_sum += confidence * weight
        elif direction == "SELL":
            sell_confidences.append(confidence)
            sell_weighted_sum += confidence * weight

    buy_total = round(buy_weighted_sum, 1)
    sell_total = round(sell_weighted_sum, 1)

    if buy_total == sell_total:
        # Couvre a la fois "aucune direction n'a de voix" (0.0 == 0.0) et
        # une vraie egalite entre BUY et SELL -- meme traitement : WAIT est
        # une decision legitime, pas un defaut par manque d'idee (meme
        # philosophie que caio_decide()/caio_decide_scenario()).
        return {"final": "WAIT", "confidence": 0.0, "buy_total": buy_total, "sell_total": sell_total}
    if buy_total > sell_total:
        return {
            "final": "BUY",
            "confidence": round(sum(buy_confidences) / len(buy_confidences), 1),
            "buy_total": buy_total, "sell_total": sell_total,
        }
    return {
        "final": "SELL",
        "confidence": round(sum(sell_confidences) / len(sell_confidences), 1),
        "buy_total": buy_total, "sell_total": sell_total,
    }


def high_conviction(
    agent_scores: dict[str, dict[str, Any]],
    fused: dict[str, Any],
    *,
    min_agents_agree: int = 3,
    min_margin: float = 30.0,
) -> bool:
    """06/08/2026, demande de Louis ("un edge tres solide", point 4 --
    selectivite plutot que frequence). Une fusion "haute conviction" exige
    DEUX choses a la fois, pas une moyenne qui peut passer un seuil sans
    vrai consensus : (1) au moins `min_agents_agree` agents distincts votent
    litteralement la direction retenue, (2) l'ecart entre le total gagnant
    et le total perdant (`min_margin`, memes unites que buy_total/sell_total)
    est net, pas un dernier moment qui bascule de justesse.

    Purement une ETIQUETTE en Phase 1 -- n'influence encore aucune decision
    d'ouverture reelle (voir docstring du module), juste journalisee dans
    decision_registry.jsonl pour permettre plus tard de comparer le taux de
    reussite des decisions 'haute conviction' contre le reste, en Phase
    Shadow."""
    if fused["final"] == "WAIT":
        return False
    agreeing = sum(
        1 for score in agent_scores.values()
        if _direction_of(str((score or {}).get("action") or "WAIT")) == fused["final"]
    )
    margin = abs(float(fused["buy_total"]) - float(fused["sell_total"]))
    return agreeing >= min_agents_agree and margin >= min_margin


def build_decision_registry_entry(
    symbol_key: str,
    agent_scores: dict[str, dict[str, Any]],
    fused: dict[str, Any],
    *,
    now_iso: str,
    executed: bool = False,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Format demande explicitement par Louis pour decision_registry.jsonl
    (06/08/2026) -- chaque entree garde le detail par agent (action ET
    confidence, pas seulement un chiffre isole : impossible sinon de
    verifier apres coup qui a vote quoi) en plus du resultat fusionne.
    `executed` reste toujours False tant que la Phase Shadow (comparaison,
    pas encore l'execution) n'existe pas -- voir docstring du module.

    `scenario_id` (06/08/2026, "un edge tres solide" point 3) : quand
    l'agent "scenario" a vote dans cette decision, garde une reference
    explicite vers son scenario_id -- seul lien possible aujourd'hui vers
    un VRAI resultat resolu (WIN_SIMULATED/LOSS_SIMULATED, scenario_log.jsonl),
    indispensable pour un jour calculer la fiabilite reelle de chaque agent
    (voir compute_agent_reliability_weights()). None si aucun scenario actif
    ce cycle -- ne fausse jamais artificiellement un lien qui n'existe pas.

    `high_conviction` : voir high_conviction() -- calcule ici plutot que
    d'obliger l'appelant a le refaire, avec les valeurs par defaut (3 agents,
    marge 30) sauf si l'appelant a deja calcule une version personnalisee."""
    return {
        "time": now_iso,
        "symbol": symbol_key,
        "agents": {
            name: {
                "action": str((score or {}).get("action") or "WAIT"),
                "confidence": round(float((score or {}).get("confidence") or 0), 1),
            }
            for name, score in agent_scores.items()
        },
        "final": fused["final"],
        "confidence": fused["confidence"],
        "high_conviction": high_conviction(agent_scores, fused),
        "scenario_id": scenario_id,
        "executed": bool(executed),
    }


def compute_agent_reliability_weights(
    resolved_entries: list[dict[str, Any]],
    *,
    min_samples: int = 20,
    min_weight: float = 0.3,
    max_weight: float = 2.0,
) -> dict[str, float] | None:
    """06/08/2026, demande de Louis ("un edge tres solide", point 3) --
    calcule un poids par agent depuis sa fiabilite REELLEMENT mesuree,
    plutot que le poids egal par defaut de fuse_agent_reports().

    `resolved_entries` : entrees de decision_registry.jsonl deja enrichies
    d'un champ `outcome_direction` ("BUY"/"SELL", la direction que le
    scenario lie a vraiment validee -- voir label_decision_outcomes())
    -- seule facon honnete aujourd'hui de savoir "qui avait raison" : le
    Decision Engine reste en Phase 1 (observation pure, aucune position
    reelle ne resulte encore de ses propres decisions), donc le SEUL
    resultat reel disponible est celui du scenario auquel la decision etait
    liee ce cycle-la (`scenario_id`). Les entrees sans `outcome_direction`
    (aucun scenario resolu correle) sont ignorees, pas comptees comme un
    echec.

    Pour chaque agent : taux de bonnes directions parmi les entrees ou il a
    vote une direction (BUY/SELL, jamais WAIT -- un WAIT n'est ni un bon ni
    un mauvais pari directionnel). Poids = ratio au taux de reussite MOYEN
    de tous les agents (>1.0 = plus fiable que la moyenne, <1.0 = moins),
    borne a [min_weight, max_weight] pour qu'un agent avec trop peu
    d'echantillons ou une serie extreme ne domine jamais totalement ni ne
    soit jamais completement exclu.

    Retourne None si le total d'entrees exploitables est sous `min_samples`
    -- pas assez de preuve pour s'ecarter du poids egal (fuse_agent_reports()
    traite None exactement comme avant, aucune regression)."""
    usable = [e for e in resolved_entries if e.get("outcome_direction") in ("BUY", "SELL")]
    if len(usable) < min_samples:
        return None

    hits: dict[str, int] = {}
    votes: dict[str, int] = {}
    for entry in usable:
        actual = entry["outcome_direction"]
        for name, agent in (entry.get("agents") or {}).items():
            direction = _direction_of(str((agent or {}).get("action") or "WAIT"))
            if direction is None:
                continue
            votes[name] = votes.get(name, 0) + 1
            if direction == actual:
                hits[name] = hits.get(name, 0) + 1

    hit_rates = {name: hits.get(name, 0) / count for name, count in votes.items() if count > 0}
    if not hit_rates:
        return None
    average_hit_rate = sum(hit_rates.values()) / len(hit_rates)
    if average_hit_rate <= 0:
        return None
    return {
        name: round(max(min_weight, min(max_weight, rate / average_hit_rate)), 3)
        for name, rate in hit_rates.items()
    }


def label_decision_outcomes(
    decision_entries: list[dict[str, Any]],
    resolved_scenarios_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    """06/08/2026 -- joint decision_registry.jsonl a scenario_log.jsonl (le
    seul historique reel de resultats disponibles aujourd'hui, voir
    compute_agent_reliability_weights()). `resolved_scenarios_by_id` :
    {scenario_id: direction_gagnante ("BUY"/"SELL")}, deja filtre par
    l'appelant sur les scenarios reellement resolus en WIN_SIMULATED (perdre
    ne "valide" pas la direction retenue -- seul un WIN confirme que la
    lecture etait la bonne. Un LOSS confirme l'inverse : la direction
    OPPOSEE etait la bonne, voir l'appelant pour ce mapping).

    Pure -- ne touche aucun fichier, se contente d'annoter une copie de
    chaque entree avec `outcome_direction` quand son `scenario_id` a une
    resolution connue (absent sinon, jamais invente)."""
    labeled = []
    for entry in decision_entries:
        scenario_id = entry.get("scenario_id")
        enriched = dict(entry)
        if scenario_id and scenario_id in resolved_scenarios_by_id:
            enriched["outcome_direction"] = resolved_scenarios_by_id[scenario_id]
        labeled.append(enriched)
    return labeled
