"""Tests isoles pour shared_memory.py -- aucune dependance MT5."""
from datetime import datetime, timedelta, timezone

from agent_report import make_agent_report
from shared_memory import SharedMemory


def test_write_read_roundtrip():
    mem = SharedMemory()
    env = mem.write("risk", "risk_manager", {"budget_pct": 0.6}, confidence=92)
    assert env["version"] == 1
    assert env["source"] == "risk_manager"
    assert mem.read_payload("risk") == {"budget_pct": 0.6}
    print("test_write_read_roundtrip OK")


def test_version_increments():
    mem = SharedMemory()
    mem.write("risk", "risk_manager", {"a": 1})
    mem.write("risk", "risk_manager", {"a": 2})
    env = mem.write("risk", "risk_manager", {"a": 3})
    assert env["version"] == 3
    print("test_version_increments OK")


def test_ownership_enforced():
    mem = SharedMemory()
    try:
        mem.write("risk", "structure_analyst", {"a": 1})
        assert False, "structure_analyst ne doit pas pouvoir ecrire dans risk"
    except PermissionError:
        pass
    mem.write("structures", "structure_analyst", {"zones": []})  # autorise
    print("test_ownership_enforced OK")


def test_unknown_compartment_rejected():
    mem = SharedMemory()
    try:
        mem.write("gold_knowledge", "gold_intelligence", {})
        assert False, "gold_knowledge n'existe pas encore en v5.1.0"
    except KeyError:
        pass
    print("test_unknown_compartment_rejected OK")


def test_state_compartment_default_confidence_100():
    mem = SharedMemory()
    env = mem.write("open_positions", "position_manager", {"tickets": []})
    assert env["confidence"] == 100.0
    print("test_state_compartment_default_confidence_100 OK")


def test_expiration_hides_stale_payload():
    mem = SharedMemory()
    now = datetime.now(timezone.utc)
    mem.write("structures", "structure_analyst", {"zone": "demand"}, ttl_seconds=60, now=now)
    assert mem.read_payload("structures", now=now) is not None
    later = now + timedelta(seconds=120)
    assert mem.is_expired("structures", now=later)
    assert mem.read_payload("structures", now=later) is None
    print("test_expiration_hides_stale_payload OK")


def test_write_report_derives_confidence_and_ttl():
    mem = SharedMemory()
    now = datetime.now(timezone.utc)
    report = make_agent_report(
        "smart_money_analyst", confidence=76, priority="MEDIUM",
        recommendation={"action": "WAIT"}, ttl_seconds=120, now=now,
    )
    env = mem.write_report("smart_money", "smart_money_analyst", report, now=now)
    assert env["confidence"] == 76
    assert env["payload"]["agent"] == "smart_money_analyst"
    assert not mem.is_expired("smart_money", now=now + timedelta(seconds=30))
    assert mem.is_expired("smart_money", now=now + timedelta(seconds=180))
    print("test_write_report_derives_confidence_and_ttl OK")


def test_snapshot_is_a_copy():
    mem = SharedMemory()
    mem.write("risk", "risk_manager", {"a": 1})
    snap = mem.snapshot()
    snap["risk"]["version"] = 999
    assert mem.read("risk")["version"] == 1
    print("test_snapshot_is_a_copy OK")


if __name__ == "__main__":
    test_write_read_roundtrip()
    test_version_increments()
    test_ownership_enforced()
    test_unknown_compartment_rejected()
    test_state_compartment_default_confidence_100()
    test_expiration_hides_stale_payload()
    test_write_report_derives_confidence_and_ttl()
    test_snapshot_is_a_copy()
    print("ALL TESTS PASSED")
