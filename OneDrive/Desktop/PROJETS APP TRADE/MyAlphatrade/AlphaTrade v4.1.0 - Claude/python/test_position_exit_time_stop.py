"""Tests isoles pour le Time Stop dans position_exit_reason() (alphatrade_engine.py).

Correctif du 02/08/2026, suite a l'audit statistique des 500 trades reels :
max_hold_sec ne fermait jamais une position perdante (verifie seulement dans
la branche TARGET, qui exige profit >= profit_target). Deux positions du
22/07/2026 sont restees ouvertes 127h avant d'etre stoppees en catastrophe
(-516$ a elles seules). Voir Audit_Statistique_500Trades_v5.1.0.html."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae

BASE_PARAMS = {
    "max_position_loss": 0,  # desactive pour isoler le Time Stop
    "max_hold_sec": 2700,  # 45min
    "position_review_sec": 3600,  # empeche reversal/momentum de se declencher en premier
    "rebond_enabled": False,
    "confidence_min": 60,
    "signal_reversal_margin": 99,
    "min_positive_exit": 0.50,
    "momentum_exit_score": 0,
    "take_profit_enabled": False,
    "profit_target": 5.00,
}

POSITION = {"direction": "BUY", "profit": -12.0}
ANALYSIS = {"signal": "WAIT", "confidence": 0}


def _call(profit, age, **param_overrides):
    params = {**BASE_PARAMS, **param_overrides}
    position = {**POSITION, "profit": profit}
    return ae.position_exit_reason(position, params, ANALYSIS, "OK", "OPEN", profit, age)


def test_time_stop_triggers_on_losing_position_past_threshold():
    reason = _call(profit=-12.0, age=2701)
    assert reason == "TIME_STOP"
    print("test_time_stop_triggers_on_losing_position_past_threshold OK")


def test_time_stop_does_not_trigger_before_threshold():
    reason = _call(profit=-12.0, age=2699)
    assert reason != "TIME_STOP"
    print("test_time_stop_does_not_trigger_before_threshold OK")


def test_time_stop_does_not_trigger_when_profitable():
    reason = _call(profit=3.0, age=5000)
    assert reason != "TIME_STOP"
    print("test_time_stop_does_not_trigger_when_profitable OK")


def test_time_stop_disabled_when_zero():
    reason = _call(profit=-12.0, age=999999, max_hold_sec=0)
    assert reason != "TIME_STOP"
    print("test_time_stop_disabled_when_zero OK")


def test_time_stop_independent_of_rebond_enabled():
    reason = _call(profit=-12.0, age=2701, rebond_enabled=True)
    assert reason == "TIME_STOP"
    print("test_time_stop_independent_of_rebond_enabled OK")


def test_max_position_loss_still_takes_priority():
    # Si le plafond brutal est aussi franchi, il doit continuer a gagner --
    # verifie que l'insertion du Time Stop n'a pas change l'ordre de priorite.
    reason = _call(profit=-50.0, age=2701, max_position_loss=20)
    assert reason == "MAX_POSITION_LOSS"
    print("test_max_position_loss_still_takes_priority OK")


if __name__ == "__main__":
    test_time_stop_triggers_on_losing_position_past_threshold()
    test_time_stop_does_not_trigger_before_threshold()
    test_time_stop_does_not_trigger_when_profitable()
    test_time_stop_disabled_when_zero()
    test_time_stop_independent_of_rebond_enabled()
    test_max_position_loss_still_takes_priority()
    print("ALL TESTS PASSED")
