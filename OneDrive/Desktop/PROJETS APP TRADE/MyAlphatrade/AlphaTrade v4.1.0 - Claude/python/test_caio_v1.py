"""Tests isoles pour caio_decide() (alphatrade_engine.py, v5.1.0). Aucun MT5
requis -- AgentReport synthetiques."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae
from agent_report import make_agent_report

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


def _mission(mode="Normal", new_positions_allowed=True):
    priority = {"Normal": "LOW", "Prudent": "MEDIUM", "Defense": "HIGH", "Protection": "CRITICAL"}[mode]
    return make_agent_report(
        "trading_mission_manager", confidence=100, priority=priority,
        recommendation={"action": "MISSION_MODE", "mode": mode, "new_positions_allowed": new_positions_allowed},
        now=NOW,
    )


def _report(agent, action, confidence, priority="MEDIUM", price=None, status="OK", arguments=None):
    rec = {"action": action}
    if price is not None:
        rec["price"] = price
    return make_agent_report(
        agent, status=status, confidence=confidence, priority=priority,
        recommendation=rec, arguments=arguments or [], ttl_seconds=180, now=NOW,
    )


def test_no_trade_when_mission_forbids_new_positions():
    reports = [_report("structure_analyst", "BUY_LIMIT", 90, price=2000)]
    decision = ae.caio_decide({}, reports, _mission("Protection", False), "adaptive", now=NOW)
    assert decision["decision"] == "NO_TRADE"
    assert "Mission Manager" in decision["raison"]
    print("test_no_trade_when_mission_forbids_new_positions OK")


def test_critical_risk_rejection_blocks_regardless_of_confidence():
    risk = make_agent_report(
        "risk_manager", confidence=95, priority="CRITICAL",
        recommendation={"action": "RISK_CAP", "any_rejected": True},
        risks=["Lot minimal du broker superieur a la limite de securite."], now=NOW,
    )
    structure = _report("structure_analyst", "BUY_LIMIT", 99, price=2000)
    decision = ae.caio_decide({}, [risk, structure], _mission(), "adaptive", now=NOW)
    assert decision["decision"] == "NO_TRADE"
    assert "risk_manager" in decision["raison"]
    print("test_critical_risk_rejection_blocks_regardless_of_confidence OK")


def test_no_trade_on_unanimous_wait():
    reports = [_report("structure_analyst", "WAIT", 91), _report("smart_money_analyst", "WAIT", 88)]
    decision = ae.caio_decide({}, reports, _mission(), "adaptive", now=NOW)
    assert decision["decision"] == "NO_TRADE"
    print("test_no_trade_on_unanimous_wait OK")


def test_no_trade_on_contradiction():
    reports = [
        _report("structure_analyst", "BUY_LIMIT", 85, price=2000),
        _report("smart_money_analyst", "SELL_LIMIT", 80, price=2010),
    ]
    decision = ae.caio_decide({}, reports, _mission(), "adaptive", now=NOW)
    assert decision["decision"] == "NO_TRADE"
    assert "Contradiction" in decision["raison"]
    print("test_no_trade_on_contradiction OK")


def test_no_trade_below_quality_threshold():
    reports = [_report("structure_analyst", "BUY_LIMIT", 45, price=2000)]  # sous le seuil 60
    decision = ae.caio_decide({}, reports, _mission(), "adaptive", now=NOW)
    assert decision["decision"] == "NO_TRADE"
    assert "seuil de qualite" in decision["raison"]
    print("test_no_trade_below_quality_threshold OK")


def test_go_selects_highest_priority_then_confidence():
    reports = [
        _report("structure_analyst", "BUY_LIMIT", 99, priority="LOW", price=2000),
        _report("smart_money_analyst", "BUY_LIMIT", 70, priority="HIGH", price=2005),
    ]
    decision = ae.caio_decide({}, reports, _mission(), "adaptive", now=NOW)
    assert decision["decision"] == "GO"
    assert decision["source_agent"] == "smart_money_analyst"  # priorite HIGH bat confiance 99% en LOW
    assert decision["price"] == 2005
    print("test_go_selects_highest_priority_then_confidence OK")


def test_entry_policy_immediate_overrides_limit_to_market():
    reports = [_report("structure_analyst", "BUY_LIMIT", 90, price=2000)]
    decision = ae.caio_decide({}, reports, _mission(), "immediate", now=NOW)
    assert decision["decision"] == "GO"
    assert decision["order_type"] == "BUY_MARKET"
    assert len(decision["overrides"]) == 1
    assert "immediate" in decision["overrides"][0]
    print("test_entry_policy_immediate_overrides_limit_to_market OK")


def test_entry_policy_pending_limit_overrides_market_to_limit():
    reports = [_report("structure_analyst", "SELL_MARKET", 90, price=None)]
    decision = ae.caio_decide({}, reports, _mission(), "pending_limit", now=NOW)
    assert decision["decision"] == "GO"
    assert decision["order_type"] == "SELL_LIMIT"
    assert len(decision["overrides"]) == 1
    print("test_entry_policy_pending_limit_overrides_market_to_limit OK")


def test_entry_policy_adaptive_no_override():
    reports = [_report("structure_analyst", "BUY_STOP", 90, price=2050)]
    decision = ae.caio_decide({}, reports, _mission(), "adaptive", now=NOW)
    assert decision["order_type"] == "BUY_STOP"
    assert decision["overrides"] == []
    print("test_entry_policy_adaptive_no_override OK")


def test_untrustworthy_report_ignored():
    stale = make_agent_report(
        "structure_analyst", confidence=99, priority="LOW",
        recommendation={"action": "BUY_LIMIT", "price": 2000}, ttl_seconds=1,
        now=NOW - timedelta(seconds=10),
    )
    decision = ae.caio_decide({}, [stale], _mission(), "adaptive", now=NOW)
    assert decision["decision"] == "NO_TRADE"
    print("test_untrustworthy_report_ignored OK")


def test_custom_confidence_threshold_from_params():
    reports = [_report("structure_analyst", "BUY_LIMIT", 70, price=2000)]
    decision = ae.caio_decide({"caio_min_confidence": 80.0}, reports, _mission(), "adaptive", now=NOW)
    assert decision["decision"] == "NO_TRADE"  # 70 < 80
    print("test_custom_confidence_threshold_from_params OK")


def test_writes_shared_memory_learning_history():
    ae.SHARED_MEMORY._store.clear()
    reports = [_report("structure_analyst", "BUY_LIMIT", 90, price=2000)]
    ae.caio_decide({}, reports, _mission(), "adaptive", now=NOW)
    envelope = ae.SHARED_MEMORY.read("learning_history")
    assert envelope is not None
    assert envelope["source"] == "caio"
    assert envelope["payload"]["decision"] == "GO"
    print("test_writes_shared_memory_learning_history OK")


def test_record_false_skips_shared_memory_write_on_go():
    # v5.1.0 -- passage d'observation (panneau Gold Brain rafraichi en continu) :
    # ne doit jamais polluer learning_history, qui ne trace que de vraies
    # tentatives d'entree.
    ae.SHARED_MEMORY._store.clear()
    reports = [_report("structure_analyst", "BUY_LIMIT", 90, price=2000)]
    decision = ae.caio_decide({}, reports, _mission(), "adaptive", now=NOW, record=False)
    assert decision["decision"] == "GO"
    assert ae.SHARED_MEMORY.read("learning_history") is None
    print("test_record_false_skips_shared_memory_write_on_go OK")


def test_record_false_skips_shared_memory_write_on_no_trade():
    ae.SHARED_MEMORY._store.clear()
    reports = [_report("structure_analyst", "WAIT", 91)]
    decision = ae.caio_decide({}, reports, _mission(), "adaptive", now=NOW, record=False)
    assert decision["decision"] == "NO_TRADE"
    assert ae.SHARED_MEMORY.read("learning_history") is None
    print("test_record_false_skips_shared_memory_write_on_no_trade OK")


if __name__ == "__main__":
    test_no_trade_when_mission_forbids_new_positions()
    test_critical_risk_rejection_blocks_regardless_of_confidence()
    test_no_trade_on_unanimous_wait()
    test_no_trade_on_contradiction()
    test_no_trade_below_quality_threshold()
    test_go_selects_highest_priority_then_confidence()
    test_entry_policy_immediate_overrides_limit_to_market()
    test_entry_policy_pending_limit_overrides_market_to_limit()
    test_entry_policy_adaptive_no_override()
    test_untrustworthy_report_ignored()
    test_custom_confidence_threshold_from_params()
    test_writes_shared_memory_learning_history()
    test_record_false_skips_shared_memory_write_on_go()
    test_record_false_skips_shared_memory_write_on_no_trade()
    print("ALL TESTS PASSED")
