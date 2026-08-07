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


def fuse_agent_reports(agent_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fusion pure (Phase 1, 06/08/2026, demande de Louis -- exemple donne :
    "BUY = 0.78 + 0.65 + 0.81 / SELL = 0.52 / Resultat: BUY / Confiance: 74%").

    `agent_scores` : {nom_agent: {"action": "BUY"/"SELL"/"WAIT"/"BUY_MARKET"/...,
    "confidence": 0-100}} -- accepte directement `recommendation` d'un
    AgentReport (meme forme).

    BUY = somme des confidences des agents ayant vote BUY, SELL = somme des
    agents ayant vote SELL (pas de somme melangee) -- direction retenue =
    la somme la plus haute. WAIT si aucune direction n'a de voix OU en cas
    d'egalite stricte (jamais un depart age au hasard sur une decision de
    trading). La confiance finale est la MOYENNE des agents ayant vote la
    direction gagnante -- pas la somme, qui grandirait artificiellement
    avec le nombre d'agents consultes et perdrait son sens 0-100."""
    buy_confidences: list[float] = []
    sell_confidences: list[float] = []
    for score in agent_scores.values():
        direction = _direction_of(str((score or {}).get("action") or "WAIT"))
        confidence = max(0.0, min(100.0, float((score or {}).get("confidence") or 0)))
        if direction == "BUY":
            buy_confidences.append(confidence)
        elif direction == "SELL":
            sell_confidences.append(confidence)

    buy_total = round(sum(buy_confidences), 1)
    sell_total = round(sum(sell_confidences), 1)

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


def build_decision_registry_entry(
    symbol_key: str,
    agent_scores: dict[str, dict[str, Any]],
    fused: dict[str, Any],
    *,
    now_iso: str,
    executed: bool = False,
) -> dict[str, Any]:
    """Format demande explicitement par Louis pour decision_registry.jsonl
    (06/08/2026) -- chaque entree garde le detail par agent (action ET
    confidence, pas seulement un chiffre isole : impossible sinon de
    verifier apres coup qui a vote quoi) en plus du resultat fusionne.
    `executed` reste toujours False tant que la Phase Shadow (comparaison,
    pas encore l'execution) n'existe pas -- voir docstring du module."""
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
        "executed": bool(executed),
    }
