"""Tests isoles pour trading_coach_observe() et learning_manager_apply()
(alphatrade_engine.py, v5.1.0). Aucun MT5 requis -- learning_state
synthetique, aucune mutation reelle de fichier (ces fonctions ne modifient
jamais learning_state.json, seulement track_position_contexts() le fait)."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


def _state(**symbols):
    return {"version": 1, "symbols": symbols, "updated_at": ""}


def _symbol(samples=0, wins=0, total_profit=0.0, weights=None, confidence_offset=0.0, last_outcome=""):
    return {
        "samples": samples, "wins": wins, "losses": samples - wins, "total_profit": total_profit,
        "avg_mfe": 0.0, "avg_mae": 0.0, "confidence_offset": confidence_offset,
        "weights": weights or {"trend": 1.0, "rsi": 1.0, "macd": 1.0, "edge": 1.0, "momentum": 1.0},
        "processed_positions": [], "last_outcome": last_outcome, "last_closed_at": "",
    }


def test_coach_ignores_small_samples():
    state = _state(XAUUSD=_symbol(samples=3, wins=2, total_profit=10.0))
    report = ae.trading_coach_observe(state, min_samples=10)
    assert report.recommendation["patterns"] == []
    assert report.confidence == 30.0
    print("test_coach_ignores_small_samples OK")


def test_coach_reports_pattern_above_threshold():
    state = _state(XAUUSD=_symbol(samples=20, wins=14, total_profit=125.5, last_outcome="WIN"))
    report = ae.trading_coach_observe(state, min_samples=10)
    assert len(report.recommendation["patterns"]) == 1
    p = report.recommendation["patterns"][0]
    assert p["symbol"] == "XAUUSD"
    assert p["winrate"] == 70.0
    assert report.confidence == 90.0
    assert report.status == "OK"
    print("test_coach_reports_pattern_above_threshold OK")


def test_coach_never_recommends_action_only_observes():
    state = _state(XAUUSD=_symbol(samples=20, wins=14, total_profit=125.5))
    report = ae.trading_coach_observe(state, min_samples=10)
    assert report.recommendation["action"] == "OBSERVE"
    print("test_coach_never_recommends_action_only_observes OK")


def test_coach_writes_shared_memory_learning_history():
    ae.SHARED_MEMORY._store.clear()
    state = _state(XAUUSD=_symbol(samples=20, wins=14, total_profit=1.0))
    ae.trading_coach_observe(state, min_samples=10)
    envelope = ae.SHARED_MEMORY.read("learning_history")
    assert envelope["source"] == "trading_coach"
    assert envelope["payload"]["type"] == "observation"
    print("test_coach_writes_shared_memory_learning_history OK")


def test_learning_manager_detects_weight_change():
    before = _state(XAUUSD=_symbol(weights={"trend": 1.0, "rsi": 1.0, "macd": 1.0, "edge": 1.0, "momentum": 1.0}))
    after = _state(XAUUSD=_symbol(weights={"trend": 1.05, "rsi": 1.0, "macd": 1.0, "edge": 1.0, "momentum": 1.0}))
    report = ae.learning_manager_apply(before, after)
    adjustments = report.recommendation["adjustments"]
    assert len(adjustments) == 1
    assert adjustments[0]["symbol"] == "XAUUSD"
    assert adjustments[0]["weight_changes"]["trend"] == [1.0, 1.05]
    assert adjustments[0]["in_bounds"] is True
    assert report.priority == "LOW"
    print("test_learning_manager_detects_weight_change OK")


def test_learning_manager_no_change_no_adjustment():
    same = _state(XAUUSD=_symbol())
    report = ae.learning_manager_apply(same, same)
    assert report.recommendation["adjustments"] == []
    print("test_learning_manager_no_change_no_adjustment OK")


def test_learning_manager_flags_out_of_bounds():
    before = _state(XAUUSD=_symbol(weights={"trend": 1.0, "rsi": 1.0, "macd": 1.0, "edge": 1.0, "momentum": 1.0}))
    # Ne devrait jamais arriver via track_position_contexts() (clamp deja en
    # place) -- verifie que learning_manager_apply() le detecterait quand meme.
    after = _state(XAUUSD=_symbol(weights={"trend": 1.50, "rsi": 1.0, "macd": 1.0, "edge": 1.0, "momentum": 1.0}))
    report = ae.learning_manager_apply(before, after)
    assert report.recommendation["adjustments"][0]["in_bounds"] is False
    assert report.priority == "MEDIUM"
    print("test_learning_manager_flags_out_of_bounds OK")


def test_learning_manager_confidence_offset_change_detected():
    before = _state(XAUUSD=_symbol(confidence_offset=0.0))
    after = _state(XAUUSD=_symbol(confidence_offset=0.45))
    report = ae.learning_manager_apply(before, after)
    a = report.recommendation["adjustments"][0]
    assert a["confidence_offset_before"] == 0.0
    assert a["confidence_offset_after"] == 0.45
    print("test_learning_manager_confidence_offset_change_detected OK")


def test_learning_manager_writes_shared_memory():
    ae.SHARED_MEMORY._store.clear()
    before = _state(XAUUSD=_symbol())
    after = _state(XAUUSD=_symbol(confidence_offset=1.0))
    ae.learning_manager_apply(before, after)
    envelope = ae.SHARED_MEMORY.read("learning_history")
    assert envelope["source"] == "learning_manager"
    assert envelope["payload"]["type"] == "adjustment"
    print("test_learning_manager_writes_shared_memory OK")


if __name__ == "__main__":
    test_coach_ignores_small_samples()
    test_coach_reports_pattern_above_threshold()
    test_coach_never_recommends_action_only_observes()
    test_coach_writes_shared_memory_learning_history()
    test_learning_manager_detects_weight_change()
    test_learning_manager_no_change_no_adjustment()
    test_learning_manager_flags_out_of_bounds()
    test_learning_manager_confidence_offset_change_detected()
    test_learning_manager_writes_shared_memory()
    print("ALL TESTS PASSED")
