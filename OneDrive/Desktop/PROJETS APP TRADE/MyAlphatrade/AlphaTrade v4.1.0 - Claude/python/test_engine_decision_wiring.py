"""Tests de cablage pour engine_decision.py dans auto_trade_step() (v1.1.5,
Phase 1, 06/08/2026 -- demande explicite de Louis : "je ferais comme
Global, mais sans casser Gold... au debut il ne trade pas. Il observe
seulement."). Meme discipline que test_scenario_wiring.py/
test_gold_brain_wiring.py -- verifie que le moteur (a) ne casse jamais le
cycle sans donnees reelles, (b) fusionne et journalise reellement quand les
rapports sont disponibles, (c) n'appelle JAMAIS open_position()/place_order()."""
import json
import os
import tempfile
from datetime import datetime, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae
from agent_report import make_agent_report

NOW = datetime(2026, 8, 6, 18, 0, 0, tzinfo=timezone.utc)


class _FakeTerminal:
    tradeapi_disabled = False
    trade_allowed = True


class _FakeAccount:
    balance = 10000.0
    equity = 10000.0
    login = 12345
    server = "Demo-Server"
    trade_mode = 0


class _FakeMT5Connected:
    """Meme surface minimale que test_scenario_wiring.py -- suffisant pour
    franchir les gates jusqu'au bloc Decision Engine. fetch_candles()
    degrade proprement sans copy_rates_from_pos (deja teste ailleurs)."""
    def account_info(self):
        return _FakeAccount()

    def terminal_info(self):
        return _FakeTerminal()


def _poison_open_position(*a, **k):
    raise AssertionError("open_position() ne doit JAMAIS etre appele par le Decision Engine (Phase 1 -- observation pure).")


def _poison_place_order(*a, **k):
    raise AssertionError("place_order() ne doit JAMAIS etre appele par le Decision Engine (Phase 1 -- observation pure).")


def test_auto_trade_step_wires_decision_engine_observation_without_crashing():
    """Sans donnees MT5 reelles (fetch_candles degrade) -- pas de crash,
    state['engine_decision'] reste simplement absent (meme logique que
    Gold Brain/Scenario Engine dans les memes conditions)."""
    ae.write_json("trading_state.json", {"enabled": True, "real_confirmed": True})
    params = ae.merge_params()
    params["engine_decision_enabled"] = True
    params["scenario_engine_enabled"] = False
    params["trading_style_engine_enabled"] = False
    params["gold_brain_enabled"] = False
    params["ai_server_enabled"] = False
    original_mt5 = ae.mt5
    original_open_position = ae.open_position
    original_place_order = ae.place_order
    ae.mt5 = _FakeMT5Connected()
    ae.open_position = _poison_open_position
    ae.place_order = _poison_place_order
    try:
        state = ae.auto_trade_step(
            params, {"XAUUSD": "XAUUSD"},
            {
                "active_symbol": "XAUUSD",
                "protection": {},
                "session_access": {"XAUUSD": {"entries_allowed": False}},
                "simulated_decision": {"eligible": False, "reason": "test", "signal": "WAIT", "confidence": 0},
                "analysis": {"XAUUSD": {}},
            },
            [], trades=[],
        )
    finally:
        ae.mt5 = original_mt5
        ae.open_position = original_open_position
        ae.place_order = original_place_order
    assert isinstance(state, dict)
    assert state.get("engine_decision") is None  # pas de candles reels -> degrade proprement
    print("test_auto_trade_step_wires_decision_engine_observation_without_crashing OK")


def test_auto_trade_step_decision_engine_fuses_and_logs_when_reports_available():
    """Avec des rapports reels (structure/smart money faux mais valides,
    indicateur classique BUY, aucun scenario actif) -- verifie la fusion
    complete + l'ecriture reelle dans decision_registry.jsonl."""
    (ae.DATA_DIR / "decision_registry.jsonl").unlink(missing_ok=True)
    ae.write_json("trading_state.json", {"enabled": True, "real_confirmed": True})
    params = ae.merge_params()
    params["engine_decision_enabled"] = True
    params["scenario_engine_enabled"] = False
    params["trading_style_engine_enabled"] = False
    params["gold_brain_enabled"] = False
    params["ai_server_enabled"] = False

    candles = [{"open": 4085, "high": 4086, "low": 4084, "close": 4085, "time": i} for i in range(60)]

    original_mt5 = ae.mt5
    original_open_position = ae.open_position
    original_place_order = ae.place_order
    original_fetch_candles = ae.fetch_candles
    original_structure_report = ae.structure_analyst_report
    original_smart_money_report = ae.smart_money_analyst_report
    original_current_scenario = ae.CURRENT_SCENARIO

    ae.mt5 = _FakeMT5Connected()
    ae.open_position = _poison_open_position
    ae.place_order = _poison_place_order
    ae.fetch_candles = lambda symbol, timeframe, limit: candles
    ae.structure_analyst_report = lambda c, p, timeframe="M5": make_agent_report(
        "structure_analyst", status="OK", confidence=78.0, priority="MEDIUM",
        recommendation={"action": "BUY_MARKET"}, arguments=["Regime UPTREND."], now=NOW,
    )
    ae.smart_money_analyst_report = lambda c, p: make_agent_report(
        "smart_money_analyst", status="OK", confidence=65.0, priority="MEDIUM",
        recommendation={"action": "BUY_MARKET"}, arguments=["Sweep bullish."], now=NOW,
    )
    ae.CURRENT_SCENARIO = None
    try:
        state = ae.auto_trade_step(
            params, {"XAUUSD": "XAUUSD"},
            {
                "active_symbol": "XAUUSD",
                "protection": {},
                "session_access": {"XAUUSD": {"entries_allowed": False}},
                "simulated_decision": {"eligible": False, "reason": "test", "signal": "SELL", "confidence": 52.0},
                "analysis": {"XAUUSD": {}},
            },
            [], trades=[],
        )
    finally:
        ae.mt5 = original_mt5
        ae.open_position = original_open_position
        ae.place_order = original_place_order
        ae.fetch_candles = original_fetch_candles
        ae.structure_analyst_report = original_structure_report
        ae.smart_money_analyst_report = original_smart_money_report
        ae.CURRENT_SCENARIO = original_current_scenario

    entry = state.get("engine_decision")
    assert entry is not None
    assert entry["symbol"] == "XAUUSD"
    assert entry["agents"]["structure"] == {"action": "BUY_MARKET", "confidence": 78.0}
    assert entry["agents"]["smart_money"] == {"action": "BUY_MARKET", "confidence": 65.0}
    assert entry["agents"]["indicator"] == {"action": "SELL", "confidence": 52.0}
    assert "scenario" not in entry["agents"]  # aucun scenario actif ici
    assert entry["final"] == "BUY"  # 78+65 > 52
    assert entry["executed"] is False

    lines = (ae.DATA_DIR / "decision_registry.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged["final"] == "BUY"
    print("test_auto_trade_step_decision_engine_fuses_and_logs_when_reports_available OK")


def test_engine_decision_disabled_by_default_writes_nothing():
    (ae.DATA_DIR / "decision_registry.jsonl").unlink(missing_ok=True)
    ae.write_json("trading_state.json", {"enabled": True, "real_confirmed": True})
    params = ae.merge_params()
    assert params.get("engine_decision_enabled") is False  # defaut de securite
    original_mt5 = ae.mt5
    ae.mt5 = _FakeMT5Connected()
    try:
        state = ae.auto_trade_step(
            params, {"XAUUSD": "XAUUSD"},
            {
                "active_symbol": "XAUUSD",
                "protection": {},
                "session_access": {"XAUUSD": {"entries_allowed": False}},
                "simulated_decision": {"eligible": False, "reason": "test", "signal": "WAIT", "confidence": 0},
                "analysis": {"XAUUSD": {}},
            },
            [], trades=[],
        )
    finally:
        ae.mt5 = original_mt5
    assert "engine_decision" not in state
    assert not (ae.DATA_DIR / "decision_registry.jsonl").exists()
    print("test_engine_decision_disabled_by_default_writes_nothing OK")


if __name__ == "__main__":
    test_auto_trade_step_wires_decision_engine_observation_without_crashing()
    test_auto_trade_step_decision_engine_fuses_and_logs_when_reports_available()
    test_engine_decision_disabled_by_default_writes_nothing()
    print("ALL TESTS PASSED")
