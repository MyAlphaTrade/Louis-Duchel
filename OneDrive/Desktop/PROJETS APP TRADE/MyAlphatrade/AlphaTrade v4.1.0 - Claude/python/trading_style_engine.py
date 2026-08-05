"""Trading Style Engine (v5.1.1, chantier 3 de la feuille de route
post-Scenario-Engine). Module pur, aucune dependance MT5/reseau.

Contexte : `strategy_mode` (STRATEGY_PROFILES dans alphatrade_engine.py --
"scalping_fast"/"scalping_safe"/"long_analysis"/"combined") est aujourd'hui
choisi UNE FOIS manuellement par Louis dans Parametres, et reste fixe quel
que soit le contexte de marche. Ce module calcule ce que le mode DEVRAIT
etre en ce moment, a partir du regime (Structure Analyst) et de la
volatilite (meme bucketing low/medium/high que scenario_generator.py, pour
rester coherent avec le reste du Scenario Engine).

Meme prudence que le reste de la feuille de route (poids appris, Gold
Microstructure) : ce module ne fait QUE recommander. Il n'ecrit jamais
params["strategy_mode"] -- observation seule, journalisee, jusqu'a preuve
faite sur assez de cycles reels (meme principe que scenario_engine_enabled/
learning_manager_apply : recommandation d'abord, application ensuite, sur
decision explicite de Louis)."""
from __future__ import annotations

# Doit rester synchronise avec les cles de STRATEGY_PROFILES
# (alphatrade_engine.py) -- pas d'import croise pour garder ce module pur
# et testable sans MT5, mais les 4 valeurs retournees ici sont garanties
# etre des cles valides de STRATEGY_PROFILES (voir test_trading_style_engine.py).
VALID_MODES = ("scalping_fast", "scalping_safe", "long_analysis", "combined")


def recommend_trading_style(regime: str | None, volatility: str) -> dict:
    """Recommande un `strategy_mode` a partir du regime de marche (Structure
    Analyst : UPTREND/DOWNTREND/RANGE/CORRECTION) et de la volatilite
    (low/medium/high). Logique :

    - Volatilite haute -> `scalping_safe` en priorite : peu importe le
      regime, une volatilite elevee justifie des confirmations plus
      strictes et moins de trades avant tout (le meme principe qui justifie
      economic_calendar_block_hours cote risque).
    - Tendance nette (UPTREND/DOWNTREND) sans volatilite haute -> `long_analysis` :
      une vraie tendance merite une lecture multi-timeframe et un objectif
      par trade plus eleve plutot que des sorties rapides qui coupent le
      mouvement en cours.
    - Range calme (RANGE + volatilite basse) -> `scalping_fast` : pas de
      tendance a suivre, mieux vaut plusieurs petits gains frequents que
      d'attendre une direction qui n'existe pas.
    - Tout le reste (CORRECTION, regime inconnu, range en volatilite
      moyenne...) -> `combined`, le mode le plus prudent par construction
      (`entry_policy: adaptive`, scalping seulement si la tendance longue
      ne contredit pas)."""
    regime = regime or "RANGE"
    volatility = volatility if volatility in ("low", "medium", "high") else "medium"

    if volatility == "high":
        mode = "scalping_safe"
        reason = f"Volatilite {volatility} -- confirmations plus strictes, moins de trades avant tout, quel que soit le regime ({regime})."
    elif regime in ("UPTREND", "DOWNTREND"):
        mode = "long_analysis"
        reason = f"Tendance nette ({regime}), volatilite {volatility} -- lecture multi-timeframe, laisser courir plutot que sortir vite."
    elif regime == "RANGE" and volatility == "low":
        mode = "scalping_fast"
        reason = f"Range calme (volatilite {volatility}) -- pas de tendance a suivre, petits gains frequents plutot qu'attendre."
    else:
        mode = "combined"
        reason = f"Contexte mixte (regime={regime}, volatilite={volatility}) -- scalping seulement si la tendance longue ne contredit pas le signal court."

    return {"mode": mode, "regime": regime, "volatility": volatility, "reason": reason}
