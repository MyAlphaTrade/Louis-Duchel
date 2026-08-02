"""Tests isoles pour performance_manager_report() et mission_state()
(alphatrade_engine.py, v5.1.0). Aucun MT5 requis -- trades/positions/params
100% synthetiques, mt5=None (verifie par l'import lui-meme).

IMPORTANT : ALPHATRADE_DATA_DIR doit etre redirige AVANT l'import du moteur --
DATA_DIR est calcule au chargement du module et protection_state()/mission_state()
ecrivent reellement sur disque (session_state.json). Sans ca, ces tests
ecraseraient l'etat de session REEL de l'app en production (~/AlphaTrade)."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="alphatrade_test_")
os.environ["ALPHATRADE_DATA_DIR"] = _TEST_DATA_DIR

import alphatrade_engine as ae

assert str(ae.DATA_DIR) == _TEST_DATA_DIR, "DATA_DIR n'a pas ete redirige -- ABANDON pour ne pas toucher les vraies donnees"

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)  # mercredi


def _trade(profit: float, days_ago: float, status: str = "CLOSED") -> dict:
    close_time = (NOW - timedelta(days=days_ago)).isoformat()
    return {"status": status, "profit": profit, "close_time": close_time}


def _params(**overrides) -> dict:
    p = {
        "daily_target": 50.0,
        "session_max_loss": -150.0,
        "session_target": 25.0,
        "profit_protection_enabled": True,
        "profit_drawdown_pct": 30.0,
        "profit_warning_ratio": 0.75,
        "giveback": 100.0,
        "mission_weekly_target": 0.0,
        "mission_monthly_target": 0.0,
        "mission_consecutive_loss_defense": 3,
    }
    p.update(overrides)
    return p


def test_utc_trade_week_month_bucketing():
    assert ae.utc_trade_week(NOW.isoformat()) == "2026-W32"
    assert ae.utc_trade_month(NOW.isoformat()) == "2026-08"
    assert ae.utc_trade_week(None) == ""
    print("test_utc_trade_week_month_bucketing OK")


def test_performance_manager_report_horizons():
    # Trouve programmatiquement un decalage "meme mois, semaine ISO differente"
    # et un decalage "mois different" plutot que de deviner un nombre de jours --
    # la position du 1er du mois dans la semaine ISO varie.
    this_month = ae.utc_trade_month(NOW.isoformat())
    this_week = ae.utc_trade_week(NOW.isoformat())
    month_only_days_ago = next(
        d for d in range(1, 32)
        if ae.utc_trade_month((NOW - timedelta(days=d)).isoformat()) == this_month
        and ae.utc_trade_week((NOW - timedelta(days=d)).isoformat()) != this_week
    )
    other_month_days_ago = next(
        d for d in range(28, 90)
        if ae.utc_trade_month((NOW - timedelta(days=d)).isoformat()) != this_month
    )
    trades = [
        _trade(10, days_ago=0),   # aujourd'hui
        _trade(-5, days_ago=1),   # cette semaine
        _trade(20, days_ago=month_only_days_ago),   # ce mois, pas cette semaine
        _trade(-100, days_ago=other_month_days_ago),  # ni ce mois ni cette semaine
    ]
    report = ae.performance_manager_report(trades, [], now=NOW)
    assert report.agent == "performance_manager"
    h = report.recommendation["horizons"]
    assert h["day"]["profit_closed"] == 10
    assert h["week"]["profit_closed"] == 5  # 10 - 5
    assert h["month"]["trades"] == 3  # exclut le trade hors mois
    print("test_performance_manager_report_horizons OK")


def test_mission_mode_normal_when_on_track():
    trades = [_trade(5, days_ago=0)]
    daily = {"profit_live": 5.0}
    report = ae.mission_state(_params(), trades, [], daily, account_login=1001, now=NOW)
    assert report.recommendation["mode"] == "Normal"
    assert report.recommendation["new_positions_allowed"] is True
    assert report.priority == "LOW"
    print("test_mission_mode_normal_when_on_track OK")


def test_mission_mode_protection_on_hard_lock():
    # protection_state() ancre sa baseline de session au premier appel (pour
    # ne pas compter un flottant deja negatif avant meme le demarrage comme
    # une perte "de cette session") -- il faut donc 2 appels : le premier
    # etablit la baseline pres de 0, le second simule une chute reelle.
    login = 1002
    ae.mission_state(_params(), [], [], {"profit_live": 0.0}, account_login=login, now=NOW)
    trades = [_trade(-160, days_ago=0)]
    daily = {"profit_live": -160.0}
    report = ae.mission_state(_params(), trades, [], daily, account_login=login, now=NOW)
    assert report.recommendation["mode"] == "Protection"
    assert report.recommendation["new_positions_allowed"] is False
    assert report.priority == "CRITICAL"
    print("test_mission_mode_protection_on_hard_lock OK")


def test_mission_mode_defense_on_consecutive_losses():
    trades = [_trade(-2, days_ago=0), _trade(-3, days_ago=0), _trade(-1, days_ago=0)]
    daily = {"profit_live": -6.0}
    report = ae.mission_state(_params(), trades, [], daily, account_login=1003, now=NOW)
    assert report.recommendation["mode"] == "Defense"
    assert report.metadata["consecutive_losses"] == 3
    assert report.priority == "HIGH"
    print("test_mission_mode_defense_on_consecutive_losses OK")


def test_mission_mode_prudent_near_daily_target():
    login = 1004
    ae.mission_state(_params(), [], [], {"profit_live": 0.0}, account_login=login, now=NOW)
    trades = [_trade(46, days_ago=0)]  # 92% de daily_target=50
    daily = {"profit_live": 46.0}
    report = ae.mission_state(_params(), trades, [], daily, account_login=login, now=NOW)
    assert report.recommendation["mode"] == "Prudent"
    print("test_mission_mode_prudent_near_daily_target OK")


def test_mission_writes_shared_memory():
    ae.SHARED_MEMORY._store.clear()
    trades = [_trade(5, days_ago=0)]
    daily = {"profit_live": 5.0}
    ae.mission_state(_params(), trades, [], daily, account_login=1005, now=NOW)
    envelope = ae.SHARED_MEMORY.read("trading_objectives")
    assert envelope is not None
    assert envelope["source"] == "trading_mission_manager"
    assert envelope["payload"]["recommendation"]["mode"] == "Normal"
    print("test_mission_writes_shared_memory OK")


def test_weekly_monthly_target_defaults_derive_from_daily():
    trades = [_trade(5, days_ago=0)]
    daily = {"profit_live": 5.0}
    report = ae.mission_state(_params(daily_target=50.0), trades, [], daily, account_login=1006, now=NOW)
    assert report.metadata["weekly_target"] == 250.0
    assert report.metadata["monthly_target"] == 1000.0
    assert report.metadata["weekly_target_auto"] is True
    assert report.metadata["monthly_target_auto"] is True
    print("test_weekly_monthly_target_defaults_derive_from_daily OK")


def test_weekly_monthly_target_auto_flag_false_when_explicitly_set():
    trades = [_trade(5, days_ago=0)]
    daily = {"profit_live": 5.0}
    params = _params(daily_target=50.0, mission_weekly_target=300.0, mission_monthly_target=1200.0)
    report = ae.mission_state(params, trades, [], daily, account_login=1006, now=NOW)
    assert report.metadata["weekly_target"] == 300.0
    assert report.metadata["monthly_target"] == 1200.0
    assert report.metadata["weekly_target_auto"] is False
    assert report.metadata["monthly_target_auto"] is False
    print("test_weekly_monthly_target_auto_flag_false_when_explicitly_set OK")


if __name__ == "__main__":
    test_utc_trade_week_month_bucketing()
    test_performance_manager_report_horizons()
    test_mission_mode_normal_when_on_track()
    test_mission_mode_protection_on_hard_lock()
    test_mission_mode_defense_on_consecutive_losses()
    test_mission_mode_prudent_near_daily_target()
    test_mission_writes_shared_memory()
    test_weekly_monthly_target_defaults_derive_from_daily()
    test_weekly_monthly_target_auto_flag_false_when_explicitly_set()
    print("ALL TESTS PASSED")
