from __future__ import annotations

import json
import logging
import math
import os
import queue
import sqlite3
import sys
import tempfile
import threading
import time
import argparse
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from market_microstructure import MicrostructureObserver
import calendar_tracker
from agent_report import AgentReport, make_agent_report, sort_by_priority, PRIORITY_ORDER
from economic_calendar import economic_calendar_report
from shared_memory import SHARED_MEMORY
from scenario import Scenario, ScenarioEvent, make_scenario, activate_scenario, close_scenario
from scenario_generator import (
    generate_scenario, validate_scenario, evaluate_scenario_health, evaluate_scalp_opportunity,
    scenario_learning_stats, scenario_weight_adjustments, scenario_threshold_adjustments,
    SCENARIO_WEIGHTS, volatility_score,
)
from trading_style_engine import recommend_trading_style
from portfolio_brain import basket_exposure, portfolio_risk_assessment
from market_microstructure_gold import gold_microstructure_score
from slack_notifier import notify_slack, blocks_caio_go, blocks_mission_target, blocks_trading_toggle, SLACK_GREEN, SLACK_RED
# v5.1.0 -- modules purs recuperes depuis l'historique git (commit f5f6403,
# 15/07/2026, "KB1-KB8"), non touches par le retrait de KB1000 comme moteur
# separe (Phase 13, 16/07/2026 -- seule l'execution dupliquee/KB8 posait
# probleme, la structure/smart money elles-memes n'ont jamais ete en cause).
from market_structure import detect_swings, classify_swings, market_structure
from market_zones import market_zones
from market_fibonacci import fibonacci_from_swings
from market_smart_money import (
    detect_fvg,
    detect_order_blocks,
    detect_bos_choch,
    detect_liquidity_grabs,
    detect_equal_levels,
    premium_discount,
)

MAGIC = 20260607
AVA_MAGIC = 7525001
VERSION = "5.1.1"
# v5.1.0 -- version propre au "Gold AI Brain" (CAIO/Mission Manager/Structure/
# Smart Money/Risk), independante de VERSION : premiere version de ce
# sous-systeme entierement nouveau, ne suit pas le numero de l'application.
GOLD_BRAIN_VERSION = "1.0"
HARD_RISK_PCT_CAP = 0.50
HARD_AUTO_POSITION_CAP = 8

DATA_DIR = Path(os.environ.get("ALPHATRADE_DATA_DIR", Path.home() / "AlphaTrade"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = {
    "XAUUSD": {
        "aliases": ["XAUUSD", "Gold vs US Dollar", "XAUUSD."],
        "label": "XAU/USD",
        "market": "gold",
    },
}

DEFAULT_PARAMS = {
    "mt5_path": r"C:\Program Files\MetaTrader 5\terminal64.exe",
    "active_symbol": "XAUUSD",
    "strategy_mode": "scalping_fast",
    "active_engine": "alphatrade_ai",
    # Export Signaux (Strategy Lab, 22/07/2026) -- desactive par defaut, et
    # jamais expose dans REMOTE_PARAM_ALLOWLIST (electron/main.js) : ne peut
    # etre change que localement, depuis Parametres sur ce PC. Sans ce garde-
    # fou, un signal externe pourrait ouvrir une position REELLE des que
    # active_engine="external_signal" est choisi -- meme si Strategy Lab ou
    # le pont d'authentification etaient un jour compromis.
    "external_signals_allow_real": False,
    "external_signal_max_age_sec": 180,
    # "Strategy Lab" DOIT rester avant "AlphaTrade AI" dans cette liste : le
    # meme MAGIC est utilise pour les deux (open_position() ne differencie
    # que par le commentaire, voir position_type="STRATLAB"/"STRATLABNR"),
    # et trade_origin() retourne au premier match magic+mot-cle -- place
    # apres, cette regle ne serait jamais atteinte puisque "alphatrade" est
    # deja un mot-cle de la regle suivante et apparait dans tous les
    # commentaires. type reste "INTERNAL_BOT" (donc origin="BOT") pour ne
    # RIEN changer aux filtres existants (renfort, exposition, verrou
    # directionnel...) -- seul origin_name change, pour l'affichage/le
    # Journal et pour l'exclusion ciblee du Rebond (should_open_rebond).
    "trade_origins": [
        {"name": "Strategy Lab", "type": "INTERNAL_BOT", "magic_numbers": [],
         "comment_keywords": ["stratlab"], "enabled": True},
        {"name": "AlphaTrade AI", "type": "INTERNAL_BOT", "magic_numbers": [MAGIC],
         "comment_keywords": ["alphatrade", "alphakaris"], "enabled": True},
        {"name": "AVA Assistant", "type": "EXTERNAL_AI", "magic_numbers": [AVA_MAGIC],
         "comment_keywords": ["ava", "bridge"], "enabled": True},
    ],
    "capital_min": 0.0,
    "auto_max_positions": 2,
    "session_target": 25.0,
    "daily_target": 50.0,
    "session_max_loss": -150.0,
    "giveback": 100.0,
    # v5.1.0 -- Trading Mission Manager : horizons semaine/mois, distincts de
    # daily_target/session_max_loss (jour). 0 = derive automatiquement de
    # daily_target (x5 semaine, x20 mois) dans mission_state().
    "mission_weekly_target": 0.0,
    "mission_monthly_target": 0.0,
    "mission_consecutive_loss_defense": 3,
    # v5.1.0 -- Economic Calendar : agent de condition (jamais directionnel),
    # bloque une entree via CAIO quand une publication macro a fort impact
    # (NFP/CPI/Fed) est imminente sur la devise du symbole actif.
    "economic_calendar_enabled": True,
    "economic_calendar_block_hours": 2.0,
    # v5.1.0 -- Slack : liste de webhooks entrants, chacun choisissant ses
    # types d'evenement (caio_go / mission_target / trading_toggle). Vide par
    # defaut -- aucune notification tant qu'aucun webhook n'est configure.
    "slack_webhooks": [],
    # v5.1.0 -- meme logique que slack_min_confidence dans AlphaTrade Global :
    # sans ce filtre, une journee a 100+ trades genererait 100+ notifications
    # "Decision CAIO GO". Seul cet evenement est filtre -- objectifs atteints
    # et demarrage/arret restent rares par nature, pas besoin de seuil.
    "slack_min_confidence": 70,
    # v5.1.0 -- CAIO v1 : seuil de qualite minimum sous lequel aucun scenario
    # n'est retenu, meme le mieux classe (voir caio_decide()).
    "caio_min_confidence": 60.0,
    # v5.1.0 -- place_order() : duree de vie d'un ordre en attente (Limit/Stop)
    # non declenche avant annulation automatique par le broker.
    "pending_order_expire_min": 60,
    # v5.1.0 -- interrupteur general de la nouvelle couche agentique (Mission
    # Manager/Structure/Smart Money/CAIO). Defaut False = comportement
    # strictement identique a avant (open_position() direct, aucun changement
    # de comportement). Bascule instantanee, jamais activee directement en
    # reel sans validation demo dediee (voir plan de securite de la
    # Proposition Technique v5.1.0).
    "gold_brain_enabled": False,
    # v5.1.1 Phase 2 -- Market Scenario Engine, observation uniquement (aucune
    # decision d'execution ne depend de ce flag tant que le CAIO scenario,
    # Phase 3, n'existe pas). Defaut False, meme securite que gold_brain_enabled.
    "scenario_engine_enabled": False,
    # v5.1.1 -- 05/08/2026, activation reelle demandee explicitement par
    # Louis (section 4 : "le systeme doit devenir actif"). Coupe-circuit
    # DEDIE et INDEPENDANT de scenario_engine_enabled ci-dessus : celui-ci ne
    # controle que la generation/journalisation (peut rester actif seul en
    # observation pure) ; celui-la controle si un scenario ACTIVE peut
    # reellement ouvrir une position MT5 (execute_scenario_anchor()). Mettre
    # a False redescend en observation pure instantanement, sans desactiver
    # scenario_engine_enabled ni perdre l'historique/apprentissage.
    "scenario_engine_execution_enabled": True,
    # v5.1.1 -- 05/08/2026, execution reelle des scalps (execute_scenario_scalp()).
    # Sans cooldown, evaluate_scalp_opportunity() redetecterait la meme
    # opportunite a chaque reevaluation DPM (par defaut toutes les 3s) tant
    # que les 4 conditions restent vraies -- empilement d'ordres sans fin.
    # Valeur reprise de l'exemple donne par Louis lui-meme (section 5 de sa
    # demande du 05/08/2026 : "Scalp cooldown | 45 sec | IA").
    "scenario_scalp_cooldown_sec": 45.0,
    # Plafond de securite par scenario, independant du cooldown -- meme
    # philosophie que auto_max_positions/portfolio_max_positions : jamais de
    # limite "infinie" meme improbable en pratique.
    "scenario_scalp_max_count": 3,
    # Fraction du lot normal pour un scalp -- plus petit que la position
    # d'ancrage (renfort d'opportunite, pas une deuxieme position principale).
    "scenario_scalp_lot_ratio": 0.5,
    # v5.1.1 -- 05/08/2026, backtest automatique intelligent (section 7 de la
    # demande de Louis). Reutilise le Scenario Replay/Learning existants --
    # voir run_auto_backtest_if_due(). Defaut True (activation demandee).
    "scenario_auto_backtest_enabled": True,
    "scenario_backtest_interval_hours": 24.0,
    # 58j : plafond reel de retention M1 du terminal MT5 observe (90j -> 0
    # bougies, confirme par sondage direct le 04/08/2026) -- au-dela, aucune
    # donnee supplementaire n'existe de toute facon.
    "scenario_backtest_days": 58,
    "scenario_learning_min_samples": 20,
    # v5.1.1 Phase 4 -- seuil sous lequel scenario_health (vivant) fait
    # basculer un scenario ACTIVE en DEGRADED (securisation avant que le prix
    # n'atteigne invalidation_price). Distinct de caio_min_confidence (seuil
    # d'activation, une seule fois, a l'entree).
    "scenario_health_degradation_threshold": 45.0,
    # Seuil d'activation dedie au CAIO scenario (Phase 3), distinct de
    # caio_min_confidence (ancien pipeline) -- voir caio_decide_scenario().
    # Defaut 60, calibre sur la distribution reelle du Scenario Replay du
    # 04/08/2026 (median 64,4/100 sur 565 scenarios) -- a affiner par la
    # Phase 5 (Learning) une fois assez de resultats accumules.
    "scenario_caio_min_confidence": 60.0,
    # v5.1.1 Phase 4/chantier 2 -- seuil du Gold Microstructure Engine pour
    # detecter une "micro_opportunity" (scalp) dans evaluate_scalp_opportunity().
    # Meme echelle 0-100 que gold_microstructure_score(). Voir market_microstructure_gold.py.
    "scenario_microstructure_min": 60.0,
    # v5.1.1 -- analyse du Scenario Replay 58j du 05/08/2026 (949 scenarios
    # resolus) : regime CORRECTION a esperance negative (-0,13R/scenario,
    # winrate 38,5% BUY comme SELL) -- signature d'un marche indecis (les
    # pertes mettent PLUS longtemps a se resoudre que les gains, l'inverse du
    # schema sain vu en UPTREND/DOWNTREND). Defaut True : aucun scenario
    # genere tant que le regime reste CORRECTION. Voir generate_scenario().
    "scenario_block_correction_regime": True,
    # v5.1.1 -- meme analyse (58j, 05/08/2026) : session Londres a un vrai
    # gradient de winrate selon la confiance (33% sous 65, 47-50% au-dessus
    # de 70) -- contrairement a CORRECTION, pas bloquee, juste une barre plus
    # haute que le seuil general. S'applique en plus de scenario_caio_min_confidence
    # (jamais en dessous). Voir caio_decide_scenario().
    "scenario_london_min_confidence": 70.0,
    # v5.1.1 -- 05/08/2026, bug trouve en observation reelle : throttle du
    # Dynamic Position Manager (evite de recalculer scenario_health depuis
    # une bougie M1 encore en formation a chaque tick de la boucle
    # principale -- source du bruit ACTIVE<->DEGRADED observe en direct,
    # plusieurs fois par seconde). Voir LAST_DPM_EVAL_AT/scenario_engine_step().
    "scenario_health_reeval_interval_sec": 3.0,
    # v5.1.1 -- 06/08/2026, task #170 (demande de Louis : "mode intraday
    # 15m/1h"). Contexte de raisonnement dedie du Scenario Engine, INDEPENDANT
    # du `timeframe` par symbole du pipeline classique -- les deux moteurs
    # peuvent tourner sur des horizons differents sans interference. Defaut
    # "M5" : comportement strictement identique a avant l'ajout de ce
    # parametre. M15/H1 : zones plus larges, cibles plus eloignees et duree de
    # vie plus longue -- tout decoule automatiquement de l'ATR/bougies reels a
    # ce nouveau timeframe (voir generate_scenario()), aucun autre reglage
    # manuel a toucher. La duree de validite maximale (auparavant fixe a 45
    # min) est desormais deduite de ce choix, voir SCENARIO_VALIDITY_MINUTES_BY_TIMEFRAME.
    "scenario_engine_timeframe": "M5",
    # v5.1.1 chantier 3 -- Trading Style Engine (trading_style_engine.py) :
    # recommande un strategy_mode a partir du regime/volatilite reels,
    # observation seule (n'ecrit jamais strategy_mode). Defaut False, meme
    # securite que scenario_engine_enabled -- voir trading_style_engine_step().
    # Defaut passe a True le 05/08/2026 (demande explicite de Louis : "plus
    # rien ne doit rester en simulation, active tout").
    "trading_style_engine_enabled": True,
    # v5.1.1 -- 05/08/2026, activation reelle demandee explicitement par
    # Louis (section 2/3 : "plus rien ne doit rester en simulation"). Quand
    # actif, une recommandation qui diverge du mode courant est vraiment
    # appliquee (ecrite dans params.json, meme mecanisme que le selecteur
    # manuel) -- pas seulement journalisee. Coupe-circuit dedie, independant
    # de trading_style_engine_enabled (qui ne fait que calculer/journaliser).
    "trading_style_auto_apply_enabled": True,
    # Anti-oscillation : delai minimum entre deux changements automatiques de
    # mode -- sans lui, un regime a la frontiere entre deux buckets de
    # volatilite ferait changer de mode a chaque cycle.
    "trading_style_switch_cooldown_sec": 300.0,
    # v5.1.1 chantier 4 -- Portfolio Brain (portfolio_brain.py) : agrege les
    # positions BOT ouvertes simultanement sur XAUUSD (principale/renfort/
    # rebond/scalp) -- biais directionnel net, perte flottante en % de
    # l'equite, detection hedge. N'ecrit rien, ne bloque rien lui-meme --
    # Defaut passe a True le 05/08/2026 (demande explicite de Louis : "plus
    # rien ne doit rester en simulation, active tout") -- bloque desormais
    # reellement les nouvelles entrees (classique ET Scenario Engine) quand
    # l'evaluation panier est LIMIT_NEW_ENTRIES/REDUCE_EXPOSURE, voir
    # status_payload() et execute_scenario_anchor()/execute_scenario_scalp().
    "portfolio_brain_enabled": True,
    # Limites du panier XAUUSD -- distinctes de auto_max_positions/
    # symbols.XAUUSD.max_positions (comptage "nouvelles entrees", deja
    # verifie proceduralement, inchange) : ici c'est l'EXPOSITION DEJA
    # OUVERTE qui est evaluee, tous types de positions confondus.
    "portfolio_max_positions": 5,
    "portfolio_max_total_lot": 0.0,  # 0 = pas de plafond de lot total (meme convention que max_floating_loss)
    "portfolio_floating_loss_warn_pct": 2.0,
    "portfolio_floating_loss_critical_pct": 5.0,
    "fast_be_enabled": True,
    "profit_protection_enabled": True,
    "profit_drawdown_pct": 30.0,
    "profit_warning_ratio": 0.75,
    "risk_pct": 0.35,
    "real_lot_cap": 0.10,
    "demo_lot_cap": 0.10,
    "anti_top_bottom": True,
    "lookback_candles": 200,
    "edge_zone_pct": 20,
    "min_score_gap": 8,
    "reinforcement_enabled": True,
    "reinforcement_min_confidence_margin": 5,
    "reinforcement_min_score_gap": 8,
    "reinforcement_cooldown_sec": 30,
    "ai_server_enabled": True,
    "ai_server_url": "http://127.0.0.1:8765",
    "ai_server_token": "",
    "ai_server_trade_confirmation": True,
    "ai_sync_interval_sec": 5,
    "ai_retrain_interval_min": 360,
    "rebond_enabled": False,
    "rebond_min_signal_pct": 55,
    "rebond_min_loss_trigger": 2.0,
    "rebond_target_pips": 1.50,
    "rebond_cooldown_sec": 60,
    "rebond_max_hold_sec": 90,
    "rebond_stop_pips": 2.00,
    "rebond_max_active": 3,
    # Rebond Fort (demande de Louis, 23/07/2026, suite a l'incident du
    # 4160->4020 sur l'or) : le Rebond normal ci-dessus se desactive
    # volontairement des que le signal de tendance principal est fort
    # (>=85%, voir should_open_rebond) -- exactement le cas d'un mouvement
    # soutenu, la` ou plus rien ne compensait la perte. Rebond Fort est un
    # 2e palier, distinct et desactivable separement, qui ne s'active QUE
    # dans ce cas-la`, avec une barre de confiance beaucoup plus haute
    # (rebond_fort_min_signal_pct) et une cible/duree adaptees a un vrai
    # retournement (pas un scalp de quelques secondes). Nombre de tentatives
    # plafonne par position perdante (rebond_fort_max_attempts) pour eviter
    # tout comportement de "doublage" repete.
    "rebond_fort_enabled": False,
    "rebond_fort_min_signal_pct": 80,
    "rebond_fort_target_pips": 15.0,
    "rebond_fort_stop_pips": 8.0,
    "rebond_fort_max_hold_sec": 900,
    "rebond_fort_max_attempts": 1,
    "microstructure_enabled": True,
    "microstructure_interval_sec": 2,
    "hyperliquid_observer_enabled": False,
    "hyperliquid_symbols": ["BTC", "ETH"],
    "symbols": {
        "XAUUSD": {
            "lot": 0.05,
            "lot_min": 0.01,
            "max_positions": 5,
            "max_position_loss": 20,
            "max_floating_loss": 50,
            "timeframe": "M5",
            "confidence_min": 60,
            "cadence_sec": 15,
            "max_trades_hour": 120,
            "max_hold_sec": 2700,  # 45min -- time stop universel (positions perdantes incluses), voir position_exit_reason()
            "position_review_sec": 300,
            "profit_target": 5.00,
            "momentum_exit_score": 55,
            "emergency_loss_limit": 50.00,
            "min_positive_exit": 0.50,
            "profit_trailing_giveback": 0.0,
            # 06/08/2026 -- "phase naissance du trade" (demande explicite de
            # Louis suite a l'audit du ticket 9748487751 : PROFIT_TRAILING a
            # ferme a -2.20$ un trade ne de 1.7 seconde, qui avait pourtant
            # touche +1.80$ de pic -- le temps que l'ordre de fermeture
            # atteigne MT5, le prix avait deja continue contre la position
            # (execute a -4.40$). Pendant ce court intervalle apres
            # l'ouverture, aucune decision Python instantanee ne doit fermer
            # la position -- seuls les filets de securite independants du
            # temps (MAX_POSITION_LOSS, stop broker) restent actifs. Voir
            # position_exit_reason().
            "trade_birth_phase_sec": 5.0,
            "signal_reversal_margin": 99,
            "cooldown_after_loss_sec": 30,
            "session_filter_enabled": False,
            "session_start_utc": 7,
            "session_end_utc": 22,
            "stop_before_end_min": 10,
            "take_profit_enabled": False,
            "take_profit_levels": [
                {"threshold": 3.75, "pct": 25, "trailing": 0.0},
                {"threshold": 7.50, "pct": 25, "trailing": 0.0},
                {"threshold": 11.25, "pct": 25, "trailing": 0.0},
            ],
            "take_profit_move_be": True,
            "lot_multiplicateur_renfort": 1.0,
            "lot_multiplicateur_rebond": 3.0,
            "lot_multiplicateur_rebond_fort": 2.0,
        },
    },
}

# entry_policy (v5.1.0) -- prefere lue par caio_decide(), PAS un filtre dur
# consomme par place_order(). Voir Proposition_Technique_MiseEnOeuvre_v5.1.0.html
# section "Decision d'architecture centrale" : le strategy_mode exprime une
# philosophie, le CAIO garde le dernier mot selon le contexte (chaque ecart
# journalise dans shared_memory["learning_history"] comme caio.entry_override).
#   immediate     -> privilegie BUY/SELL MARKET (modes scalping)
#   pending_limit -> privilegie BUY/SELL LIMIT ancres sur zone (analyse posee)
#   adaptive      -> aucune preference fixe, y compris Buy/Sell Stop sur cassure confirmee
STRATEGY_PROFILES = {
    "scalping_fast": {
        "label": "Scalping rapide",
        "description": "Plus reactif: petits gains frequents, signaux courts et sorties rapides.",
        "entry_policy": "immediate",
        "global": {"lookback_candles": 120, "min_score_gap": 8, "edge_zone_pct": 18},
        "symbols": {
            "XAUUSD":   {"timeframe": "M5", "confidence_min": 55, "cadence_sec": 10, "position_review_sec": 60,  "profit_target": 3.00,  "max_hold_sec": 600},
        },
    },
    "scalping_safe": {
        "label": "Scalping prudent",
        "description": "Moins de trades: confirmations plus propres et filtres de risque plus stricts.",
        "entry_policy": "immediate",
        "global": {"lookback_candles": 200, "min_score_gap": 10, "edge_zone_pct": 20},
        "symbols": {
            "XAUUSD":   {"timeframe": "M5", "confidence_min": 60, "cadence_sec": 15, "position_review_sec": 120, "profit_target": 5.00,  "max_hold_sec": 1800},
        },
    },
    "long_analysis": {
        "label": "Analyse longue",
        "description": "Moins d'entrees: lecture multi-timeframe, objectif par trade plus eleve.",
        "entry_policy": "pending_limit",
        "global": {"lookback_candles": 300, "min_score_gap": 12, "edge_zone_pct": 24},
        "symbols": {
            "XAUUSD":   {"timeframe": "M15", "confidence_min": 65, "cadence_sec": 60, "position_review_sec": 300, "profit_target": 10.0,  "max_hold_sec": 3600, "max_positions": 3},
        },
    },
    "combined": {
        "label": "Mode combine",
        "description": "Scalping seulement si la tendance longue ne contredit pas le signal court.",
        "entry_policy": "adaptive",
        "global": {"lookback_candles": 240, "min_score_gap": 8, "edge_zone_pct": 20},
        "symbols": {
            "XAUUSD":   {"timeframe": "M5", "confidence_min": 58, "cadence_sec": 12, "position_review_sec": 120, "profit_target": 5.00, "max_hold_sec": 1800},
        },
    },
}

ENTRY_POLICY_VALUES = ("immediate", "pending_limit", "adaptive")


def entry_policy_for_mode(mode: str) -> str:
    profile = STRATEGY_PROFILES.get(mode, STRATEGY_PROFILES["scalping_fast"])
    return profile.get("entry_policy", "immediate")


def trading_style_engine_step(
    params: dict, structure_report: AgentReport, candles: list[dict], now: datetime | None = None,
) -> dict | None:
    """v5.1.1 chantier 3 -- Trading Style Engine, observation seule (meme
    garde que Phase 2-5 du Scenario Engine). Calcule ce que `strategy_mode`
    DEVRAIT etre a partir du regime reel (Structure Analyst) et de la
    volatilite reelle (meme bucketing que scenario_generator.py), journalise
    la recommandation dans trading_style_log.jsonl et TRADING_STYLE_STATE
    pour une future UI (chantier 5) -- mais n'ecrit JAMAIS params["strategy_mode"].
    Retourne None si desactive (`trading_style_engine_enabled`, defaut False)."""
    if not bool(params.get("trading_style_engine_enabled", False)):
        return None
    now = now or datetime.now(timezone.utc)
    regime = (structure_report.metadata or {}).get("regime")
    vol_score = volatility_score(candles)
    volatility = "high" if vol_score >= 65 else "low" if vol_score <= 35 else "medium"
    recommendation = recommend_trading_style(regime, volatility)
    current_mode = str(params.get("strategy_mode") or "scalping_fast")
    entry = {
        "at": now.isoformat(),
        "current_mode": current_mode,
        "recommended_mode": recommendation["mode"],
        "matches_current": recommendation["mode"] == current_mode,
        "regime": recommendation["regime"],
        "volatility": recommendation["volatility"],
        "reason": recommendation["reason"],
    }
    TRADING_STYLE_STATE.clear()
    TRADING_STYLE_STATE.update(entry)
    append_jsonl("trading_style_log.jsonl", entry)
    return entry


def apply_trading_style_recommendation(entry: dict, params: dict, *, now: datetime | None = None) -> bool:
    """Applique reellement la recommandation du Trading Style Engine (v5.1.1,
    05/08/2026, activation demandee explicitement par Louis : "plus rien ne
    doit rester en simulation"). Ecrit params["strategy_mode"] dans
    params.json -- meme cle que le selecteur manuel de l'UI, aucun chemin
    special -- le prochain merge_params() du cycle suivant le lit
    normalement. Throttle (trading_style_switch_cooldown_sec) pour eviter
    l'oscillation si le regime reste a la frontiere entre deux buckets de
    volatilite. Retourne True seulement si un changement reel a eu lieu
    (journalise via log_ai_adaptation() -- alimente l'historique, section 6)."""
    global LAST_TRADING_STYLE_SWITCH_AT
    now = now or datetime.now(timezone.utc)
    if not bool(params.get("trading_style_auto_apply_enabled", True)):
        return False
    if entry.get("matches_current"):
        return False
    cooldown = max(0.0, float(params.get("trading_style_switch_cooldown_sec", 300.0)))
    if LAST_TRADING_STYLE_SWITCH_AT is not None and (now - LAST_TRADING_STYLE_SWITCH_AT).total_seconds() < cooldown:
        return False
    new_mode = str(entry.get("recommended_mode") or "")
    old_mode = str(entry.get("current_mode") or "")
    if new_mode not in STRATEGY_PROFILES or new_mode == old_mode:
        return False
    saved = read_json("params.json", {}) or {}
    saved["strategy_mode"] = new_mode
    write_json("params.json", saved)
    LAST_TRADING_STYLE_SWITCH_AT = now
    log_ai_adaptation("trading_style_engine", "strategy_mode", old_mode, new_mode, str(entry.get("reason") or ""), now=now)
    return True


AI_SERVER_STATE = {
    "enabled": True,
    "connected": False,
    "mode": "OBSERVATION",
    "url": "http://127.0.0.1:8765",
    "models": {},
    "predictions": {},
    "last_sync": None,
    "error": "",
}
AI_TRAIN_ATTEMPTS: dict[str, float] = {}
CLOSE_ATTEMPTS: dict[int, float] = {}
# 06/08/2026 -- monitoring latence (demande de Louis) : time.perf_counter()
# au moment ou le dernier snapshot de positions (live_positions()) a ete pris
# dans la boucle principale -- lu par close_bot_position() pour savoir a quel
# point les donnees de profit utilisees pour la decision de fermeture etaient
# fraiches. 0.0 tant que la boucle n'a pas encore tourne une fois (tests).
_PERF_POSITIONS_SNAPSHOT_AT: float = 0.0
TAKE_PROFIT_STATE: dict[int, dict] = {}  # {ticket: {tp_done, be_applied}}
FAST_BE_STATE: dict[int, bool] = {}  # {ticket: True} une fois le Break-Even rapide appliqué (fast_breakeven_step)
PROFIT_TRAIL_RATCHET_STATE: dict[int, float] = {}  # {ticket: dernier SL appliqué} par profit_trailing_ratchet_step

# ── Module Capture Rebond ──────────────────────────────────────────────────────
# Gère les positions contra-tendance sur rebonds identifiés via zones S&D
# multi-timeframe. La position principale reste ouverte; seul le rebond est
# capturé avec un lot dynamique, puis fermé rapidement avant la résistance.
# Supporte plusieurs rebonds simultanés (jusqu'à rebond_max_active).
REBOND_STATES: list[dict] = []  # [{ticket, direction, open_price, target_price, lot, opened_at, main_direction}, ...]
REBOND_META: dict = {
    "zones": [],              # Zones S&D identifiées sur M5/M15
    "last_scan": 0.0,         # Dernier scan des zones
    "last_rebond_at": 0.0,    # Dernier rebond ouvert (cooldown)
}

# v5.1.1 Phase 2 -- Market Scenario Engine. Objet de travail du process
# (comme REBOND_STATES/TAKE_PROFIT_STATE/FAST_BE_STATE), sa forme serialisee
# (.to_dict()) est publiee dans SHARED_MEMORY["active_scenarios"] pour les
# autres lecteurs (UI, futur CAIO scenario). Un seul scenario actif a la
# fois -- principe mono-actif XAUUSD deja etabli.
CURRENT_SCENARIO: Scenario | None = None
# v5.1.1 -- 05/08/2026, bug trouve en observation reelle : sans throttling,
# dynamic_position_manager_step() se relancait a chaque tick de la boucle
# principale (0,5s, puis 0,1s -- voir plus bas), recalculant scenario_health
# depuis des bougies M1 encore en formation. Resultat observe : la sante
# oscillait entre ~35 et ~68 plusieurs fois par seconde (ACTIVE<->DEGRADED
# en boucle), pur bruit intra-bougie, pas un vrai changement de marche.
# Suit le meme domaine temporel que `now` (reel en live, simule en replay) --
# JAMAIS time.time(), sinon le rejeu (qui tourne en boucle serree sur un
# temps simule) supprimerait quasiment toutes les reevaluations. Reinitialise
# a None au debut/fin de run_scenario_replay(), meme principe que CURRENT_SCENARIO.
LAST_DPM_EVAL_AT: datetime | None = None

# v5.1.1 chantier 3 -- Trading Style Engine. Derniere recommandation connue
# (meme statut que AI_SERVER_STATE/REBOND_META : instantane de travail du
# process, pas persiste au-dela du redemarrage). Observation seule -- ne
# remplace jamais params["strategy_mode"], voir trading_style_engine_step().
TRADING_STYLE_STATE: dict = {}
# v5.1.1 -- 05/08/2026, throttle de apply_trading_style_recommendation()
# (meme principe que LAST_DPM_EVAL_AT) : empeche un changement automatique de
# strategy_mode a chaque cycle si le regime oscille a la frontiere entre deux
# buckets de volatilite.
LAST_TRADING_STYLE_SWITCH_AT: datetime | None = None

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception as exc:
    mt5 = None
    MT5_IMPORT_ERROR = str(exc)
else:
    MT5_IMPORT_ERROR = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(name: str, payload: dict) -> None:
    path = DATA_DIR / name
    fd, tmp = tempfile.mkstemp(prefix="alphatrade_", suffix=".tmp", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
        # Windows peut refuser le rename si le fichier est temporairement verrouillé par Electron.
        # On retente jusqu'à 5 fois avec un court delai avant de propager l'erreur.
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def read_json(name: str, fallback=None):
    try:
        path = DATA_DIR / name
        if not path.exists():
            return fallback
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


# 06/08/2026 -- audit latence MT5<->AlphaTrade (demande explicite de Louis) :
# params.json etait relu et re-parse DEPUIS LE DISQUE deux fois par cycle de
# la boucle principale (merge_params() + effective_params_for_strategy()),
# soit ~20 lectures disque/seconde meme quand rien n'a change. Cache par
# mtime -- ne relit reellement le fichier que si sa date de modification a
# change depuis le dernier appel (donc a chaque vraie sauvegarde depuis
# Parametres, jamais autrement). Reserve aux lectures pures (jamais aux
# endroits qui lisent puis reecrivent params.json dans la meme fonction --
# ceux-la doivent voir l'etat reel du disque, pas un cache potentiellement
# perime, voir les 2 autres appels directs a read_json("params.json", ...)
# plus bas dans ce fichier).
_PARAMS_JSON_CACHE: dict = {"mtime": None, "data": {}}


def _cached_params_json() -> dict:
    path = DATA_DIR / "params.json"
    try:
        mtime = path.stat().st_mtime if path.exists() else None
    except OSError:
        mtime = None
    if mtime != _PARAMS_JSON_CACHE["mtime"]:
        _PARAMS_JSON_CACHE["data"] = read_json("params.json", {}) or {}
        _PARAMS_JSON_CACHE["mtime"] = mtime
    return _PARAMS_JSON_CACHE["data"]


# 06/08/2026 -- audit latence MT5<->AlphaTrade (demande explicite de Louis) :
# log() faisait un open/write/close DISQUE SYNCHRONE a chaque appel, dans la
# boucle de trading elle-meme (des dizaines d'appels/seconde en periode
# active, voir alphatrade.log ~11 Mo). Un trade ne doit jamais attendre
# l'ecriture du journal -- log() ne fait plus que deposer la ligne dans une
# file, un thread dedie (_log_writer_loop) l'ecrit en arriere-plan. print()
# reste synchrone (stdout, deja tres rapide, utile pour le direct au
# demarrage) ; seule l'ecriture DISQUE est deportee."""
_LOG_QUEUE: "queue.Queue[str]" = queue.Queue()
_LOG_WRITER_STARTED = False


def _log_writer_loop() -> None:
    log_path = DATA_DIR / "alphatrade.log"
    while True:
        line = _LOG_QUEUE.get()
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass  # jamais faire planter le moteur pour une ligne de journal perdue
        finally:
            _LOG_QUEUE.task_done()


def _ensure_log_writer_started() -> None:
    global _LOG_WRITER_STARTED
    if _LOG_WRITER_STARTED:
        return
    threading.Thread(target=_log_writer_loop, name="alphatrade-log-writer", daemon=True).start()
    _LOG_WRITER_STARTED = True


def log(message: str, level: str = "INFO") -> None:
    _ensure_log_writer_started()
    line = f"[{datetime.now().strftime('%H:%M:%S')}] [{level}] {message}"
    print(line, flush=True)
    _LOG_QUEUE.put(line)


class _StdlibLogBridge(logging.Handler):
    """Redirige les modules utilisant `logging` standard (ex: slack_notifier,
    qui journalise ses echecs d'envoi via logging.getLogger) vers le meme
    alphatrade.log / Journal visible dans l'app que le reste du moteur --
    05/08/2026, audit Slack : sans ce pont, `logging` n'a aucun handler
    configure nulle part dans l'app, donc un echec d'envoi Slack (mauvaise
    URL, timeout, etc.) ne laissait absolument AUCUNE trace visible pour
    Louis -- ni dans le Journal, ni dans la console Electron. Erreur
    silencieuse confirmee, exactement le symptome remonte."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = "ERROR" if record.levelno >= logging.ERROR else "WARNING" if record.levelno >= logging.WARNING else "INFO"
            log(f"[{record.name}] {record.getMessage()}", level)
        except Exception:
            pass


logging.getLogger("slack_notifier").addHandler(_StdlibLogBridge())
logging.getLogger("slack_notifier").setLevel(logging.WARNING)
logging.getLogger("slack_notifier").propagate = False


_REASON_LOG_THROTTLE: dict[str, float] = {}


def log_reason_throttled(key: str, reason: str, *, min_interval_sec: float = 3.0) -> None:
    """Journalise `reason` au plus une fois toutes les `min_interval_sec` --
    05/08/2026, bug de spam trouve en observation reelle : le texte de
    `reason` embarque souvent un pourcentage qui change legerement a chaque
    cycle (ex: "confiance 67,6%" -> "67,7%" -> "67,8%"...), ce qui rendait
    l'ancien garde-fou `if state.get("reason") != reason` inefficace -- il
    considerait chaque variation comme un nouveau message et journalisait a
    chaque cycle. Devenu tres visible une fois la boucle principale accelere
    a 0,1s (voir time.sleep() dans main()). Throttle pur sur le temps, pas
    sur le texte : la MEME situation bloquee ne doit pas spammer le Journal,
    peu importe si le chiffre affiche bouge legerement.

    05/08/2026 (bis) -- premiere version stockait l'horodatage dans le dict
    `trading_state` passe par l'appelant, mais `load_trading_state()`
    RECONSTRUIT ce dict a un schema fixe (10 cles nommees) a chaque lecture
    et jette silencieusement toute cle inconnue -- l'horodatage etait donc
    perdu a chaque cycle et le throttle ne freinait jamais rien en pratique
    (spam confirme en observation reelle malgre ce garde-fou). Corrige en
    gardant l'horodatage dans une variable de module en memoire, cle par
    `key` (un identifiant fixe par site d'appel), plutot que dans un fichier
    dont le schema est round-trippe a chaque tick."""
    now = time.time()
    last_at = _REASON_LOG_THROTTLE.get(key, 0.0)
    if now - last_at < min_interval_sec:
        return
    log(reason, "INFO")
    _REASON_LOG_THROTTLE[key] = now


def append_jsonl(name: str, payload: dict) -> None:
    with (DATA_DIR / name).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")


def log_ai_adaptation(
    module: str, parameter: str, old_value, new_value, reason: str, *, now: datetime | None = None,
) -> None:
    """Historique des adaptations IA (v5.1.1, 05/08/2026, section 6 de la
    demande de Louis : "je veux voir en temps reel l'evolution du systeme").
    Un seul point d'entree, append-only -- appele UNIQUEMENT quand un
    parametre est REELLEMENT modifie automatiquement (jamais fabrique/simule) :
    aujourd'hui, le Trading Style Engine (apply_trading_style_recommendation())
    et le Scenario Learning (run_scenario_learning(), quand les poids appris
    different reellement des precedents). Persiste dans ai_adaptations_log.jsonl,
    lu par le futur onglet Historique (chantier UI)."""
    now = now or datetime.now(timezone.utc)
    append_jsonl("ai_adaptations_log.jsonl", {
        "at": now.isoformat(),
        "module": module,
        "parameter": parameter,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
    })
    log(f"Adaptation IA [{module}]: {parameter} {old_value} -> {new_value} -- {reason}", "SUCCESS")


def recent_ai_adaptations(limit: int = 30) -> list[dict]:
    """Lit les `limit` dernieres adaptations reelles (les plus recentes en
    premier) pour l'onglet Historique (section 6) -- lecture seule, jamais
    aucun impact sur le cycle de trading si le fichier est absent/corrompu."""
    path = DATA_DIR / "ai_adaptations_log.jsonl"
    if not path.exists():
        return []
    try:
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    out.reverse()
    return out


def load_scenario_weights() -> dict[str, float]:
    """Branchement Phase 5 (05/08/2026) -- lit scenario_learned_weights.json
    (ecrit par run_scenario_learning()) et retourne ses `learned_weights` si
    le fichier existe et est valide (mêmes 6 cles que SCENARIO_WEIGHTS,
    valeurs numeriques). Retombe sur SCENARIO_WEIGHTS (constante figee) si le
    fichier est absent, corrompu, ou incomplet -- jamais d'exception propagee
    jusqu'au cycle de trading pour un probleme de calibration."""
    try:
        data = read_json("scenario_learned_weights.json", None)
        if not data:
            return SCENARIO_WEIGHTS
        learned = data.get("learned_weights")
        if not isinstance(learned, dict) or set(learned) != set(SCENARIO_WEIGHTS):
            return SCENARIO_WEIGHTS
        return {k: float(v) for k, v in learned.items()}
    except Exception as exc:  # noqa: BLE001 -- calibration optionnelle, ne doit jamais casser le cycle
        log(f"Scenario Learning: lecture scenario_learned_weights.json echouee ({exc}), poids par defaut utilises.", "WARNING")
        return SCENARIO_WEIGHTS


def log_scenario_event(scenario: Scenario, log_name: str = "scenario_log.jsonl") -> None:
    """Journalise l'etat courant d'un Scenario dans scenario_log.jsonl --
    correction de Louis du 04/08/2026 : le scenario doit garder trace de
    pourquoi la zone existe, pourquoi elle etait valide/invalide, combien de
    fois le prix a reagi dessus, et son resultat final -- sinon "il restera
    juste un filtre sophistique", jamais exploitable pour l'extension future
    de calibration statistique (toujours v5.1.1, pas une version separee).
    Meme convention append-only que caio_decisions.jsonl/learning_events.jsonl.

    Ecrit `scenario.to_dict()` en entier a chaque appel (y compris `history`
    et l'alias `health_curve`) -- une ligne par changement d'etat, pas
    seulement a la cloture, pour pouvoir reconstruire toute la trajectoire
    (scenario_confidence -> scenario_health -> outcome) sans avoir a rejouer
    les transitions.

    Appele depuis scenario_engine_step() (Phase 2), lui-meme branche dans
    auto_trade_step() derriere `scenario_engine_enabled` -- observation
    uniquement, aucune position reelle n'en depend. `log_name` : parametrable
    pour le Scenario Replay (scenario_replay_log.jsonl, v5.1.1), jamais
    melange avec les vraies donnees d'observation live."""
    append_jsonl(log_name, scenario.to_dict())


def merge_params() -> dict:
    saved = _cached_params_json()
    merged = json.loads(json.dumps(DEFAULT_PARAMS))
    for key, value in saved.items():
        if key == "symbols" and isinstance(value, dict):
            for sym, sym_params in value.items():
                if sym in merged["symbols"] and isinstance(sym_params, dict):
                    merged["symbols"][sym].update(sym_params)
        else:
            merged[key] = value
    if not (DATA_DIR / "params.json").exists():
        write_json("params.json", merged)
    return merged


def effective_params_for_strategy(params: dict) -> dict:
    effective = json.loads(json.dumps(params))
    mode = str(effective.get("strategy_mode") or "scalping_fast")
    profile = STRATEGY_PROFILES.get(mode, STRATEGY_PROFILES["scalping_fast"])
    saved = _cached_params_json()
    for key, value in profile.get("global", {}).items():
        # Ne pas écraser si l'utilisateur a explicitement défini la valeur
        if key not in saved:
            effective[key] = value
    for symbol_key, overrides in profile.get("symbols", {}).items():
        if symbol_key in effective.get("symbols", {}):
            saved_sym = saved.get("symbols", {}).get(symbol_key, {})
            for k, v in overrides.items():
                # Appliquer le profil si: clé absente OU valeur encore égale au défaut
                # (valeur changée par l'utilisateur → préservée)
                default_val = DEFAULT_PARAMS.get("symbols", {}).get(symbol_key, {}).get(k)
                if k not in saved_sym or saved_sym.get(k) == default_val:
                    effective["symbols"][symbol_key][k] = v
    effective["strategy_profile"] = {
        "key": mode,
        "label": profile.get("label", mode),
        "description": profile.get("description", ""),
    }
    return effective


def initialize_mt5(params: dict) -> bool:
    if mt5.initialize():
        log("Terminal MT5 actif detecte automatiquement.")
        return True
    configured = str(params.get("mt5_path") or "").strip()
    candidates = [
        configured,
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            if mt5.initialize(path=candidate):
                log(f"Terminal MT5 detecte: {candidate}")
                return True
            log(f"Connexion refusee via {candidate}: {mt5.last_error()}", "WARNING")
    return bool(mt5.initialize())


def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATA_DIR / "alphatrade.db")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
          id TEXT PRIMARY KEY,
          ticket INTEGER,
          position_id INTEGER,
          symbol TEXT,
          direction TEXT,
          origin TEXT,
          lot REAL,
          open_price REAL,
          open_time TEXT,
          close_price REAL,
          close_time TEXT,
          profit REAL,
          status TEXT
        )
        """
    )
    # 05/08/2026 -- migration additive (bug trouve en observation reelle,
    # Louis) : le bucket "origin" seul (BOT/EXTERNAL_AI/MANUAL) ne suffisait
    # pas a l'UI pour afficher le nom precis de l'EA externe (ex: "AT
    # Global") une fois le trade cloture et relu depuis la base -- seules
    # les positions ENCORE OUVERTES (jamais persistees, calculees a chaque
    # lecture via trade_origin()) l'avaient. ADD COLUMN est idempotent via
    # le garde OperationalError : aucune perte de donnees existantes, les
    # anciennes lignes restent NULL et retombent sur legacy_origin_name().
    for column in ("origin_name TEXT", "origin_type TEXT", "origin_magic INTEGER"):
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass  # colonne deja presente
    conn.commit()
    return conn


def resolve_symbol(key: str) -> str | None:
    if mt5 is None:
        return None
    for alias in SYMBOLS[key]["aliases"]:
        info = mt5.symbol_info(alias)
        if info is not None:
            mt5.symbol_select(alias, True)
            return alias
    return None


def tf_const(name: str):
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    return mapping.get(str(name).upper(), mt5.TIMEFRAME_M5)


def ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return values[-1]
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0) for x in deltas[-period:]]
    losses = [max(-x, 0) for x in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def default_learning_state() -> dict:
    symbols = {}
    for key in SYMBOLS:
        symbols[key] = {
            "samples": 0,
            "wins": 0,
            "losses": 0,
            "total_profit": 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "confidence_offset": 0.0,
            "weights": {
                "trend": 1.0,
                "rsi": 1.0,
                "macd": 1.0,
                "edge": 1.0,
                "momentum": 1.0,
            },
            "processed_positions": [],
            "last_outcome": "",
            "last_closed_at": "",
        }
    return {"version": 1, "symbols": symbols, "updated_at": ""}


def load_learning_state() -> dict:
    state = read_json("learning_state.json", {}) or {}
    merged = default_learning_state()
    for key, value in state.items():
        if key != "symbols":
            merged[key] = value
    for key, value in (state.get("symbols") or {}).items():
        if key not in merged["symbols"] or not isinstance(value, dict):
            continue
        merged["symbols"][key].update(value)
        merged["symbols"][key]["weights"].update(value.get("weights") or {})
    return merged


def save_learning_state(state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json("learning_state.json", state)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def ai_server_request(params: dict, path: str, payload: dict | None = None, timeout: float = 1.5) -> dict:
    base = str(params.get("ai_server_url") or "http://127.0.0.1:8765").rstrip("/")
    body = None if payload is None else json.dumps(payload, ensure_ascii=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = str(params.get("ai_server_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers=headers,
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def update_ai_server_state(
    params: dict,
    symbol_names: dict[str, str],
    analyses: dict[str, dict],
    train_missing: bool = False,
) -> dict:
    global AI_SERVER_STATE
    enabled = bool(params.get("ai_server_enabled", True))
    base = str(params.get("ai_server_url") or "http://127.0.0.1:8765").rstrip("/")
    if not enabled:
        AI_SERVER_STATE = {
            **AI_SERVER_STATE,
            "enabled": False,
            "connected": False,
            "url": base,
            "error": "Serveur IA desactive dans les parametres.",
        }
        return AI_SERVER_STATE
    try:
        health = ai_server_request(params, "/health", timeout=0.8)
        model_payload = ai_server_request(params, "/v1/models", timeout=0.8)
        models = dict(model_payload.get("models") or {})
        retrain_minutes = max(30, int(params.get("ai_retrain_interval_min", 360)))
        for key, name in symbol_names.items():
            model = models.get(key)
            due = model is None
            if model and model.get("trained_at"):
                try:
                    trained_at = datetime.fromisoformat(str(model["trained_at"]))
                    if trained_at.tzinfo is None:
                        trained_at = trained_at.replace(tzinfo=timezone.utc)
                    due = (
                        datetime.now(timezone.utc) - trained_at.astimezone(timezone.utc)
                    ).total_seconds() >= retrain_minutes * 60
                except ValueError:
                    due = True
            last_attempt = float(AI_TRAIN_ATTEMPTS.get(key, 0))
            if due and (train_missing or time.time() - last_attempt >= 1800):
                AI_TRAIN_ATTEMPTS[key] = time.time()
                candles = symbol_candles(
                    name,
                    params.get("symbols", {}).get(key, {}),
                    limit=1200,
                )
                trained = ai_server_request(
                    params,
                    "/v1/train",
                    {
                        "symbol": key,
                        "candles": candles,
                        "horizon_bars": 3 if key == "XAUUSD" else 5,
                    },
                    timeout=30,
                )
                if trained.get("active_model"):
                    models[key] = trained["active_model"]
        predictions = {}
        for key, name in symbol_names.items():
            candles = symbol_candles(
                name,
                params.get("symbols", {}).get(key, {}),
                limit=120,
            )
            predictions[key] = ai_server_request(
                params,
                "/v1/predict",
                {
                    "symbol": key,
                    "candles": candles,
                    "local": analyses.get(key, {}),
                },
                timeout=2,
            )
        AI_SERVER_STATE = {
            "enabled": True,
            "connected": bool(health.get("ok")),
            "mode": "OBSERVATION",
            "url": base,
            "server_version": health.get("version"),
            "models": models,
            "predictions": predictions,
            "last_sync": utc_now(),
            "error": "",
        }
    except (OSError, ValueError, urllib.error.URLError) as exc:
        AI_SERVER_STATE = {
            **AI_SERVER_STATE,
            "enabled": True,
            "connected": False,
            "url": base,
            "last_sync": utc_now(),
            "error": str(exc),
        }
    return AI_SERVER_STATE


def server_trade_confirmation(
    params: dict,
    active: str,
    symbol: str,
    decision: dict,
    analysis: dict,
    payload: dict,
    positions: list[dict],
    lot_info: dict,
) -> tuple[bool, dict]:
    if not bool(params.get("ai_server_enabled", True)):
        return True, {"ok": True, "approved": True, "reason": "Serveur IA desactive."}
    if not bool(params.get("ai_server_trade_confirmation", True)):
        return True, {"ok": True, "approved": True, "reason": "Confirmation serveur IA desactivee."}

    context = {
        "symbol_key": active,
        "symbol": symbol,
        "local_decision": {
            "signal": decision.get("signal"),
            "confidence": decision.get("confidence"),
            "reason": decision.get("reason"),
            "eligible": decision.get("eligible"),
        },
        "analysis": {
            "signal": analysis.get("signal"),
            "confidence": analysis.get("confidence"),
            "trend": analysis.get("trend"),
            "fast_signal": analysis.get("fast_signal"),
            "score_gap": analysis.get("score_gap"),
            "rsi": analysis.get("rsi"),
            "edge_position": analysis.get("edge_position"),
            "learned_threshold": analysis.get("learned_threshold"),
            "zone": analysis.get("zone"),
            "strategy_mode": analysis.get("strategy_mode"),
            "multi_timeframe_bias": analysis.get("multi_timeframe_bias"),
            "multi_timeframe_score": analysis.get("multi_timeframe_score"),
            "support_zone": analysis.get("support_zone"),
            "resistance_zone": analysis.get("resistance_zone"),
        },
        "protection": payload.get("protection"),
        "session_access": payload.get("session_access", {}).get(active),
        "positions": [
            {
                "symbol_key": item.get("symbol_key"),
                "origin": item.get("origin"),
                "direction": item.get("direction"),
                "lot": item.get("lot"),
                "profit": item.get("profit"),
                "open_price": item.get("open_price"),
                "current_price": item.get("current_price"),
            }
            for item in positions[:8]
        ],
        "lot_safety": lot_info,
        "params": {
            "auto_max_positions": params.get("auto_max_positions"),
            "risk_pct": params.get("risk_pct"),
            "min_score_gap": params.get("min_score_gap"),
            "anti_top_bottom": params.get("anti_top_bottom"),
            "lookback_candles": params.get("lookback_candles"),
            "symbol": params.get("symbols", {}).get(active, {}),
            "strategy_mode": params.get("strategy_mode"),
            "strategy_profile": params.get("strategy_profile"),
        },
    }
    try:
        reply = ai_server_request(
            params,
            "/v1/decision",
            {"context": context},
            timeout=22,
        )
    except (OSError, ValueError, urllib.error.URLError) as exc:
        reply = {
            "ok": False,
            "approved": False,
            "decision": "WAIT",
            "confidence": 0,
            "reason": f"Serveur IA indisponible: {exc}",
        }
    approved = bool(reply.get("ok")) and bool(reply.get("approved"))
    return approved, reply


def candle_reversal_context(rates, edge_position: float, edge_limit: float, rsi_value: float) -> dict:
    if rates is None or len(rates) < 8:
        return {"signal": "WAIT", "confidence": 0.0, "reason": "Pas assez de bougies."}
    last = rates[-1]
    prev = rates[-2]
    open_price = float(last[1])
    high = float(last[2])
    low = float(last[3])
    close = float(last[4])
    prev_open = float(prev[1])
    prev_close = float(prev[4])
    body = max(abs(close - open_price), 1e-9)
    upper_wick = max(0.0, high - max(open_price, close))
    lower_wick = max(0.0, min(open_price, close) - low)
    closes = [float(row[4]) for row in rates[-8:]]
    short_momentum = closes[-1] - closes[-4]
    bearish_candle = close < open_price
    bullish_candle = close > open_price
    bearish_engulf = bearish_candle and prev_close > prev_open and close < prev_open and open_price >= prev_close
    bullish_engulf = bullish_candle and prev_close < prev_open and close > prev_open and open_price <= prev_close
    top_extreme = edge_position >= 100 - edge_limit
    bottom_extreme = edge_position <= edge_limit

    if top_extreme:
        rejection = bool(
            bearish_engulf
            or bearish_candle
            or upper_wick >= body * 1.15
            or short_momentum < 0
            or rsi_value >= 60
        )
        if rejection:
            confidence = 55 + min(18, (edge_position - (100 - edge_limit)) * 0.5) + min(10, max(0, rsi_value - 58) * 0.35)
            if bearish_engulf:
                confidence += 6
            if upper_wick >= body * 1.15:
                confidence += 4
            if short_momentum < 0:
                confidence += 4
            return {
                "signal": "SELL",
                "confidence": round(clamp(confidence, 55, 82), 1),
                "reason": "Zone haute: rejet/essoufflement detecte, reanalyse en SELL.",
            }

    if bottom_extreme:
        rejection = bool(
            bullish_engulf
            or bullish_candle
            or lower_wick >= body * 1.15
            or short_momentum > 0
            or rsi_value <= 40
        )
        if rejection:
            confidence = 55 + min(18, (edge_limit - edge_position) * 0.5) + min(10, max(0, 42 - rsi_value) * 0.35)
            if bullish_engulf:
                confidence += 6
            if lower_wick >= body * 1.15:
                confidence += 4
            if short_momentum > 0:
                confidence += 4
            return {
                "signal": "BUY",
                "confidence": round(clamp(confidence, 55, 82), 1),
                "reason": "Zone basse: rejet/rebond detecte, reanalyse en BUY.",
            }

    return {"signal": "WAIT", "confidence": 0.0, "reason": "Aucun retournement confirme."}


def timeframe_trend_context(symbol: str, timeframe: str, limit: int = 160) -> dict:
    rates = mt5.copy_rates_from_pos(symbol, tf_const(timeframe), 0, limit)
    if rates is None or len(rates) < 55:
        return {"timeframe": timeframe, "trend": "COLLECTING", "score": 0.0}
    closes = [float(row[4]) for row in rates]
    highs = [float(row[2]) for row in rates[-80:]]
    lows = [float(row[3]) for row in rates[-80:]]
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    momentum = closes[-1] - closes[-8]
    support = min(lows) if lows else closes[-1]
    resistance = max(highs) if highs else closes[-1]
    zone_pos = (closes[-1] - support) / (resistance - support) if resistance > support else 0.5
    trend = "RANGE"
    score = 0.0
    if e9 > e21 > e50 and momentum > 0:
        trend = "BULLISH"
        score = 1.0
    elif e9 < e21 < e50 and momentum < 0:
        trend = "BEARISH"
        score = -1.0
    elif e9 > e21:
        trend = "BULLISH"
        score = 0.45
    elif e9 < e21:
        trend = "BEARISH"
        score = -0.45
    return {
        "timeframe": timeframe,
        "trend": trend,
        "score": round(score, 3),
        "ema9": round(e9, 2),
        "ema21": round(e21, 2),
        "ema50": round(e50, 2),
        "support": round(support, 5),
        "resistance": round(resistance, 5),
        "zone_position": round(zone_pos * 100, 1),
    }


def multi_timeframe_context(symbol: str, symbol_key: str | None) -> dict:
    frames = ["M5", "M15", "M30", "H1"]
    contexts = [timeframe_trend_context(symbol, frame) for frame in frames]
    valid = [item for item in contexts if item.get("trend") != "COLLECTING"]
    if not valid:
        return {"bias": "COLLECTING", "score": 0.0, "frames": contexts}
    total = sum(float(item.get("score") or 0) for item in valid)
    avg = total / max(1, len(valid))
    bullish = sum(1 for item in valid if item.get("trend") == "BULLISH")
    bearish = sum(1 for item in valid if item.get("trend") == "BEARISH")
    bias = "RANGE"
    if avg >= 0.35 and bullish >= bearish:
        bias = "BULLISH"
    elif avg <= -0.35 and bearish >= bullish:
        bias = "BEARISH"
    supports = [float(item.get("support") or 0) for item in valid if item.get("support")]
    resistances = [float(item.get("resistance") or 0) for item in valid if item.get("resistance")]
    return {
        "bias": bias,
        "score": round(avg, 3),
        "frames": contexts,
        "support_zone": round(max(supports), 5) if supports else 0,
        "resistance_zone": round(min(resistances), 5) if resistances else 0,
    }


def external_signal_entry_decision(symbol_key: str, params: dict) -> dict:
    """Construit une decision compatible avec le format 'simulated_decision'
    a partir du dernier signal recu de Strategy Lab (electron/main.js ecrit
    external_signal.json quand une commande EXTERNAL_SIGNAL arrive au
    heartbeat). Un signal est consomme une seule fois (marque consumed=True
    apres lecture) pour ne pas rouvrir/re-fermer une position a chaque tick
    tant qu'aucun nouveau signal n'arrive -- WAIT entre deux signaux."""
    empty = {
        "symbol": symbol_key, "signal": "WAIT", "confidence": 0, "eligible": False,
        "reason": "Aucun signal externe recent de Strategy Lab.", "engine": "external_signal",
    }
    data = read_json("external_signal.json", None)
    if not data or data.get("consumed"):
        return empty

    max_age = float(params.get("external_signal_max_age_sec", 180))
    received_at = data.get("received_at")
    age_sec = (time.time() * 1000 - received_at) / 1000 if received_at else max_age + 1
    if age_sec > max_age:
        return {**empty, "reason": f"Signal externe trop ancien ({age_sec:.0f}s), ignore."}

    if data.get("symbol") != symbol_key:
        return {**empty, "reason": f"Signal externe pour {data.get('symbol')}, symbole actif {symbol_key}."}

    action = data.get("action")
    if action not in ("BUY", "SELL"):
        return empty

    # Un seul declenchement par signal recu : on le marque consomme
    # immediatement, y compris si le mode REEL le neutralise plus haut dans
    # status_payload() -- sinon un signal REEL ignore une fois reviendrait
    # WAIT->BUY->WAIT en boucle a chaque tick tant qu'aucun nouveau signal
    # n'arrive, au lieu de rester WAIT proprement.
    write_json("external_signal.json", {**data, "consumed": True})

    confidence = data.get("confidence")
    confidence = float(confidence) if isinstance(confidence, (int, float)) else 100.0
    strategy_name = data.get("strategy_name") or "Strategy Lab"
    # allow_reinforcement : seul reglage que Strategy Lab peut faire varier
    # par signal (Louis, 24/07/2026) -- tout le reste (seuils de confiance,
    # take-profit/break-even, calcul du lot) reste entierement pilote par
    # les reglages globaux existants d'AlphaTrade, pas duplique ici. True
    # par defaut si absent du payload (comportement inchange pour les
    # signaux qui ne le precisent pas).
    allow_reinforcement = bool(data.get("allow_reinforcement", True))
    # entry_price/stop_loss/take_profit sont conserves pour affichage/journalisation
    # uniquement -- la decision d'entree ne fait que choisir la direction
    # (BUY/SELL) ; le lot, le stop-loss et le take-profit reels restent
    # entierement calcules par le pipeline commun existant (lot_info,
    # symbol_params), jamais par la source du signal.
    return {
        "symbol": symbol_key, "signal": action, "confidence": confidence,
        "eligible": True, "engine": "external_signal",
        "reason": f"Signal externe Strategy Lab: {strategy_name} ({confidence:.0f}%).",
        "entry_price": data.get("entry_price"), "stop_loss": data.get("stop_loss"),
        "take_profit": data.get("take_profit"), "allow_reinforcement": allow_reinforcement,
    }


ENGINE_REGISTRY = {
    "alphatrade_ai": {
        "label": "AlphaTrade AI",
        "description": "Moteur historique : EMA, RSI, MACD, momentum, multi-timeframe, mémoire adaptative.",
        "capabilities": {
            "multi_timeframe": True, "ema_rsi_macd": True, "smart_money": False,
            "fibonacci": False, "zones_institutionnelles": False, "ia_locale": True,
            "ia_cloud": True, "memoire": True, "lot_auto": False, "tp_paliers": False, "break_even_reel": False,
        },
    },
    "external_signal": {
        "label": "Strategy Lab (signaux externes)",
        "description": "Decision d'entree pilotee par les signaux BUY/SELL exportes depuis AlphaTrade Strategy Lab. En mode REEL, n'ouvre une position que si \"Accepter les signaux externes en mode reel\" est active dans Parametres.",
        "capabilities": {
            "multi_timeframe": False, "ema_rsi_macd": False, "smart_money": False,
            "fibonacci": False, "zones_institutionnelles": False, "ia_locale": False,
            "ia_cloud": False, "memoire": False, "lot_auto": False, "tp_paliers": False, "break_even_reel": False,
        },
    },
}


def fetch_candles(symbol: str, timeframe: str, limit: int) -> list[dict]:
    """Bougies recentes au format attendu par les modules purs KB2/KB3/KB5
    (open/high/low/close, ordre chronologique). Meme pattern MT5 que
    symbol_analysis() (copy_rates_from_pos). Liste vide si indisponible --
    les agents degradent proprement en UNAVAILABLE plutot que de planter."""
    if mt5 is None:
        return []
    rates = mt5.copy_rates_from_pos(symbol, tf_const(timeframe), 0, limit)
    if rates is None:
        return []
    return [
        {"open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])}
        for r in rates
    ]


def gold_microstructure_snapshot(symbol_names: dict[str, str], params: dict) -> dict:
    """v5.1.1 chantier 2 -- instantane du Gold Microstructure Engine
    (market_microstructure_gold.py) pour l'onglet Microstructure de l'app.
    Distinct de `microstructure.snapshot()` (OBI/Kyle lambda, market_microstructure.py,
    carnet d'ordres crypto/DOM -- indisponible sur XAUUSD, voir l'audit du
    04/08/2026) : ici les bougies XAUUSD elles-memes sont la donnee, toujours
    disponibles via MT5, deja utilisees reellement par scenario_confidence et
    evaluate_scalp_opportunity() (chantier 2) -- ce bloc rend ce calcul visible,
    au lieu de rester invisible derriere le Scenario Engine (demande de Louis,
    05/08/2026 : l'onglet Microstructure existant n'avait pas ete adapte).
    Aucune direction de scenario n'existe forcement a cet instant (ce bloc
    tourne independamment de scenario_engine_enabled) -- calcule donc le score
    pour BUY et SELL, les deux lectures possibles du meme instantane de marche."""
    symbol = symbol_names.get("XAUUSD")
    if not symbol:
        return {"available": False, "reason": "XAUUSD indisponible."}
    timeframe = str(params.get("symbols", {}).get("XAUUSD", {}).get("timeframe", "M5"))
    candles = fetch_candles(symbol, timeframe, 30)
    if len(candles) < 12:
        return {"available": False, "reason": "Pas assez de bougies recentes."}
    buy = gold_microstructure_score(candles, "BUY")
    sell = gold_microstructure_score(candles, "SELL")
    return {
        "available": True,
        "timeframe": timeframe,
        "velocity": buy["velocity"],  # direction-agnostique, identique pour BUY/SELL
        "acceleration": buy["acceleration"],
        "size_trend": buy["size_trend"],
        "buy": {"score": buy["score"], "rejection": buy["rejection"]},
        "sell": {"score": sell["score"], "rejection": sell["rejection"]},
    }


def symbol_analysis(symbol: str, params: dict, symbol_key: str | None = None, learning_state: dict | None = None) -> dict:
    if mt5 is None:
        return {}
    requested_lookback = max(20, int(params.get("lookback_candles", 200)))
    rates = mt5.copy_rates_from_pos(symbol, tf_const(params.get("timeframe", "M5")), 0, max(120, requested_lookback + 60))
    if rates is None or len(rates) < 30:
        return {
            "signal": "WAIT",
            "confidence": 0,
            "score_buy": 0,
            "score_sell": 0,
            "trend": "COLLECTING",
            "rsi": 50,
        }
    closes = [float(row[4]) for row in rates]
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    rv = rsi(closes)
    macd = ema(closes, 12) - ema(closes, 26)
    prev_macd = ema(closes[:-1], 12) - ema(closes[:-1], 26)
    trend = "BULLISH" if e9 > e21 > e50 else "BEARISH" if e9 < e21 < e50 else "RANGE"
    momentum = ((closes[-1] - closes[-5]) / closes[-5] * 10000) if closes[-5] else 0

    learned = (
        (learning_state or {}).get("symbols", {}).get(symbol_key, {})
        if symbol_key
        else {}
    )
    weights = learned.get("weights") or {}
    weight = lambda name: clamp(float(weights.get(name, 1.0)), 0.65, 1.35)
    components = {
        "trend": 1 if e9 > e21 else -1 if e9 < e21 else 0,
        "rsi": 1 if 50 <= rv <= 70 else -1 if 30 <= rv < 50 else 0,
        "macd": 1 if macd > 0 and macd > prev_macd else -1 if macd < 0 and macd < prev_macd else 0,
        "edge": 0,
        "momentum": 1 if momentum > 0 else -1 if momentum < 0 else 0,
    }
    buy = 25.0
    sell = 25.0
    if e9 > e21:
        buy += 18 * weight("trend")
    if e9 < e21:
        sell += 18 * weight("trend")
    if 50 <= rv <= 70:
        buy += 16 * weight("rsi")
    if 30 <= rv <= 50:
        sell += 16 * weight("rsi")
    if macd > 0 and macd > prev_macd:
        buy += 16 * weight("macd")
    if macd < 0 and macd < prev_macd:
        sell += 16 * weight("macd")

    lookback = max(5, min(len(closes), requested_lookback))
    zone = max(1, float(params.get("edge_zone_pct", 20))) / 100
    recent = closes[-lookback:]
    low, high = min(recent), max(recent)
    pos = (closes[-1] - low) / (high - low) if high > low else 0.5
    if pos < 1 - zone:
        buy += 8 * weight("edge")
        components["edge"] = 1
    if pos > zone:
        sell += 8 * weight("edge")
        if components["edge"] == 0:
            components["edge"] = -1
    if momentum > 0:
        buy += min(12, momentum / 3) * weight("momentum")
    if momentum < 0:
        sell += min(12, -momentum / 3) * weight("momentum")

    mtf = multi_timeframe_context(symbol, symbol_key)
    strategy_mode = str(params.get("strategy_mode") or "scalping_fast")
    mtf_bias = str(mtf.get("bias") or "RANGE")
    mtf_weight = 8.0
    if strategy_mode == "long_analysis":
        mtf_weight = 18.0
    elif strategy_mode == "combined":
        mtf_weight = 12.0
    elif strategy_mode in ("scalping_safe", "synthetic_scalp"):
        mtf_weight = 10.0
    if mtf_bias == "BULLISH":
        buy += mtf_weight
    elif mtf_bias == "BEARISH":
        sell += mtf_weight

    buy = round(max(0, min(100, buy)), 1)
    sell = round(max(0, min(100, sell)), 1)
    confidence = max(buy, sell)
    signal = "WAIT"
    learned_threshold = clamp(
        float(params.get("confidence_min", 62)) + float(learned.get("confidence_offset", 0)),
        55,
        82,
    )
    if confidence >= learned_threshold:
        signal = "BUY" if buy > sell else "SELL"
    fast_timeframe = mt5.TIMEFRAME_M5
    fast_rates = mt5.copy_rates_from_pos(symbol, fast_timeframe, 0, 40)
    fast_signal = "WAIT"
    fast_momentum = 0.0
    if fast_rates is not None and len(fast_rates) >= 15:
        fast_closes = [float(row[4]) for row in fast_rates]
        fast_e5 = ema(fast_closes, 5)
        fast_e13 = ema(fast_closes, 13)
        fast_momentum = fast_closes[-1] - fast_closes[-4]
        if fast_e5 > fast_e13 and fast_momentum > 0:
            fast_signal = "BUY"
        elif fast_e5 < fast_e13 and fast_momentum < 0:
            fast_signal = "SELL"
    reversal = candle_reversal_context(rates, round(pos * 100, 1), max(5.0, min(45.0, float(params.get("edge_zone_pct", 20)))), rv)
    score_gap = round(abs(buy - sell), 1)
    mtf_conflict = signal in {"BUY", "SELL"} and mtf_bias in {"BULLISH", "BEARISH"} and (
        (signal == "BUY" and mtf_bias == "BEARISH") or (signal == "SELL" and mtf_bias == "BULLISH")
    )
    regime_risk = 0
    if score_gap < float(params.get("min_score_gap", 8)):
        regime_risk += 30
    if mtf_conflict:
        regime_risk += 35
    if abs(fast_momentum) > max(abs(momentum), 1e-6) * 1.8:
        regime_risk += 20
    if reversal["signal"] not in {"WAIT", signal}:
        regime_risk += 15
    regime_risk = min(100, regime_risk)
    quant_veto = regime_risk >= 85
    quant_signal = "WAIT" if quant_veto else signal
    return {
        "signal": signal,
        "confidence": confidence,
        "score_buy": buy,
        "score_sell": sell,
        "trend": trend,
        "rsi": round(rv, 1),
        "ema9": round(e9, 2),
        "ema21": round(e21, 2),
        "ema50": round(e50, 2),
        "macd": round(macd, 4),
        "momentum": round(momentum, 2),
        "edge_position": round(pos * 100, 1),
        "components": components,
        "learned_threshold": round(learned_threshold, 1),
        "learning_samples": int(learned.get("samples", 0)),
        "learning_weights": {name: round(weight(name), 3) for name in components},
        "fast_signal": fast_signal,
        "fast_momentum": round(fast_momentum, 5),
        "score_gap": score_gap,
        "quant_signal": quant_signal,
        "quant_confidence": round(confidence if not quant_veto else max(0, confidence - regime_risk / 2), 1),
        "quant_regime_risk": regime_risk,
        "quant_veto": quant_veto,
        "quant_reason": "Gouverneur de risque actif" if quant_veto else "Consensus signal, structure et multi-timeframe",
        "strategy_mode": strategy_mode,
        "multi_timeframe_bias": mtf_bias,
        "multi_timeframe_score": mtf.get("score", 0),
        "multi_timeframe": mtf.get("frames", []),
        "support_zone": mtf.get("support_zone", 0),
        "resistance_zone": mtf.get("resistance_zone", 0),
        "reversal_signal": reversal["signal"],
        "reversal_confidence": reversal["confidence"],
        "reversal_reason": reversal["reason"],
    }


def symbol_candles(symbol: str, params: dict, limit: int = 90) -> list[dict]:
    if mt5 is None:
        return []
    rates = mt5.copy_rates_from_pos(symbol, tf_const(params.get("timeframe", "M5")), 0, limit)
    if rates is None:
        return []
    candles = []
    for row in rates:
        candles.append(
            {
                "time": int(row[0]),
                "open": round(float(row[1]), 5),
                "high": round(float(row[2]), 5),
                "low": round(float(row[3]), 5),
                "close": round(float(row[4]), 5),
            }
        )
    return candles


def _origin_rule_result(rule: dict, magic: int) -> dict:
    origin_type = str(rule.get("type") or "EXTERNAL_AI")
    origin = "BOT" if origin_type == "INTERNAL_BOT" else "EXTERNAL_AI"
    return {"origin_name": str(rule.get("name") or "?"), "origin_type": origin_type,
            "origin_magic": magic, "origin": origin}


def trade_origin(magic: int, comment: str = "", params: dict | None = None) -> dict:
    """Identifie l'origine d'un trade MT5 via un registre configurable
    (params["trade_origins"]) au lieu de constantes en dur — priorité au
    magic number exact, puis aux mots-clés du commentaire (certains comptes
    démo ne conservent pas toujours le magic number). Une origine inconnue
    n'est JAMAIS attribuée automatiquement à une origine existante (ex: AVA) :
    elle retourne "Autre EA (magic)", type UNKNOWN. Le champ "origin"
    (BOT/EXTERNAL_AI/MANUAL) est dérivé pour rester strictement compatible
    avec les filtres existants ailleurs dans le moteur (aucun n'est modifié)."""
    normalized = str(comment or "").lower()
    magic = int(magic or 0)
    rules = (params or {}).get("trade_origins") or DEFAULT_PARAMS["trade_origins"]
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if magic and magic in (rule.get("magic_numbers") or []):
            return _origin_rule_result(rule, magic)
        if any(kw in normalized for kw in (rule.get("comment_keywords") or []) if kw):
            return _origin_rule_result(rule, magic)
    if magic == 0:
        return {"origin_name": "Manuel", "origin_type": "MANUAL", "origin_magic": 0, "origin": "MANUAL"}
    return {"origin_name": f"Autre EA ({magic})", "origin_type": "UNKNOWN", "origin_magic": magic, "origin": "EXTERNAL_AI"}


def live_positions(symbol_names: dict[str, str], params: dict | None = None) -> list[dict]:
    if mt5 is None:
        return []
    rows = []
    all_positions = mt5.positions_get()
    if not all_positions:
        return rows
    reverse = {v: k for k, v in symbol_names.items()}
    for p in all_positions:
        key = reverse.get(p.symbol)
        if key is None and "EURUSD" in p.symbol.upper():
            key = "EURUSD"
        if key is None and "XAU" in p.symbol.upper():
            key = "XAUUSD"
        if key is None:
            continue
        origin_info = trade_origin(int(getattr(p, "magic", 0)), str(getattr(p, "comment", "")), params)
        rows.append(
            {
                "ticket": int(p.ticket),
                "symbol_key": key,
                "symbol": p.symbol,
                "direction": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "origin": origin_info["origin"],
                "origin_name": origin_info["origin_name"],
                "origin_type": origin_info["origin_type"],
                "origin_magic": origin_info["origin_magic"],
                "lot": float(p.volume),
                "open_price": float(p.price_open),
                "current_price": float(p.price_current),
                "profit": round(float(p.profit), 2),
                "open_timestamp": int(p.time),
                "open_time": datetime.fromtimestamp(int(p.time)).isoformat(timespec="seconds"),
                "comment": str(getattr(p, "comment", "")),
            }
        )
    return rows


_HISTORY_FULL_RESCAN_STATE: dict[str, float] = {"last": 0.0}


def sync_history(conn: sqlite3.Connection, symbol_names: dict[str, str], params: dict | None = None, days: int = 7) -> list[dict]:
    reverse = {v: k for k, v in symbol_names.items()}

    def legacy_origin_name(origin: str) -> tuple[str, str]:
        """L'historique en base ne stocke que le bucket origin (BOT/EXTERNAL_AI/
        MANUAL), pas le magic number ni le commentaire — impossible de
        distinguer AVA d'un autre EA externe pour ces vieilles lignes. On
        retombe sur le nom du moteur interne (registre) ou un libellé
        générique honnête plutôt que de deviner."""
        rules = (params or {}).get("trade_origins") or DEFAULT_PARAMS["trade_origins"]
        if origin == "BOT":
            bot_rule = next((r for r in rules if r.get("type") == "INTERNAL_BOT"), None)
            return (str(bot_rule["name"]) if bot_rule else "AlphaTrade AI"), "INTERNAL_BOT"
        if origin == "MANUAL":
            return "Manuel", "MANUAL"
        return "IA/EA externe (historique)", "EXTERNAL_AI"

    def from_db() -> list[dict]:
        rows = conn.execute(
            "SELECT id,ticket,position_id,symbol,direction,origin,lot,open_price,open_time,close_price,close_time,profit,status FROM trades ORDER BY close_time DESC LIMIT 500"
        ).fetchall()
        keys = ["id", "ticket", "position_id", "symbol", "direction", "origin", "lot", "open_price", "open_time", "close_price", "close_time", "profit", "status"]
        output = []
        for row in rows:
            item = dict(zip(keys, row))
            item["symbol_key"] = reverse.get(item["symbol"], "EURUSD" if "EURUSD" in item["symbol"].upper() else "XAUUSD" if "XAU" in item["symbol"].upper() else item["symbol"])
            item["move"] = round((item["close_price"] - item["open_price"]) if item["direction"] == "BUY" else (item["open_price"] - item["close_price"]), 2)
            item["origin_name"], item["origin_type"] = legacy_origin_name(str(item.get("origin") or ""))
            item["origin_magic"] = None
            output.append(item)
        return output

    if mt5 is None:
        return from_db()
    # 06/08/2026 -- audit latence MT5<->AlphaTrade (demande explicite de
    # Louis) : cette fonction est appelee toutes les 2s par la boucle
    # principale et rescannait `days` (7) jours COMPLETS de deals MT5 a
    # CHAQUE appel -- l'appel le plus lourd de toute la boucle. La fenetre
    # normale est resserree a quelques heures (tres largement superieure a
    # max_hold_sec, la plus longue duree de maintien reelle d'un trade,
    # quelques dizaines de minutes au pire) pour ne jamais casser
    # l'appariement DEAL_ENTRY_IN/DEAL_ENTRY_OUT d'un trade encore ouvert.
    # Le rescan complet `days` jours ne tourne plus qu'en filet de securite
    # toutes les 15 minutes (horloge/deconnexion MT5/trade tenu anormalement
    # longtemps) -- jamais retire, seulement moins frequent.
    now_ts = time.time()
    full_rescan = (now_ts - _HISTORY_FULL_RESCAN_STATE["last"]) > 900
    start = datetime.now() - (timedelta(days=days) if full_rescan else timedelta(hours=3))
    end = datetime.now() + timedelta(minutes=2)
    deals = mt5.history_deals_get(start, end)
    if full_rescan:
        _HISTORY_FULL_RESCAN_STATE["last"] = now_ts
    if not deals:
        return from_db()
    entries: dict[int, dict] = {}
    exits: dict[int, list] = {}
    for d in deals:
        symbol = getattr(d, "symbol", "")
        key = reverse.get(symbol)
        if key is None and "EURUSD" in symbol.upper():
            key = "EURUSD"
        if key is None and "XAU" in symbol.upper():
            key = "XAUUSD"
        if key is None:
            continue
        entry_type = int(getattr(d, "entry", -1))
        pos_id = int(getattr(d, "position_id", 0) or getattr(d, "order", 0))
        if entry_type == mt5.DEAL_ENTRY_IN:
            origin_info = trade_origin(int(getattr(d, "magic", 0)), str(getattr(d, "comment", "")), params)
            entries[pos_id] = {
                "position_id": pos_id,
                "ticket": int(getattr(d, "ticket", 0)),
                "symbol": symbol,
                "symbol_key": key,
                "direction": "BUY" if int(getattr(d, "type", -1)) == mt5.DEAL_TYPE_BUY else "SELL",
                "origin": origin_info["origin"],
                "origin_name": origin_info["origin_name"],
                "origin_type": origin_info["origin_type"],
                "origin_magic": origin_info["origin_magic"],
                "lot": float(getattr(d, "volume", 0)),
                "open_price": float(getattr(d, "price", 0)),
                "open_time": datetime.fromtimestamp(int(getattr(d, "time", 0))).isoformat(timespec="seconds"),
            }
        elif entry_type in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
            exits.setdefault(pos_id, []).append(d)

    trades = []
    for pos_id, entry in entries.items():
        closed = exits.get(pos_id, [])
        if not closed:
            continue
        close_time = max(int(getattr(d, "time", 0)) for d in closed)
        close_price = float(closed[-1].price)
        profit = sum(float(getattr(d, "profit", 0)) + float(getattr(d, "commission", 0)) + float(getattr(d, "swap", 0)) for d in closed)
        trade = {
            **entry,
            "id": f"MT5-{pos_id}",
            "close_price": close_price,
            "close_time": datetime.fromtimestamp(close_time).isoformat(timespec="seconds"),
            "profit": round(profit, 2),
            "status": "CLOSED",
            "move": round((close_price - entry["open_price"]) if entry["direction"] == "BUY" else (entry["open_price"] - close_price), 2),
        }
        # Calendrier (Dashboard mobile + Calendrier desktop) : sync_history() rescanne
        # jusqu'a `days` jours de deals MT5 a CHAQUE tick (pas un flux d'evenements
        # "nouveau trade"), donc sans ce garde-fou un meme trade serait recompte a
        # chaque re-scan. On ne verifie/enregistre qu'AVANT l'upsert -- si la ligne
        # existe deja, ce trade a deja ete compte dans calendar_data.json.
        already_recorded = conn.execute("SELECT 1 FROM trades WHERE id=?", (trade["id"],)).fetchone()
        if not already_recorded:
            calendar_tracker.record_trade(trade["symbol_key"], trade["profit"])
        conn.execute(
            """
            INSERT OR REPLACE INTO trades
            (id,ticket,position_id,symbol,direction,origin,lot,open_price,open_time,close_price,close_time,profit,status,origin_name,origin_type,origin_magic)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trade["id"],
                trade["ticket"],
                trade["position_id"],
                trade["symbol"],
                trade["direction"],
                trade["origin"],
                trade["lot"],
                trade["open_price"],
                trade["open_time"],
                trade["close_price"],
                trade["close_time"],
                trade["profit"],
                trade["status"],
                trade.get("origin_name"),
                trade.get("origin_type"),
                trade.get("origin_magic"),
            ),
        )
        trades.append(trade)
    conn.commit()

    rows = conn.execute(
        """
        SELECT id,ticket,position_id,symbol,direction,origin,lot,open_price,open_time,close_price,close_time,profit,status,origin_name,origin_type,origin_magic
        FROM trades ORDER BY close_time DESC LIMIT 500
        """
    ).fetchall()
    keys = ["id", "ticket", "position_id", "symbol", "direction", "origin", "lot", "open_price", "open_time", "close_price", "close_time", "profit", "status", "origin_name", "origin_type", "origin_magic"]
    output = []
    for row in rows:
        item = dict(zip(keys, row))
        item["symbol_key"] = reverse.get(item["symbol"], "EURUSD" if "EURUSD" in item["symbol"].upper() else "XAUUSD" if "XAU" in item["symbol"].upper() else item["symbol"])
        item["move"] = round((item["close_price"] - item["open_price"]) if item["direction"] == "BUY" else (item["open_price"] - item["close_price"]), 2)
        # Lignes anterieures a cette migration (ou origine inconnue) : pas de
        # nom precis stocke -- retombe sur le meme repli honnete que
        # from_db() plutot que d'afficher None.
        if not item.get("origin_name"):
            item["origin_name"], item["origin_type"] = legacy_origin_name(str(item.get("origin") or ""))
        output.append(item)
    return output


def stats(trades: list[dict], positions: list[dict]) -> dict:
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    wins = [t for t in closed if float(t.get("profit") or 0) > 0]
    losses = [t for t in closed if float(t.get("profit") or 0) < 0]
    gross_win = sum(float(t["profit"]) for t in wins)
    gross_loss = abs(sum(float(t["profit"]) for t in losses))
    total = gross_win - gross_loss
    winrate = (len(wins) / len(closed) * 100) if closed else 0
    avg_win = gross_win / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    expectancy = (winrate / 100 * avg_win) - ((100 - winrate) / 100 * avg_loss)
    floating = sum(float(p.get("profit") or 0) for p in positions)
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(winrate, 1),
        "profit_closed": round(total, 2),
        "profit_floating": round(floating, 2),
        "profit_live": round(total + floating, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (999 if gross_win else 0),
        "expectancy": round(expectancy, 3),
    }


def utc_trade_day(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return str(value)[:10]


def daily_stats(trades: list[dict], positions: list[dict]) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    today_trades = [t for t in trades if utc_trade_day(t.get("close_time")) == today]
    return stats(today_trades, positions)


def utc_trade_week(value: str | None) -> str:
    """Identifiant semaine ISO (annee-Wxx) pour regrouper close_time -- meme
    conversion UTC que utc_trade_day()."""
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        parsed = parsed.astimezone(timezone.utc)
        iso = parsed.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except (TypeError, ValueError):
        return ""


def utc_trade_month(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc).strftime("%Y-%m")
    except (TypeError, ValueError):
        return ""


def performance_manager_report(trades: list[dict], positions: list[dict], now: datetime | None = None) -> AgentReport:
    """Performance Manager (v5.1.0) -- agent de constat, agrege les resultats
    realises par jour/semaine/mois. Distinct du Trading Mission Manager, qui
    decide des consequences comportementales a partir de ces chiffres.
    Voir Proposition_Technique_MiseEnOeuvre_v5.1.0.html, "Detail technique"."""
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()
    week_id = utc_trade_week(now.isoformat())
    month_id = utc_trade_month(now.isoformat())
    day_trades = [t for t in trades if utc_trade_day(t.get("close_time")) == today]
    week_trades = [t for t in trades if utc_trade_week(t.get("close_time")) == week_id]
    month_trades = [t for t in trades if utc_trade_month(t.get("close_time")) == month_id]
    horizons = {
        "day": stats(day_trades, positions),
        "week": stats(week_trades, positions),
        "month": stats(month_trades, positions),
    }
    return make_agent_report(
        "performance_manager",
        status="OK",
        confidence=100,
        priority="LOW",
        recommendation={"action": "REPORT", "horizons": horizons},
        ttl_seconds=60,
        now=now,
        metadata={"week_id": week_id, "month_id": month_id},
    )


def application_session_stats(trades: list[dict], positions: list[dict], account_login: int | None) -> dict:
    stored = read_json("session_state.json", {}) or {}
    if stored.get("account") != account_login:
        return stats([], [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")])
    started_at = str(stored.get("reset_at") or "")
    if not started_at:
        return stats([], [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")])
    try:
        threshold = datetime.fromisoformat(started_at)
        if threshold.tzinfo is None:
            threshold = threshold.astimezone()
        threshold = threshold.astimezone(timezone.utc)
    except ValueError:
        return stats([], [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")])
    session_trades = []
    for trade in trades:
        closed_at = trade.get("close_time")
        if not closed_at:
            continue
        try:
            closed = datetime.fromisoformat(str(closed_at))
            if closed.tzinfo is None:
                closed = closed.astimezone()
            closed = closed.astimezone(timezone.utc)
        except ValueError:
            continue
        if closed >= threshold and trade.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS"):
            session_trades.append(trade)
    bot_positions = [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    return stats(session_trades, bot_positions)


def session_access(symbol_key: str, symbol_params: dict) -> dict:
    filter_enabled = bool(symbol_params.get("session_filter_enabled", False))
    if not filter_enabled:
        return {
            "state": "OPEN",
            "entries_allowed": True,
            "reason": f"{symbol_key}: trading autorise sans restriction de session.",
        }
    now = datetime.now(timezone.utc)
    start = int(symbol_params.get("session_start_utc", 8))
    end = int(symbol_params.get("session_end_utc", 17))
    stop_before = max(0, int(symbol_params.get("stop_before_end_min", 30)))
    minute = now.hour * 60 + now.minute
    start_minute = start * 60
    end_minute = end * 60
    preclose_minute = max(start_minute, end_minute - stop_before)
    if start_minute <= minute < preclose_minute:
        return {
            "state": "OPEN",
            "entries_allowed": True,
            "reason": f"{symbol_key}: session autorisee {start:02d}h-{end:02d}h UTC.",
        }
    if preclose_minute <= minute < end_minute:
        return {
            "state": "PRECLOSE",
            "entries_allowed": False,
            "reason": f"{symbol_key}: pre-fermeture, nouvelles entrees bloquees.",
        }
    return {
        "state": "CLOSED",
        "entries_allowed": False,
        "reason": f"{symbol_key}: hors session autorisee {start:02d}h-{end:02d}h UTC.",
    }


def reset_session_state(account_login: int | None, current_daily_profit: float) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    stored = read_json("session_state.json", {}) or {}
    same_day = stored.get("date") == today and stored.get("account") == account_login
    payload = {
        "date": today,
        "account": account_login,
        "session_number": int(stored.get("session_number", 1)) + 1 if same_day else 1,
        "session_baseline": round(current_daily_profit, 2),
        # Réinitialiser daily_peak au redémarrage pour débloquer le plancher
        # Le pic repart de zéro à chaque redémarrage
        "daily_peak": round(max(0.0, current_daily_profit), 2),
        "session_locked": False,
        "daily_locked": False,
        "reset_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json("session_state.json", payload)
    return payload


def protection_state(params: dict, daily: dict, account_login: int | None) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    stored = read_json("session_state.json", {}) or {}
    same_session = stored.get("date") == today and stored.get("account") == account_login
    current = float(daily.get("profit_live") or 0)
    # A newly connected account starts from its current daily result. Trades
    # completed before AlphaTrade connected must not complete a fresh session.
    baseline = float(stored.get("session_baseline") or 0) if same_session else current
    session_profit = current - baseline
    daily_peak = max(float(stored.get("daily_peak") or stored.get("peak") or 0), current) if same_session else max(0.0, current)
    enabled = bool(params.get("profit_protection_enabled", True))
    activation = max(0.0, float(params.get("daily_target", 50)) * 0.5)
    pct = max(0.0, float(params.get("profit_drawdown_pct", 30)))
    allowance = daily_peak * pct / 100
    max_allowance = max(0.0, float(params.get("giveback", 100)))
    if max_allowance:
        allowance = min(allowance, max_allowance)
    floor = max(activation, daily_peak - allowance) if daily_peak >= activation else 0.0
    warning_ratio = min(0.95, max(0.1, float(params.get("profit_warning_ratio", 0.75))))
    warning_floor = max(floor, daily_peak - allowance * warning_ratio)
    activated = enabled and daily_peak >= activation
    session_locked = bool(stored.get("session_locked", stored.get("hard_locked", False))) if same_session else False
    daily_locked = bool(stored.get("daily_locked", False)) if same_session else False
    state = "INACTIVE"
    reason = f"Protection journaliere active a partir de +${activation:.2f}."
    # Comparé à session_profit (perte DEPUIS le début de session), pas à
    # current (absolu) — sinon une position déjà ouverte AVANT le
    # redémarrage se retrouve fermée immédiatement au clic Démarrer dès que
    # son flottant dépasse ce seuil, sans avoir eu la moindre chance d'être
    # gérée normalement. Corrigé le 17/07/2026 (demande de Louis : le moteur
    # doit reconnaître une position déjà ouverte et continuer à la gérer).
    if session_profit <= float(params.get("session_max_loss", -150)):
        daily_locked = True
        state = "HARD_LOCK"
        reason = "Perte maximale de la session atteinte."
    elif session_profit >= float(params.get("session_target", 25)):
        session_locked = True
        state = "TARGET_REACHED"
        reason = "Objectif de cette session atteint; nouvelle session requise."
    elif activated and current <= floor:
        daily_locked = True
        state = "HARD_LOCK"
        reason = "Plancher de protection du profit journalier atteint."
    elif daily_locked:
        state = "HARD_LOCK"
        reason = "Journee verrouillee apres declenchement de la protection."
    elif session_locked:
        state = "TARGET_REACHED"
        reason = "Session verrouillee; utilisez Nouvelle session pour reprendre."
    elif activated and current <= warning_floor:
        state = "WARNING"
        reason = "Zone d'avertissement: nouvelles entrees bloquees, observation IA limitee."
    elif activated:
        state = "ARMED"
        reason = "Protection du profit armee."

    payload = {
        "date": today,
        "account": account_login,
        "state": state,
        "reason": reason,
        "enabled": enabled,
        "activated": activated,
        "hard_locked": daily_locked,
        "daily_locked": daily_locked,
        "session_locked": session_locked,
        "session_number": int(stored.get("session_number", 1)) if same_session else 1,
        "reset_at": stored.get("reset_at") if same_session else datetime.now(timezone.utc).isoformat(),
        "session_baseline": round(baseline, 2),
        "session_profit": round(session_profit, 2),
        "current": round(current, 2),
        "peak": round(daily_peak, 2),
        "daily_peak": round(daily_peak, 2),
        "allowance": round(allowance, 2),
        "floor": round(floor, 2),
        "warning_floor": round(warning_floor, 2),
    }
    write_json("session_state.json", payload)
    return payload


def mission_state(
    params: dict,
    trades: list[dict],
    positions: list[dict],
    daily: dict,
    account_login: int | None,
    now: datetime | None = None,
) -> AgentReport:
    """Trading Mission Manager v1 (v5.1.0). Etend protection_state() (jour
    seulement, tout-ou-rien) aux horizons semaine/mois et a un mode gradue.
    Le Risk Manager gere un trade ; celui-ci gere la journee entiere et les
    objectifs semaine/mois. Voir Proposition_Technique_MiseEnOeuvre_v5.1.0.html,
    section "Mission Manager -- ce qu'il publie"."""
    now = now or datetime.now(timezone.utc)
    day_state = protection_state(params, daily, account_login)  # inchangee, reutilisee telle quelle
    perf_report = performance_manager_report(trades, positions, now)
    horizons = perf_report.recommendation["horizons"]
    week_profit = float(horizons["week"]["profit_live"])
    month_profit = float(horizons["month"]["profit_live"])

    daily_target = float(params.get("daily_target", 50))
    weekly_target_configured = float(params.get("mission_weekly_target", 0))
    monthly_target_configured = float(params.get("mission_monthly_target", 0))
    weekly_target = weekly_target_configured or daily_target * 5
    monthly_target = monthly_target_configured or daily_target * 20
    session_max_loss = float(params.get("session_max_loss", -150))
    session_profit = float(day_state["session_profit"])
    daily_ratio = (session_profit / daily_target) if daily_target > 0 else 0.0

    closed_sorted = sorted(
        (t for t in trades if t.get("status") == "CLOSED"),
        key=lambda t: t.get("close_time") or "",
        reverse=True,
    )
    consecutive_losses = 0
    for t in closed_sorted:
        if float(t.get("profit") or 0) < 0:
            consecutive_losses += 1
        else:
            break

    defense_threshold = int(params.get("mission_consecutive_loss_defense", 3))
    if day_state["state"] == "HARD_LOCK" or session_profit <= session_max_loss:
        mode = "Protection"
    elif consecutive_losses >= defense_threshold:
        mode = "Defense"
    elif daily_ratio >= 0.9 or day_state["state"] == "WARNING":
        mode = "Prudent"
    else:
        mode = "Normal"

    if mode in ("Defense", "Protection"):
        psychological_state = "Sous pression"
    elif daily_ratio >= 0.5 and consecutive_losses == 0:
        psychological_state = "Confiant"
    else:
        psychological_state = "Neutre"

    aggressiveness_level = {"Normal": 70, "Prudent": 45, "Defense": 20, "Protection": 0}[mode]
    # Coussin restant avant le plancher dur de session -- budget de risque
    # macro (journee), distinct du budget micro par-trade du Risk Manager.
    risk_appetite = max(0.0, session_profit - session_max_loss)
    new_positions_allowed = mode != "Protection" and day_state["state"] not in ("HARD_LOCK", "TARGET_REACHED")

    priority = {"Normal": "LOW", "Prudent": "MEDIUM", "Defense": "HIGH", "Protection": "CRITICAL"}[mode]
    recommendation = {
        "action": "MISSION_MODE",
        "mode": mode,
        "new_positions_allowed": new_positions_allowed,
    }
    report = make_agent_report(
        "trading_mission_manager",
        status="OK",
        confidence=100,
        priority=priority,
        recommendation=recommendation,
        arguments=[day_state["reason"]],
        ttl_seconds=30,
        now=now,
        metadata={
            "daily_target": daily_target,
            "weekly_target": weekly_target,
            "monthly_target": monthly_target,
            "weekly_target_auto": weekly_target_configured <= 0,
            "monthly_target_auto": monthly_target_configured <= 0,
            "daily_profit": session_profit,
            "weekly_profit": week_profit,
            "monthly_profit": month_profit,
            "psychological_state": psychological_state,
            "aggressiveness_level": aggressiveness_level,
            "risk_appetite": risk_appetite,
            "consecutive_losses": consecutive_losses,
            "day_state": day_state["state"],
        },
    )
    SHARED_MEMORY.write_report("trading_objectives", "trading_mission_manager", report, now=now)
    return report


def lot_safety_state(params: dict, account, symbol_names: dict[str, str]) -> dict:
    """05-06/08/2026 -- lot calcule PUREMENT depuis le capital et le risque
    (capital x risk_pct / distance de stop), exactement comme AlphaTrade
    Global (EA_Bridge/local_functions.py calculate_lot() : risk_amount /
    (sl_distance * contract_size), aucun plafond au-dela du minimum broker)
    -- demande explicite et repetee de Louis : "les parametres manuel ne
    doivent plus du tout impacter ces decisions". L'ancien champ "lot"
    (Paramètres > Renfort & Rebond > "Lot fixe") N'EST PLUS LU ICI.

    06/08/2026 -- `real_lot_cap`/`demo_lot_cap` (carte Securite) retires du
    chemin de decision actif : Louis a explicitement demande de reprendre le
    mecanisme de Global a l'identique ("il calcule de facon automatique...
    regarde le code de Global simplement et applique ce meme mecanisme"),
    et le code de Global n'a aucun plafond de compte. Ces deux parametres
    restent lisibles dans params.json (compat/affichage eventuel) mais
    n'influencent plus jamais `effective_lot`. Seuls des garde-fous
    techniques du broker (lot minimum, pas de volume) subsistent -- ce ne
    sont pas des leviers de decision, juste ce que MT5 accepte."""
    is_demo = bool(account and ("demo" in str(account.server).lower() or int(account.trade_mode) == 0))
    balance = float(account.balance) if account else 0.0
    effective_risk_pct = min(
        max(0.0, float(params.get("risk_pct", 0.35))),
        HARD_RISK_PCT_CAP,
    )
    risk_budget = max(0.0, balance * effective_risk_pct / 100)
    result = {}
    for key, symbol_params in params.get("symbols", {}).items():
        requested_min = max(0.0, float(symbol_params.get("lot_min", 0)))
        name = symbol_names.get(key)
        info = mt5.symbol_info(name) if mt5 and name else None
        tick = mt5.symbol_info_tick(name) if mt5 and name else None
        # Le "Lot minimum" configuré par l'utilisateur doit toujours être
        # respecté, pas seulement en repli quand MT5 est déconnecté — bug
        # trouvé le 16/07/2026 (même défaut que celui déjà corrigé pour
        # KB1000) : avec MT5 connecté, seul le minimum technique du broker
        # (souvent 0.01) était utilisé, ignorant totalement la valeur voulue
        # par l'utilisateur.
        broker_min = max(float(info.volume_min), requested_min) if info else requested_min
        broker_step = float(info.volume_step) if info else broker_min or 0.01
        loss_per_lot = 0.0
        risk_lot_cap = 0.0
        if mt5 and info and tick:
            stop_distance = max(
                float(info.point),
                money_price_distance(
                    name,
                    "BUY",
                    1.0,
                    float(tick.ask),
                    info,
                    float(symbol_params.get("emergency_loss_limit", 3.0)),
                ),
            )
            estimated = mt5.order_calc_profit(
                mt5.ORDER_TYPE_BUY,
                name,
                1.0,
                float(tick.ask),
                float(tick.ask) - stop_distance,
            )
            loss_per_lot = abs(float(estimated or 0))
            if loss_per_lot > 0 and risk_budget > 0:
                risk_lot_cap = risk_budget / loss_per_lot
        # 06/08/2026 -- le lot EST le calcul de risque, plein point. Aucun
        # plafond de compte manuel ne le reduit plus (voir docstring) --
        # seul le pas de volume du broker (arrondi) s'applique encore, ce
        # n'est pas une decision, c'est ce que MT5 accepte comme volume valide.
        effective = risk_lot_cap
        if broker_step > 0:
            effective = math.floor((effective + 1e-12) / broker_step) * broker_step
        effective = round(effective, 8)
        rejected = effective < broker_min or effective <= 0
        result[key] = {
            "broker_min": broker_min,
            "broker_step": broker_step,
            "effective_lot": 0.0 if rejected else effective,
            "risk_budget": round(risk_budget, 2),
            "effective_risk_pct": effective_risk_pct,
            "estimated_loss_per_lot": round(loss_per_lot, 2),
            "risk_lot_cap": round(risk_lot_cap, 8),
            "rejected": rejected,
            "reason": (
                "Lot minimal du broker superieur au lot calcule par le risque (capital insuffisant pour ce risque)."
                if rejected
                else "Lot calcule depuis le capital et le risque (aucun plafond manuel, comme AlphaTrade Global)."
            ),
        }
    return result


def risk_manager_report(
    params: dict, account, symbol_names: dict[str, str], now: datetime | None = None
) -> AgentReport:
    """Risk Manager (v5.1.0) -- formalise lot_safety_state() en AgentReport.
    Determine le risque acceptable pour CE trade precis (en fonction du
    contexte et de l'exposition deja engagee) -- distinct du Trading Mission
    Manager, qui gere la journee entiere. priority CRITICAL des qu'un symbole
    est rejete (lot minimal broker superieur a la limite de securite) : le
    CAIO doit alors bloquer toute entree quelle que soit la confiance des
    autres agents (veto direct, voir caio_decide()).
    Voir Proposition_Technique_MiseEnOeuvre_v5.1.0.html, "Detail technique"."""
    now = now or datetime.now(timezone.utc)
    if account is None:
        report = make_agent_report(
            "risk_manager", status="UNAVAILABLE", confidence=0, priority="CRITICAL",
            recommendation={"action": "RISK_CAP", "lots": {}, "any_rejected": True},
            risks=["Compte MT5 indisponible -- aucun budget de risque calculable."],
            ttl_seconds=15, now=now,
        )
        SHARED_MEMORY.write_report("risk", "risk_manager", report, now=now)
        return report
    lots = lot_safety_state(params, account, symbol_names)
    any_rejected = any(v.get("rejected") for v in lots.values())
    reasons = [f"{key}: {v['reason']}" for key, v in lots.items()]
    report = make_agent_report(
        "risk_manager",
        status="OK",
        confidence=40.0 if any_rejected else 92.0,
        priority="CRITICAL" if any_rejected else "LOW",
        recommendation={"action": "RISK_CAP", "lots": lots, "any_rejected": any_rejected},
        arguments=[] if any_rejected else reasons,
        risks=reasons if any_rejected else [],
        ttl_seconds=30,
        now=now,
    )
    SHARED_MEMORY.write_report("risk", "risk_manager", report, now=now)
    return report


def portfolio_brain_report(params: dict, positions: list[dict], equity: float, now: datetime | None = None) -> AgentReport:
    """Portfolio Brain (v5.1.1, chantier 4) -- formalise l'exposition du
    panier XAUUSD (positions BOT ouvertes simultanement) en AgentReport,
    meme contrat que risk_manager_report(). `positions` : deja filtrees par
    l'appelant sur le symbole actif (voir trading_style_engine_step() pour
    le meme principe de filtrage cote appelant plutot que dans le module pur).
    Ce rapport lui-meme ne ferme et ne bloque rien -- le blocage reel des
    nouvelles entrees (05/08/2026, demande explicite de Louis) est applique
    par status_payload() (pipeline classique) et execute_scenario_anchor()/
    execute_scenario_scalp() (Scenario Engine), tous deux lisant
    protection["portfolio_blocks"]."""
    now = now or datetime.now(timezone.utc)
    exposure = basket_exposure(positions, equity)
    assessment = portfolio_risk_assessment(
        exposure,
        max_positions=int(params.get("portfolio_max_positions", 5)),
        max_total_lot=float(params.get("portfolio_max_total_lot", 0.0) or 0.0),
        floating_loss_warn_pct=float(params.get("portfolio_floating_loss_warn_pct", 2.0)),
        floating_loss_critical_pct=float(params.get("portfolio_floating_loss_critical_pct", 5.0)),
    )
    report = make_agent_report(
        "portfolio_brain",
        status="OK",
        confidence=assessment["confidence"],
        priority=assessment["priority"],
        recommendation={"action": assessment["action"], "exposure": exposure},
        arguments=assessment["reasons"] if assessment["reasons"] else [f"Panier XAUUSD dans les limites ({exposure['position_count']} position(s))."],
        risks=assessment["reasons"],
        ttl_seconds=30,
        now=now,
        metadata={"exposure": exposure},
    )
    SHARED_MEMORY.write_report("portfolio", "portfolio_brain", report, now=now)
    return report


def _unavailable_agent_report(agent: str, compartment: str, reason: str, now: datetime | None = None) -> AgentReport:
    now = now or datetime.now(timezone.utc)
    report = make_agent_report(
        agent, status="UNAVAILABLE", confidence=0, priority="LOW",
        recommendation={"action": "WAIT"}, risks=[reason], ttl_seconds=30, now=now,
    )
    SHARED_MEMORY.write_report(compartment, agent, report, now=now)
    return report


def structure_analyst_report(
    candles: list[dict], current_price: float, timeframe: str = "H1", lookback: int = 2, now: datetime | None = None
) -> AgentReport:
    """Structure Analyst (v5.1.0) -- formalise KB2 (market_structure) + KB3
    (market_zones), deja codes et testes (15/07/2026), en AgentReport. Identifie
    la structure de marche -- zones, supply/demand, regime -- competence
    absente du moteur historique. `candles` : liste chronologique de dicts
    {"high","low"} minimum. Voir Proposition_Technique..., "Detail technique"."""
    now = now or datetime.now(timezone.utc)
    if len(candles) < (2 * lookback + 3):
        return _unavailable_agent_report(
            "structure_analyst", "structures", "Pas assez de bougies pour une structure fiable.", now
        )
    structure = market_structure(candles, lookback)
    zones = market_zones(structure["swings"])
    regime = structure["regime"]

    demand = [z for z in zones["supply_demand"] if z["type"] == "demand" and z["price"] < current_price]
    supply = [z for z in zones["supply_demand"] if z["type"] == "supply" and z["price"] > current_price]
    nearest_demand = min(demand, key=lambda z: current_price - z["price"], default=None)
    nearest_supply = min(supply, key=lambda z: z["price"] - current_price, default=None)

    if regime == "UPTREND" and nearest_demand:
        recommendation = {"action": "BUY_LIMIT", "price": round(nearest_demand["price"], 5)}
        confidence, priority = 82, "MEDIUM"
        arguments = [f"Regime {regime}, zone demand a {nearest_demand['price']:.2f}."]
    elif regime == "DOWNTREND" and nearest_supply:
        recommendation = {"action": "SELL_LIMIT", "price": round(nearest_supply["price"], 5)}
        confidence, priority = 82, "MEDIUM"
        arguments = [f"Regime {regime}, zone supply a {nearest_supply['price']:.2f}."]
    else:
        recommendation = {"action": "WAIT"}
        confidence, priority = 55, "LOW"
        arguments = [f"Regime {regime}, aucune zone exploitable proche du prix."]

    report = make_agent_report(
        "structure_analyst",
        status="OK",
        confidence=confidence,
        priority=priority,
        recommendation=recommendation,
        arguments=arguments,
        ttl_seconds=180,
        now=now,
        metadata={
            "timeframe": timeframe,
            "regime": regime,
            "swing_count": structure["swing_count"],
            "institutional_zones": len(zones["institutional"]),
        },
    )
    SHARED_MEMORY.write_report("structures", "structure_analyst", report, now=now)
    return report


def smart_money_analyst_report(
    candles: list[dict], current_price: float, lookback: int = 2, now: datetime | None = None
) -> AgentReport:
    """Smart Money Analyst (v5.1.0) -- formalise KB5 (market_smart_money),
    deja code et teste (15/07/2026), en AgentReport. Lit l'empreinte
    institutionnelle -- sweeps de liquidite, CHOCH, premium/discount -- pour
    distinguer une vraie cassure d'un piege. Distinct du Structure Analyst :
    celui-ci detecte la structure technique, celui-la en interprete l'intention.
    Voir Proposition_Technique..., "Detail technique"."""
    now = now or datetime.now(timezone.utc)
    if len(candles) < (2 * lookback + 3):
        return _unavailable_agent_report(
            "smart_money_analyst", "smart_money", "Pas assez de bougies pour une lecture fiable.", now
        )
    swings = detect_swings(candles, lookback)
    labeled = classify_swings(swings)
    fvgs = detect_fvg(candles)
    order_blocks = detect_order_blocks(candles)
    bos_choch = detect_bos_choch(labeled)
    liquidity_grabs = detect_liquidity_grabs(candles, swings)
    equal_levels = detect_equal_levels(swings)
    fib = fibonacci_from_swings(swings, current_price=current_price)
    pd = (
        premium_discount(fib["swing_low"], fib["swing_high"], current_price)
        if fib["swing_low"] is not None
        else {"zone": None, "position_pct": None}
    )

    recent_cutoff = max(0, len(candles) - 5)
    recent_grabs = [g for g in liquidity_grabs if g["index"] >= recent_cutoff]
    recent_choch = [e for e in bos_choch if e["type"] == "CHOCH" and e["index"] >= recent_cutoff]

    if recent_grabs:
        g = recent_grabs[-1]
        action = "SELL_LIMIT" if g["type"] == "bearish" else "BUY_LIMIT"
        recommendation = {"action": action, "price": round(g["level"], 5)}
        confidence, priority = 78, "MEDIUM"
        arguments = [f"Sweep de liquidite ({g['type']}) sur {g['level']:.2f} -- biais contraire au balayage."]
        risks: list[str] = []
    elif recent_choch:
        e = recent_choch[-1]
        recommendation = {"action": "WAIT"}
        confidence, priority = 65, "MEDIUM"
        arguments = []
        risks = [f"CHOCH {e['direction']} recent -- changement de biais pas encore confirme."]
    elif pd["zone"] in ("DISCOUNT", "PREMIUM"):
        action = "BUY_LIMIT" if pd["zone"] == "DISCOUNT" else "SELL_LIMIT"
        price = fib["nearest_level"][1] if fib["nearest_level"] else current_price
        recommendation = {"action": action, "price": round(price, 5)}
        confidence, priority = 60, "LOW"
        arguments = [f"Prix en zone {pd['zone']} ({pd['position_pct']}%) du dernier range."]
        risks = []
    else:
        recommendation = {"action": "WAIT"}
        confidence, priority = 50, "LOW"
        arguments = []
        risks = []

    report = make_agent_report(
        "smart_money_analyst",
        status="OK",
        confidence=confidence,
        priority=priority,
        recommendation=recommendation,
        arguments=arguments,
        risks=risks,
        ttl_seconds=180,
        now=now,
        metadata={
            "fvg_count": len(fvgs),
            "order_block_count": len(order_blocks),
            "bos_choch_count": len(bos_choch),
            "equal_highs": len(equal_levels["equal_highs"]),
            "equal_lows": len(equal_levels["equal_lows"]),
            "premium_discount": pd,
        },
    )
    SHARED_MEMORY.write_report("smart_money", "smart_money_analyst", report, now=now)
    return report


def _caio_no_trade(reason: str) -> dict:
    return {"decision": "NO_TRADE", "order_type": None, "price": None, "raison": reason, "overrides": []}


def _direction_of(action: str) -> str | None:
    if action.startswith("BUY"):
        return "BUY"
    if action.startswith("SELL"):
        return "SELL"
    return None


def _apply_entry_policy(action: str, entry_policy: str, overrides: list[str], source_agent: str) -> str:
    """entry_policy est une PREFERENCE, pas un filtre dur (correction de
    Louis, 31/07/2026) : le CAIO peut s'ecarter du mode si le contexte le
    justifie -- pour la v1, chaque ecart reel est journalise dans `overrides`
    (ecrit ensuite dans shared_memory["learning_history"])."""
    if action == "WAIT":
        return action
    if entry_policy == "immediate":
        market_action = "BUY_MARKET" if action.startswith("BUY") else "SELL_MARKET"
        if market_action != action:
            overrides.append(f"entry_policy=immediate: {action} -> {market_action} (source: {source_agent}).")
        return market_action
    if entry_policy == "pending_limit":
        limit_action = "BUY_LIMIT" if action.startswith("BUY") else "SELL_LIMIT"
        if limit_action != action:
            overrides.append(f"entry_policy=pending_limit: {action} -> {limit_action} (source: {source_agent}).")
        return limit_action
    return action  # adaptive : aucune contrainte de type d'ordre


def caio_decide(
    params: dict,
    reports: list[AgentReport],
    mission_report: AgentReport,
    entry_policy: str,
    now: datetime | None = None,
    record: bool = True,
) -> dict:
    """Chief AI Officer v1 (v5.1.0) -- arbitre les rapports de tous les agents
    et rend la decision finale : GO ou NO_TRADE. Ne fait AUCUNE analyse de
    marche lui-meme -- etend server_trade_confirmation() (precedent le plus
    proche), mais compare de vraies hypotheses plutot que des scores nus.
    Pas encore l'arbitrage multi-scenarios complet (Scenario Generator,
    v5.1.1) : un seul candidat retenu par cycle parmi les rapports fournis.

    Regle d'or de l'implementation : aucun agent n'appelle mt5.order_send --
    seul le retour de cette fonction pilote place_order() (Execution Manager).
    Voir Proposition_Technique_MiseEnOeuvre_v5.1.0.html, "Le CAIO arbitre des
    rapports, pas des scores" et "Regle d'or de l'implementation".

    `record=False` : passage d'observation (panneau Gold Brain rafraichi en
    continu meme sans tentative d'entree) -- n'ecrit rien dans
    learning_history, qui ne doit tracer que de vraies tentatives, jamais un
    flux d'arrieres-plan a 2 Hz."""
    now = now or datetime.now(timezone.utc)

    # 1. Priorite CRITICAL d'abord -- une contrainte dure bloque tout,
    # independamment de la confiance des autres agents.
    if not mission_report.recommendation.get("new_positions_allowed", True):
        decision = _caio_no_trade(
            f"Trading Mission Manager: mode {mission_report.recommendation.get('mode')}, "
            "nouvelles positions interdites."
        )
        if record:
            SHARED_MEMORY.write("learning_history", "caio", decision, confidence=100, now=now)
        return decision
    for report in sort_by_priority(reports):
        if report.priority == "CRITICAL" and report.recommendation.get("any_rejected"):
            reason = f"{report.agent}: " + ("; ".join(report.risks) or "risque critique.")
            decision = _caio_no_trade(reason)
            if record:
                SHARED_MEMORY.write("learning_history", "caio", decision, confidence=100, now=now)
            return decision

    # 2. Rapports exploitables : fiables (ni UNAVAILABLE ni perimes) et
    # porteurs d'une recommandation directionnelle (pas WAIT).
    usable = [r for r in reports if r.is_trustworthy(now) and r.recommendation.get("action") != "WAIT"]
    if not usable:
        decision = _caio_no_trade("Aucun agent ne propose de scenario exploitable -- WAIT unanime ou indisponible.")
        if record:
            SHARED_MEMORY.write("learning_history", "caio", decision, confidence=100, now=now)
        return decision

    directions = {_direction_of(r.recommendation["action"]) for r in usable} - {None}
    if len(directions) > 1:
        decision = _caio_no_trade("Contradiction entre agents (directions opposees) -- pas de consensus exploitable.")
        if record:
            SHARED_MEMORY.write("learning_history", "caio", decision, confidence=100, now=now)
        return decision

    # 3. Retient la meilleure hypothese (priorite puis confiance) -- jamais
    # une moyenne de scores.
    ranked = sorted(usable, key=lambda r: (PRIORITY_ORDER.get(r.priority, len(PRIORITY_ORDER)), -r.confidence))
    winner = ranked[0]
    min_confidence = float(params.get("caio_min_confidence", 60.0))
    if winner.confidence < min_confidence:
        decision = _caio_no_trade(
            f"Meilleure hypothese ({winner.agent}, {winner.confidence:.0f}%) sous le seuil de qualite "
            f"({min_confidence:.0f}%) -- le meilleur trade est parfois de ne rien faire."
        )
        if record:
            SHARED_MEMORY.write("learning_history", "caio", decision, confidence=100, now=now)
        return decision

    overrides: list[str] = []
    action = winner.recommendation["action"]
    order_type = _apply_entry_policy(action, entry_policy, overrides, winner.agent)
    decision = {
        "decision": "GO",
        "order_type": order_type,
        "price": winner.recommendation.get("price"),
        "raison": f"{winner.agent}: " + ("; ".join(winner.arguments) or action) + f" (confiance {winner.confidence:.0f}%).",
        "overrides": overrides,
        "source_agent": winner.agent,
    }
    if record:
        SHARED_MEMORY.write("learning_history", "caio", decision, confidence=winner.confidence, now=now)
    return decision


def trading_coach_observe(learning_state: dict, min_samples: int = 10, now: datetime | None = None) -> AgentReport:
    """Trading Coach (v5.1.0) -- observe les resultats sur la duree et
    detecte des motifs. JAMAIS de decision, jamais d'ajustement applique
    directement (c'est le role du Learning Manager). Lit `learning_state`
    (deja alimente par track_position_contexts(), non modifie ici -- lecture
    seule). Jamais de constat base sur un echantillon trop petit."""
    now = now or datetime.now(timezone.utc)
    patterns = []
    for symbol_key, learned in (learning_state.get("symbols") or {}).items():
        samples = int(learned.get("samples", 0))
        if samples < min_samples:
            continue
        winrate = round(int(learned.get("wins", 0)) / samples * 100, 1)
        patterns.append({
            "symbol": symbol_key,
            "samples": samples,
            "winrate": winrate,
            "total_profit": round(float(learned.get("total_profit", 0)), 2),
            "last_outcome": learned.get("last_outcome", ""),
        })
    confidence = 90.0 if patterns else 30.0
    arguments = [
        f"{p['symbol']}: {p['winrate']}% sur {p['samples']} trades (P&L {p['total_profit']})." for p in patterns
    ]
    report = make_agent_report(
        "trading_coach", status="OK", confidence=confidence, priority="LOW",
        recommendation={"action": "OBSERVE", "patterns": patterns},
        arguments=arguments, ttl_seconds=300, now=now,
    )
    SHARED_MEMORY.write("learning_history", "trading_coach", {"type": "observation", **report.to_dict()}, confidence=confidence, now=now)
    return report


def learning_manager_apply(before_state: dict, after_state: dict, now: datetime | None = None) -> AgentReport:
    """Learning Manager (v5.1.0). Ne modifie PAS learning_state lui-meme --
    track_position_contexts() reste la seule fonction qui applique des
    ajustements (deja live-testee) ; approche volontairement prudente, meme
    philosophie que la Phase 3bis (ne pas toucher un mecanisme deja en
    production sans necessite). Compare un avant/apres pour PUBLIER les
    ajustements reellement appliques en AgentReport et verifier que les
    bornes existantes (clamp 0.65-1.35 poids, -4/10 confidence_offset) ont
    tenu -- c'est la formalisation demandee, pas une reecriture du moteur
    d'apprentissage. `priority` monte a MEDIUM si un ajustement depasse ses
    bornes (ne devrait jamais arriver, alerte si observe)."""
    now = now or datetime.now(timezone.utc)
    adjustments = []
    for symbol_key, after in (after_state.get("symbols") or {}).items():
        before = (before_state.get("symbols") or {}).get(symbol_key, {})
        before_weights = before.get("weights", {}) or {}
        after_weights = after.get("weights", {}) or {}
        changed = {k: [before_weights.get(k), v] for k, v in after_weights.items() if before_weights.get(k) != v}
        offset_before = float(before.get("confidence_offset", 0))
        offset_after = float(after.get("confidence_offset", 0))
        if not changed and offset_before == offset_after:
            continue
        in_bounds = all(0.65 <= v <= 1.35 for _, v in changed.values()) and -4 <= offset_after <= 10
        adjustments.append({
            "symbol": symbol_key,
            "weight_changes": changed,
            "confidence_offset_before": offset_before,
            "confidence_offset_after": offset_after,
            "in_bounds": in_bounds,
        })
    priority = "MEDIUM" if any(not a["in_bounds"] for a in adjustments) else "LOW"
    report = make_agent_report(
        "learning_manager", status="OK", confidence=100, priority=priority,
        recommendation={"action": "ADJUSTMENTS_APPLIED", "adjustments": adjustments},
        ttl_seconds=300, now=now,
    )
    SHARED_MEMORY.write("learning_history", "learning_manager", {"type": "adjustment", **report.to_dict()}, confidence=100, now=now)
    return report


def is_demo_account(account) -> bool:
    return bool(account and ("demo" in str(account.server).lower() or int(account.trade_mode) == 0))


def mt5_trading_permission() -> tuple[bool, str]:
    if not mt5:
        return False, "Module MetaTrader 5 indisponible."
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None:
        return False, "Connexion MT5 indisponible."
    if bool(getattr(terminal, "tradeapi_disabled", False)):
        return (
            False,
            "Trading automatique bloque par MT5 (10027). Activez le bouton Trading Algo dans MT5.",
        )
    if not bool(getattr(terminal, "trade_allowed", True)):
        return (
            False,
            "Trading automatique desactive dans MT5. Activez le bouton Trading Algo dans MT5.",
        )
    if not bool(getattr(account, "trade_allowed", True)):
        return False, "Ce compte MT5 n'autorise pas actuellement les operations de trading."
    if not bool(getattr(account, "trade_expert", True)):
        return (
            False,
            "Les Expert Advisors sont interdits sur ce compte. Autorisez le trading algorithmique dans MT5.",
        )
    return True, ""


def load_trading_state() -> dict:
    state = read_json("trading_state.json", {}) or {}
    return {
        "enabled": bool(state.get("enabled", False)),
        "real_confirmed": bool(state.get("real_confirmed", False)),
        "last_entry_at": float(state.get("last_entry_at", 0)),
        "last_attempt_at": float(state.get("last_attempt_at", 0)),
        "entry_times": [float(value) for value in state.get("entry_times", [])],
        "last_action": str(state.get("last_action", "")),
        "last_error": str(state.get("last_error", "")),
        "allowed": bool(state.get("allowed", False)),
        "account_mode": str(state.get("account_mode", "-")),
        "reason": str(state.get("reason", "")),
    }


def save_trading_state(state: dict) -> None:
    write_json("trading_state.json", state)


def position_contexts() -> dict:
    return read_json("position_context.json", {}) or {}


def save_position_contexts(contexts: dict) -> None:
    write_json("position_context.json", contexts)


def track_position_contexts(
    positions: list[dict],
    trades: list[dict],
    analyses: dict,
    learning_state: dict,
) -> dict:
    contexts = position_contexts()
    live_tickets = {
        str(position["ticket"])
        for position in positions
        if position.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
    }
    now_iso = datetime.now(timezone.utc).isoformat()
    for position in positions:
        if position.get("origin", "").upper() not in ("BOT", "ALPHATRADE", "ALPHAKARIS"):
            continue
        ticket = str(position["ticket"])
        context = contexts.get(ticket)
        if not context:
            context = {
                "ticket": int(position["ticket"]),
                "symbol_key": position.get("symbol_key"),
                "direction": position.get("direction"),
                "opened_at": position.get("open_time"),
                "analysis": analyses.get(position.get("symbol_key"), {}),
                "max_profit": float(position.get("profit") or 0),
                "min_profit": float(position.get("profit") or 0),
            }
        profit = float(position.get("profit") or 0)
        context["max_profit"] = round(max(float(context.get("max_profit") or profit), profit), 2)
        context["min_profit"] = round(min(float(context.get("min_profit") or profit), profit), 2)
        context["last_seen_at"] = now_iso
        contexts[ticket] = context

    closed_by_position = {
        str(int(trade.get("position_id") or 0)): trade
        for trade in trades
        if trade.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS") and trade.get("status") == "CLOSED"
    }
    for ticket, context in list(contexts.items()):
        if ticket in live_tickets:
            continue
        trade = closed_by_position.get(ticket)
        if not trade:
            continue
        key = context.get("symbol_key") or trade.get("symbol_key")
        learned = learning_state["symbols"].get(key)
        if not learned:
            contexts.pop(ticket, None)
            continue
        processed = {str(value) for value in learned.get("processed_positions", [])}
        position_id = str(int(trade.get("position_id") or 0))
        if position_id in processed:
            contexts.pop(ticket, None)
            continue
        profit = float(trade.get("profit") or 0)
        reward = clamp(profit / max(0.25, abs(float(context.get("min_profit") or 0)), abs(float(context.get("max_profit") or 0))), -1, 1)
        direction_sign = 1 if context.get("direction") == "BUY" else -1
        features = (context.get("analysis") or {}).get("components") or {}
        weights = learned.get("weights") or {}
        for name in ("trend", "rsi", "macd", "edge", "momentum"):
            stance = int(features.get(name, 0) or 0)
            if stance == 0:
                continue
            alignment = 1 if stance == direction_sign else -1
            delta = 0.025 * reward * alignment
            weights[name] = round(clamp(float(weights.get(name, 1.0)) + delta, 0.65, 1.35), 4)
        learned["weights"] = weights
        samples = int(learned.get("samples", 0)) + 1
        learned["samples"] = samples
        learned["wins"] = int(learned.get("wins", 0)) + (1 if profit > 0 else 0)
        learned["losses"] = int(learned.get("losses", 0)) + (1 if profit < 0 else 0)
        learned["total_profit"] = round(float(learned.get("total_profit", 0)) + profit, 2)
        learned["avg_mfe"] = round(
            ((float(learned.get("avg_mfe", 0)) * (samples - 1)) + max(0, float(context.get("max_profit") or 0))) / samples,
            3,
        )
        learned["avg_mae"] = round(
            ((float(learned.get("avg_mae", 0)) * (samples - 1)) + abs(min(0, float(context.get("min_profit") or 0)))) / samples,
            3,
        )
        offset = float(learned.get("confidence_offset", 0))
        offset += 0.45 if profit < 0 else -0.12
        learned["confidence_offset"] = round(clamp(offset, -4, 10), 2)
        learned["last_outcome"] = "WIN" if profit > 0 else "LOSS" if profit < 0 else "FLAT"
        learned["last_closed_at"] = trade.get("close_time") or now_iso
        learned["processed_positions"] = [*list(processed)[-199:], position_id]
        append_jsonl(
            "learning_events.jsonl",
            {
                "timestamp": now_iso,
                "event": "LEARNING_UPDATE",
                "symbol_key": key,
                "position_id": position_id,
                "profit": profit,
                "max_favorable_excursion": context.get("max_profit", 0),
                "max_adverse_excursion": context.get("min_profit", 0),
                "confidence_offset": learned["confidence_offset"],
                "weights": weights,
            },
        )
        contexts.pop(ticket, None)
    save_position_contexts(contexts)
    save_learning_state(learning_state)
    return contexts


def money_price_distance(symbol: str, direction: str, volume: float, price: float, info, money_target: float) -> float:
    """Calcule la distance de prix (en unités de prix) pour atteindre money_target en profit.
    Utilise order_calc_profit en priorité, puis trade_tick_value/trade_tick_size si le premier
    échoue (cas des indices synthétiques Deriv où order_calc_profit peut retourner None)."""
    point = float(info.point)
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    probe_close = price - point if direction == "BUY" else price + point
    probe = mt5.order_calc_profit(order_type, symbol, volume, price, probe_close)
    loss_per_point = abs(float(probe or 0))
    if loss_per_point <= 0:
        # Fallback: utilise les specs du contrat (fiable pour synthétiques Deriv)
        tick_size = float(getattr(info, "trade_tick_size", 0) or point)
        tick_value = float(getattr(info, "trade_tick_value", 0) or 0)
        if tick_value > 0 and tick_size > 0:
            loss_per_point = volume * tick_value * (point / tick_size)
    if loss_per_point <= 0:
        return max(point, float(getattr(info, "trade_stops_level", 0)) * point)
    points = max(1.0, abs(money_target) / loss_per_point)
    return points * point


def send_deal(request: dict):
    info = mt5.symbol_info(request["symbol"]) if mt5 else None
    fills = []
    if info is not None:
        filling_flags = int(getattr(info, "filling_mode", 0))
        if filling_flags & 1:
            fills.append(mt5.ORDER_FILLING_FOK)
        if filling_flags & 2:
            fills.append(mt5.ORDER_FILLING_IOC)
        if int(getattr(info, "trade_exemode", -1)) != 2:
            fills.append(mt5.ORDER_FILLING_RETURN)
    fills.extend([mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC])
    last_result = None
    for filling in dict.fromkeys(fills):
        attempt = {**request, "type_filling": filling}
        checked = mt5.order_check(attempt)
        if checked is None:
            continue
        last_result = checked
        if int(checked.retcode) == mt5.TRADE_RETCODE_INVALID_FILL:
            continue
        if int(checked.retcode) != 0:
            return checked
        result = mt5.order_send(attempt)
        last_result = result
        if result is not None and int(result.retcode) in {
            mt5.TRADE_RETCODE_DONE,
            mt5.TRADE_RETCODE_DONE_PARTIAL,
            mt5.TRADE_RETCODE_PLACED,
        }:
            return result
        if result is not None and int(result.retcode) != mt5.TRADE_RETCODE_INVALID_FILL:
            break
    return last_result


def open_position(
    symbol_key: str, symbol: str, direction: str, params: dict, lot_info: dict, analysis: dict, allow_real: bool,
    position_type: str = "NORMAL", sl_price: float | None = None, tp_price: float | None = None,
):
    """`sl_price`/`tp_price` (05/08/2026, activation execution reelle du
    Scenario Engine, demande explicite de Louis) : override optionnel pour un
    appelant qui a deja calcule ses propres niveaux (ex: invalidation_price /
    dernier target d'un Scenario) -- le TP fixe du profil classique
    (profit_target/take_profit_levels) n'a pas de sens pour une position dont
    le plan de sortie est deja celui du scenario. None (defaut) preserve tel
    quel le comportement existant du moteur classique -- rien ne change pour
    ses appels."""
    account = mt5.account_info()
    if not account:
        return False, "Compte MT5 indisponible.", None
    if not is_demo_account(account) and not allow_real:
        return False, "Confirmation du compte reel requise.", None
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return False, "Prix ou specification symbole indisponible.", None
    volume = float(lot_info.get("effective_lot") or 0)
    if volume <= 0:
        return False, str(lot_info.get("reason") or "Lot invalide."), None
    symbol_params = params.get("symbols", {}).get(symbol_key, {})
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    price = float(tick.ask if direction == "BUY" else tick.bid)
    point = float(info.point)
    spread_distance = max(0.0, float(tick.ask) - float(tick.bid))
    broker_stop_distance = float(getattr(info, "trade_stops_level", 0)) * point
    min_distance = max(point, broker_stop_distance + spread_distance + (5 * point))
    if sl_price is not None and tp_price is not None:
        # Niveaux fournis par l'appelant (Scenario Engine) -- on respecte
        # quand meme la distance minimale broker pour eviter un rejet MT5,
        # sans recalculer quoi que ce soit d'autre.
        tp = price + max(tp_price - price, min_distance) if direction == "BUY" else price - max(price - tp_price, min_distance)
        sl = price - max(price - sl_price, min_distance) if direction == "BUY" else price + max(sl_price - price, min_distance)
    else:
        if bool(symbol_params.get("take_profit_enabled", False)) and symbol_params.get("take_profit_levels"):
            raw_target = float(symbol_params["take_profit_levels"][-1].get("threshold", 0) or 0)
        else:
            raw_target = float(symbol_params.get("profit_target", 0.50))
        if raw_target <= 0:
            raw_target = float(symbol_params.get("profit_target", 0.50))
        if "confidence" in analysis:
            confidence_ratio = min(1.0, max(0.5, float(analysis["confidence"]) / 100))
            effective_target = raw_target * confidence_ratio
        else:
            effective_target = raw_target
        tp_distance = max(
            min_distance,
            money_price_distance(symbol, direction, volume, price, info, effective_target),
        )
        tp = price + tp_distance if direction == "BUY" else price - tp_distance
        # v5.1.0 — filet de sécurité broker obligatoire (lacune critique de l'audit
        # stratégique du 30/07/2026 : aucun stop-loss n'était jamais posé côté broker).
        # Ancré sur le pire cas déjà toléré par la logique de sortie logicielle
        # (max_position_loss, sinon emergency_loss_limit — voir position_exit_reason())
        # avec une marge de sécurité, pour ne jamais se déclencher avant elle en
        # fonctionnement normal : il ne sert que de dernier recours (crash du process,
        # coupure MT5, gap de prix) là où la protection logicielle n'a pas pu agir.
        protective_limit = abs(float(symbol_params.get("max_position_loss", 0) or 0))
        if protective_limit <= 0:
            protective_limit = abs(float(symbol_params.get("emergency_loss_limit", 50.0)))
        broker_sl_safety_margin = 1.25
        sl_distance = max(
            min_distance,
            money_price_distance(symbol, direction, volume, price, info, protective_limit * broker_sl_safety_margin),
        )
        sl = price - sl_distance if direction == "BUY" else price + sl_distance
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": round(sl, int(info.digits)),
        "tp": round(tp, int(info.digits)),
        "deviation": 30,
        "magic": MAGIC,
        "comment": f"AlphaTrade {VERSION} {position_type}" if position_type != "NORMAL" else f"AlphaTrade {VERSION}",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    started = time.perf_counter()
    result = send_deal(request)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    ok = bool(result is not None and int(result.retcode) in {
        mt5.TRADE_RETCODE_DONE,
        mt5.TRADE_RETCODE_DONE_PARTIAL,
        mt5.TRADE_RETCODE_PLACED,
    })
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "ENTRY",
        "ok": ok,
        "symbol": symbol,
        "symbol_key": symbol_key,
        "direction": direction,
        "volume": volume,
        "price_requested": price,
        "retcode": int(result.retcode) if result is not None else None,
        "comment": str(getattr(result, "comment", "")) if result is not None else str(mt5.last_error()),
        "latency_ms": latency_ms,
        "analysis": analysis,
        "broker_stop_loss": ok,
        "broker_stop_loss_price": round(sl, int(info.digits)) if ok else None,
        "catastrophic_loss_limit": float(symbol_params.get("emergency_loss_limit", 3.0)),
        "profit_target": float(symbol_params.get("profit_target", 0.50)),
    }
    append_jsonl("learning_events.jsonl", event)
    if ok:
        return True, f"{direction} {volume:.3f} {symbol} execute en {latency_ms:.0f} ms.", event
    return False, f"Ordre refuse: {event['retcode']} {event['comment']}", event


# v5.1.0 -- (direction, "LIMIT"/"STOP"/None) par order_type. None = marche
# immediat, delegue a open_position() (deja teste, pas duplique).
ORDER_TYPE_KIND = {
    "BUY_MARKET": ("BUY", None),
    "SELL_MARKET": ("SELL", None),
    "BUY_LIMIT": ("BUY", "LIMIT"),
    "SELL_LIMIT": ("SELL", "LIMIT"),
    "BUY_STOP": ("BUY", "STOP"),
    "SELL_STOP": ("SELL", "STOP"),
}


def place_order(
    symbol_key: str,
    symbol: str,
    order_type: str,
    params: dict,
    lot_info: dict,
    analysis: dict,
    allow_real: bool,
    price_hint: float | None = None,
    position_type: str = "NORMAL",
):
    """Execution Manager (v5.1.0). Regle d'or de l'implementation : SEULE
    fonction autorisee a appeler mt5.order_send pour une ouverture -- aucun
    agent ne decide du type d'ordre ici, il execute fidelement `order_type`
    deja fixe par caio_decide(). Gere les 6 types (Market delegue a
    open_position(), Limit/Stop nouveaux ici). Voir
    Proposition_Technique_MiseEnOeuvre_v5.1.0.html, "Types d'ordre MT5"."""
    if order_type not in ORDER_TYPE_KIND:
        return False, f"Type d'ordre inconnu: {order_type}.", None
    direction, kind = ORDER_TYPE_KIND[order_type]
    if kind is None:
        return open_position(symbol_key, symbol, direction, params, lot_info, analysis, allow_real, position_type)

    account = mt5.account_info()
    if not account:
        return False, "Compte MT5 indisponible.", None
    if not is_demo_account(account) and not allow_real:
        return False, "Confirmation du compte reel requise.", None
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return False, "Prix ou specification symbole indisponible.", None
    volume = float(lot_info.get("effective_lot") or 0)
    if volume <= 0:
        return False, str(lot_info.get("reason") or "Lot invalide."), None
    if not price_hint or price_hint <= 0:
        return False, "Prix requis pour un ordre en attente.", None

    point = float(info.point)
    current = float(tick.ask if direction == "BUY" else tick.bid)
    spread_distance = max(0.0, float(tick.ask) - float(tick.bid))
    broker_stop_distance = float(getattr(info, "trade_stops_level", 0)) * point
    min_distance = max(point, broker_stop_distance + spread_distance + (5 * point))

    # Coherence du prix demande avec le type -- rejet explicite (avec raison
    # lisible) plutot qu'un rejet MT5 opaque si le sens est incoherent.
    if kind == "LIMIT":
        if direction == "BUY" and price_hint >= current - min_distance:
            return False, "Buy Limit doit etre sous le prix courant (distance broker respectee).", None
        if direction == "SELL" and price_hint <= current + min_distance:
            return False, "Sell Limit doit etre au-dessus du prix courant (distance broker respectee).", None
        mt5_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
    else:
        if direction == "BUY" and price_hint <= current + min_distance:
            return False, "Buy Stop doit etre au-dessus du prix courant (distance broker respectee).", None
        if direction == "SELL" and price_hint >= current - min_distance:
            return False, "Sell Stop doit etre sous le prix courant (distance broker respectee).", None
        mt5_type = mt5.ORDER_TYPE_BUY_STOP if direction == "BUY" else mt5.ORDER_TYPE_SELL_STOP

    symbol_params = params.get("symbols", {}).get(symbol_key, {})
    # Meme filet de securite broker que open_position() (voir sa note v5.1.0).
    protective_limit = abs(float(symbol_params.get("max_position_loss", 0) or 0))
    if protective_limit <= 0:
        protective_limit = abs(float(symbol_params.get("emergency_loss_limit", 50.0)))
    sl_distance = max(
        min_distance,
        money_price_distance(symbol, direction, volume, price_hint, info, protective_limit * 1.25),
    )
    sl = price_hint - sl_distance if direction == "BUY" else price_hint + sl_distance

    if bool(symbol_params.get("take_profit_enabled", False)) and symbol_params.get("take_profit_levels"):
        raw_target = float(symbol_params["take_profit_levels"][-1].get("threshold", 0) or 0)
    else:
        raw_target = float(symbol_params.get("profit_target", 0.50))
    if raw_target <= 0:
        raw_target = float(symbol_params.get("profit_target", 0.50))
    tp_distance = max(min_distance, money_price_distance(symbol, direction, volume, price_hint, info, raw_target))
    tp = price_hint + tp_distance if direction == "BUY" else price_hint - tp_distance

    # Un ordre en attente non declenche n'a pas vocation a rester actif
    # indefiniment si le contexte qui l'a justifie a disparu (voir shared
    # memory `valid_until` du rapport qui l'a genere).
    expire_minutes = max(1, int(params.get("pending_order_expire_min", 60)))
    expiration_dt = datetime.now() + timedelta(minutes=expire_minutes)

    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": volume,
        "type": mt5_type,
        "price": round(price_hint, int(info.digits)),
        "sl": round(sl, int(info.digits)),
        "tp": round(tp, int(info.digits)),
        "deviation": 30,
        "magic": MAGIC,
        "comment": f"AlphaTrade {VERSION} {order_type}" if position_type == "NORMAL" else f"AlphaTrade {VERSION} {position_type}",
        "type_time": mt5.ORDER_TIME_SPECIFIED,
        "expiration": int(expiration_dt.timestamp()),
    }
    started = time.perf_counter()
    result = send_deal(request)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    ok = bool(result is not None and int(result.retcode) in {
        mt5.TRADE_RETCODE_DONE,
        mt5.TRADE_RETCODE_DONE_PARTIAL,
        mt5.TRADE_RETCODE_PLACED,
    })
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "PENDING_ORDER",
        "ok": ok,
        "symbol": symbol,
        "symbol_key": symbol_key,
        "order_type": order_type,
        "direction": direction,
        "volume": volume,
        "price_requested": price_hint,
        "sl": round(sl, int(info.digits)),
        "tp": round(tp, int(info.digits)),
        "expiration": expiration_dt.isoformat(),
        "retcode": int(result.retcode) if result is not None else None,
        "comment": str(getattr(result, "comment", "")) if result is not None else str(mt5.last_error()),
        # task #170 (06/08/2026) -- ticket MT5 de l'ordre en attente pose,
        # necessaire au Scenario Engine pour surveiller/annuler cet ordre
        # precis (voir execute_scenario_anchor()/cancel_pending_order()).
        "order_ticket": int(getattr(result, "order", 0) or 0) or None if ok else None,
        "latency_ms": latency_ms,
        "analysis": analysis,
    }
    append_jsonl("learning_events.jsonl", event)
    if ok:
        return True, f"{order_type} {volume:.3f} {symbol} pose a {price_hint:.2f} en {latency_ms:.0f} ms.", event
    return False, f"Ordre refuse: {event['retcode']} {event['comment']}", event


def cancel_pending_order(symbol: str, ticket: int):
    """task #170 (06/08/2026) -- annule un ordre en attente encore non
    declenche (TRADE_ACTION_REMOVE). Utilise quand un scenario ayant pose un
    ordre en attente (anchor_status == "PENDING") atteint un statut terminal
    (INVALIDATED/EXPIRED/COMPLETED) avant declenchement -- meme philosophie
    que _price_beyond_final_target() dans scenario_generator.py : une idee
    perimee ne doit pas rester active a attendre un declenchement qui n'a
    plus de sens, plutot que de compter uniquement sur l'expiration broker
    (pending_order_expire_min, potentiellement jusqu'a 60 min plus tard)."""
    request = {"action": mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
    result = mt5.order_send(request)
    ok = bool(result is not None and int(result.retcode) == mt5.TRADE_RETCODE_DONE)
    if ok:
        return True, f"Ordre en attente {ticket} ({symbol}) annule."
    comment = str(getattr(result, "comment", "")) if result is not None else str(mt5.last_error())
    return False, f"Annulation refusee pour l'ordre {ticket}: {comment}"


def close_bot_position(position: dict, reason: str):
    symbol = position["symbol"]
    ticket = int(position["ticket"])
    now = time.time()
    last_attempt = CLOSE_ATTEMPTS.get(ticket, 0.0)
    if now - last_attempt < 5.0:
        return False, f"Fermeture {ticket} en attente avant nouvelle tentative."
    CLOSE_ATTEMPTS[ticket] = now
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, "Prix indisponible pour fermeture."
    is_buy = position["direction"] == "BUY"
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": symbol,
        "volume": float(position["lot"]),
        "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
        "price": float(tick.bid if is_buy else tick.ask),
        "deviation": 40,
        "magic": MAGIC,
        # Keep the broker comment short. Some MT5 brokers reject long comments
        # before the request reaches the market.
        "comment": "AT close",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    # 06/08/2026 -- monitoring latence (demande explicite de Louis, audit
    # ticket 9748487751 : une position vue a +1.80$ a ete fermee par decision
    # a -2.20$, executee a -4.40$ -- l'ecart entre "profit vu" et "profit
    # execute" vient de la fraicheur du snapshot de positions ET du temps
    # d'aller-retour MT5, mesures ici separement pour la premiere fois.
    snapshot_age_ms = round((time.perf_counter() - _PERF_POSITIONS_SNAPSHOT_AT) * 1000, 1) if _PERF_POSITIONS_SNAPSHOT_AT else None
    started = time.perf_counter()
    result = send_deal(request)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    ok = bool(result is not None and int(result.retcode) in {
        mt5.TRADE_RETCODE_DONE,
        mt5.TRADE_RETCODE_DONE_PARTIAL,
        mt5.TRADE_RETCODE_PLACED,
    })
    append_jsonl(
        "learning_events.jsonl",
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "EXIT",
            "ok": ok,
            "ticket": ticket,
            "symbol": symbol,
            "direction": position["direction"],
            "profit_seen": float(position.get("profit") or 0),
            "reason": reason,
            "retcode": int(result.retcode) if result is not None else None,
            "comment": str(getattr(result, "comment", "")) if result is not None else str(mt5.last_error()),
            "latency_ms": latency_ms,
            "snapshot_age_ms": snapshot_age_ms,
        },
    )
    # Visible dans le Journal (pas seulement dans learning_events.jsonl) des
    # que la latence totale devient significative -- seuil choisi pour ne
    # jamais noyer le Journal en fonctionnement normal (ordre MT5 typique:
    # quelques dizaines de ms), mais remonter tout ce qui pourrait expliquer
    # un ecart profit vu / profit execute comme sur le ticket audite.
    total_ms = (snapshot_age_ms or 0) + latency_ms
    if total_ms >= 150:
        log(
            f"[PERFORMANCE] Fermeture {ticket} ({reason}): snapshot vieux de {snapshot_age_ms}ms"
            f" + ordre MT5 {latency_ms}ms = {round(total_ms, 1)}ms au total.",
            "WARNING",
        )
    if ok:
        CLOSE_ATTEMPTS.pop(ticket, None)
        return True, f"Fermeture {ticket} {reason}: OK."
    detail = str(getattr(result, "comment", "")) if result is not None else str(mt5.last_error())
    retcode = int(result.retcode) if result is not None else None
    return False, f"Fermeture {ticket} {reason}: REFUSEE ({retcode}: {detail})."


def log_trade_exit(
    ticket: int,
    symbol_key: str,
    direction: str,
    open_timestamp: float,
    reason: str,
    profit: float,
    peak_profit: float,
    age: float,
) -> None:
    entry_at = None
    if open_timestamp:
        try:
            entry_at = datetime.fromtimestamp(open_timestamp, tz=timezone.utc).isoformat()
        except Exception:
            pass
    captured_pct = round(profit / peak_profit * 100, 1) if peak_profit > 0 else 0.0
    append_jsonl("trade_exits.jsonl", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticket": ticket,
        "symbol": symbol_key,
        "direction": direction,
        "entry_at": entry_at,
        "age_sec": round(age, 1),
        "reason": reason,
        "profit": round(profit, 2),
        "peak_profit": round(peak_profit, 2),
        "captured_pct": captured_pct,
    })


def take_profit_step(positions: list[dict], params: dict, symbol_names: dict[str, str]) -> None:
    """Clôture partielle progressive selon un tableau explicite de niveaux
    Take Profit (seuil $ / % fermé), défini par l'utilisateur — jusqu'à 6
    niveaux (take_profit_levels). Remplace le 17/07/2026 l'ancien calcul par
    formule (profit_target * palier * 0.25), source de confusion avec le
    "Palier" du trail dynamique (retiré à la même date, voir position_exit_reason).
    Le % de chaque niveau porte sur le lot ENCORE OUVERT au moment où ce
    niveau se déclenche (pas sur le lot initial) — décision explicite de
    Louis le 17/07/2026 : les volumes fermés diminuent à chaque palier
    puisque la base se réduit à chaque clôture partielle précédente."""
    global TAKE_PROFIT_STATE
    bot_positions = [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    open_tickets = {int(p.get("ticket", 0)) for p in bot_positions}
    for t in list(TAKE_PROFIT_STATE.keys()):
        if t not in open_tickets:
            del TAKE_PROFIT_STATE[t]
    for position in bot_positions:
        ticket = int(position.get("ticket", 0))
        if not ticket:
            continue
        symbol_key = position.get("symbol_key", "")
        pos_params = params.get("symbols", {}).get(symbol_key, {})
        if not bool(pos_params.get("take_profit_enabled", False)):
            continue
        levels = pos_params.get("take_profit_levels") or []
        if not levels:
            continue
        profit = float(position.get("profit") or 0)
        current_vol = float(position.get("lot") or 0)
        move_be = bool(pos_params.get("take_profit_move_be", True))
        if ticket not in TAKE_PROFIT_STATE:
            TAKE_PROFIT_STATE[ticket] = {"tp_done": 0, "be_applied": False, "level_peak": 0.0}
        state = TAKE_PROFIT_STATE[ticket]
        tp_done = int(state.get("tp_done", 0))
        if tp_done >= len(levels):
            continue
        next_tp = tp_done + 1
        level = levels[tp_done]
        trigger = float(level.get("threshold", 0) or 0)
        close_pct = max(0.0, min(100.0, float(level.get("pct", 0) or 0))) / 100.0
        if trigger <= 0 or close_pct <= 0:
            continue
        # Trailing par palier (22/07/2026, demande de Louis) : suit le pic de
        # profit atteint AVANT que ce palier ne soit touché (level_peak, remis
        # à zéro à chaque palier franchi — pas le pic de toute la position,
        # qui inclurait les paliers déjà fermés) et ferme le même % que ce
        # palier aurait fermé si le profit retombe de "trailing" $ depuis ce
        # pic, sans attendre le seuil complet. Le Break-Even (BE rapide ou
        # après 1er TP) reste le filet de secours : il ne sert que si aucun
        # trailing n'a été configuré sur ce palier ou si le retournement va
        # plus vite que la vérification (tick suivant).
        level_trailing = max(0.0, float(level.get("trailing", 0) or 0))
        level_peak = max(float(state.get("level_peak", 0) or 0), profit)
        state["level_peak"] = level_peak
        hit_threshold = profit >= trigger
        hit_trailing = (
            level_trailing > 0
            and 0 < level_peak < trigger
            and profit <= level_peak - level_trailing
        )
        if not hit_threshold and not hit_trailing:
            continue
        symbol = symbol_names.get(symbol_key)
        if not symbol:
            continue
        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            continue
        lot_step = float(sym_info.volume_step)
        lot_min = float(sym_info.volume_min)
        raw_vol = current_vol * close_pct
        vol_to_close = round(raw_vol / lot_step) * lot_step
        vol_to_close = max(lot_min, min(vol_to_close, current_vol))
        if vol_to_close < lot_min:
            log(f"[TP{next_tp}] Volume {vol_to_close:.2f} < minimum {lot_min}, TP ignoré.", "WARNING")
            state["tp_done"] = next_tp
            state["level_peak"] = 0.0
            continue
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            continue
        is_buy = position.get("direction") == "BUY"
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": vol_to_close,
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "price": float(tick.bid if is_buy else tick.ask),
            "deviation": 40,
            "magic": MAGIC,
            "comment": f"AT TP{next_tp}",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = mt5.order_send(request)
        ok = result is not None and int(result.retcode) in {
            mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL, mt5.TRADE_RETCODE_PLACED
        }
        if ok:
            state["tp_done"] = next_tp
            state["level_peak"] = 0.0
            trigger_note = "trailing" if hit_trailing and not hit_threshold else f"seuil {trigger:.2f}$"
            log(
                f"[TP{next_tp}/{len(levels)}] Fermeture partielle {int(close_pct*100)}%"
                f" ({vol_to_close:.2f} lot) à +{profit:.2f}$ ({trigger_note}) | {symbol_key}",
                "SUCCESS",
            )
            if next_tp == 1 and move_be and not state.get("be_applied"):
                entry_price = float(position.get("open_price") or 0)
                if entry_price > 0:
                    sl_req = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": ticket,
                        "symbol": symbol,
                        "sl": entry_price,
                        "tp": 0.0,
                    }
                    sl_res = mt5.order_send(sl_req)
                    if sl_res is not None and int(sl_res.retcode) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}:
                        state["be_applied"] = True
                        log(f"[TP1] SL break even appliqué à {entry_price} sur ticket {ticket}", "SUCCESS")
                    else:
                        log(f"[TP1] SL break even refusé: {sl_res}", "WARNING")
        else:
            retcode = int(result.retcode) if result else None
            log(f"[TP{next_tp}] Fermeture partielle refusée ({retcode}) — {symbol_key}", "ERROR")


def fast_breakeven_step(positions: list[dict], params: dict, symbol_names: dict[str, str]) -> None:
    """Sécurise le profit dès que la distance technique minimale autorisée
    par le broker pour un stop (trade_stops_level, en points) est franchie —
    remonte le stop au prix d'entrée (Break-Even réel, broker) immédiatement,
    indépendamment de la clôture partielle par Take Profit (take_profit_step,
    qui n'applique son propre BE qu'après le 1er niveau). Demande de Louis le
    17/07/2026 : sécuriser le minimum de profit techniquement atteignable dès
    que possible, pour limiter les pertes en cas de retournement — avant même
    d'atteindre la cible de profit configurée. S'applique à toute position
    ouverte par le bot, quel que soit le moteur source du signal (pipeline
    de sortie partagé). Le seuil réel inclut aussi le spread courant : un BE
    placé sous le spread se ferait immédiatement toucher par le bruit normal
    du marché."""
    global FAST_BE_STATE
    if mt5 is None or not bool(params.get("fast_be_enabled", True)):
        return
    bot_positions = [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    open_tickets = {int(p.get("ticket", 0)) for p in bot_positions}
    for t in list(FAST_BE_STATE.keys()):
        if t not in open_tickets:
            del FAST_BE_STATE[t]
    for position in bot_positions:
        ticket = int(position.get("ticket", 0))
        if not ticket or FAST_BE_STATE.get(ticket):
            continue
        profit = float(position.get("profit") or 0)
        if profit <= 0:
            continue
        symbol_key = position.get("symbol_key", "")
        symbol = symbol_names.get(symbol_key)
        entry_price = float(position.get("open_price") or 0)
        volume = float(position.get("lot") or 0)
        direction = position.get("direction")
        if not symbol or entry_price <= 0 or volume <= 0 or direction not in ("BUY", "SELL"):
            continue
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            continue
        point = float(info.point)
        spread_distance = max(0.0, float(tick.ask) - float(tick.bid))
        broker_stop_distance = float(getattr(info, "trade_stops_level", 0)) * point
        min_distance = broker_stop_distance + spread_distance + (2 * point)
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        probe_close = entry_price + min_distance if direction == "BUY" else entry_price - min_distance
        estimated = mt5.order_calc_profit(order_type, symbol, volume, entry_price, probe_close)
        min_be_profit = abs(float(estimated or 0))
        if min_be_profit <= 0 or profit < min_be_profit:
            continue
        # Récupère le TP broker actuel pour le préserver — TRADE_ACTION_SLTP
        # exige les deux valeurs, et ce BE rapide ne doit pas annuler la
        # cible de profit déjà posée à l'ouverture.
        raw_pos = mt5.positions_get(ticket=ticket)
        current_tp = float(raw_pos[0].tp) if raw_pos else 0.0
        sl_req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": entry_price,
            "tp": current_tp,
        }
        sl_res = mt5.order_send(sl_req)
        if sl_res is not None and int(sl_res.retcode) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}:
            FAST_BE_STATE[ticket] = True
            log(
                f"[BE RAPIDE] Break-Even appliqué à {entry_price} sur ticket {ticket} "
                f"(profit {profit:.2f}$ >= minimum broker {min_be_profit:.2f}$) — {symbol_key}",
                "SUCCESS",
            )
        else:
            retcode = int(sl_res.retcode) if sl_res else None
            log(f"[BE RAPIDE] Break-Even refusé sur ticket {ticket} ({retcode}) — {symbol_key}", "WARNING")


def profit_trailing_ratchet_step(positions: list[dict], params: dict, symbol_names: dict[str, str]) -> None:
    """05/08/2026 -- demande explicite de Louis, en reaction a un incident
    observe en direct : une position en profit fermee par PROFIT_TRAILING
    (position_exit_reason()) s'est retrouvee negative, parce que la decision
    ET l'ordre de fermeture passent tous deux par ce process Python -- entre
    l'instant ou le giveback est detecte et celui ou l'ordre atteint
    reellement MT5, le prix peut deja avoir bouge davantage, surtout avec un
    profit_trailing_giveback tres serre (ex: 0,10$). La boucle principale
    tourne deja a 100ms (voir commentaire au-dessus de time.sleep(0.1),
    deja abaisse ce jour depuis 500ms) -- la reponse n'est pas une boucle
    encore plus rapide, mais de deplacer la protection cote broker.

    Meme principe que fast_breakeven_step() (deja en prod, meme fichier) :
    des que le pic de profit progresse, on remonte le SL reel de la position
    (TRADE_ACTION_SLTP) pour verrouiller `peak - profit_trailing_giveback`
    directement chez le broker -- son execution ne depend plus d'aucun
    aller-retour reseau vers ce process. PROFIT_TRAILING dans
    position_exit_reason() reste actif en filet de securite (ex: gap de prix
    plus rapide que le SL broker lui-meme), jamais retire ni affaibli.

    Ratchet strict : le SL ne recule jamais (PROFIT_TRAIL_RATCHET_STATE
    memorise le dernier prix applique par ticket), et ne descend jamais sous
    le prix d'entree -- ce mecanisme ne peut jamais transformer un gain
    deja acquis en perte, seulement le securiser plus tot."""
    global PROFIT_TRAIL_RATCHET_STATE
    if mt5 is None:
        return
    bot_positions = [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    open_tickets = {int(p.get("ticket", 0)) for p in bot_positions}
    for t in list(PROFIT_TRAIL_RATCHET_STATE.keys()):
        if t not in open_tickets:
            del PROFIT_TRAIL_RATCHET_STATE[t]
    for position in bot_positions:
        symbol_key = position.get("symbol_key", "")
        pos_params = params.get("symbols", {}).get(symbol_key, {})
        # Meme condition d'activation que PROFIT_TRAILING dans
        # position_exit_reason() -- inerte si Take Profit gere deja la sortie.
        if bool(pos_params.get("take_profit_enabled", False)):
            continue
        trailing_giveback = max(0.0, float(pos_params.get("profit_trailing_giveback", 0) or 0))
        if trailing_giveback <= 0:
            continue
        min_positive_exit = max(0.0, float(pos_params.get("min_positive_exit", 0.05)))
        ticket = int(position.get("ticket", 0))
        profit = float(position.get("profit") or 0)
        if not ticket or profit < min_positive_exit:
            continue
        symbol = symbol_names.get(symbol_key)
        entry_price = float(position.get("open_price") or 0)
        volume = float(position.get("lot") or 0)
        direction = position.get("direction")
        if not symbol or entry_price <= 0 or volume <= 0 or direction not in ("BUY", "SELL"):
            continue
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            continue
        is_buy = direction == "BUY"
        current_price = float(tick.bid if is_buy else tick.ask)
        point = float(info.point)
        # Distance de prix equivalente a "trailing_giveback" $ pour ce volume
        # -- meme technique de sonde que fast_breakeven_step() (order_calc_profit
        # plutot qu'un calcul tick_value/tick_size manuel, pour rester coherent
        # avec le reste du fichier).
        probe_distance = 100 * point
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        probe_price = current_price + probe_distance if is_buy else current_price - probe_distance
        probe_profit = mt5.order_calc_profit(order_type, symbol, volume, current_price, probe_price)
        if not probe_profit:
            continue
        price_per_dollar = probe_distance / abs(float(probe_profit))
        lock_price = (
            current_price - (trailing_giveback * price_per_dollar) if is_buy
            else current_price + (trailing_giveback * price_per_dollar)
        )
        # Ne verrouille jamais en dessous du prix d'entree (ce mecanisme ne
        # doit jamais transformer un gain acquis en perte, seulement le
        # securiser) et ne recule jamais par rapport a un SL deja pousse.
        lock_price = max(lock_price, entry_price) if is_buy else min(lock_price, entry_price)
        last_applied = PROFIT_TRAIL_RATCHET_STATE.get(ticket)
        if last_applied is not None:
            if is_buy and lock_price <= last_applied + point:
                continue
            if not is_buy and lock_price >= last_applied - point:
                continue
        raw_pos = mt5.positions_get(ticket=ticket)
        if not raw_pos:
            continue
        current_sl = float(raw_pos[0].sl or 0)
        current_tp = float(raw_pos[0].tp or 0)
        if current_sl > 0:
            if is_buy and lock_price <= current_sl + point:
                continue
            if not is_buy and lock_price >= current_sl - point:
                continue
        sl_req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": symbol,
            "sl": round(lock_price, int(info.digits)),
            "tp": current_tp,
        }
        sl_res = mt5.order_send(sl_req)
        if sl_res is not None and int(sl_res.retcode) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}:
            PROFIT_TRAIL_RATCHET_STATE[ticket] = lock_price
            log(
                f"[TRAILING SL] Stop remonté à {lock_price:.5g} sur ticket {ticket} "
                f"(profit {profit:.2f}$, giveback protégé {trailing_giveback}$) — {symbol_key}",
                "SUCCESS",
            )


def position_exit_reason(
    position: dict,
    pos_params: dict,
    position_analysis: dict,
    protection_state_name: str,
    session_state_name: str,
    peak: float,
    age: float,
) -> str:
    profit = float(position.get("profit") or 0)
    review_sec = max(30, int(pos_params.get("position_review_sec", 120)))
    opposite = "SELL" if position.get("direction") == "BUY" else "BUY"
    threshold = float(position_analysis.get("learned_threshold") or pos_params.get("confidence_min", 62))
    reversal = (
        position_analysis.get("signal") == opposite
        and float(position_analysis.get("confidence") or 0)
        >= threshold + float(pos_params.get("signal_reversal_margin", 7))
    )
    rebond_enabled = bool(pos_params.get("rebond_enabled", False))
    max_position_loss = float(pos_params.get("max_position_loss", 0) or 0)

    # Protection catastrophe sur retournement de signal — vérifiée AVANT le
    # plafond brutal (MAX_POSITION_LOSS) pour qu'elle ait réellement une
    # chance d'agir. Correctif du 17/07/2026 : avant, réglée au même montant
    # que max_position_loss (checké juste après, sans condition), elle
    # n'avait jamais l'occasion de se déclencher — le plafond aveugle gagnait
    # toujours la course puisqu'il ne demande rien d'autre que le montant.
    # Son seuil est désormais plafonné à celui du plafond brutal, jamais
    # au-delà, pour ne jamais dépasser le pire cas déjà accepté par ailleurs.
    if not rebond_enabled and age >= review_sec and reversal:
        catastrophic_limit = abs(float(pos_params.get("emergency_loss_limit", 3.0)))
        if max_position_loss > 0:
            catastrophic_limit = min(catastrophic_limit, abs(max_position_loss))
        if profit <= -catastrophic_limit:
            return "CATASTROPHIC_PROTECTION"

    # Protection individuelle par position — max_position_loss, indépendante
    # de l'âge de la position ou d'un signal inversé (filet de sécurité absolu).
    if max_position_loss > 0 and profit <= -abs(max_position_loss):
        return "MAX_POSITION_LOSS"

    # Time stop (02/08/2026, audit statistique 500 trades) -- avant ce
    # correctif, max_hold_sec ne fermait JAMAIS une position perdante : il
    # n'etait verifie que dans la branche TARGET plus bas, qui exige en plus
    # profit >= profit_target. Deux positions du 22/07 sont restees ouvertes
    # 127h (profil scalping, duree mediane 44s) avant d'etre stoppees en
    # catastrophe (-516$ a elles seules) faute de filet de securite base sur
    # le temps pour une position en perte. Ce filet est desormais reellement
    # universel (independant de rebond_enabled/take_profit_enabled), comme
    # l'annonce deja l'infobulle "Max hold (s)" dans Parametres.
    max_hold_sec = int(pos_params.get("max_hold_sec", 3600) or 0)
    if max_hold_sec > 0 and age >= max_hold_sec and profit < 0:
        return "TIME_STOP"

    # Reaching the session target stops new entries, but must not liquidate
    # positions that were already open. Only a critical hard lock may force
    # an immediate protection exit.
    if protection_state_name == "HARD_LOCK":
        return "PROTECTION"
    if session_state_name in {"PRECLOSE", "CLOSED"}:
        return "SESSION"
    # 06/08/2026 -- "phase naissance du trade" (demande de Louis, audit ticket
    # 9748487751 : PROFIT_TRAILING a ferme a -2.20$ un trade ne 1.7 seconde
    # plus tot, execute a -4.40$ apres la latence MT5 -- la position n'a
    # jamais eu le temps de "respirer"). Pendant les premieres
    # trade_birth_phase_sec, aucune sortie basee sur un mouvement de prix
    # instantane (MOMENTUM_EXIT, PROFIT_TRAILING plus bas) n'est autorisee --
    # seuls les filets de securite independants du temps restent actifs
    # (MAX_POSITION_LOSS et CATASTROPHIC_PROTECTION deja verifies plus haut,
    # stop broker gere separement par open_position()/profit_trailing_ratchet_step()).
    # Ce n'est pas un delai avant toute protection : c'est un delai avant
    # qu'une DECISION PYTHON puisse fermer au marche.
    in_birth_phase = age < max(0.0, float(pos_params.get("trade_birth_phase_sec", 5.0)))
    min_positive_exit = max(0.0, float(pos_params.get("min_positive_exit", 0.05)))
    # Sortie sur perte de momentum — actif même quand rebond_enabled=True
    momentum_exit_score = float(pos_params.get("momentum_exit_score", 0))
    if not in_birth_phase and momentum_exit_score > 0 and profit >= min_positive_exit:
        opp_key = "score_sell" if position.get("direction") == "BUY" else "score_buy"
        if float(position_analysis.get(opp_key, 0)) >= momentum_exit_score:
            return "MOMENTUM_EXIT"
    # Si le module Capture Rebond est actif, on ne ferme JAMAIS sur signal inversé
    # positif ici — la position principale reste ouverte, le rebond est géré
    # par auto_rebond_step (la protection catastrophe équivalente côté perte
    # est déjà vérifiée plus haut, avant le plafond brutal).
    if not rebond_enabled:
        if age >= review_sec and reversal and profit >= min_positive_exit:
            return "SIGNAL_REVERSED_POSITIVE"
    # Fermeture sur profit cible atteint — seulement si Take Profit est
    # désactivé (sinon les niveaux Take Profit gèrent seuls la sortie sur
    # profit, cf. carte "Cible profit & Protection" : "Cible profit $" ne
    # sert de cible broker que si Take Profit est désactivé).
    if not bool(pos_params.get("take_profit_enabled", False)):
        # Trailing de la cible de profit (22/07/2026, demande de Louis) : sans
        # cela, une position qui devient positive sans jamais atteindre
        # "Cible profit $" continue de courir jusqu'au retournement complet,
        # rien ne la ferme entre-temps. Dès que le pic (peak, position entière)
        # a dépassé "Profit min. sortie $", on suit ce pic ; si le profit
        # retombe de "profit_trailing_giveback" $ depuis ce pic, on ferme
        # immédiatement — sans attendre max_hold_sec, contrairement à TARGET
        # ci-dessous, puisqu'il s'agit ici de sécuriser un profit déjà acquis,
        # pas d'attendre que la cible complète soit atteinte.
        trailing_giveback = max(0.0, float(pos_params.get("profit_trailing_giveback", 0) or 0))
        if not in_birth_phase and trailing_giveback > 0 and peak >= min_positive_exit and profit <= peak - trailing_giveback:
            return "PROFIT_TRAILING"
        if age >= max(review_sec, int(pos_params.get("max_hold_sec", 45))) and profit >= float(
            pos_params.get("profit_target", 0.50)
        ):
            return "TARGET"
    return ""


# ── Fonctions du module Capture Rebond ────────────────────────────────────────
# Refonte du 17/07/2026 : le déclenchement se base désormais sur la perte en
# cours de la position principale + un retracement en temps réel
# (should_open_rebond), plus sur une zone S&D préexistante — voir le
# docstring de should_open_rebond() pour le détail de ce changement.


def rebond_lot(main_lot: float, params: dict, is_demo: bool, tier: str = "normal") -> float:
    """Calcule le lot du rebond : lot principal × multiplicateur (configurable,
    different pour le palier Fort). 06/08/2026 -- plus de plafond de compte
    manuel (demo_lot_cap/real_lot_cap) ici : retire du chemin de decision
    actif partout, meme mecanisme que lot_safety_state() (voir sa docstring)
    -- comme AlphaTrade Global, seul le calcul de risque decide."""
    sym_params = params.get("symbols", {}).get("XAUUSD", {})
    lot_min = float(sym_params.get("lot_min", 0.01))
    mult_key = "lot_multiplicateur_rebond_fort" if tier == "fort" else "lot_multiplicateur_rebond"
    mult_rebond = float(sym_params.get(mult_key, 1.0))
    lot = main_lot * max(0.0, mult_rebond)
    lot = max(lot_min, lot)
    # Arrondir au step 0.01
    lot = round(round(lot / 0.01) * 0.01, 3)
    return lot


def should_open_rebond(
    symbol_key: str,
    symbol: str,
    positions: list[dict],
    analysis: dict,
    params: dict,
) -> tuple[bool, str, dict | None]:
    """Décide si on doit ouvrir une position contra-tendance de rebond.

    Refonte du 17/07/2026 (demande de Louis, suite à l'incident où des
    positions plongeaient fortement sans qu'aucun rebond ne se déclenche) :
    la décision se base désormais sur la PERTE EN COURS de la position
    principale et un retracement détecté en temps réel (score contra/RSI
    extrême, déjà des indicateurs instantanés) — plus sur une zone
    offre/demande préexistante. L'ancienne exigence de zone échouait
    précisément pendant les mouvements frais et rapides, exactement quand un
    rebond est le plus nécessaire (le niveau opposé n'a pas encore eu le
    temps de se former). Objectif explicite : entrer vite pour capter le
    retracement qui se forme, puis fermer rapidement (voir
    check_close_rebond, cible/stop/durée max, inchangé).
    Retourne (ok, raison, info_rebond_ou_None)."""
    global REBOND_STATES, REBOND_META
    rebond_max = int(params.get("rebond_max_active", 3))
    sym_rebond_count = sum(1 for s in REBOND_STATES if s.get("symbol_key") == symbol_key)
    if sym_rebond_count >= rebond_max:
        return False, f"Maximum {rebond_max} rebonds simultanés actifs sur {symbol_key}.", None
    cooldown = float(params.get("rebond_cooldown_sec", 60))
    sym_meta = REBOND_META.get(symbol_key, {"last_rebond_at": 0.0})
    if time.time() - float(sym_meta.get("last_rebond_at", 0)) < cooldown:
        return False, "Cooldown rebond en cours.", None
    # Chercher une position principale ouverte par le bot (exclure les rebonds
    # ET les positions issues d'un signal Strategy Lab -- Louis, 24/07/2026 :
    # AlphaTrade ne doit jamais ouvrir de position inverse contre un signal
    # que l'utilisateur a lui-meme choisi de suivre. Seule cette exclusion
    # cible le Rebond ; le Renfort et le verrou directionnel restent
    # inchanges (origin reste "BOT" pour ces positions partout ailleurs).
    rebond_t_check = {int(s.get("ticket") or 0) for s in REBOND_STATES}
    bot_positions = [p for p in positions if p.get("symbol_key") == symbol_key
                     and p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
                     and p.get("origin_name") != "Strategy Lab"
                     and int(p.get("ticket", 0)) not in rebond_t_check]
    if not bot_positions:
        return False, "Aucune position principale ouverte (rebond promu — pas de nouveau rebond).", None
    main_pos = bot_positions[0]
    main_dir = str(main_pos.get("direction", ""))
    if main_dir not in ("BUY", "SELL"):
        return False, "Direction principale inconnue.", None
    # Se baser sur la perte EN COURS de la position principale — avant cette
    # refonte, rien ne liait le déclenchement du rebond au P&L réel de la
    # position qu'il est censé aider.
    main_profit = float(main_pos.get("profit") or 0)
    min_loss_trigger = abs(float(params.get("rebond_min_loss_trigger", 2.0)))
    if main_profit > -min_loss_trigger:
        return False, f"Position principale pas encore assez en perte ({main_profit:.2f}$ < seuil {min_loss_trigger:.2f}$).", None
    # La contra-direction est l'opposé de la position principale
    contra_dir = "BUY" if main_dir == "SELL" else "SELL"
    # Vérifier que l'analyse multi-TF confirme un rebond contra probable
    score_buy = float(analysis.get("score_buy", 0))
    score_sell = float(analysis.get("score_sell", 0))
    rsi_val = float(analysis.get("rsi", 50))
    main_score = score_sell if contra_dir == "BUY" else score_buy
    if contra_dir == "BUY":
        contra_score = score_buy
        rsi_ok = rsi_val <= 35
    else:
        contra_score = score_sell
        rsi_ok = rsi_val >= 65

    tier = "normal"
    if main_score >= 85:
        # Rebond normal (scalp 1-2 points) est volontairement desactive
        # quand la tendance principale est forte -- c'est justement le cas
        # d'un mouvement soutenu (ex: incident du 23/07/2026, 4160->4020)
        # ou aucune contre-position ne se declenchait jamais. Rebond Fort
        # est le seul palier qui peut encore s'ouvrir ici, avec une barre de
        # confiance beaucoup plus haute et un plafond d'essais par position
        # perdante (pas de "doublage" repete).
        if not bool(params.get("rebond_fort_enabled", False)):
            return False, f"Signal principal trop fort ({main_score:.0f}%) — Rebond normal desactive, Rebond Fort non active.", None
        fort_threshold = float(params.get("rebond_fort_min_signal_pct", 80))
        if contra_score < fort_threshold:
            return False, f"Signal principal fort ({main_score:.0f}%) — signal contra ({contra_score:.0f}%) sous le seuil Rebond Fort ({fort_threshold:.0f}%).", None
        main_ticket = int(main_pos.get("ticket", 0))
        fort_state = REBOND_META.setdefault(symbol_key, {}).setdefault("fort_attempts", {"main_ticket": None, "count": 0})
        if fort_state.get("main_ticket") != main_ticket:
            fort_state["main_ticket"] = main_ticket
            fort_state["count"] = 0
        max_attempts = int(params.get("rebond_fort_max_attempts", 1))
        if fort_state["count"] >= max_attempts:
            return False, f"Rebond Fort: {max_attempts} tentative(s) deja utilisee(s) pour cette position perdante.", None
        tier = "fort"
    else:
        min_signal_pct = float(params.get("rebond_min_signal_pct", 55))
        if contra_score < min_signal_pct and not rsi_ok:
            reason_reject = f"Signal contra ({contra_score:.0f}%) insuffisant et RSI non extrême — rebond refusé."
            append_jsonl("rebond_log.jsonl", {
                "ts": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol_key, "result": "REJECTED", "reason": reason_reject,
                "contra_score": round(contra_score, 1), "rsi": round(rsi_val, 1),
                "main_score": round(main_score, 1), "rsi_ok": rsi_ok,
                "main_profit": round(main_profit, 2),
            })
            return False, reason_reject, None

    # Obtenir le prix actuel via le nom MT5 résolu
    tick = mt5.symbol_info_tick(symbol) if mt5 else None
    if tick is None:
        return False, "Prix actuel indisponible.", None
    current_price = float(tick.bid if contra_dir == "SELL" else tick.ask)
    # Cible calculée en temps réel (distance fixe configurable, differente
    # par palier) — plus d'attente d'une ancienne zone S&D : on vise à
    # capter le retracement en cours, pas un niveau structurel lointain.
    target_key = "rebond_fort_target_pips" if tier == "fort" else "rebond_target_pips"
    target_default = 15.0 if tier == "fort" else 1.50
    target_pips = max(0.10, float(params.get(target_key, target_default)))
    target = current_price + target_pips if contra_dir == "BUY" else current_price - target_pips
    if tier == "fort":
        fort_state["count"] += 1
    append_jsonl("rebond_log.jsonl", {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol_key, "result": "OK", "tier": tier,
        "reason": "Rebond autorisé (perte en cours + retracement détecté).",
        "contra_score": round(contra_score, 1), "rsi": round(rsi_val, 1),
        "main_score": round(main_score, 1), "rsi_ok": rsi_ok,
        "main_profit": round(main_profit, 2), "contra_dir": contra_dir,
        "target_price": round(target, 5),
    })
    return True, "Rebond autorisé." if tier == "normal" else "Rebond Fort autorisé.", {
        "direction": contra_dir,
        "target_price": target,
        "current_price": current_price,
        "tier": tier,
    }


def check_close_rebond(symbol: str, rebond_state: dict, params: dict) -> tuple[bool, str]:
    """Vérifie si une position de rebond doit être fermée.
    Conditions: prix proche de la cible, stop atteint, ou durée maximale."""
    if not rebond_state.get("ticket"):
        return False, ""
    if mt5 is None:
        return False, ""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False, ""
    now = time.time()
    direction = str(rebond_state.get("direction", ""))
    target = float(rebond_state.get("target_price", 0))
    open_price = float(rebond_state.get("open_price", 0))
    current = float(tick.bid if direction == "BUY" else tick.ask)
    age = now - float(rebond_state.get("opened_at", now))
    tier = rebond_state.get("tier", "normal")
    if tier == "fort":
        max_hold = float(params.get("rebond_fort_max_hold_sec", 900))
        stop_pts = float(params.get("rebond_fort_stop_pips", 8.00))
    else:
        max_hold = float(params.get("rebond_max_hold_sec", 90))
        stop_pts = float(params.get("rebond_stop_pips", 2.00))
    if direction == "BUY" and current >= target:
        return True, "Cible rebond atteinte (résistance approchée)."
    if direction == "SELL" and current <= target:
        return True, "Cible rebond atteinte (support approché)."
    if direction == "BUY" and current < open_price - stop_pts:
        return True, "Stop rebond: prix retourné contre le BUY contra."
    if direction == "SELL" and current > open_price + stop_pts:
        return True, "Stop rebond: prix retourné contre le SELL contra."
    if age >= max_hold:
        return True, f"Durée maximale rebond atteinte ({max_hold:.0f}s)."
    return False, ""


def auto_rebond_step(
    params: dict,
    symbol_key: str,
    symbol: str,
    positions: list[dict],
    analysis: dict,
    allow_real: bool,
    is_demo: bool,
    main_lot: float = 0.0,
) -> dict:
    """Étape principale du module Capture Rebond (multi-rebond).
    `main_lot` (05/08/2026) : effective_lot deja calcule par lot_safety_state()
    pour la position principale (voir auto_trade_step(), payload["lot_safety"]) --
    plus jamais lu depuis symbols.<key>.lot (retire, demande explicite de
    Louis : les parametres manuel ne doivent plus impacter les decisions).
    Gère jusqu'à rebond_max_active rebonds simultanés."""
    global REBOND_STATES, REBOND_META
    rebond_enabled = bool(params.get("rebond_enabled", False))
    if not rebond_enabled:
        return {"rebond_active": False, "reason": "Module Capture Rebond désactivé."}

    bot_flag_r = {"BOT", "ALPHATRADE", "ALPHAKARIS"}

    # ── Récupération après redémarrage ─────────────────────────────────────────
    known_tickets = {s.get("ticket") for s in REBOND_STATES}
    for p in positions:
        if (p.get("symbol_key") == symbol_key
                and p.get("origin", "").upper() in bot_flag_r
                and "REBOND" in str(p.get("comment", "")).upper()
                and int(p.get("ticket", 0)) not in known_tickets):
            ticket = int(p["ticket"])
            REBOND_STATES.append({
                "ticket": ticket,
                "direction": p.get("direction"),
                "main_direction": "BUY" if p.get("direction") == "SELL" else "SELL",
                "open_price": float(p.get("open_price", 0)),
                "target_price": 0.0,
                "lot": float(p.get("lot", 0)),
                "opened_at": float(p.get("open_timestamp", time.time())),
            })
            log(f"[REBOND] État restauré après redémarrage — ticket #{ticket}", "INFO")

    # ── 1. Fermeture des rebonds actifs ────────────────────────────────────────
    # Promotion: quand plus aucune position normale active, le rebond passe en mode position normale
    all_rebond_t = {int(s.get("ticket") or 0) for s in REBOND_STATES}
    drift_t = 0
    normal_count = sum(
        1 for p in positions
        if p.get("symbol_key") == symbol_key
        and p.get("origin", "").upper() in bot_flag_r
        and int(p.get("ticket", 0)) not in all_rebond_t
        and int(p.get("ticket", 0)) != drift_t
    )
    promoted = (normal_count == 0 and len(REBOND_STATES) > 0)

    still_active = []
    for rs in REBOND_STATES:
        ticket = int(rs.get("ticket") or 0)
        rebond_pos = next((p for p in positions if int(p.get("ticket", 0)) == ticket), None)

        # Mise à jour du peak (pour profit_lock si promu)
        if rebond_pos:
            curr_profit = float(rebond_pos.get("profit", 0))
            rs["peak_profit"] = max(float(rs.get("peak_profit", 0)), curr_profit)

        if promoted and rebond_pos:
            # Promu en position normale: cible profit (pos_params.profit_target,
            # partagée) + stop de sécurité uniquement. Refonte du 17/07/2026 :
            # l'ancien trailing par paliers est retiré (Palier n'existe plus),
            # la cible de profit gère déjà la sortie sur profit — cf. demande
            # de Louis, "on a déjà la cible de profit qui gère cela".
            if not rs.get("promoted"):
                rs["promoted"] = True
                log(f"[REBOND] Ticket #{ticket} promu en position normale (cible profit active).", "INFO")
            curr_profit = float(rebond_pos.get("profit", 0))
            sym_params_r = params.get("symbols", {}).get(symbol_key, {})
            promoted_target = float(sym_params_r.get("profit_target", 0.0) or 0)
            should_close, close_reason = False, ""
            if promoted_target > 0 and curr_profit >= promoted_target:
                should_close = True
                close_reason = f"Rebond promu — cible profit atteinte (+{curr_profit:.2f}$)"
            elif mt5:
                tick_r = mt5.symbol_info_tick(symbol)
                if tick_r:
                    direction_r = str(rs.get("direction", ""))
                    open_price_r = float(rs.get("open_price", 0))
                    stop_pts_r = float(params.get("rebond_stop_pips", 2.00))
                    cur_r = float(tick_r.bid if direction_r == "BUY" else tick_r.ask)
                    if direction_r == "BUY" and cur_r < open_price_r - stop_pts_r:
                        should_close, close_reason = True, "Rebond promu — stop sécurité."
                    elif direction_r == "SELL" and cur_r > open_price_r + stop_pts_r:
                        should_close, close_reason = True, "Rebond promu — stop sécurité."
        else:
            should_close, close_reason = check_close_rebond(symbol, rs, params)

        if should_close:
            if rebond_pos is None:
                rebond_pos = next((p for p in positions if int(p.get("ticket", 0)) == ticket), None)
            if rebond_pos:
                rebond_profit = float(rebond_pos.get("profit", 0))
                ok, msg = close_bot_position(rebond_pos, f"REBOND_{close_reason[:20]}")
                if ok:
                    log(f"[REBOND] Fermé ticket #{ticket}: {close_reason} | Profit: {rebond_profit:.2f}", "SUCCESS")
                    REBOND_META[symbol_key]["last_rebond_at"] = time.time()
                    if "Cible" in close_reason and rebond_profit > 0:
                        main_dir = rs.get("main_direction")
                        if main_dir in ("BUY", "SELL"):
                            lot_renfort = {"effective_lot": main_lot, "reason": "Renfort Phase 3 — résistance atteinte après rebond"}
                            ok_r, msg_r, _ = open_position(symbol_key, symbol, main_dir, params, lot_renfort, analysis, allow_real)
                            if ok_r:
                                log(f"[REBOND Phase3] Renfort {main_dir} ouvert à la résistance.", "SUCCESS")
                            else:
                                log(f"[REBOND Phase3] Renfort refusé: {msg_r}", "WARNING")
                else:
                    log(f"[REBOND] Fermeture échouée ticket #{ticket}: {msg}", "ERROR")
                    still_active.append(rs)
            else:
                log(f"[REBOND] Ticket #{ticket} déjà fermé par MT5 (TP).", "INFO")
                REBOND_META.setdefault(symbol_key, {"zones": [], "last_scan": 0.0, "last_rebond_at": 0.0})["last_rebond_at"] = time.time()
        else:
            still_active.append(rs)
    REBOND_STATES[:] = still_active

    # ── 2. Décision d'ouverture ──────────────────────────────────────────────────
    # Refonte du 17/07/2026 : plus de scan de zones S&D, should_open_rebond()
    # décide désormais à partir de la perte en cours de la position principale
    # et d'un retracement en temps réel (voir son docstring).
    ok, reason, rebond_info = should_open_rebond(symbol_key, symbol, positions, analysis, params)
    if not ok:
        return {
            "rebond_active": len(REBOND_STATES) > 0,
            "rebond_count": len(REBOND_STATES),
            "reason": reason,
        }

    # ── 3. Calcul du lot dynamique ──────────────────────────────────────────────
    tier = rebond_info.get("tier", "normal")
    lot = rebond_lot(main_lot, params, is_demo, tier=tier)
    lot_reason = "Rebond Fort contra-tendance (signal principal fort)" if tier == "fort" else "Rebond contra-tendance (perte en cours + retracement)"
    lot_info_rebond = {"effective_lot": lot, "reason": lot_reason}

    # ── 4. Ouverture ────────────────────────────────────────────────────────────
    direction = str(rebond_info["direction"])
    target_price = float(rebond_info["target_price"])
    ok_open, msg_open, event = open_position(
        symbol_key, symbol, direction, params, lot_info_rebond, analysis, allow_real, position_type="REBOND",
    )
    if ok_open and event:
        time.sleep(0.2)
        fresh_positions = live_positions({symbol_key: symbol}, params)
        known_now = {s.get("ticket") for s in REBOND_STATES}
        new_pos = next(
            (p for p in sorted(fresh_positions, key=lambda x: -int(x.get("open_timestamp", 0)))
             if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
             and p.get("direction") == direction
             and p.get("symbol_key") == symbol_key
             and int(p.get("ticket", 0)) not in known_now),
            None,
        )
        new_entry = {
            "ticket": int(new_pos["ticket"]) if new_pos else None,
            "direction": direction,
            "main_direction": "SELL" if direction == "BUY" else "BUY",
            "open_price": float(rebond_info["current_price"]),
            "target_price": target_price,
            "lot": lot,
            "tier": tier,
            "opened_at": time.time(),
        }
        REBOND_STATES.append(new_entry)
        REBOND_META[symbol_key]["last_rebond_at"] = time.time()
        log(
            f"[REBOND{'-FORT' if tier == 'fort' else ''}] {direction} {lot:.3f} ouvert @ {rebond_info['current_price']:.2f} "
            f"| Cible: {target_price:.2f} "
            f"| Rebonds actifs: {len(REBOND_STATES)}/{params.get('rebond_max_active', 3)}",
            "SUCCESS",
        )
        return {
            "rebond_active": True,
            "rebond_count": len(REBOND_STATES),
            "direction": direction,
            "lot": lot,
            "tier": tier,
            "open_price": rebond_info["current_price"],
            "target_price": target_price,
            "last_action": msg_open,
        }
    else:
        log(f"[REBOND] Ouverture refusée: {msg_open}", "WARNING")
        return {"rebond_active": len(REBOND_STATES) > 0, "rebond_count": len(REBOND_STATES), "reason": f"Rebond refusé: {msg_open}"}


# ── Fin module Capture Rebond ──────────────────────────────────────────────────


def check_mission_target_slack(params: dict, mission: dict, state: dict) -> None:
    """Notifie Slack une seule fois par periode (jour/semaine/mois) quand le
    Trading Mission Manager atteint son objectif -- deduplique via
    state['slack_mission_notified'][periode] = cle_de_periode, persiste dans
    trading_state.json comme le reste de `state`."""
    if not mission:
        return
    now = datetime.now(timezone.utc)
    notified = state.setdefault("slack_mission_notified", {})
    periods = {
        "day": (now.strftime("%Y-%m-%d"), mission.get("daily_profit"), mission.get("daily_target"), "journalier"),
        "week": (now.strftime("%G-W%V"), mission.get("weekly_profit"), mission.get("weekly_target"), "hebdomadaire"),
        "month": (now.strftime("%Y-%m"), mission.get("monthly_profit"), mission.get("monthly_target"), "mensuel"),
    }
    for key, (period_key, profit, target, label) in periods.items():
        if profit is None or target is None or float(target) <= 0 or float(profit) < float(target):
            continue
        if notified.get(key) == period_key:
            continue
        notified[key] = period_key
        notify_slack(params, "mission_target", SLACK_GREEN, *blocks_mission_target(label, float(profit), float(target)))


def gold_brain_snapshot(
    params: dict,
    account,
    symbol: str,
    symbol_names: dict[str, str],
    symbol_params: dict,
    analysis: dict,
    decision: dict,
    payload: dict,
    positions: list[dict],
    trades: list[dict] | None,
    *,
    record: bool = True,
) -> dict:
    """v5.1.0 -- calcule un instantane Gold Brain complet (rapports des 4
    agents + arbitrage CAIO), utilise a la fois pour l'observation continue
    (record=False, chaque cycle, panneau toujours alimente) et pour une
    vraie tentative d'entree (record=True, seul cas trace dans
    learning_history). Factorise pour ne jamais diverger entre les deux
    chemins d'appel."""
    candle_timeframe = str(symbol_params.get("timeframe", "M5"))
    candles = fetch_candles(symbol, candle_timeframe, 300)
    current_price = candles[-1]["close"] if candles else float(analysis.get("close") or 0)
    reports = [
        structure_analyst_report(candles, current_price, timeframe=candle_timeframe),
        smart_money_analyst_report(candles, current_price),
        risk_manager_report(params, account, symbol_names),
    ]
    if bool(params.get("economic_calendar_enabled", True)):
        reports.append(economic_calendar_report(
            symbol, block_hours=float(params.get("economic_calendar_block_hours", 2.0) or 2.0),
        ))
    classic_signal = str(decision.get("signal") or "")
    if classic_signal in ("BUY", "SELL"):
        reports.append(make_agent_report(
            "alphatrade_ai_classic", status="OK",
            confidence=float(analysis.get("confidence") or 0), priority="MEDIUM",
            recommendation={"action": f"{classic_signal}_MARKET"},
            arguments=[str(decision.get("reason") or "Signal du pipeline classique.")],
            ttl_seconds=60,
        ))
    # 05/08/2026 -- bug trouve en observation reelle (rapporte par Louis,
    # capture d'ecran a l'appui) : payload["today_stats"] vient de
    # daily_stats(trades, positions), qui n'est JAMAIS filtre par origine --
    # il agrege TOUTES les positions/trades du compte MT5, y compris ceux
    # d'une autre application (ex: AT Global, origin EXTERNAL_AI). Passe tel
    # quel a mission_state() -> protection_state(), qui ECRASE
    # session_state.json (meme fichier que le calcul correct, deja filtre,
    # fait juste avant dans status_payload()) avec un "Pic"/session_profit
    # qui compte les gains d'un autre logiciel comme si c'etaient ceux
    # d'AlphaTrade Gold. Confirme : 4 positions ouvertes, toutes
    # origin=EXTERNAL_AI (AT Global) ; $0.42 de trades AlphaTrade clotures
    # aujourd'hui ; pourtant daily_peak affichait $118.44. Corrige en
    # recalculant ici les VRAIES stats du jour, deja filtrees BOT/ALPHATRADE/
    # ALPHAKARIS (meme filtre que application_session_stats()) -- l'objectif
    # d'AlphaTrade Gold ne doit refleter QUE ses propres gains, jamais ceux
    # d'un autre logiciel qui partage le meme compte MT5.
    bot_trades = [t for t in (trades or []) if str(t.get("origin", "")).upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    bot_positions_today = [
        p for p in positions if str(p.get("origin", "")).upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
    ]
    daily = daily_stats(bot_trades, bot_positions_today)
    mission_report = mission_state(
        params, trades or [], positions, daily, int(account.login) if account else None,
    )
    entry_policy = entry_policy_for_mode(str(params.get("strategy_mode") or "scalping_fast"))
    caio_result = caio_decide(params, reports, mission_report, entry_policy, record=record)
    return {
        "decision": caio_result["decision"],
        "order_type": caio_result.get("order_type"),
        "price": caio_result.get("price"),
        "source_agent": caio_result.get("source_agent"),
        "raison": caio_result.get("raison"),
        "overrides": caio_result.get("overrides", []),
        "entry_policy": entry_policy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mission": {
            "mode": mission_report.recommendation.get("mode"),
            "new_positions_allowed": mission_report.recommendation.get("new_positions_allowed"),
            "priority": mission_report.priority,
            **mission_report.metadata,
        },
        "reports": {r.agent: r.to_dict() for r in reports},
    }


def caio_decide_scenario(scenario: Scenario, params: dict, *, now: datetime | None = None) -> dict:
    """CAIO -- mode (a), arbitre un scenario deja VALIDATED (v5.1.1 Phase 3,
    section 4.3 de Architecture_ScenarioEngine_v5.1.1.html). Ne cree pas la
    validite -- deja faite par le Scenario Validator (Phase 2) -- decide
    seulement si la confiance justifie l'activation, meme philosophie que
    caio_decide() : NO_TRADE (ici WAIT) est une decision legitime, pas un
    defaut par manque d'idee.

    Seuil dedie `scenario_caio_min_confidence`, DISTINCT de `caio_min_confidence`
    (celui de l'ancien CAIO/pipeline classique) -- bug trouve via le Scenario
    Replay du 04/08/2026 : reutiliser le meme seuil (75, calibre pour un score
    a agent unique) bloquait 99,8% des 565 scenarios generes sur 30j (median
    Scenario Confidence 64,4/100, max observe 75,3). Defaut 60 ici, choisi sur
    la distribution reelle observee (~82% des scenarios generes l'atteignent) --
    a affiner par la Phase 5 (Learning) une fois assez de resultats WIN/LOSS
    accumules.

    Cette fonction transitionne VALIDATED -> ACTIVE (via activate_scenario())
    mais N'APPELLE ELLE-MEME JAMAIS place_order()/open_position() -- elle
    reste une decision d'arbitrage pure, tracee (scenario_log.jsonl).
    L'execution reelle (activee le 05/08/2026, demande explicite de Louis,
    leve la garde d'observation posee le 04/08/2026 section 11) se fait
    ensuite, separement, par execute_scenario_anchor() appelee depuis
    auto_trade_step() -- separation deliberee : le CAIO decide QUOI activer,
    execute_scenario_anchor() decide SI/COMMENT l'executer reellement (gates
    Demarrer/protection/flag scenario_engine_execution_enabled).

    Seuil relève en session Londres (05/08/2026, analyse du Scenario Replay
    58j) : winrate par tranche de confiance en session londres --
    [60-65)=33,3% (n=24), [65-70)=35,1% (n=97), [70-75)=47,6% (n=82),
    [75-80)=50,0% (n=10). Gradient net (contrairement a CORRECTION, ou la
    confiance ne discriminait pas) : Londres reste exploitable, juste avec
    une barre plus haute -- `scenario_london_min_confidence` (defaut 70)
    s'applique en plus de `scenario_caio_min_confidence` (jamais en dessous,
    voir max() plus bas)."""
    now = now or datetime.now(timezone.utc)
    if scenario.status != "VALIDATED":
        return {"decision": "WAIT", "reason": f"Scenario non VALIDATED (status={scenario.status})."}
    min_confidence = float(params.get("scenario_caio_min_confidence", 60.0))
    if (scenario.market_context or {}).get("session") == "london":
        min_confidence = max(min_confidence, float(params.get("scenario_london_min_confidence", 70.0)))
    if scenario.scenario_confidence < min_confidence:
        return {
            "decision": "WAIT",
            "reason": (
                f"Scenario Confidence ({scenario.scenario_confidence:.0f}) sous le seuil "
                f"({min_confidence:.0f}) -- le meilleur trade est parfois de ne rien faire."
            ),
        }
    activate_scenario(
        scenario, f"CAIO active le scenario (confiance {scenario.scenario_confidence:.0f}).", now=now,
    )
    return {"decision": "GO", "reason": f"Scenario active avec confiance {scenario.scenario_confidence:.0f}."}


def dynamic_position_manager_step(
    scenario: Scenario,
    params: dict,
    current_price: float,
    structure_report: AgentReport,
    smart_money_report: AgentReport,
    risk_report: AgentReport,
    candles: list[dict],
    analysis: dict,
    now: datetime | None = None,
    log_name: str = "scenario_log.jsonl",
) -> None:
    """Dynamic Position Manager (v5.1.1, Phase 4, mode b du CAIO -- section 9
    de Architecture_ScenarioEngine_v5.1.1.html). Pour un scenario ACTIVE/
    DEGRADED : recalcule scenario_health en continu, fait basculer
    ACTIVE<->DEGRADED selon `scenario_health_degradation_threshold`, cloture
    le scenario si invalidation_price est franchi / le dernier target est
    atteint / le delai de validite expire, et evalue une opportunite de
    scalp (4 conditions -- ancien renfort directionnel remplace, point 6 de
    la relecture de Louis).

    Cette fonction-ci n'appelle elle-meme jamais place_order()/open_position()/
    close_bot_position() -- elle reste l'evaluation pure (sante, transitions,
    cloture logique). Les clotures produisent un outcome/outcome_profit
    SIMULES (distance de prix en points, pas un P&L reel) tel quel, MEME
    depuis l'activation de l'execution reelle (05/08/2026) -- c'est un calcul
    de reference constant, comparable d'un scenario a l'autre, independant
    du slippage/spread reels de la position d'ancrage. La fermeture REELLE de
    cette position, elle, est geree separement par l'appelant
    (close_scenario_anchor_if_needed(), auto_trade_step()) juste apres cette
    fonction, des qu'un statut terminal est atteint."""
    now = now or datetime.now(timezone.utc)
    if scenario.status not in ("ACTIVE", "DEGRADED"):
        return

    points = current_price - float(scenario.anchor_plan.get("entry", current_price))
    if scenario.direction == "SELL":
        points = -points

    invalidated = (
        (scenario.direction == "BUY" and current_price <= scenario.invalidation_price)
        or (scenario.direction == "SELL" and current_price >= scenario.invalidation_price)
    )
    if invalidated:
        close_scenario(
            scenario, "INVALIDATED", "LOSS_SIMULATED", profit=round(points, 5),
            note=f"Invalidation atteinte (prix {current_price}, seuil {scenario.invalidation_price}).", now=now,
        )
        log_scenario_event(scenario, log_name)
        return

    last_target = scenario.targets[-1]["price"] if scenario.targets else None
    completed = last_target is not None and (
        (scenario.direction == "BUY" and current_price >= last_target)
        or (scenario.direction == "SELL" and current_price <= last_target)
    )
    if completed:
        close_scenario(
            scenario, "COMPLETED", "WIN_SIMULATED", profit=round(points, 5),
            note=f"Dernier target atteint ({last_target}).", now=now,
        )
        log_scenario_event(scenario, log_name)
        return

    if scenario.is_expired(now):
        outcome = "WIN_SIMULATED" if points > 0 else "LOSS_SIMULATED" if points < 0 else "BREAKEVEN_SIMULATED"
        close_scenario(
            scenario, "EXPIRED", outcome, profit=round(points, 5),
            note="Duree de validite maximale depassee (scenario actif).", now=now,
        )
        log_scenario_event(scenario, log_name)
        return

    before_status = scenario.status
    health = evaluate_scenario_health(
        scenario, structure_report, smart_money_report, candles, analysis, now=now, weights=load_scenario_weights(),
    )
    scenario.update_health(health, f"Sante recalculee ({health:.0f}).", now=now)
    threshold = float(params.get("scenario_health_degradation_threshold", 45.0))
    if health < threshold and scenario.status == "ACTIVE":
        scenario.scalp_allowed = False
        scenario.transition("DEGRADED", f"Sante ({health:.0f}) sous le seuil ({threshold:.0f}).", now=now)
    elif health >= threshold and scenario.status == "DEGRADED":
        scenario.scalp_allowed = True
        scenario.transition("ACTIVE", f"Sante remontee ({health:.0f}) au-dessus du seuil ({threshold:.0f}).", now=now)
    if scenario.status != before_status:
        log_scenario_event(scenario, log_name)

    if scenario.status == "ACTIVE":
        checks = evaluate_scalp_opportunity(
            scenario, current_price, risk_report, analysis, now=now, candles=candles,
            microstructure_min=float(params.get("scenario_microstructure_min", 60.0)),
        )
        if all(checks.values()):
            scenario.simulated_scalp_count += 1
            scenario.history.append(ScenarioEvent(
                at=now.isoformat(), status=scenario.status,
                note=f"Opportunite de scalp detectee (#{scenario.simulated_scalp_count}), aucun ordre reel.",
                scenario_health=scenario.scenario_health,
            ))
            log_scenario_event(scenario, log_name)


# v5.1.1 -- 06/08/2026, task #170. Duree de validite maximale d'un scenario
# CANDIDATE/VALIDATED selon le timeframe de raisonnement choisi
# (scenario_engine_timeframe) -- un scenario construit sur des bougies H1 a
# besoin de bien plus que 45 min pour que son hypothese ait une chance
# reelle de se realiser, l'inverse serait incoherent avec ses propres cibles
# (calculees en multiples d'ATR sur ce meme timeframe, voir generate_scenario()).
# "M5": 45 preserve exactement le comportement historique (defaut inchange).
SCENARIO_VALIDITY_MINUTES_BY_TIMEFRAME = {"M1": 15, "M5": 45, "M15": 180, "H1": 720}


def scenario_engine_step(
    params: dict,
    symbol_key: str,
    candles: list[dict],
    current_price: float,
    structure_report: AgentReport,
    smart_money_report: AgentReport,
    risk_report: AgentReport,
    economic_report: AgentReport | None,
    analysis: dict,
    now: datetime | None = None,
    log_name: str = "scenario_log.jsonl",
) -> Scenario | None:
    """Market Scenario Engine (v5.1.1, Phase 3) -- orchestre Scenario
    Generator + Scenario Validator + CAIO scenario a chaque cycle, persiste
    dans SHARED_MEMORY['active_scenarios'] et scenario_log.jsonl. Le CAIO peut
    activer un scenario (VALIDATED -> ACTIVE, caio_decide_scenario) -- CETTE
    fonction-ci ne place jamais d'ordre elle-meme, mais l'appelant
    (auto_trade_step()) appelle execute_scenario_anchor() juste apres avec le
    scenario retourne : depuis l'activation de l'execution reelle (05/08/2026,
    demande explicite de Louis, section 4), un scenario ACTIVE peut donc bel
    et bien ouvrir une vraie position MT5 -- voir execute_scenario_anchor()
    pour tous les garde-fous (bouton Demarrer, protection de session, flag
    scenario_engine_execution_enabled). Branche depuis auto_trade_step()
    derriere le flag `scenario_engine_enabled` (regle d'integration de Louis,
    04/08/2026 : aucun module ne doit rester isole apres ses tests unitaires).
    `log_name` : utilise par le Scenario Replay (run_scenario_replay()) pour
    ecrire dans scenario_replay_log.jsonl plutot que scenario_log.jsonl, sans
    jamais melanger les deux -- le Replay n'appelle JAMAIS
    execute_scenario_anchor() (voir run_scenario_replay(), aucun acces MT5
    reel pendant un rejeu historique)."""
    global CURRENT_SCENARIO, LAST_DPM_EVAL_AT
    now = now or datetime.now(timezone.utc)

    scenario = CURRENT_SCENARIO
    if scenario is not None and (
        scenario.symbol_key != symbol_key or scenario.status in ("INVALIDATED", "EXPIRED", "COMPLETED")
    ):
        scenario = None  # scenario clos ou d'un autre symbole -- on en cherche un nouveau

    if scenario is None:
        se_timeframe = str(params.get("scenario_engine_timeframe") or "M5")
        scenario = generate_scenario(
            symbol_key, candles, current_price, structure_report, smart_money_report, analysis,
            maximum_validity_min=SCENARIO_VALIDITY_MINUTES_BY_TIMEFRAME.get(se_timeframe, 45),
            now=now, weights=load_scenario_weights(),
            block_correction_regime=bool(params.get("scenario_block_correction_regime", True)),
        )
        if scenario is None:
            return None
        log_scenario_event(scenario, log_name)

    if scenario.status in ("CANDIDATE", "VALIDATED"):
        before_status = scenario.status
        validate_scenario(scenario, current_price, smart_money_report, risk_report, economic_report, now=now)
        if scenario.status != before_status:
            log_scenario_event(scenario, log_name)

    if scenario.status == "VALIDATED":
        # v5.1.1 Phase 3 -- CAIO arbitre (mode a). Ne place jamais d'ordre
        # reel (voir caio_decide_scenario()) : seule la transition VALIDATED
        # -> ACTIVE change, tracee dans scenario_log.jsonl.
        before_status = scenario.status
        caio_decide_scenario(scenario, params, now=now)
        if scenario.status != before_status:
            log_scenario_event(scenario, log_name)

    if scenario.status in ("ACTIVE", "DEGRADED"):
        # v5.1.1 Phase 4 -- Dynamic Position Manager (mode b du CAIO). Journalise
        # deja en interne (log_scenario_event) sur chaque changement pertinent.
        # Throttle (05/08/2026, voir LAST_DPM_EVAL_AT) : evite de recalculer
        # scenario_health depuis une bougie encore en formation a chaque tick
        # de la boucle principale -- source du bruit ACTIVE<->DEGRADED observe
        # en direct. Base sur `now` (pas time.time()), correct en live comme
        # en rejeu (temps simule).
        reeval_interval = max(0.5, float(params.get("scenario_health_reeval_interval_sec", 3.0)))
        if LAST_DPM_EVAL_AT is None or (now - LAST_DPM_EVAL_AT).total_seconds() >= reeval_interval:
            dynamic_position_manager_step(
                scenario, params, current_price, structure_report, smart_money_report, risk_report, candles, analysis,
                now=now, log_name=log_name,
            )
            LAST_DPM_EVAL_AT = now

    CURRENT_SCENARIO = scenario
    SHARED_MEMORY.write(
        "active_scenarios", "scenario_generator", scenario.to_dict(), confidence=scenario.scenario_confidence, now=now,
    )
    return scenario


def _find_scenario_anchor_position(scenario: Scenario, symbol_names: dict[str, str], params: dict) -> dict | None:
    """Identifie la position MT5 reelle d'un ancrage via le tag "SCENARIO" du
    commentaire (open_position()/place_order() ne retournent pas le ticket
    directement) -- le plus recemment ouvert sur ce symbole/sens en cas
    d'ambiguite. Factorise depuis execute_scenario_anchor() (task #170,
    06/08/2026) pour servir aussi bien a une entree au marche (MARKET,
    immediate) qu'a la detection du declenchement d'un ordre en attente
    (LIMIT/STOP, voir plus bas)."""
    candidates = [
        p for p in live_positions(symbol_names, params)
        if p["symbol_key"] == scenario.symbol_key and p["direction"] == scenario.direction
        and "SCENARIO" in p.get("comment", "")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p["open_timestamp"])


def execute_scenario_anchor(
    scenario: Scenario,
    params: dict,
    symbol_names: dict[str, str],
    account,
    protection: dict,
    trading_enabled: bool,
    allow_real: bool,
    current_price: float = 0.0,
    now: datetime | None = None,
    log_name: str = "scenario_log.jsonl",
) -> None:
    """Execution Manager -- Scenario Engine (v5.1.1, activation reelle du
    05/08/2026, demande explicite de Louis, section 4 : "le systeme doit
    devenir actif, plus aucun module critique ne doit rester isole ou
    theorique"). Ouvre la VRAIE position d'ancrage MT5 d'un scenario
    ACTIVE/DEGRADED avec les niveaux calcules par le Scenario Generator
    (invalidation_price -> SL, dernier target -> TP), jamais le TP fixe du
    profil classique : c'est tout l'interet du scenario face aux anciens
    reglages statiques.

    task #170 (06/08/2026, demande de Louis : "ordres en attente (limite/
    stop)") -- la zone touchee qui valide un scenario (voir validate_scenario())
    est "collante" (reaction_count > 0 reste vrai meme si le prix en est
    reparti depuis) : au moment ou CE cycle-ci active reellement l'ancrage, le
    prix courant peut donc s'etre eloigne de l'entree ideale
    (scenario.anchor_plan["entry"]). Le chasser au marche degraderait
    l'execution reelle par rapport a ce que le Scenario Generator a prevu.
    Decision purement geometrique (pas un reglage manuel -- coherente avec la
    regle de Louis "aucune valeur en dur ne doit bloquer l'IA") : si le prix
    est encore dans la moitie de la largeur de zone autour de l'entree ideale,
    entree immediate au marche (comportement historique, inchange) ; sinon un
    ordre en attente est pose exactement au niveau de l'entree ideale --
    BUY_LIMIT/SELL_LIMIT si ce niveau attend un repli, BUY_STOP/SELL_STOP s'il
    attend une cassure confirmee -- laissant le marche venir a la zone plutot
    que l'inverse. `current_price` optionnel (defaut 0.0) : un appelant qui ne
    le fournit pas (anciens appels/tests) conserve exactement l'ancien
    comportement (toujours MARKET), aucune regression.

    Gate dedie `scenario_engine_execution_enabled` (defaut True depuis
    l'activation), INDEPENDANT de `scenario_engine_enabled` (qui ne fait que
    generer/journaliser) -- coupe-circuit immediat sans toucher a
    l'observation si Louis veut redescendre en observation pure plus tard.
    Respecte aussi les memes garde-fous que le pipeline classique : bouton
    Demarrer (trading_enabled), protection de session (WARNING/HARD_LOCK/
    TARGET_REACHED), confirmation compte reel (allow_real, re-verifiee de
    toute facon dans open_position()/place_order()). Ces gates ne s'appliquent
    qu'a la pose d'un NOUVEL ordre -- la surveillance d'un ordre PENDING deja
    pose (declenchement/reste en attente) continue meme si l'un d'eux devient
    actif entre-temps : un ordre reel deja sur le broker doit rester supervise,
    pas abandonne silencieusement.

    Distinction deliberee entre blocage TRANSITOIRE (Demarrer pas encore
    clique, protection momentanement active -- on ne touche pas a
    anchor_status, nouvelle tentative au prochain cycle tant que le scenario
    reste ACTIVE/DEGRADED) et ECHEC DEFINITIF pour CE scenario (ordre
    reellement tente et refuse, symbole introuvable, scenario sans cible) --
    anchor_status passe alors a FAILED, plus jamais retente."""
    now = now or datetime.now(timezone.utc)

    if scenario.anchor_status == "PENDING":
        # Surveillance d'un ordre en attente deja pose -- independant des
        # gates ci-dessous (voir docstring). Deux issues possibles : declenche
        # (une position SCENARIO est apparue) ou toujours en attente (rien a
        # faire, nouvelle verification au prochain cycle). L'annulation sur
        # statut terminal est geree par close_scenario_anchor_if_needed(), pas
        # ici (symetrie avec le chemin OPEN existant).
        position = _find_scenario_anchor_position(scenario, symbol_names, params)
        if position is not None:
            scenario.anchor_status = "OPEN"
            scenario.anchor_ticket = position["ticket"]
            scenario.pending_order_ticket = None
            scenario.history.append(ScenarioEvent(
                at=now.isoformat(), status=scenario.status,
                note=f"Ordre en attente declenche -- position d'ancrage {position['ticket']} ouverte.",
                scenario_health=scenario.scenario_health,
            ))
            log_scenario_event(scenario, log_name)
        return

    if scenario.anchor_status != "NONE" or scenario.status not in ("ACTIVE", "DEGRADED"):
        return
    if not bool(params.get("scenario_engine_execution_enabled", True)):
        return
    if not trading_enabled:
        return  # transitoire -- IA pas demarree, retente au prochain cycle
    if protection.get("state") in ("WARNING", "HARD_LOCK", "TARGET_REACHED") or protection.get("portfolio_blocks"):
        return  # transitoire -- protection de session ou panier Portfolio Brain active

    symbol = symbol_names.get(scenario.symbol_key)
    if not symbol or not scenario.targets or scenario.invalidation_price is None:
        scenario.anchor_status = "FAILED"
        scenario.history.append(ScenarioEvent(
            at=now.isoformat(), status=scenario.status,
            note="Position d'ancrage impossible: symbole non resolu ou niveaux (cible/invalidation) manquants.",
            scenario_health=scenario.scenario_health,
        ))
        log_scenario_event(scenario, log_name)
        return

    lot_info = lot_safety_state(params, account, symbol_names).get(scenario.symbol_key, {})

    entry_price = float(scenario.anchor_plan.get("entry") or (scenario.zone["low"] + scenario.zone["high"]) / 2)
    zone_half_width = max(0.0, (scenario.zone["high"] - scenario.zone["low"]) / 2.0)
    pending_order_type: str | None = None
    if current_price > 0 and zone_half_width > 0:
        if scenario.direction == "BUY":
            if current_price > entry_price + zone_half_width:
                pending_order_type = "BUY_LIMIT"  # prix reparti au-dessus -- attendre un repli vers la zone
            elif current_price < entry_price - zone_half_width:
                pending_order_type = "BUY_STOP"  # entree prevue au-dessus du prix actuel -- attendre la cassure
        else:
            if current_price < entry_price - zone_half_width:
                pending_order_type = "SELL_LIMIT"  # prix reparti en-dessous -- attendre un rebond vers la zone
            elif current_price > entry_price + zone_half_width:
                pending_order_type = "SELL_STOP"  # entree prevue sous le prix actuel -- attendre la cassure

    if pending_order_type is None:
        ok, message, _event = open_position(
            scenario.symbol_key, symbol, scenario.direction, params, lot_info,
            {"confidence": scenario.scenario_confidence}, allow_real,
            position_type="SCENARIO", sl_price=scenario.invalidation_price, tp_price=scenario.targets[-1]["price"],
        )
        scenario.anchor_status = "OPEN" if ok else "FAILED"
        if ok:
            position = _find_scenario_anchor_position(scenario, symbol_names, params)
            if position is not None:
                scenario.anchor_ticket = position["ticket"]
        scenario.history.append(ScenarioEvent(
            at=now.isoformat(), status=scenario.status,
            note=f"Position d'ancrage {'ouverte' if ok else 'refusee'}: {message}",
            scenario_health=scenario.scenario_health,
        ))
    else:
        ok, message, event = place_order(
            scenario.symbol_key, symbol, pending_order_type, params, lot_info,
            {"confidence": scenario.scenario_confidence}, allow_real,
            price_hint=entry_price, position_type="SCENARIO",
        )
        scenario.anchor_status = "PENDING" if ok else "FAILED"
        if ok and event:
            scenario.pending_order_ticket = event.get("order_ticket")
        scenario.history.append(ScenarioEvent(
            at=now.isoformat(), status=scenario.status,
            note=f"Ordre en attente {pending_order_type} {'pose' if ok else 'refuse'} a {entry_price}: {message}",
            scenario_health=scenario.scenario_health,
        ))
    log_scenario_event(scenario, log_name)


def close_scenario_anchor_if_needed(
    scenario: Scenario, positions: list[dict], now: datetime | None = None, log_name: str = "scenario_log.jsonl",
) -> None:
    """Ferme reellement la position d'ancrage MT5 quand le scenario atteint
    un statut terminal (COMPLETED/EXPIRED/INVALIDATED) -- symetrique
    d'execute_scenario_anchor() pour l'ouverture, meme regle d'activation
    (05/08/2026, demande explicite de Louis, section 4). Le SL/TP broker
    (poses a l'ouverture sur invalidation_price/dernier target, voir
    execute_scenario_anchor()) restent un filet de securite independant --
    cette fermeture logicielle est le chemin normal, generalement plus
    rapide que d'attendre que le prix atteigne exactement ces niveaux au
    tick pres.

    task #170 (06/08/2026) -- symetrie identique pour un ancrage PENDING
    (ordre en attente encore non declenche) : plutot que d'attendre
    l'expiration broker (jusqu'a pending_order_expire_min, potentiellement
    bien plus tard qu'un scenario reste valide), l'ordre est annule
    immediatement des que le scenario devient terminal -- une idee perimee ne
    doit pas rester postee sur le marche.

    Idempotent : si la position est deja fermee cote broker (SL/TP deja
    declenche avant que ce code ne s'execute), close_bot_position() echoue
    proprement (position introuvable dans `positions`) -- on marque quand
    meme CLOSED plutot que de retenter indefiniment une position qui n'existe
    deja plus. Meme logique pour un ordre PENDING deja disparu (declenche
    entre-temps ou expire cote broker)."""
    now = now or datetime.now(timezone.utc)
    if scenario.status not in ("INVALIDATED", "EXPIRED", "COMPLETED"):
        return

    if scenario.anchor_status == "PENDING":
        ticket = scenario.pending_order_ticket
        if not ticket:
            scenario.anchor_status = "CLOSED"
            scenario.history.append(ScenarioEvent(
                at=now.isoformat(), status=scenario.status,
                note="Ordre en attente sans ticket connu -- rien a annuler, marque cloture.",
                scenario_health=scenario.scenario_health,
            ))
            log_scenario_event(scenario, log_name)
            return
        # `symbol` n'est utilise que pour le texte du log -- cancel_pending_order()
        # n'en a pas besoin cote requete MT5 (TRADE_ACTION_REMOVE ne prend que
        # le ticket) -- scenario.symbol_key est toujours disponible, pas
        # besoin de symbol_names ici (positions ne contient pas cet ordre
        # PENDING, qui n'est justement pas encore une position).
        ok, message = cancel_pending_order(scenario.symbol_key, ticket)
        if ok:
            scenario.anchor_status = "CLOSED"
            scenario.pending_order_ticket = None
        # Echec (deja declenche/expire cote broker, ou ordre introuvable) :
        # on ne boucle pas indefiniment -- si l'ordre a ete declenche entre
        # temps, le prochain cycle d'execute_scenario_anchor() (branche
        # PENDING) le detectera comme position OPEN et cette fonction
        # prendra alors le relais normalement au cycle suivant.
        scenario.history.append(ScenarioEvent(
            at=now.isoformat(), status=scenario.status,
            note=f"Ordre en attente {'annule' if ok else 'annulation echouee'}: {message}",
            scenario_health=scenario.scenario_health,
        ))
        log_scenario_event(scenario, log_name)
        return

    if scenario.anchor_status != "OPEN":
        return
    position = next((p for p in positions if int(p.get("ticket") or 0) == scenario.anchor_ticket), None)
    if position is None:
        scenario.anchor_status = "CLOSED"
        scenario.history.append(ScenarioEvent(
            at=now.isoformat(), status=scenario.status,
            note="Position d'ancrage deja fermee cote broker (SL/TP ou fermeture externe).",
            scenario_health=scenario.scenario_health,
        ))
        log_scenario_event(scenario, log_name)
        return
    ok, message = close_bot_position(position, f"scenario {scenario.status.lower()}")
    if ok:
        scenario.anchor_status = "CLOSED"
    # Si echec (ex: throttle CLOSE_ATTEMPTS de close_bot_position, 5s min entre
    # tentatives sur le meme ticket), anchor_status reste volontairement OPEN
    # -- nouvelle tentative au prochain cycle, pas de boucle d'erreur infinie
    # grace au throttle deja present dans close_bot_position() lui-meme.
    scenario.history.append(ScenarioEvent(
        at=now.isoformat(), status=scenario.status,
        note=f"Position d'ancrage {'fermee' if ok else 'fermeture refusee'}: {message}",
        scenario_health=scenario.scenario_health,
    ))
    log_scenario_event(scenario, log_name)


def execute_scenario_scalp(
    scenario: Scenario,
    params: dict,
    symbol_names: dict[str, str],
    account,
    protection: dict,
    current_price: float,
    risk_report: AgentReport,
    candles: list[dict],
    analysis: dict,
    trading_enabled: bool,
    allow_real: bool,
    now: datetime | None = None,
    log_name: str = "scenario_log.jsonl",
) -> None:
    """Execution Manager -- scalps du Scenario Engine (v5.1.1, 05/08/2026,
    demande explicite de Louis, section 2/3 : "ouvrir des scalps uniquement
    selon les regles definies"). Reevalue evaluate_scalp_opportunity() (les
    memes 4 conditions que le Dynamic Position Manager utilise pour la
    detection pure/simulee -- scenario_active, zone_favorable, risk_panier_ok,
    micro_opportunity) et, si toutes vraies ET hors cooldown ET sous le
    plafond par scenario, ouvre une VRAIE petite position via open_position()
    -- lot reduit (scenario_scalp_lot_ratio) par rapport a l'ancrage, SL sur
    l'invalidation du scenario (meme these que l'ancrage), TP sur la cible la
    PLUS PROCHE (targets[0], pas targets[-1] comme l'ancrage -- un scalp vise
    une capture rapide, pas le mouvement complet).

    Meme separation deliberee que execute_scenario_anchor() : cette fonction
    ne fait QUE l'execution, jamais la detection (deja faite par
    dynamic_position_manager_step()/evaluate_scalp_opportunity(), qui restent
    purement simulees/observation -- simulated_scalp_count n'est jamais
    touche ici, executed_scalp_count est le compteur reel distinct)."""
    now = now or datetime.now(timezone.utc)
    if scenario.status != "ACTIVE" or not scenario.scalp_allowed:
        return
    if not bool(params.get("scenario_engine_execution_enabled", True)):
        return
    if not trading_enabled:
        return  # transitoire
    if protection.get("state") in ("WARNING", "HARD_LOCK", "TARGET_REACHED") or protection.get("portfolio_blocks"):
        return  # transitoire
    max_scalps = max(0, int(params.get("scenario_scalp_max_count", 3)))
    if scenario.executed_scalp_count >= max_scalps:
        return  # plafond definitif pour ce scenario -- pas transitoire, jamais retente
    cooldown = max(0.0, float(params.get("scenario_scalp_cooldown_sec", 45.0)))
    if scenario.last_scalp_executed_at:
        try:
            last = datetime.fromisoformat(scenario.last_scalp_executed_at)
            if (now - last).total_seconds() < cooldown:
                return  # transitoire -- cooldown pas encore ecoule
        except ValueError:
            pass

    checks = evaluate_scalp_opportunity(
        scenario, current_price, risk_report, analysis, now=now, candles=candles,
        microstructure_min=float(params.get("scenario_microstructure_min", 60.0)),
    )
    if not all(checks.values()):
        return  # pas d'opportunite ce cycle -- rien a journaliser, deja fait par le DPM

    symbol = symbol_names.get(scenario.symbol_key)
    if not symbol or not scenario.targets or scenario.invalidation_price is None:
        return

    lot_info = dict(lot_safety_state(params, account, symbol_names).get(scenario.symbol_key, {}))
    ratio = max(0.01, min(1.0, float(params.get("scenario_scalp_lot_ratio", 0.5))))
    lot_info["effective_lot"] = round(float(lot_info.get("effective_lot") or 0) * ratio, 8)
    ok, message, _event = open_position(
        scenario.symbol_key, symbol, scenario.direction, params, lot_info,
        {"confidence": scenario.scenario_confidence}, allow_real,
        position_type="SCENARIO_SCALP", sl_price=scenario.invalidation_price, tp_price=scenario.targets[0]["price"],
    )
    scenario.last_scalp_executed_at = now.isoformat()  # cooldown demarre meme sur un refus --
    # evite de re-tenter en boucle serree si le refus est systemique (lot invalide, marche ferme...)
    if ok:
        scenario.executed_scalp_count += 1
    scenario.history.append(ScenarioEvent(
        at=now.isoformat(), status=scenario.status,
        note=f"Scalp #{scenario.executed_scalp_count} {'execute' if ok else 'refuse'}: {message}",
        scenario_health=scenario.scenario_health,
    ))
    log_scenario_event(scenario, log_name)


def fetch_candles_range(symbol: str, timeframe: str, date_from: datetime, date_to: datetime) -> list[dict]:
    """Bougies historiques sur une plage precise (mt5.copy_rates_range) --
    distinct de fetch_candles() (les N dernieres bougies relatives a
    maintenant). Utilise uniquement par le Scenario Replay (v5.1.1)."""
    if mt5 is None:
        return []
    rates = mt5.copy_rates_range(symbol, tf_const(timeframe), date_from, date_to)
    if rates is None:
        return []
    return [
        {"open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "time": int(r[0])}
        for r in rates
    ]


def run_scenario_replay(params: dict, symbol_names: dict[str, str], days: int, step_candles: int = 5) -> None:
    """Scenario Replay (v5.1.1) -- rejoue l'historique MT5 a travers EXACTEMENT
    les memes fonctions que le cycle live (generate_scenario/validate_scenario/
    caio_decide_scenario/dynamic_position_manager_step, via scenario_engine_step),
    aucune logique de decision dupliquee. Reponse a la question de Louis du
    04/08/2026 : plutot que d'attendre plusieurs semaines de collecte en
    direct, rejoue ce qui existe deja.

    Ecrit dans scenario_replay_log.jsonl -- JAMAIS dans scenario_log.jsonl,
    pour ne jamais melanger donnees rejouees et donnees d'observation reelle.

    Limites assumees et documentees (pas masquees) :
    - risk_report est un rapport neutre synthetique -- aucun solde de compte
      historique reconstituable, risk_ok toujours vrai en replay.
    - economic_report est toujours absent -- l'API du calendrier economique
      ne sert que la semaine courante, aucun historique disponible ;
      market_ok toujours vrai en replay. Le Scenario Validator est donc
      legerement plus permissif qu'en conditions live sur ces deux points.
    - Comme le reste du Scenario Engine : aucun ordre MT5 reel, quel que
      soit le resultat (meme garde d'observation que caio_decide_scenario()/
      dynamic_position_manager_step())."""
    global CURRENT_SCENARIO, LAST_DPM_EVAL_AT
    active = str(params.get("active_symbol") or "XAUUSD")
    symbol = symbol_names.get(active)
    if not symbol:
        log(f"Scenario Replay: symbole {active} introuvable dans symbol_names.", "ERROR")
        return
    symbol_params = params.get("symbols", {}).get(active, {})
    timeframe = str(symbol_params.get("timeframe", "M5"))

    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days)
    log(f"Scenario Replay: chargement de l'historique {symbol} {timeframe} sur {days}j...", "INFO")
    all_candles = fetch_candles_range(symbol, timeframe, date_from, date_to)
    if len(all_candles) < 360:
        log(f"Scenario Replay: historique insuffisant ({len(all_candles)} bougies) pour {days}j -- abandon.", "ERROR")
        return

    replay_log = "scenario_replay_log.jsonl"
    (DATA_DIR / replay_log).unlink(missing_ok=True)  # rejeu propre a chaque lancement, jamais d'accumulation
    CURRENT_SCENARIO = None
    LAST_DPM_EVAL_AT = None
    risk_report_neutral = make_agent_report(
        "risk_manager", status="OK", confidence=70.0, priority="LOW",
        recommendation={"action": "WAIT", "any_rejected": False},
        arguments=["Replay -- pas de solde de compte historique reconstituable, risque suppose acceptable."],
    )

    window = 300  # meme profondeur d'analyse que le cycle live (fetch_candles(..., 300))
    n_cycles = 0
    scenario_ids_seen: set[str] = set()
    for i in range(window, len(all_candles), max(1, step_candles)):
        candles_window = all_candles[i - window:i]
        bar = all_candles[i]
        now_sim = datetime.fromtimestamp(bar["time"], tz=timezone.utc)
        current_price = bar["close"]

        structure_report = structure_analyst_report(candles_window, current_price, timeframe=timeframe, now=now_sim)
        smart_money_report = smart_money_analyst_report(candles_window, current_price, now=now_sim)

        scenario = scenario_engine_step(
            params, active, candles_window, current_price,
            structure_report, smart_money_report, risk_report_neutral, None, {},
            now=now_sim, log_name=replay_log,
        )
        n_cycles += 1
        if scenario is not None:
            scenario_ids_seen.add(scenario.scenario_id)

    CURRENT_SCENARIO = None  # ne laisse jamais un scenario rejoue fuiter dans l'etat live
    LAST_DPM_EVAL_AT = None
    log(
        f"Scenario Replay termine: {n_cycles} cycles simules sur {days}j, "
        f"{len(scenario_ids_seen)} scenarios generes -> {replay_log}.",
        "SUCCESS",
    )


def run_scenario_learning(min_samples: int = 20) -> None:
    """Scenario Learning (v5.1.1, Phase 5) -- lit scenario_log.jsonl (observation
    live) + scenario_replay_log.jsonl (rejeu historique), calcule le winrate
    par facteur categoriel (session/tendance/volatilite/direction) sur les
    scenarios REELLEMENT resolus (WIN/LOSS simules -- un scenario jamais
    active n'a rien a apprendre), et persiste des poids alternatifs bornes
    dans scenario_learned_weights.json.

    Cette fonction ne fait que CALCULER et PERSISTER les poids -- elle ne les
    applique jamais elle-meme. L'application au calcul reel (voir
    load_scenario_weights(), branche dans generate_scenario()/
    evaluate_scenario_health() depuis le meme jour, "Phase 5" ci-dessus) est
    faite ailleurs, deliberement separee de ce calcul : cette fonction reste
    rejouable independamment (ex: apres un nouveau Scenario Replay) sans
    jamais risquer de coupler le calcul des poids a leur lecture."""
    entries: list[dict] = []
    for name in ("scenario_log.jsonl", "scenario_replay_log.jsonl"):
        path = DATA_DIR / name
        if not path.exists():
            continue
        by_id: dict[str, dict] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            by_id[d["scenario_id"]] = d  # garde le dernier etat connu de chaque scenario (deduplique)
        entries.extend(by_id.values())

    stats = scenario_learning_stats(entries, min_samples=min_samples)
    if stats["n_resolved"] < min_samples:
        log(
            f"Scenario Learning: {stats['n_resolved']} scenarios resolus, sous le seuil ({min_samples}) -- rien appris.",
            "INFO",
        )
        return

    learned_weights = scenario_weight_adjustments(stats, SCENARIO_WEIGHTS)
    # v5.1.1 -- 05/08/2026, historique reel des adaptations (demande explicite
    # de Louis, section 6 : "je veux voir en temps reel l'evolution du
    # systeme"). Compare aux poids PRECEDEMMENT appliques (le fichier qu'on
    # est en train d'ecraser) -- SCENARIO_WEIGHTS (base figee) si c'est le
    # tout premier calcul. Seuil 0.01 pour ignorer le bruit d'arrondi flottant.
    previous = read_json("scenario_learned_weights.json", None)
    previous_weights = previous.get("learned_weights") if previous else None
    baseline_weights = previous_weights if isinstance(previous_weights, dict) else SCENARIO_WEIGHTS
    now_iso = datetime.now(timezone.utc)
    for factor, new_value in learned_weights.items():
        old_value = float(baseline_weights.get(factor, SCENARIO_WEIGHTS.get(factor, 0.0)))
        if abs(float(new_value) - old_value) > 0.01:
            log_ai_adaptation(
                "scenario_learning", f"scenario_weight.{factor}", round(old_value, 3), round(float(new_value), 3),
                f"Apres {stats['n_resolved']} scenarios resolus (winrate global {stats['overall_winrate']}%).",
                now=now_iso,
            )
    write_json("scenario_learned_weights.json", {
        "computed_at": now_iso.isoformat(),
        "n_resolved": stats["n_resolved"],
        "overall_winrate": stats["overall_winrate"],
        "base_weights": SCENARIO_WEIGHTS,
        "learned_weights": learned_weights,
        "stats": stats,
    })
    log(
        f"Scenario Learning: {stats['n_resolved']} scenarios resolus, winrate {stats['overall_winrate']}% "
        f"-> scenario_learned_weights.json mis a jour (applique au prochain scenario via load_scenario_weights()).",
        "SUCCESS",
    )


def calibrate_scenario_thresholds(params: dict, *, min_samples: int = 20, now: datetime | None = None) -> None:
    """05/08/2026 -- calibration REELLE des seuils Scenario Engine (demande
    explicite de Louis : "des valeurs qui doivent s'ajuster... et non
    statiques", en reaction directe aux cartes "Piloté par l'intelligence"
    qui affichaient un texte fige "Jamais ajuste" sans aucun mecanisme
    derriere). Meme source de donnees et meme discipline que
    run_scenario_learning() (rejouable independamment, jamais couplee a
    l'application) mais ECRIT DIRECTEMENT dans params.json -- ces seuils sont
    lus par params.get(...) partout dans le moteur, contrairement aux poids
    de score qui passent par un fichier "appris" separe.

    Ne touche QUE scenario_caio_min_confidence / scenario_london_min_confidence
    / scenario_health_degradation_threshold / scenario_block_correction_regime
    -- voir scenario_threshold_adjustments() pour pourquoi les seuils
    scalp/Portfolio Brain n'y figurent pas encore (donnees de resultat
    manquantes, pas une omission)."""
    now = now or datetime.now(timezone.utc)
    entries: list[dict] = []
    for name in ("scenario_log.jsonl", "scenario_replay_log.jsonl"):
        path = DATA_DIR / name
        if not path.exists():
            continue
        by_id: dict[str, dict] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            by_id[d["scenario_id"]] = d
        entries.extend(by_id.values())

    stats = scenario_learning_stats(entries, min_samples=min_samples)
    if stats["n_resolved"] < min_samples:
        return  # deja journalise par run_scenario_learning() juste avant -- pas la peine de repeter

    current = {
        "scenario_caio_min_confidence": params.get("scenario_caio_min_confidence", 60.0),
        "scenario_london_min_confidence": params.get("scenario_london_min_confidence", 70.0),
        "scenario_health_degradation_threshold": params.get("scenario_health_degradation_threshold", 45.0),
        "scenario_block_correction_regime": params.get("scenario_block_correction_regime", True),
    }
    adjustments = scenario_threshold_adjustments(stats, current)
    if not adjustments:
        return

    saved = read_json("params.json", {}) or {}
    changed = False
    for key, new_value in adjustments.items():
        old_value = current[key]
        if isinstance(new_value, bool):
            differs = bool(new_value) != bool(old_value)
        else:
            differs = abs(float(new_value) - float(old_value)) > 0.01
        if not differs:
            continue
        saved[key] = new_value
        changed = True
        log_ai_adaptation(
            "scenario_threshold_calibration", key,
            old_value if not isinstance(old_value, bool) else bool(old_value),
            new_value if not isinstance(new_value, bool) else bool(new_value),
            f"Apres {stats['n_resolved']} scenarios resolus (winrate global {stats['overall_winrate']}%).",
            now=now,
        )
    if changed:
        write_json("params.json", saved)
        log(f"Calibration des seuils Scenario Engine: {len(adjustments)} valeur(s) evaluee(s), "
            f"params.json mis a jour.", "SUCCESS")


def run_auto_backtest_if_due(params: dict, symbol_names: dict[str, str], *, now: datetime | None = None) -> None:
    """Backtest automatique intelligent (v5.1.1, 05/08/2026, section 7 de la
    demande de Louis). Reutilise le Scenario Replay (run_scenario_replay())
    et le Scenario Learning (run_scenario_learning()) deja construits et
    testes -- pas de second moteur de backtest duplique. Se declenche au
    demarrage (jamais lance encore) puis toutes les
    scenario_backtest_interval_hours (defaut 24h) -- throttle persiste dans
    auto_backtest_state.json, jamais perdu au redemarrage.

    Persiste un resume exploitable par l'UI dans auto_backtest_result.json :
    periode testee, nb de trades, winrate, profit, drawdown, meilleures/pires
    conditions (session/tendance), poids proposes par le Learning -- exactement
    la liste demandee par Louis (section 7)."""
    if not bool(params.get("scenario_auto_backtest_enabled", True)):
        return
    now = now or datetime.now(timezone.utc)
    state = read_json("auto_backtest_state.json", {}) or {}
    last_run = state.get("last_run_at")
    interval_hours = max(1.0, float(params.get("scenario_backtest_interval_hours", 24.0)))
    if last_run:
        try:
            last_dt = datetime.fromisoformat(last_run)
            if (now - last_dt).total_seconds() < interval_hours * 3600:
                return
        except ValueError:
            pass

    days = max(1, int(params.get("scenario_backtest_days", 58)))
    log(f"Backtest automatique: declenchement (rejeu {days}j)...", "INFO")
    run_scenario_replay(params, symbol_names, days=days)
    write_json("auto_backtest_state.json", {"last_run_at": now.isoformat()})
    run_scenario_learning(min_samples=int(params.get("scenario_learning_min_samples", 20)))
    calibrate_scenario_thresholds(params, min_samples=int(params.get("scenario_learning_min_samples", 20)), now=now)

    replay_path = DATA_DIR / "scenario_replay_log.jsonl"
    if not replay_path.exists():
        log("Backtest automatique: aucun scenario_replay_log.jsonl produit -- historique MT5 insuffisant.", "WARNING")
        return
    by_id: dict[str, dict] = {}
    for line in replay_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        by_id[d["scenario_id"]] = d
    entries = list(by_id.values())
    stats = scenario_learning_stats(entries, min_samples=max(5, int(params.get("scenario_learning_min_samples", 20)) // 2))

    resolved = [e for e in entries if e.get("outcome") in ("WIN_SIMULATED", "LOSS_SIMULATED", "BREAKEVEN_SIMULATED")]
    resolved.sort(key=lambda e: e.get("created_at") or "")
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for e in resolved:
        cumulative += float(e.get("outcome_profit") or 0.0)
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    def _best_worst(bucket: dict) -> tuple[str | None, str | None]:
        if not bucket:
            return None, None
        ranked = sorted(bucket.items(), key=lambda kv: kv[1]["winrate"])
        return ranked[-1][0], ranked[0][0]

    best_session, worst_session = _best_worst(stats["by_session"])
    best_trend, worst_trend = _best_worst(stats["by_trend"])
    learned = read_json("scenario_learned_weights.json", None)

    write_json("auto_backtest_result.json", {
        "computed_at": now.isoformat(),
        "period_days": days,
        "period_from": (now - timedelta(days=days)).date().isoformat(),
        "period_to": now.date().isoformat(),
        "n_trades": stats["n_resolved"],
        "winrate": stats["overall_winrate"],
        "total_profit_points": round(cumulative, 3),
        "max_drawdown_points": round(max_drawdown, 3),
        "best_session": best_session,
        "worst_session": worst_session,
        "best_trend": best_trend,
        "worst_trend": worst_trend,
        "proposed_weights": learned.get("learned_weights") if learned else None,
    })
    log(
        f"Backtest automatique termine: {stats['n_resolved']} scenarios resolus, "
        f"winrate {stats['overall_winrate']}%, drawdown {round(max_drawdown, 2)} pts.",
        "SUCCESS",
    )


def auto_trade_step(
    params: dict, symbol_names: dict[str, str], payload: dict, positions: list[dict], trades: list[dict] | None = None
) -> dict:
    state = load_trading_state()
    account = mt5.account_info()
    demo = is_demo_account(account)
    state["allowed"] = bool(account and (demo or state.get("real_confirmed")))
    state["account_mode"] = "DEMO" if demo else "REAL" if account else "-"
    if not account:
        state["enabled"] = False
        state["reason"] = "Compte MT5 indisponible."
        save_trading_state(state)
        return state
    if not demo and not state.get("real_confirmed"):
        state["enabled"] = False
        state["reason"] = "Confirmation explicite requise pour le compte reel."
        save_trading_state(state)
        return state
    capital_min = float(params.get("capital_min", 0.0))
    if capital_min > 0 and account:
        balance = float(account.balance)
        if balance < capital_min:
            state["reason"] = f"Capital insuffisant: {balance:.2f}$ < minimum requis {capital_min:.2f}$"
            save_trading_state(state)
            return state
    if not state.get("enabled"):
        state["reason"] = "Connecte a MT5. En attente d'un clic sur Demarrer."
        save_trading_state(state)
        return state
    permission_granted, permission_reason = mt5_trading_permission()
    if not permission_granted:
        if state.get("reason") != permission_reason:
            log(permission_reason, "ERROR")
        state["enabled"] = False
        state["reason"] = permission_reason
        state["last_error"] = permission_reason
        save_trading_state(state)
        return state

    protection = payload.get("protection", {})
    active = payload.get("active_symbol")
    symbol = symbol_names.get(active)
    symbol_params = params.get("symbols", {}).get(active, {})
    access = payload.get("session_access", {}).get(active, {})

    gold_brain_enabled = bool(params.get("gold_brain_enabled", False))
    if gold_brain_enabled and symbol:
        # v5.1.0 -- observation continue : le panneau se remplit a chaque
        # cycle (meme cadence que le reste du moteur), independamment de
        # l'eligibilite du signal classique (tous les gates plus bas dans
        # cette fonction -- eligibilite, session, cadence, renfort... --
        # restent inchanges pour la VRAIE decision d'entree, plus loin dans
        # cette meme fonction, qui ecrase cet instantane avec record=True).
        try:
            state["gold_brain"] = gold_brain_snapshot(
                params, account, symbol, symbol_names, symbol_params,
                payload.get("analysis", {}).get(active, {}),
                payload.get("simulated_decision", {}),
                payload, positions, trades, record=False,
            )
            check_mission_target_slack(params, state["gold_brain"].get("mission"), state)
        except Exception as exc:  # noqa: BLE001 -- observation seule, ne doit jamais casser le cycle de trading
            log(f"Gold Brain (observation): {exc}", "ERROR")

    # v5.1.1 Phase 2 -- Market Scenario Engine, observation uniquement (regle
    # d'integration de Louis, 04/08/2026 : le flux doit exister reellement de
    # auto_trade_step() jusqu'au log, meme si l'execution reste desactivee).
    # Flag independant de gold_brain_enabled -- les deux peuvent tourner en
    # parallele sans interference, aucun n'ecrit sur les positions ici.
    if bool(params.get("scenario_engine_enabled", False)) and symbol:
        try:
            # task #170 (06/08/2026) -- contexte dedie du Scenario Engine, peut
            # differer du `timeframe` du pipeline classique (mode intraday 15m/1h).
            se_timeframe = str(params.get("scenario_engine_timeframe") or symbol_params.get("timeframe", "M5"))
            se_candles = fetch_candles(symbol, se_timeframe, 300)
            se_analysis = payload.get("analysis", {}).get(active, {})
            se_price = se_candles[-1]["close"] if se_candles else float(se_analysis.get("close") or 0)
            se_structure = structure_analyst_report(se_candles, se_price, timeframe=se_timeframe)
            se_smart_money = smart_money_analyst_report(se_candles, se_price)
            se_risk = risk_manager_report(params, account, symbol_names)
            se_econ = (
                economic_calendar_report(symbol, block_hours=float(params.get("economic_calendar_block_hours", 2.0) or 2.0))
                if bool(params.get("economic_calendar_enabled", True))
                else None
            )
            state["scenario"] = None
            scenario = scenario_engine_step(
                params, active, se_candles, se_price, se_structure, se_smart_money, se_risk, se_econ, se_analysis,
            )
            if scenario is not None:
                # v5.1.1 -- 05/08/2026, activation reelle demandee explicitement
                # par Louis (section 4). Appele juste apres scenario_engine_step()
                # (qui ne place lui-meme jamais d'ordre), avec tous les elements
                # de garde deja disponibles ici : bouton Demarrer (state["enabled"]
                # est garanti True a ce point, sinon la fonction serait deja
                # retournee plus haut), protection de session, confirmation compte
                # reel -- meme calcul que allow_real_entry plus bas dans cette
                # fonction pour le pipeline classique.
                try:
                    execute_scenario_anchor(
                        scenario, params, symbol_names, account, protection,
                        trading_enabled=bool(state.get("enabled")),
                        allow_real=bool(demo or state.get("real_confirmed")),
                        current_price=se_price,
                    )
                    close_scenario_anchor_if_needed(scenario, positions)
                    execute_scenario_scalp(
                        scenario, params, symbol_names, account, protection, se_price, se_risk, se_candles, se_analysis,
                        trading_enabled=bool(state.get("enabled")),
                        allow_real=bool(demo or state.get("real_confirmed")),
                    )
                except Exception as exc:  # noqa: BLE001 -- une erreur d'execution ne doit jamais casser le cycle
                    log(f"Scenario Engine (execution): {exc}", "ERROR")
                state["scenario"] = scenario.to_dict()
        except Exception as exc:  # noqa: BLE001 -- observation seule, ne doit jamais casser le cycle de trading
            log(f"Scenario Engine (observation): {exc}", "ERROR")

    # v5.1.1 chantier 3 -- Trading Style Engine, observation seule (meme regle
    # d'integration que le Scenario Engine ci-dessus). Flag independant --
    # peut tourner seul, avec le Scenario Engine, ou avec Gold Brain, sans
    # interference (aucun n'ecrit sur les positions ici). Reutilise
    # se_candles/se_structure du bloc precedent s'ils existent deja (evite un
    # double fetch MT5 quand les deux moteurs sont actifs), sinon les calcule.
    if bool(params.get("trading_style_engine_enabled", False)) and symbol:
        try:
            ts_candles = se_candles if "se_candles" in locals() else fetch_candles(symbol, str(symbol_params.get("timeframe", "M5")), 300)
            ts_structure = se_structure if "se_structure" in locals() else structure_analyst_report(
                ts_candles, ts_candles[-1]["close"] if ts_candles else 0.0, timeframe=str(symbol_params.get("timeframe", "M5")),
            )
            ts_entry = trading_style_engine_step(params, ts_structure, ts_candles)
            state["trading_style"] = ts_entry
            if ts_entry is not None:
                apply_trading_style_recommendation(ts_entry, params)
        except Exception as exc:  # noqa: BLE001 -- une erreur d'adaptation ne doit jamais casser le cycle de trading
            log(f"Trading Style Engine: {exc}", "ERROR")

    bot_positions = [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
    contexts = position_contexts()

    # v5.1.1 chantier 4 -- Portfolio Brain, observation seule (meme regle
    # d'integration que les autres chantiers post-Scenario-Engine). Utilise
    # TOUTES les positions BOT du symbole actif (y compris rebond/renfort --
    # contrairement a symbol_main_positions plus bas, qui les exclut
    # deliberement du comptage "nouvelles entrees") : le panier, c'est bien
    # l'exposition reelle deja ouverte, tous types confondus.
    if bool(params.get("portfolio_brain_enabled", False)) and active:
        try:
            basket_positions = [p for p in bot_positions if p.get("symbol_key") == active]
            equity = float(account.equity) if account else 0.0
            state["portfolio"] = portfolio_brain_report(params, basket_positions, equity).to_dict()
        except Exception as exc:  # noqa: BLE001 -- observation seule, ne doit jamais casser le cycle de trading
            log(f"Portfolio Brain (observation): {exc}", "ERROR")

    # Protection portefeuille : perte flottante totale par symbole (max_floating_loss)
    floating_breach: set[str] = set()
    floating_by_symbol: dict[str, float] = {}
    for position in bot_positions:
        key = str(position.get("symbol_key") or "")
        floating_by_symbol[key] = floating_by_symbol.get(key, 0.0) + float(position.get("profit") or 0)
    for key, floating in floating_by_symbol.items():
        limit = float(params.get("symbols", {}).get(key, {}).get("max_floating_loss", 0) or 0)
        if limit > 0 and floating <= -abs(limit):
            floating_breach.add(key)

    for position in bot_positions:
        pos_params = params.get("symbols", {}).get(position.get("symbol_key"), {})
        profit = float(position.get("profit") or 0)
        context = contexts.get(str(position.get("ticket")), {})
        peak = max(profit, float(context.get("max_profit") or profit))
        age = max(0, time.time() - float(position.get("open_timestamp") or time.time()))
        position_analysis = payload.get("analysis", {}).get(position.get("symbol_key"), {})
        if position.get("symbol_key") in floating_breach:
            close_reason = "MAX_FLOATING_LOSS"
        else:
            close_reason = position_exit_reason(
                position,
                pos_params,
                position_analysis,
                str(protection.get("state") or ""),
                str(payload.get("session_access", {}).get(position.get("symbol_key"), {}).get("state") or ""),
                peak,
                age,
            )
        if close_reason:
            ok, message = close_bot_position(position, close_reason)
            if ok:
                log_trade_exit(
                    ticket=int(position.get("ticket", 0)),
                    symbol_key=str(position.get("symbol_key", "")),
                    direction=str(position.get("direction", "")),
                    open_timestamp=float(position.get("open_timestamp") or 0),
                    reason=close_reason,
                    profit=float(position.get("profit") or 0),
                    peak_profit=peak,
                    age=age,
                )
            if "en attente avant nouvelle tentative" not in message:
                log(message, "SUCCESS" if ok else "ERROR")
            state["last_action"] = message
            if not ok:
                state["last_error"] = message
            save_trading_state(state)
            return state

    now = time.time()
    # Exclure les positions secondaires (rebonds) du comptage
    rebond_tickets = {int(s.get("ticket") or 0) for s in REBOND_STATES}
    drift_ticket = 0
    symbol_bot_positions = [
        p for p in bot_positions
        if p.get("symbol_key") == active
        and int(p.get("ticket", 0)) not in rebond_tickets
        and int(p.get("ticket", 0)) != drift_ticket
    ]
    # Pour le comptage max, on compte TOUTES les positions principales
    # (pas seulement dans le sens du signal actuel)
    symbol_main_positions = symbol_bot_positions
    max_positions = max(
        1,
        min(
            HARD_AUTO_POSITION_CAP,
            int(params.get("auto_max_positions", 2)),
            int(symbol_params.get("max_positions", 5)),
        ),
    )
    # Réserver 1 slot pour le rebond
    rebond_enabled = bool(params.get("rebond_enabled", False))
    effective_max = max(1, max_positions - 1) if rebond_enabled and max_positions > 1 else max_positions
    if len(symbol_main_positions) >= effective_max:
        state["reason"] = f"Max {effective_max} positions sur {active} (1 réservé rebond)."
        save_trading_state(state)
        return state

    decision = payload.get("simulated_decision", {})
    if not symbol or not decision.get("eligible"):
        reason = str(decision.get("reason") or "Aucun signal eligible.")
        log_reason_throttled("decision_blocked", reason)
        state["reason"] = reason
        save_trading_state(state)
        return state
    if not access.get("entries_allowed"):
        state["reason"] = str(access.get("reason") or "Session fermee.")
        save_trading_state(state)
        return state

    cadence = max(1, int(symbol_params.get("cadence_sec", 30)))
    last_attempt = max(
        float(state.get("last_entry_at", 0)),
        float(state.get("last_attempt_at", 0)),
    )
    if now - last_attempt < cadence:
        state["reason"] = "Cadence minimale en cours."
        save_trading_state(state)
        return state
    entry_times = [value for value in state.get("entry_times", []) if now - float(value) < 3600]
    max_hour = max(1, int(symbol_params.get("max_trades_hour", 120)))
    if len(entry_times) >= max_hour:
        state["reason"] = "Limite de trades par heure atteinte."
        state["entry_times"] = entry_times
        save_trading_state(state)
        return state

    analysis = payload.get("analysis", {}).get(active, {})
    if symbol_main_positions:
        directions = {position.get("direction") for position in symbol_main_positions}
        if str(decision.get("signal")) not in directions:
            state["reason"] = "Signal oppose a la position principale ouverte; nouvelle entree bloquee."
            save_trading_state(state)
            return state
        if not bool(params.get("reinforcement_enabled", True)):
            state["reason"] = "Renfort desactive dans les parametres."
            save_trading_state(state)
            return state
        # Renfort desactive pour CE signal precis, choisi depuis Strategy Lab
        # au moment de l'envoi (voir external_signal_entry_decision -- encode
        # dans le commentaire MT5 de la position via position_type="STRATLABX",
        # pas dans un etat local separe a synchroniser). Les reglages globaux
        # de renfort (seuils, marge, cooldown) restent inchanges pour tout le
        # reste -- seul ce signal precis est mis hors renfort.
        if any("stratlabx" in str(position.get("comment") or "").lower() for position in symbol_main_positions):
            state["reason"] = "Renfort desactive pour ce signal Strategy Lab."
            save_trading_state(state)
            return state
        first_profit = max(float(position.get("profit") or 0) for position in symbol_main_positions)
        threshold = float(analysis.get("learned_threshold") or symbol_params.get("confidence_min", 62))
        confidence = float(analysis.get("confidence") or 0)
        margin = max(1.0, float(params.get("reinforcement_min_confidence_margin", 5)))
        required_gap = max(1.0, float(params.get("reinforcement_min_score_gap", 15)))
        trend = str(analysis.get("trend") or "RANGE")
        fast_signal = str(analysis.get("fast_signal") or "WAIT")
        signal = str(decision.get("signal") or "WAIT")
        trend_confirms = (
            (signal == "BUY" and trend == "BULLISH")
            or (signal == "SELL" and trend == "BEARISH")
        )
        score_gap = float(analysis.get("score_gap") or 0)
        if first_profit < 0 and not (
            confidence >= threshold + margin
            and score_gap >= required_gap
        ):
            state["reason"] = "Renfort refuse: signal insuffisant pour renforcer en negatif."
            save_trading_state(state)
            return state
        newest_open = max(float(position.get("open_timestamp") or 0) for position in symbol_main_positions)
        reinforcement_pause = max(10, int(params.get("reinforcement_cooldown_sec", 30)))
        if newest_open and now - newest_open < reinforcement_pause:
            state["reason"] = f"Renfort en attente: {int(reinforcement_pause - (now - newest_open))} s."
            save_trading_state(state)
            return state
    learned = payload.get("learning", {}).get("symbols", {}).get(active, {})
    if learned.get("last_outcome") == "LOSS" and learned.get("last_closed_at"):
        try:
            closed_at = datetime.fromisoformat(str(learned["last_closed_at"]))
            if closed_at.tzinfo is None:
                closed_at = closed_at.astimezone()
            elapsed = (datetime.now(timezone.utc) - closed_at.astimezone(timezone.utc)).total_seconds()
            cooldown = max(0, int(symbol_params.get("cooldown_after_loss_sec", 75)))
            if elapsed < cooldown:
                state["reason"] = f"Pause apres perte: {int(cooldown - elapsed)} s restantes."
                save_trading_state(state)
                return state
        except ValueError:
            pass
    lot_info = payload.get("lot_safety", {}).get(active, {})
    # Renfort: lot de base par défaut. lot_multiplicateur_renfort s'applique
    # uniquement si la confiance IA dépasse le seuil + la même marge de
    # confiance que le renfort en négatif (reinforcement_min_confidence_margin,
    # désormais partagée entre les deux gates — fusion du 17/07/2026).
    if symbol_main_positions:
        mult_renfort = float(symbol_params.get("lot_multiplicateur_renfort", 1.0))
        if mult_renfort > 1.0:
            conf_renfort = float(analysis.get("confidence") or 0)
            thresh_renfort = float(analysis.get("learned_threshold") or symbol_params.get("confidence_min", 62))
            high_conf_min = thresh_renfort + margin
            if conf_renfort >= high_conf_min:
                base = float(lot_info.get("effective_lot", 0))
                # 06/08/2026 -- account_cap retire de lot_safety_state() (voir
                # sa docstring) : plus de plafond manuel a appliquer ici non plus.
                renfort_lot = round(base * mult_renfort, 8)
                broker_min = float(lot_info.get("broker_min", 0))
                if renfort_lot >= max(0.001, broker_min):
                    lot_info = {**lot_info, "effective_lot": renfort_lot, "reason": f"Renfort x{mult_renfort} (confiance {conf_renfort:.1f}%)"}

    approved_by_server, server_reply = server_trade_confirmation(
        params,
        active,
        symbol,
        decision,
        analysis,
        payload,
        positions,
        lot_info,
    )
    state["last_server_decision"] = server_reply
    if not approved_by_server:
        reason = str(server_reply.get("reason") or "Entree bloquee par validation IA serveur.")
        server_signal = str(server_reply.get("decision") or "WAIT")
        server_confidence = float(server_reply.get("confidence") or 0)
        message = f"Validation IA serveur: {server_signal} {server_confidence:.1f}% - {reason}"
        log_reason_throttled("server_validation_blocked", message)
        state["reason"] = message
        save_trading_state(state)
        return state
    state["last_attempt_at"] = now
    save_trading_state(state)
    # position_type encode l'origine (STRATLAB) et, pour les signaux Strategy
    # Lab uniquement, si le Renfort reste autorise sur CETTE position -- lu
    # plus tard directement depuis le commentaire MT5 par le gate de renfort
    # (aucun etat local supplementaire a maintenir, le commentaire suit deja
    # la position pendant toute sa duree de vie).
    if str(decision.get("engine")) == "external_signal":
        entry_position_type = "STRATLAB" if decision.get("allow_reinforcement", True) else "STRATLABX"
    else:
        entry_position_type = "NORMAL"

    allow_real_entry = bool(demo or state.get("real_confirmed"))
    if not gold_brain_enabled:
        # Comportement inchange -- defaut, strictement identique a avant v5.1.0.
        ok, message, _ = open_position(
            active, symbol, str(decision.get("signal")), params, lot_info, analysis,
            allow_real_entry, position_type=entry_position_type,
        )
    else:
        # v5.1.0 -- CAIO v1 arbitre en dernier ressort avant execution (Regle
        # d'or : seul le CAIO decide, seul place_order() execute). N'ecrase
        # aucun des filtres deja passes ci-dessus (renfort, cooldown, session,
        # validation IA serveur) -- les complete d'un avis independant
        # Structure/Smart Money/Risk avant le dernier geste. record=True ici :
        # c'est une vraie tentative d'entree (contrairement au passage
        # d'observation plus haut dans cette fonction), donc tracee dans
        # learning_history. Ecrase l'instantane d'observation avec cette
        # decision plus significative pour l'onglet Gold Brain.
        snapshot = gold_brain_snapshot(
            params, account, symbol, symbol_names, symbol_params, analysis, decision,
            payload, positions, trades, record=True,
        )
        state["gold_brain"] = snapshot
        # Log persistant (02/08/2026, suite audit statistique complet) --
        # learning_history (shared_memory.py) n'est qu'un instantane RAM, ecrase
        # a chaque nouvelle decision et perdu au redemarrage : impossible de savoir
        # retrospectivement quel trade a ete decide par Gold Brain plutot que par
        # l'ancien pipeline. caio_decisions.jsonl comble ce trou, meme convention
        # append-only que learning_events.jsonl/trade_exits.jsonl. Pas de ticket MT5
        # ici (aucune des deux fonctions d'execution ne le retourne aujourd'hui) --
        # correlation avec trades.json/alphatrade.db par horodatage + symbole +
        # direction, a la precision pres du cycle (quelques secondes).
        if snapshot["decision"] != "GO":
            state["reason"] = f"Gold AI Brain: {snapshot['raison']}"
            append_jsonl("caio_decisions.jsonl", {
                "timestamp": utc_now(),
                "symbol_key": active,
                "decision": "NO_TRADE",
                "source_agent": snapshot.get("source_agent"),
                "raison": snapshot.get("raison"),
                "order_attempted": False,
            })
            save_trading_state(state)
            return state
        ok, message, _ = place_order(
            active, symbol, snapshot["order_type"], params, lot_info, analysis,
            allow_real_entry, price_hint=snapshot.get("price"), position_type=entry_position_type,
        )
        winner_confidence = float(
            (snapshot.get("reports", {}).get(snapshot.get("source_agent"), {}) or {}).get("confidence", 0) or 0
        )
        append_jsonl("caio_decisions.jsonl", {
            "timestamp": utc_now(),
            "symbol_key": active,
            "decision": "GO",
            "order_type": snapshot.get("order_type"),
            "source_agent": snapshot.get("source_agent"),
            "raison": snapshot.get("raison"),
            "price": snapshot.get("price"),
            "confidence": winner_confidence,
            "order_attempted": True,
            "order_ok": ok,
            "order_message": message,
        })
        if ok:
            if winner_confidence >= float(params.get("slack_min_confidence", 70)):
                notify_slack(
                    params, "caio_go", SLACK_GREEN if str(snapshot["order_type"]).startswith("BUY") else SLACK_RED,
                    *blocks_caio_go(active, snapshot["order_type"], snapshot.get("price"), snapshot.get("source_agent"), snapshot.get("raison")),
                )
    log(message, "SUCCESS" if ok else "ERROR")
    state["last_action"] = message
    state["reason"] = message
    if ok:
        state["last_entry_at"] = now
        state["entry_times"] = [*entry_times, now]
        state["last_error"] = ""
    else:
        state["last_error"] = message
    save_trading_state(state)

    # ── Module Capture Rebond ──────────────────────────────────────────────────
    # Exécuté après la logique principale. Gère les positions contra-tendance
    # sur rebonds sans interférer avec la position principale.
    if symbol and active and bool(params.get("rebond_enabled", False)):
        rebond_result = auto_rebond_step(
            params,
            active,
            symbol,
            positions,
            payload.get("analysis", {}).get(active, {}),
            bool(demo or state.get("real_confirmed")),
            demo,
            main_lot=float(payload.get("lot_safety", {}).get(active, {}).get("effective_lot") or 0),
        )
        state["rebond"] = rebond_result
        save_trading_state(state)
    # ── Fin module Capture Rebond ──────────────────────────────────────────────

    return state


def fast_confirmation_state(
    signal: str,
    fast_signal: str,
    trend: str,
    confidence: float,
    confidence_min: float,
    score_gap: float,
    min_score_gap: float,
) -> tuple[bool, bool]:
    if signal not in {"BUY", "SELL"}:
        return False, False
    if fast_signal in {signal, "WAIT"}:
        return False, False
    # Si le fast_signal est dans le sens contraire mais que la confiance
    # principale est très forte (≥ confidence_min + 10) → on laisse passer
    # pour que le module Capture Rebond puisse gérer le rebond
    if confidence >= confidence_min + 10:
        return False, True
    trend_confirms = (
        (signal == "BUY" and trend == "BULLISH")
        or (signal == "SELL" and trend == "BEARISH")
    )
    strong_primary_signal = bool(
        trend_confirms
        and confidence >= confidence_min + 6
        and score_gap >= min_score_gap * 2
    )
    return not strong_primary_signal, strong_primary_signal


def status_payload(params: dict, symbol_names: dict[str, str], trades: list[dict], positions: list[dict]) -> dict:
    account = mt5.account_info() if mt5 else None
    learning = load_learning_state()
    status_symbols = {}
    analyses = {}
    for key, name in symbol_names.items():
        tick = mt5.symbol_info_tick(name) if mt5 else None
        info = mt5.symbol_info(name) if mt5 else None
        tick_price = float(tick.bid) if tick else 0
        spread = round(float(tick.ask - tick.bid), 2) if tick else 0
        sym_trades = [t for t in trades if t.get("symbol_key") == key]
        sym_positions = [p for p in positions if p.get("symbol_key") == key]
        status_symbols[key] = {
            "name": name,
            "label": SYMBOLS[key]["label"],
            "price": round(tick_price, 2),
            "spread": spread,
            "trade_mode": int(info.trade_mode) if info else None,
            "positions": sym_positions,
            "stats": stats(sym_trades, sym_positions),
            "candles": symbol_candles(name, params.get("symbols", {}).get(key, {})),
        }
        analyses[key] = symbol_analysis(
            name,
            {**params, **params.get("symbols", {}).get(key, {})},
            key,
            learning,
        )

    all_stats = stats(trades, positions)
    bot_stats = stats([t for t in trades if t.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")], [p for p in positions if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")])
    external_stats = stats(
        [t for t in trades if t.get("origin") == "EXTERNAL_AI"],
        [p for p in positions if p.get("origin") == "EXTERNAL_AI"],
    )
    manual_stats = stats(
        [t for t in trades if t.get("origin") == "MANUAL"],
        [p for p in positions if p.get("origin") == "MANUAL"],
    )
    today_stats = daily_stats(trades, positions)
    account_login = int(account.login) if account else None
    session_stats = application_session_stats(trades, positions, account_login)
    protection = protection_state(params, session_stats, account_login)
    lot_safety = lot_safety_state(params, account, symbol_names)
    access = {
        key: session_access(key, params.get("symbols", {}).get(key, {}))
        for key in SYMBOLS
    }
    active = params.get("active_symbol", "XAUUSD")
    if active not in symbol_names and symbol_names:
        active = next(iter(symbol_names.keys()))
    active_analysis = analyses.get(active, {})
    active_access = access.get(active, {"state": "CLOSED", "entries_allowed": False, "reason": "Actif indisponible."})
    active_lot_safety = lot_safety.get(active, {"rejected": True, "reason": "Lot non valide."})
    # v5.1.1 -- 05/08/2026, application reelle du Portfolio Brain (demande
    # explicite de Louis : "plus rien ne doit rester en simulation"). Calcule
    # ici (pas seulement dans auto_trade_step(), qui tourne APRES et
    # consommerait un `eligible` deja fige) pour que le blocage agisse
    # vraiment sur la decision d'entree du pipeline classique, pas seulement
    # sur l'affichage du panneau Portfolio Brain.
    portfolio_bot_positions = [
        p for p in positions
        if p.get("symbol_key") == active and p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
    ]
    portfolio_exposure = basket_exposure(portfolio_bot_positions, float(account.equity) if account else 0.0)
    portfolio_assessment = portfolio_risk_assessment(
        portfolio_exposure,
        max_positions=int(params.get("portfolio_max_positions", 5)),
        max_total_lot=float(params.get("portfolio_max_total_lot", 0.0) or 0.0),
        floating_loss_warn_pct=float(params.get("portfolio_floating_loss_warn_pct", 2.0)),
        floating_loss_critical_pct=float(params.get("portfolio_floating_loss_critical_pct", 5.0)),
    )
    portfolio_blocks = (
        bool(params.get("portfolio_brain_enabled", False))
        and portfolio_assessment["action"] in ("LIMIT_NEW_ENTRIES", "REDUCE_EXPOSURE")
    )
    protection_blocks = protection["state"] in {"WARNING", "HARD_LOCK", "TARGET_REACHED"} or portfolio_blocks
    # Expose au reste du pipeline (execute_scenario_anchor()/execute_scenario_scalp(),
    # qui recoivent ce meme dict `protection` via payload) sans surcharger
    # `state`, qui reste le vocabulaire de la protection de session -- le
    # panier est une raison de blocage distincte, pas un nouvel etat de session.
    protection["portfolio_blocks"] = portfolio_blocks
    protection["portfolio_reasons"] = portfolio_assessment["reasons"]
    lot_blocks = bool(active_lot_safety.get("rejected"))
    confidence_min = float(
        active_analysis.get("learned_threshold")
        or params.get("symbols", {}).get(active, {}).get(
            "confidence_min",
            params.get("confidence_min", 62),
        )
    )
    signal = active_analysis.get("signal", "WAIT")
    confidence = float(active_analysis.get("confidence", 0) or 0)
    score_gap = float(active_analysis.get("score_gap", 0) or 0)
    min_score_gap = max(3.0, float(params.get("min_score_gap", 8)))
    edge_position = float(active_analysis.get("edge_position", 50) or 50)
    edge_limit = max(5.0, min(45.0, float(params.get("edge_zone_pct", 20))))
    fast_signal = str(active_analysis.get("fast_signal", "WAIT"))
    trend = str(active_analysis.get("trend", "RANGE"))
    rsi_value = float(active_analysis.get("rsi", 50) or 50)
    decision_signal = signal
    decision_confidence = confidence
    reversal_signal = str(active_analysis.get("reversal_signal", "WAIT"))
    reversal_confidence = float(active_analysis.get("reversal_confidence", 0) or 0)
    reversal_reason = str(active_analysis.get("reversal_reason", ""))
    edge_blocks = bool(
        params.get("anti_top_bottom", True)
        and (
            (signal == "BUY" and edge_position >= 100 - edge_limit)
            or (signal == "SELL" and edge_position <= edge_limit)
        )
    )
    reversal_min = max(
        52.0,
        confidence_min - float(params.get("symbols", {}).get(active, {}).get("signal_reversal_margin", 7)),
    )
    reversal_trend_ok = bool(
        trend == "RANGE"
        or (reversal_signal == "BUY" and trend == "BULLISH")
        or (reversal_signal == "SELL" and trend == "BEARISH")
    )
    reversal_fast_ok = bool(fast_signal in {reversal_signal, "WAIT"})
    reversal_applied = bool(
        edge_blocks
        and reversal_signal in {"BUY", "SELL"}
        and reversal_signal != signal
        and reversal_confidence >= reversal_min
        and reversal_trend_ok
        and reversal_fast_ok
    )
    if reversal_applied:
        decision_signal = reversal_signal
        decision_confidence = reversal_confidence
        edge_blocks = False
    fast_blocks, fast_override = fast_confirmation_state(
        decision_signal,
        fast_signal,
        trend,
        decision_confidence,
        confidence_min,
        score_gap,
        min_score_gap,
    )
    if reversal_applied and fast_blocks and fast_signal == signal:
        fast_blocks = False
        fast_override = True
    rsi_extreme = bool(
        (decision_signal == "BUY" and rsi_value >= 70)
        or (decision_signal == "SELL" and rsi_value <= 30)
    )
    rsi_hard_extreme = bool(
        (decision_signal == "BUY" and rsi_value >= 88)
        or (decision_signal == "SELL" and rsi_value <= 12)
    )
    direction_trend_confirms = bool(
        (decision_signal == "BUY" and trend == "BULLISH")
        or (decision_signal == "SELL" and trend == "BEARISH")
    )
    strategy_mode = str(params.get("strategy_mode") or "scalping_fast")
    mtf_bias = str(active_analysis.get("multi_timeframe_bias") or "RANGE")
    quant_veto = bool(active_analysis.get("quant_veto"))
    mtf_blocks = bool(
        strategy_mode in {"combined", "long_analysis"}
        and mtf_bias in {"BULLISH", "BEARISH"}
        and (
            (decision_signal == "BUY" and mtf_bias == "BEARISH")
            or (decision_signal == "SELL" and mtf_bias == "BULLISH")
        )
        and not reversal_applied
    )
    rsi_override = bool(
        rsi_extreme
        and not rsi_hard_extreme
        and fast_signal == decision_signal
        and direction_trend_confirms
        and decision_confidence >= confidence_min + 12
        and score_gap >= min_score_gap * 2
    )
    rsi_blocks = rsi_extreme and not rsi_override
    gap_blocks = decision_signal in {"BUY", "SELL"} and score_gap < min_score_gap and not reversal_applied
    eligible = bool(
        decision_signal in {"BUY", "SELL"}
        and active_access.get("entries_allowed")
        and not protection_blocks
        and not lot_blocks
        and not edge_blocks
        and not rsi_blocks
        and not fast_blocks
        and not gap_blocks
        and not mtf_blocks
        and not quant_veto
    )
    if quant_veto:
        decision_reason = (
            f"Entree bloquee par le gouverneur quantitatif: risque de regime "
            f"{float(active_analysis.get('quant_regime_risk', 0)):.0f}%."
        )
    elif protection_blocks:
        decision_reason = (
            f"Portfolio Brain: {'; '.join(portfolio_assessment['reasons'])}"
            if portfolio_blocks and not (protection["state"] in {"WARNING", "HARD_LOCK", "TARGET_REACHED"})
            else protection["reason"]
        )
    elif lot_blocks:
        decision_reason = active_lot_safety.get("reason")
    elif not active_access.get("entries_allowed"):
        decision_reason = active_access.get("reason")
    elif edge_blocks:
        if reversal_signal in {"BUY", "SELL"} and reversal_signal != signal:
            decision_reason = (
                f"Entree bloquee: {signal} en zone extreme; reanalyse {reversal_signal} "
                f"insuffisante ({reversal_confidence:.1f}% / {reversal_min:.1f}%)."
            )
        else:
            decision_reason = "Entree bloquee: achat en zone haute ou vente en zone basse; inverse non confirme."
    elif reversal_applied:
        decision_reason = reversal_reason or f"Zone extreme: reanalyse inverse en {decision_signal}."
    elif rsi_blocks:
        decision_reason = f"Entree bloquee: RSI {rsi_value:.1f} en zone extreme."
    elif rsi_override:
        decision_reason = (
            f"Signal {decision_signal} fort confirme: RSI {rsi_value:.1f} eleve, "
            "mais tendance et confirmation rapide concordantes."
        )
    elif fast_blocks:
        decision_reason = f"Entree bloquee: signal principal {signal}, confirmation rapide {fast_signal}."
    elif gap_blocks:
        decision_reason = f"Entree bloquee: ecart BUY/SELL {score_gap:.1f}, minimum {min_score_gap:.1f}."
    elif mtf_blocks:
        decision_reason = f"Entree bloquee: mode {strategy_mode}, tendance large {mtf_bias} contre {decision_signal}."
    elif decision_signal == "WAIT":
        decision_reason = (
            f"En attente d'un signal: confiance {decision_confidence:.1f}%, "
            f"seuil requis {confidence_min:.1f}%."
        )
    elif fast_override:
        decision_reason = (
            f"Signal {signal} fort et tendance {trend}: "
            f"entree autorisee malgre le rebond rapide {fast_signal}."
        )
    else:
        decision_reason = f"Signal {decision_signal} eligible a {decision_confidence:.1f}%."
    simulated_decision = {
        "mode": "SIMULATION",
        "symbol": active,
        "signal": decision_signal,
        "raw_signal": signal,
        "confidence": decision_confidence,
        "raw_confidence": confidence,
        "confidence_min": confidence_min,
        "fast_signal": fast_signal,
        "fast_override": fast_override,
        "rsi_override": rsi_override,
        "reversal_applied": reversal_applied,
        "reversal_min": round(reversal_min, 1),
        "reversal_reason": reversal_reason,
        "strategy_mode": strategy_mode,
        "multi_timeframe_bias": mtf_bias,
        "score_gap": score_gap,
        "min_score_gap": min_score_gap,
        "eligible": eligible,
        "reason": decision_reason,
        "engine": "alphatrade_ai",
    }
    active_engine = str(params.get("active_engine") or "alphatrade_ai")
    if active_engine == "external_signal":
        # Garde-fou valide avec Louis (22/07/2026) : un signal externe ne peut
        # ouvrir une vraie position en mode REEL que si external_signals_allow_real
        # est actif -- ce parametre n'est jamais dans REMOTE_PARAM_ALLOWLIST
        # (electron/main.js), donc uniquement modifiable localement sur ce PC.
        is_real_mode = bool(account) and not ("demo" in str(account.server).lower() or int(account.trade_mode) == 0)
        if is_real_mode and not bool(params.get("external_signals_allow_real", False)):
            # Consomme quand meme le signal en attente (sinon il resterait en
            # file et se declencherait plus tard si le parametre est active),
            # mais ne l'utilise jamais pour decider une entree en mode REEL.
            external_signal_entry_decision(active, params)
            simulated_decision = {
                "symbol": active, "signal": "WAIT", "confidence": 0, "eligible": False,
                "reason": "Signaux externes desactives en mode reel (activez-le dans Parametres).",
                "engine": "external_signal",
            }
        else:
            simulated_decision = external_signal_entry_decision(active, params)
    return {
        "version": VERSION,
        "state": "connected" if account else "disconnected",
        "mode": "DEMO" if account and ("demo" in str(account.server).lower() or int(account.trade_mode) == 0) else "REAL" if account else "-",
        "account": int(account.login) if account else None,
        "server": str(account.server) if account else "",
        "balance": round(float(account.balance), 2) if account else 0,
        "equity": round(float(account.equity), 2) if account else 0,
        "margin": round(float(account.margin), 2) if account else 0,
        "free_margin": round(float(account.margin_free), 2) if account else 0,
        "active_symbol": active,
        "strategy_profile": params.get("strategy_profile", {}),
        # v5.1.0 -- source de verite unique exposee au frontend, corrige la
        # desync deja documentee (audit Phase 3) entre STRATEGY_PROFILES
        # (Python), strategyProfiles (renderer.js, valeurs differentes) et les
        # <option> d'index.html. Le frontend doit lire ce champ plutot que
        # garder sa propre copie locale.
        "strategy_profiles": STRATEGY_PROFILES,
        "gold_brain_version": GOLD_BRAIN_VERSION,
        "symbols": status_symbols,
        "analysis": analyses,
        "learning": learning,
        "ai_server": AI_SERVER_STATE,
        "signal": active_analysis.get("signal", "WAIT"),
        "confidence": active_analysis.get("confidence", 0),
        "score_buy": active_analysis.get("score_buy", 0),
        "score_sell": active_analysis.get("score_sell", 0),
        "stats": all_stats,
        "session_stats": session_stats,
        "origin_stats": {
            "ALPHATRADE": bot_stats,
            "EXTERNAL_AI": external_stats,
            "MANUAL": manual_stats,
        },
        "today_stats": today_stats,
        "protection": protection,
        "lot_safety": lot_safety,
        "session_access": access,
        "simulated_decision": simulated_decision,
        "ai_adaptations": recent_ai_adaptations(),
        # 06/08/2026 -- Louis : "les ecrans dans parametres qui n'actualisent
        # pas". Root cause : la carte "Pilote par l'IA" (renderIntelCards(),
        # renderer.js) lit le params JS global, qui n'etait rempli qu'UNE
        # SEULE FOIS par fillSettings() au demarrage -- jamais rafraichi par
        # le flux status-update (contrairement au footer "Calibre/Jamais
        # ajuste", deja branche sur ai_adaptations juste au-dessus). Un
        # calibrage cote Python (calibrate_scenario_thresholds()) restait
        # donc invisible tant que l'app n'etait pas redemarree. Liste
        # explicite (pas tout `params`, qui contient des tableaux/dicts bien
        # plus lourds type take_profit_levels/symbols) des seuls champs
        # reellement affiches par cette carte.
        "live_params": {
            k: params.get(k)
            for k in (
                "scenario_caio_min_confidence",
                "scenario_london_min_confidence",
                "scenario_health_degradation_threshold",
                "scenario_scalp_cooldown_sec",
                "scenario_scalp_max_count",
                "scenario_scalp_lot_ratio",
                "scenario_block_correction_regime",
                "portfolio_floating_loss_warn_pct",
                "portfolio_floating_loss_critical_pct",
                "scenario_engine_execution_enabled",
                "scenario_engine_enabled",
            )
        },
        "auto_backtest": read_json("auto_backtest_result.json", None),
        "positions": positions,
        "timestamp": int(time.time()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AlphaTrade MT5 monitoring engine")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Write one status/history snapshot, then exit.",
    )
    parser.add_argument(
        "--replay-days",
        type=int,
        default=0,
        help="Scenario Replay (v5.1.1) -- rejoue N jours d'historique MT5 dans scenario_replay_log.jsonl, puis quitte. Aucun ordre reel.",
    )
    parser.add_argument(
        "--learn",
        action="store_true",
        help="Scenario Learning (v5.1.1, Phase 5) -- calcule scenario_learned_weights.json depuis les logs existants, puis quitte. Aucun acces MT5 necessaire.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log(f"AlphaTrade engine v{VERSION} - data: {DATA_DIR}")
    params = effective_params_for_strategy(merge_params())

    if args.learn:
        # v5.1.1 Phase 5 -- ne touche jamais MT5, lit uniquement les logs deja
        # sur disque. Quitte immediatement apres, meme discipline que --replay-days.
        run_scenario_learning()
        return 0

    conn = db_conn()
    microstructure = MicrostructureObserver(DATA_DIR)

    if mt5 is None:
        log(f"MetaTrader5 indisponible: {MT5_IMPORT_ERROR}", "ERROR")
        write_json(
            "status.json",
            {
                "version": VERSION,
                "state": "missing_mt5",
                "error": MT5_IMPORT_ERROR,
                "timestamp": int(time.time()),
                "stats": stats([], []),
                "positions": [],
                "symbols": {},
                "analysis": {},
            },
        )
        return 3 if args.once else wait_for_stop_without_mt5()

    if not initialize_mt5(params):
        log(f"MT5 initialize refuse: {mt5.last_error()}", "ERROR")
        return 2

    account = mt5.account_info()
    log(f"MT5 connecte - compte {account.login if account else '?'} - serveur {account.server if account else '?'}")
    account_key = (int(account.login), str(account.server)) if account else None
    symbol_names = {}
    _startup_params = merge_params()
    for key in SYMBOLS:
        _sym_enabled = _startup_params.get("symbols", {}).get(key, {}).get("enabled", True)
        if not _sym_enabled:
            log(f"Symbole {key} desactive (enabled=false dans les parametres).", "INFO")
            continue
        name = resolve_symbol(key)
        if name:
            symbol_names[key] = name
            log(f"Symbole disponible sur MT5: {key} -> {name}", "SUCCESS")
        else:
            log(f"Symbole introuvable sur MT5: {key}", "WARNING")

    if args.replay_days > 0:
        # v5.1.1 -- Scenario Replay : mode one-off, ne touche jamais a
        # trading_state.json ni a la session live, quitte immediatement apres.
        run_scenario_replay(params, symbol_names, args.replay_days)
        return 0

    if not args.once:
        # Le baseline de session doit inclure le flottant réel des positions
        # bot déjà ouvertes AVANT ce redémarrage, sinon session_max_loss
        # (comparé à session_profit dans protection_state) considère ce
        # flottant comme une perte "de cette session" et ferme la position
        # immédiatement au premier cycle — corrigé le 17/07/2026.
        _startup_positions = live_positions(symbol_names, _startup_params)
        _startup_bot_floating = sum(
            float(p.get("profit") or 0) for p in _startup_positions
            if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
        )
        reset_session_state(int(account.login) if account else None, _startup_bot_floating)
        log("Nouvelle session AlphaTrade ouverte; historique MT5 conserve.", "SUCCESS")
    startup_state = load_trading_state()
    startup_state["enabled"] = False
    startup_state["real_confirmed"] = False
    startup_state["reason"] = "Application ouverte en lecture MT5. Cliquez sur Demarrer pour autoriser les nouvelles positions."
    save_trading_state(startup_state)

    # Précharger l'historique de chaque symbole au démarrage.
    # MT5 télécharge les données de façon asynchrone après symbol_select — sans ce
    # premier appel, copy_rates_from_pos retourne None pendant les premières minutes,
    # ce qui force l'analyse en mode COLLECTING (BUY/SELL = 0%).
    for _key, _name in symbol_names.items():
        _sym_params = {**params, **params.get("symbols", {}).get(_key, {})}
        _tf = tf_const(_sym_params.get("timeframe", "M1"))
        _rates = mt5.copy_rates_from_pos(_name, _tf, 0, 300)
        if _rates is None or len(_rates) < 30:
            log(f"Historique {_key} en cours de telechargement — analyse disponible sous 30s.", "INFO")
        else:
            log(f"Historique {_key} pret: {len(_rates)} bougies chargees.", "SUCCESS")

    last_history = 0.0
    last_auto_backtest_check = 0.0
    last_ai_sync = 0.0
    last_microstructure = 0.0
    gold_microstructure_snapshot_cache: dict = {"available": False, "reason": "Pas encore calcule."}
    last_hyperliquid = 0.0
    ai_bootstrap_attempted = False
    last_command_timestamp = int((read_json("command.json", {}) or {}).get("timestamp") or 0)
    trades: list[dict] = []
    while True:
        params = effective_params_for_strategy(merge_params())
        cmd = read_json("command.json", {}) or {}
        command_timestamp = int(cmd.get("timestamp") or 0)
        is_new_command = command_timestamp > last_command_timestamp
        if cmd.get("command") == "STOP_MONITOR" and is_new_command:
            log("Commande STOP_MONITOR recue.")
            break
        if cmd.get("command") == "ENABLE_TRADING" and is_new_command:
            trading_state = load_trading_state()
            account_now = mt5.account_info()
            real_confirmed = bool((cmd.get("payload") or {}).get("confirm_real"))
            permission_granted, permission_reason = mt5_trading_permission()
            if not permission_granted:
                trading_state["enabled"] = False
                trading_state["real_confirmed"] = False
                trading_state["reason"] = permission_reason
                trading_state["last_error"] = permission_reason
                log(permission_reason, "ERROR")
            elif account_now and (is_demo_account(account_now) or real_confirmed):
                trading_state["enabled"] = True
                trading_state["real_confirmed"] = bool(real_confirmed and not is_demo_account(account_now))
                trading_state["reason"] = "IA demarree: prises de position autorisees."
                trading_state["last_error"] = ""
                log("IA demarree: prises de position autorisees.", "SUCCESS")
            else:
                trading_state["enabled"] = False
                trading_state["real_confirmed"] = False
                trading_state["reason"] = "Activation refusee: confirmation requise."
                trading_state["last_error"] = trading_state["reason"]
                log(trading_state["reason"], "WARNING")
            save_trading_state(trading_state)
            if trading_state["enabled"]:
                account_mode = "REEL" if trading_state.get("real_confirmed") else "DEMO"
                notify_slack(params, "trading_toggle", SLACK_GREEN, *blocks_trading_toggle(True, account_mode))
        if cmd.get("command") == "DISABLE_TRADING" and is_new_command:
            trading_state = load_trading_state()
            was_enabled = bool(trading_state.get("enabled"))
            account_mode = "REEL" if trading_state.get("real_confirmed") else "DEMO"
            trading_state["enabled"] = False
            trading_state["real_confirmed"] = False
            trading_state["reason"] = "IA arretee: nouvelles prises de position bloquees."
            save_trading_state(trading_state)
            log("IA arretee: nouvelles prises de position bloquees.")
            if was_enabled:
                notify_slack(params, "trading_toggle", SLACK_RED, *blocks_trading_toggle(False, account_mode))
        if cmd.get("command") == "RESET_LEARNING" and is_new_command:
            save_learning_state(default_learning_state())
            save_position_contexts({})
            log("Memoire d'apprentissage reinitialisee pour XAUUSD et EURUSD.", "SUCCESS")

        live_account = mt5.account_info()
        live_account_key = (int(live_account.login), str(live_account.server)) if live_account else None
        if live_account_key != account_key:
            account_key = live_account_key
            symbol_names = {}
            log(
                f"Changement de compte MT5 detecte: {live_account.login if live_account else '?'} - "
                f"{live_account.server if live_account else '?'}"
            )
            _live_params = merge_params()
            for key in SYMBOLS:
                if not _live_params.get("symbols", {}).get(key, {}).get("enabled", True):
                    continue
                name = resolve_symbol(key)
                if name:
                    symbol_names[key] = name
                    log(f"Symbole disponible sur MT5: {key} -> {name}", "SUCCESS")
                else:
                    log(f"Symbole introuvable sur MT5: {key}", "WARNING")
            if live_account:
                _switch_positions = live_positions(symbol_names, params)
                _switch_bot_floating = sum(
                    float(p.get("profit") or 0) for p in _switch_positions
                    if p.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")
                )
                reset_session_state(int(live_account.login), _switch_bot_floating)
                log("Nouvelle session AlphaTrade initialisee pour ce compte.", "SUCCESS")

        positions = live_positions(symbol_names, params)
        # 06/08/2026 -- monitoring latence (demande explicite de Louis, audit
        # ticket 9748487751) : date de ce snapshot de positions, consulte par
        # close_bot_position() pour mesurer l'age reel des donnees de profit
        # au moment de la decision de fermeture -- voir _PERF_POSITIONS_SNAPSHOT_AT.
        global _PERF_POSITIONS_SNAPSHOT_AT
        _PERF_POSITIONS_SNAPSHOT_AT = time.perf_counter()
        now = time.time()
        if now - last_history > 2:
            trades = sync_history(conn, symbol_names, params)
            write_json("trades.json", {"trades": trades, "ts": int(time.time())})
            last_history = now
        if now - last_auto_backtest_check > 600:
            # v5.1.1 -- 05/08/2026, section 7. Verification peu couteuse
            # (lecture d'un petit fichier JSON) toutes les 10 min -- le vrai
            # rejeu ne se declenche que si run_auto_backtest_if_due() juge
            # que l'intervalle configure (scenario_backtest_interval_hours)
            # est vraiment ecoule.
            try:
                run_auto_backtest_if_due(params, symbol_names)
            except Exception as exc:  # noqa: BLE001 -- un backtest rate ne doit jamais casser le cycle de trading
                log(f"Backtest automatique: {exc}", "ERROR")
            last_auto_backtest_check = now
        if cmd.get("command") == "NEW_SESSION" and is_new_command:
            account_now = mt5.account_info()
            account_login = int(account_now.login) if account_now else None
            session_now = application_session_stats(trades, positions, account_login)
            state_now = protection_state(params, session_now, account_login)
            bot_positions = [position for position in positions if position.get("origin", "").upper() in ("BOT", "ALPHATRADE", "ALPHAKARIS")]
            if state_now.get("daily_locked"):
                log("Nouvelle session refusee: la protection journaliere est verrouillee.", "WARNING")
            else:
                # 05/08/2026 -- bug trouve en observation reelle : cet appel
                # passait 0.0 en dur au lieu du flottant bot reel (contrairement
                # aux 2 autres appels de reset_session_state(), au demarrage et
                # au changement de symbole, qui calculent deja correctement ce
                # flottant). Consequence : la session se reverrouillait quasi
                # immediatement apres "Nouvelle session" des que le profit_live
                # cumule du jour depassait deja session_target -- meme sans
                # aucun nouveau trade AlphaTrade -- puisque session_profit
                # (current - baseline) retombait directement sur `current` brut
                # (baseline force a 0) au lieu d'une vraie difference depuis
                # ce redemarrage de session.
                _new_session_bot_floating = sum(float(p.get("profit") or 0) for p in bot_positions)
                reset_session_state(
                    account_login,
                    _new_session_bot_floating,
                )
                log(
                    "Nouvelle session AlphaTrade demarree; positions externes et historique MT5 conserves.",
                    "SUCCESS",
                )
            last_command_timestamp = command_timestamp
        elif is_new_command:
            last_command_timestamp = command_timestamp
        preliminary_learning = load_learning_state()
        if bool(params.get("microstructure_enabled", True)):
            micro_interval = max(1, int(params.get("microstructure_interval_sec", 2)))
            if time.time() - last_microstructure >= micro_interval:
                # OBI/OFI/Kyle lambda/POC XAUUSD retires le 05/08/2026 (carnet
                # d'ordres non fourni par ce broker, restait N/D en permanence,
                # jamais lu par une decision) -- seul le Gold Microstructure
                # Engine (bougies, toujours disponibles) est calcule ici desormais.
                last_microstructure = time.time()
                gold_microstructure_snapshot_cache = gold_microstructure_snapshot(symbol_names, params)
            if (
                bool(params.get("hyperliquid_observer_enabled", False))
                and time.time() - last_hyperliquid >= 5
            ):
                microstructure.poll_hyperliquid(params.get("hyperliquid_symbols") or ["BTC", "ETH"])
                last_hyperliquid = time.time()
        preliminary_analyses = {
            key: symbol_analysis(
                name,
                {**params, **params.get("symbols", {}).get(key, {})},
                key,
                preliminary_learning,
            )
            for key, name in symbol_names.items()
        }
        ai_interval = max(2, int(params.get("ai_sync_interval_sec", 5)))
        if time.time() - last_ai_sync >= ai_interval:
            update_ai_server_state(
                params,
                symbol_names,
                preliminary_analyses,
                train_missing=not ai_bootstrap_attempted,
            )
            ai_bootstrap_attempted = True
            last_ai_sync = time.time()
        if bool(params.get("reinforcement_enabled", True)):
            track_position_contexts(positions, trades, preliminary_analyses, preliminary_learning)
        payload = status_payload(params, symbol_names, trades, positions)
        # Conserver l'analyse du premier appel — le deuxième appel (après trades)
        # peut retourner {} vide pour les synthétiques, écrasant les vraies valeurs.
        _first_analysis = dict(payload.get("analysis") or {})
        payload["microstructure"] = {**microstructure.snapshot(), "gold": dict(gold_microstructure_snapshot_cache)}
        if args.once:
            auto_state = load_trading_state()
            auto_state["allowed"] = is_demo_account(mt5.account_info())
            auto_state["reason"] = "Mode test --once: aucun ordre envoye."
        else:
            fast_breakeven_step(positions, params, symbol_names)
            take_profit_step(positions, params, symbol_names)
            profit_trailing_ratchet_step(positions, params, symbol_names)
            auto_state = auto_trade_step(params, symbol_names, payload, positions, trades)
            positions = live_positions(symbol_names, params)
            payload = status_payload(params, symbol_names, trades, positions)
            payload["microstructure"] = {**microstructure.snapshot(), "gold": dict(gold_microstructure_snapshot_cache)}
            # Restaurer l'analyse du premier appel pour l'affichage temps réel.
            if _first_analysis:
                payload["analysis"] = _first_analysis
        payload["auto_trading"] = auto_state
        write_json("status.json", payload)
        if args.once:
            break
        # v5.1.1 -- 05/08/2026, demande de Louis : vitesse de synchronisation
        # MT5 alignee sur AlphaTrade Global (MONITOR_INTERVAL_MS=100 dans
        # EA_Bridge/alphatg_bridge.py -- ~10 mises a jour/sec). Solde/equite/
        # positions/status.json se rafraichissent donc 5x plus vite (0,5s ->
        # 0,1s). Sans danger pour le bruit du Scenario Engine : le Dynamic
        # Position Manager a son propre throttle independant de cette boucle
        # (scenario_health_reeval_interval_sec, voir LAST_DPM_EVAL_AT), tout
        # comme la Microstructure/AI Sync avaient deja le leur.
        time.sleep(0.1)

    mt5.shutdown()
    return 0


def wait_for_stop_without_mt5() -> int:
    while True:
        cmd = read_json("command.json", {}) or {}
        if cmd.get("command") == "STOP_MONITOR":
            return 0
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
