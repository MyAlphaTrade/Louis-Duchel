"""Tests pour le branchement reel du Trading Style Engine (v5.1.1,
chantier 3) dans alphatrade_engine.py : trading_style_engine_step(),
TRADING_STYLE_STATE, persistance trading_style_log.jsonl -- reste une
evaluation pure, ne modifie jamais params['strategy_mode'] elle-meme.
L'application reelle (05/08/2026, demande explicite de Louis) est testee
separement : apply_trading_style_recommendation()."""
import json
import os
import tempfile
from datetime import datetime, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae
from agent_report import make_agent_report

NOW = datetime(2026, 8, 4, 10, 30, 0, tzinfo=timezone.utc)


def _uptrend_structure():
    return make_agent_report(
        "structure_analyst", status="OK", confidence=82.0, priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": 4086.5},
        arguments=["Regime UPTREND."], metadata={"regime": "UPTREND", "timeframe": "M5"}, now=NOW,
    )


def _range_structure():
    return make_agent_report(
        "structure_analyst", status="OK", confidence=60.0, priority="LOW",
        recommendation={"action": "WAIT"},
        arguments=["Range."], metadata={"regime": "RANGE", "timeframe": "M5"}, now=NOW,
    )


def _flat_candles(n=60, price=4085.0, rng=2.0):
    # meme volatilite recente que baseline -> vol_score ~50 (medium)
    return [{"open": price, "high": price + rng / 2, "low": price - rng / 2, "close": price, "time": i} for i in range(n)]


def test_disabled_by_default_returns_none_and_leaves_state_untouched():
    ae.TRADING_STYLE_STATE.clear()
    result = ae.trading_style_engine_step({}, _uptrend_structure(), _flat_candles(), now=NOW)
    assert result is None
    assert ae.TRADING_STYLE_STATE == {}
    print("test_disabled_by_default_returns_none_and_leaves_state_untouched OK")


def test_enabled_returns_recommendation_and_updates_state():
    ae.TRADING_STYLE_STATE.clear()
    params = {"trading_style_engine_enabled": True, "strategy_mode": "scalping_fast"}
    result = ae.trading_style_engine_step(params, _uptrend_structure(), _flat_candles(), now=NOW)
    assert result is not None
    assert result["recommended_mode"] == "long_analysis"  # UPTREND + volatilite medium
    assert result["current_mode"] == "scalping_fast"
    assert result["matches_current"] is False
    assert ae.TRADING_STYLE_STATE["recommended_mode"] == "long_analysis"
    print("test_enabled_returns_recommendation_and_updates_state OK")


def test_never_writes_strategy_mode_even_when_recommendation_differs():
    """Garde d'observation obligatoire (meme principe que le Scenario Engine) :
    la recommandation ne doit JAMAIS ecraser params['strategy_mode'], meme
    quand elle differe du mode actuel."""
    ae.TRADING_STYLE_STATE.clear()
    params = {"trading_style_engine_enabled": True, "strategy_mode": "scalping_fast"}
    ae.trading_style_engine_step(params, _uptrend_structure(), _flat_candles(), now=NOW)
    assert params["strategy_mode"] == "scalping_fast"  # inchange
    print("test_never_writes_strategy_mode_even_when_recommendation_differs OK")


def test_matches_current_true_when_recommendation_agrees():
    ae.TRADING_STYLE_STATE.clear()
    params = {"trading_style_engine_enabled": True, "strategy_mode": "long_analysis"}
    result = ae.trading_style_engine_step(params, _uptrend_structure(), _flat_candles(), now=NOW)
    assert result["matches_current"] is True
    print("test_matches_current_true_when_recommendation_agrees OK")


def test_range_context_recommends_combined_when_volatility_not_low():
    ae.TRADING_STYLE_STATE.clear()
    params = {"trading_style_engine_enabled": True, "strategy_mode": "scalping_fast"}
    result = ae.trading_style_engine_step(params, _range_structure(), _flat_candles(), now=NOW)
    assert result["recommended_mode"] == "combined"
    print("test_range_context_recommends_combined_when_volatility_not_low OK")


def test_logs_to_dedicated_jsonl_file_never_mixed_with_scenario_log():
    log_path = ae.DATA_DIR / "trading_style_log.jsonl"
    log_path.unlink(missing_ok=True)
    scenario_log_path = ae.DATA_DIR / "scenario_log.jsonl"
    scenario_log_before = scenario_log_path.read_text(encoding="utf-8") if scenario_log_path.exists() else ""
    params = {"trading_style_engine_enabled": True, "strategy_mode": "scalping_fast"}
    ae.trading_style_engine_step(params, _uptrend_structure(), _flat_candles(), now=NOW)
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["recommended_mode"] == "long_analysis"
    # scenario_log.jsonl (autre moteur) ne doit pas avoir bouge
    scenario_log_after = scenario_log_path.read_text(encoding="utf-8") if scenario_log_path.exists() else ""
    assert scenario_log_after == scenario_log_before
    print("test_logs_to_dedicated_jsonl_file_never_mixed_with_scenario_log OK")


def test_never_calls_real_execution():
    """Meme garde de securite systematique que le Scenario Engine : aucune
    fonction du Trading Style Engine ne doit jamais appeler place_order()/
    open_position(), meme indirectement."""
    original_place_order = ae.place_order
    original_open_position = ae.open_position

    def _poison(*a, **k):
        raise AssertionError("trading_style_engine_step() ne doit jamais executer d'ordre reel")

    ae.place_order = _poison
    ae.open_position = _poison
    try:
        params = {"trading_style_engine_enabled": True, "strategy_mode": "scalping_fast"}
        result = ae.trading_style_engine_step(params, _uptrend_structure(), _flat_candles(), now=NOW)
        assert result is not None
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
    print("test_never_calls_real_execution OK")


def test_apply_writes_strategy_mode_to_params_json_when_it_differs():
    ae.LAST_TRADING_STYLE_SWITCH_AT = None
    (ae.DATA_DIR / "params.json").unlink(missing_ok=True)
    (ae.DATA_DIR / "ai_adaptations_log.jsonl").unlink(missing_ok=True)
    entry = {"current_mode": "scalping_fast", "recommended_mode": "combined", "matches_current": False, "reason": "test"}
    applied = ae.apply_trading_style_recommendation(entry, {}, now=NOW)
    assert applied is True
    saved = json.loads((ae.DATA_DIR / "params.json").read_text(encoding="utf-8"))
    assert saved["strategy_mode"] == "combined"
    lines = [json.loads(l) for l in (ae.DATA_DIR / "ai_adaptations_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["module"] == "trading_style_engine"
    assert lines[0]["old_value"] == "scalping_fast" and lines[0]["new_value"] == "combined"
    print("test_apply_writes_strategy_mode_to_params_json_when_it_differs OK")


def test_apply_noop_when_recommendation_matches_current():
    ae.LAST_TRADING_STYLE_SWITCH_AT = None
    entry = {"current_mode": "scalping_fast", "recommended_mode": "scalping_fast", "matches_current": True, "reason": "test"}
    assert ae.apply_trading_style_recommendation(entry, {}, now=NOW) is False
    print("test_apply_noop_when_recommendation_matches_current OK")


def test_apply_noop_when_auto_apply_disabled():
    ae.LAST_TRADING_STYLE_SWITCH_AT = None
    entry = {"current_mode": "scalping_fast", "recommended_mode": "combined", "matches_current": False, "reason": "test"}
    params = {"trading_style_auto_apply_enabled": False}
    assert ae.apply_trading_style_recommendation(entry, params, now=NOW) is False
    print("test_apply_noop_when_auto_apply_disabled OK")


def test_apply_respects_cooldown_between_switches():
    from datetime import timedelta
    ae.LAST_TRADING_STYLE_SWITCH_AT = NOW
    entry = {"current_mode": "scalping_fast", "recommended_mode": "combined", "matches_current": False, "reason": "test"}
    soon_after = NOW + timedelta(seconds=30)  # sous le cooldown par defaut (300s)
    assert ae.apply_trading_style_recommendation(entry, {}, now=soon_after) is False
    print("test_apply_respects_cooldown_between_switches OK")


def test_apply_never_calls_real_execution():
    original_place_order = ae.place_order
    original_open_position = ae.open_position

    def _poison(*a, **k):
        raise AssertionError("apply_trading_style_recommendation() ne doit jamais executer d'ordre reel")

    ae.place_order = _poison
    ae.open_position = _poison
    ae.LAST_TRADING_STYLE_SWITCH_AT = None
    try:
        entry = {"current_mode": "scalping_fast", "recommended_mode": "long_analysis", "matches_current": False, "reason": "test"}
        ae.apply_trading_style_recommendation(entry, {}, now=NOW)
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
    print("test_apply_never_calls_real_execution OK")


if __name__ == "__main__":
    test_disabled_by_default_returns_none_and_leaves_state_untouched()
    test_enabled_returns_recommendation_and_updates_state()
    test_never_writes_strategy_mode_even_when_recommendation_differs()
    test_matches_current_true_when_recommendation_agrees()
    test_range_context_recommends_combined_when_volatility_not_low()
    test_logs_to_dedicated_jsonl_file_never_mixed_with_scenario_log()
    test_never_calls_real_execution()
    test_apply_writes_strategy_mode_to_params_json_when_it_differs()
    test_apply_noop_when_recommendation_matches_current()
    test_apply_noop_when_auto_apply_disabled()
    test_apply_respects_cooldown_between_switches()
    test_apply_never_calls_real_execution()
    print("ALL TESTS PASSED")
