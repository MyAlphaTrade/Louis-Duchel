"""Portfolio Brain (v5.1.1, chantier 4 de la feuille de route
post-Scenario-Engine). Module pur, aucune dependance MT5/reseau.

AlphaTrade Gold reste mono-actif (XAUUSD exclusivement, principe jamais
remis en cause) -- ici "panier"/"portfolio" ne designe donc pas plusieurs
symboles, mais l'ensemble des positions BOT ouvertes SIMULTANEMENT sur ce
seul symbole (position principale + renfort + rebond + scalp) : un
sous-risque reel qu'aucun agent existant ne regarde dans son ensemble
aujourd'hui.

Ce qui existe deja et n'est PAS duplique ici (reste la source de verite,
inchange -- section 12 de Architecture_ScenarioEngine_v5.1.1.html,
"jamais remplaces par une logique probabiliste") :
  - `max_floating_loss` par symbole + le plafond `auto_max_positions`/
    `max_positions` : verifies proceduralement dans auto_trade_step()
    (garde-fous durs, toujours actifs).
  - Risk Manager (`risk_manager_report()`) : budget de risque pour UN
    nouveau trade, base sur lot_safety_state().

Ce que Portfolio Brain ajoute (signal qui n'existe nulle part encore) :
  - Le biais directionnel NET du panier (BUY et SELL ouverts en meme temps
    = position couverte/hedge, jamais detecte aujourd'hui).
  - La perte flottante du panier en % de l'EQUITE reelle (aujourd'hui
    seulement compare a une limite en $ fixe par symbole, pas relative a
    la taille du compte).

Module pur : formalise un signal (AgentReport, cote alphatrade_engine.py),
n'ecrit et ne bloque rien lui-meme. Depuis le 05/08/2026 (demande explicite
de Louis : "plus rien ne doit rester en simulation"), c'est l'appelant --
status_payload() pour le pipeline classique, execute_scenario_anchor()/
execute_scenario_scalp() pour le Scenario Engine -- qui traduit
`action in ("LIMIT_NEW_ENTRIES", "REDUCE_EXPOSURE")` en blocage reel des
nouvelles entrees, derriere le flag portfolio_brain_enabled."""
from __future__ import annotations


def basket_exposure(positions: list[dict], equity: float) -> dict:
    """Agrege les positions BOT ouvertes sur XAUUSD (mono-actif). Chaque
    entree de `positions` doit exposer au moins {direction, lot, profit}."""
    buy_lot = sum(float(p.get("lot") or 0) for p in positions if p.get("direction") == "BUY")
    sell_lot = sum(float(p.get("lot") or 0) for p in positions if p.get("direction") == "SELL")
    total_lot = buy_lot + sell_lot
    net_lot = buy_lot - sell_lot
    floating_pnl = sum(float(p.get("profit") or 0) for p in positions)
    floating_pnl_pct = (floating_pnl / equity * 100.0) if equity > 0 else 0.0
    net_direction = "BUY" if net_lot > 0 else "SELL" if net_lot < 0 else "NEUTRAL"
    return {
        "position_count": len(positions),
        "buy_lot": round(buy_lot, 2),
        "sell_lot": round(sell_lot, 2),
        "total_lot": round(total_lot, 2),
        "net_lot": round(net_lot, 2),
        "net_direction": net_direction,
        "floating_pnl": round(floating_pnl, 2),
        "floating_pnl_pct": round(floating_pnl_pct, 2),
        "hedged": buy_lot > 0 and sell_lot > 0,
    }


def portfolio_risk_assessment(
    exposure: dict,
    *,
    max_positions: int,
    max_total_lot: float,
    floating_loss_warn_pct: float,
    floating_loss_critical_pct: float,
) -> dict:
    """Evalue le risque du panier deja ouvert contre des limites -- toutes
    passees par l'appelant (params.json, jamais de valeur en dur ici, meme
    regle que tout le reste du projet). Retourne priority/action/reasons/
    confidence, meme vocabulaire que les autres agents (risk_manager,
    scenario_generator) pour rester lisible cote CAIO plus tard."""
    reasons: list[str] = []
    priority = "LOW"
    action = "OK"

    if exposure["position_count"] > max_positions:
        reasons.append(f"{exposure['position_count']} positions ouvertes sur XAUUSD > limite panier {max_positions}.")
        priority = "HIGH"
        action = "LIMIT_NEW_ENTRIES"

    if max_total_lot > 0 and exposure["total_lot"] > max_total_lot:
        reasons.append(f"Lot total du panier {exposure['total_lot']} > limite {max_total_lot}.")
        priority = "HIGH"
        action = "LIMIT_NEW_ENTRIES"

    if exposure["floating_pnl_pct"] <= -abs(floating_loss_critical_pct):
        reasons.append(
            f"Perte flottante du panier {exposure['floating_pnl_pct']}% de l'equite <= seuil critique -{floating_loss_critical_pct}%."
        )
        priority = "CRITICAL"
        action = "REDUCE_EXPOSURE"
    elif exposure["floating_pnl_pct"] <= -abs(floating_loss_warn_pct):
        reasons.append(
            f"Perte flottante du panier {exposure['floating_pnl_pct']}% de l'equite <= seuil d'alerte -{floating_loss_warn_pct}%."
        )
        if priority == "LOW":
            priority = "MEDIUM"

    if exposure["hedged"]:
        reasons.append("Positions BUY et SELL ouvertes simultanement sur XAUUSD (panier couvert/hedge).")
        if priority == "LOW":
            priority = "MEDIUM"

    confidence = 90.0 if not reasons else max(20.0, 90.0 - 15.0 * len(reasons))
    return {"priority": priority, "action": action, "reasons": reasons, "confidence": confidence}
