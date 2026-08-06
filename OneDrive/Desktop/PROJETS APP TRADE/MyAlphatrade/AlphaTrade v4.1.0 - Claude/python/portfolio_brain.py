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


def floating_loss_learning_stats(
    worst_by_day: dict[str, float], daily_pnl_by_day: dict[str, float], min_samples: int = 10,
) -> dict:
    """task #174 (06/08/2026, demande de Louis : construire le suivi
    maintenant plutot que de laisser le calibrage Portfolio Brain comme un
    module mort). Regarde, pour chaque JOUR (pas chaque scenario -- le
    panier est une notion journaliere, voir basket_exposure()), la pire
    perte flottante atteinte (`worst_by_day`, alimente en continu par
    l'appelant a chaque cycle) et le P&L REEL final de ce meme jour
    (`daily_pnl_by_day`, deja calcule par calendar_tracker.py -- pas
    duplique ici). Bucket par tranche de profondeur, meme discipline que
    scenario_learning_stats()/scalp_learning_stats() (min_samples par case).

    Uniquement les jours presents dans les DEUX dicts -- un jour sans P&L
    final connu (session en cours) n'a rien a apprendre encore."""
    days = sorted(set(worst_by_day) & set(daily_pnl_by_day))

    def _depth_band(pct: float) -> str:
        depth = abs(pct)
        if depth < 2.0:
            return "0-2"
        if depth < 5.0:
            return "2-5"
        if depth < 10.0:
            return "5-10"
        return "10+"

    groups: dict[str, list[str]] = {}
    for day in days:
        groups.setdefault(_depth_band(worst_by_day[day]), []).append(day)

    by_band: dict[str, dict] = {}
    for band, day_list in groups.items():
        if len(day_list) < min_samples:
            continue
        bad_days = sum(1 for d in day_list if daily_pnl_by_day[d] < 0)
        by_band[band] = {
            "samples": len(day_list),
            "bad_day_rate": round(bad_days / len(day_list) * 100, 1),
            "avg_day_profit": round(sum(daily_pnl_by_day[d] for d in day_list) / len(day_list), 2),
        }

    bad_total = sum(1 for d in days if daily_pnl_by_day[d] < 0)
    return {
        "n_days": len(days),
        "overall_bad_day_rate": round(bad_total / len(days) * 100, 1) if days else 0.0,
        "by_depth_band": by_band,
    }


def floating_loss_threshold_adjustments(
    stats: dict, current: dict, *, max_warn_step: float = 0.5, max_critical_step: float = 0.5, min_edge: float = 20.0,
) -> dict:
    """task #174 (06/08/2026) -- calibration reelle de
    portfolio_floating_loss_warn_pct/critical_pct depuis le VRAI resultat de
    fin de journee (voir floating_loss_learning_stats()).

    Nuance causale honnete (a documenter, pas a cacher) : WARN seul ne
    bloque rien (action reste "OK", voir portfolio_risk_assessment()) --
    donc son signal est purement observationnel, aucun biais. CRITICAL, lui,
    declenche REDUCE_EXPOSURE (bloque les nouvelles entrees) : "le jour a
    quand meme fini negatif malgre le blocage" reste un signal utilisable,
    mais avec un biais CONSERVATEUR (le blocage ne peut qu'attenuer, jamais
    aggraver, l'issue mesuree) -- donc pas de fausse precision, preuve
    exigee 2x plus forte et pas maximal identique a warn_pct, jamais plus
    genereux.

    Garde-fou : critical_pct doit toujours rester strictement au-dela du
    NOUVEAU warn_pct (apres son propre ajustement dans ce meme appel), pas
    seulement de l'ancien -- jamais les deux seuils qui se croisent."""
    adjustments: dict = {}
    by_band = stats.get("by_depth_band") or {}
    if not by_band:
        return adjustments
    overall = stats.get("overall_bad_day_rate", 0.0)

    def _band_floor(band: str) -> float:
        return 0.0 if band == "0-2" else float(band.split("-")[0]) if "-" in band else 10.0

    # Bande la moins profonde dont le taux de mauvaise journee depasse
    # nettement la moyenne globale -- l'alerte doit se declencher des cette
    # profondeur, pas plus tard.
    risky_bands = sorted(
        (b for b, v in by_band.items() if (v["bad_day_rate"] - overall) >= min_edge), key=_band_floor,
    )
    if not risky_bands:
        return adjustments

    current_warn = float(current.get("portfolio_floating_loss_warn_pct", 2.0))
    target_warn = _band_floor(risky_bands[0])
    step_warn = max(-max_warn_step, min(max_warn_step, target_warn - current_warn))
    new_warn = current_warn
    if abs(step_warn) >= 0.1:
        new_warn = round(current_warn + step_warn, 1)
        adjustments["portfolio_floating_loss_warn_pct"] = new_warn

    # Seuil critique : preuve 2x plus stricte, jamais sous le nouveau warn_pct.
    stricter = [b for b in risky_bands if (by_band[b]["bad_day_rate"] - overall) >= min_edge * 2]
    if stricter:
        current_critical = float(current.get("portfolio_floating_loss_critical_pct", 5.0))
        target_critical = max(_band_floor(stricter[0]), new_warn + 0.1)
        step_critical = max(-max_critical_step, min(max_critical_step, target_critical - current_critical))
        if abs(step_critical) >= 0.1:
            new_critical = round(current_critical + step_critical, 1)
            if new_critical > new_warn:
                adjustments["portfolio_floating_loss_critical_pct"] = new_critical

    return adjustments
