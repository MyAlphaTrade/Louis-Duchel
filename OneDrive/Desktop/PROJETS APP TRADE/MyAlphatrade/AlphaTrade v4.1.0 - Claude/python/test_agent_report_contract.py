"""Tests isoles pour agent_report.py -- aucune dependance MT5."""
from datetime import datetime, timedelta, timezone

from agent_report import AgentReport, make_agent_report, sort_by_priority


def test_valid_report_roundtrip():
    r = make_agent_report(
        "structure_analyst",
        status="OK",
        confidence=86,
        priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": 2385.40},
        arguments=["FVG non comble"],
        risks=["news dans 3h"],
        ttl_seconds=300,
    )
    d = r.to_dict()
    assert d["agent"] == "structure_analyst"
    assert d["confidence"] == 86
    assert d["recommendation"]["action"] == "BUY_LIMIT"
    assert d["expiration"] is not None
    print("test_valid_report_roundtrip OK")


def test_invalid_status_rejected():
    try:
        AgentReport(agent="x", status="BROKEN", confidence=50, priority="LOW", recommendation={"action": "WAIT"})
        assert False, "devait lever ValueError"
    except ValueError:
        pass
    print("test_invalid_status_rejected OK")


def test_invalid_priority_rejected():
    try:
        AgentReport(agent="x", status="OK", confidence=50, priority="URGENT", recommendation={"action": "WAIT"})
        assert False, "devait lever ValueError"
    except ValueError:
        pass
    print("test_invalid_priority_rejected OK")


def test_recommendation_must_have_action():
    try:
        AgentReport(agent="x", status="OK", confidence=50, priority="LOW", recommendation={"price": 100})
        assert False, "devait lever ValueError"
    except ValueError:
        pass
    print("test_recommendation_must_have_action OK")


def test_confidence_clamped():
    r = AgentReport(agent="x", status="OK", confidence=150, priority="LOW", recommendation={"action": "WAIT"})
    assert r.confidence == 100.0
    r2 = AgentReport(agent="x", status="OK", confidence=-10, priority="LOW", recommendation={"action": "WAIT"})
    assert r2.confidence == 0.0
    print("test_confidence_clamped OK")


def test_expiration_and_trustworthiness():
    now = datetime.now(timezone.utc)
    fresh = make_agent_report(
        "risk_manager", confidence=90, priority="CRITICAL",
        recommendation={"action": "RISK_CAP", "max_risk_pct": 0.6}, ttl_seconds=60, now=now,
    )
    assert not fresh.is_expired(now)
    assert fresh.is_trustworthy(now)

    stale = make_agent_report(
        "structure_analyst", confidence=80, priority="MEDIUM",
        recommendation={"action": "WAIT"}, ttl_seconds=60, now=now - timedelta(seconds=120),
    )
    assert stale.is_expired(now)
    assert not stale.is_trustworthy(now)

    unavailable = make_agent_report(
        "smart_money_analyst", status="UNAVAILABLE", confidence=0, priority="LOW",
        recommendation={"action": "WAIT"},
    )
    assert not unavailable.is_trustworthy(now)
    print("test_expiration_and_trustworthiness OK")


def test_sort_by_priority():
    reports = [
        make_agent_report("a", confidence=90, priority="LOW", recommendation={"action": "WAIT"}),
        make_agent_report("b", confidence=92, priority="CRITICAL", recommendation={"action": "RISK_CAP"}),
        make_agent_report("c", confidence=83, priority="MEDIUM", recommendation={"action": "BUY_LIMIT"}),
        make_agent_report("d", confidence=70, priority="HIGH", recommendation={"action": "WAIT"}),
    ]
    ordered = sort_by_priority(reports)
    assert [r.agent for r in ordered] == ["b", "d", "c", "a"]
    print("test_sort_by_priority OK")


if __name__ == "__main__":
    test_valid_report_roundtrip()
    test_invalid_status_rejected()
    test_invalid_priority_rejected()
    test_recommendation_must_have_action()
    test_confidence_clamped()
    test_expiration_and_trustworthiness()
    test_sort_by_priority()
    print("ALL TESTS PASSED")
