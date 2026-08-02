"""Tests isoles pour risk_manager_report() (alphatrade_engine.py, v5.1.0).
Aucun MT5 requis -- mt5=None degrade proprement lot_safety_state() vers le
seul plafond de compte (account_cap), verifie explicitement ci-dessous."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


class FakeAccount:
    def __init__(self, balance=1000.0, server="Broker-Demo", trade_mode=0):
        self.balance = balance
        self.server = server
        self.trade_mode = trade_mode


def _params(lot=0.10, lot_min=0.01, real_lot_cap=0.10, risk_pct=0.35):
    return {
        "real_lot_cap": real_lot_cap,
        "demo_lot_cap": real_lot_cap,
        "risk_pct": risk_pct,
        "symbols": {"XAUUSD": {"lot": lot, "lot_min": lot_min}},
    }


def test_no_account_is_unavailable_critical():
    report = ae.risk_manager_report(_params(), None, {"XAUUSD": "XAUUSD"})
    assert report.status == "UNAVAILABLE"
    assert report.priority == "CRITICAL"
    assert report.confidence == 0
    print("test_no_account_is_unavailable_critical OK")


def test_normal_lot_within_cap_is_low_priority():
    account = FakeAccount(balance=1000.0)
    report = ae.risk_manager_report(_params(lot=0.05, real_lot_cap=0.10), account, {"XAUUSD": "XAUUSD"})
    assert report.status == "OK"
    assert report.priority == "LOW"
    assert report.recommendation["any_rejected"] is False
    lot = report.recommendation["lots"]["XAUUSD"]
    assert lot["effective_lot"] == 0.05  # sans MT5, account_cap est le seul plafond actif
    print("test_normal_lot_within_cap_is_low_priority OK")


def test_lot_below_broker_min_rejected_critical():
    # account_cap tres bas force effective < broker_min -> rejete
    account = FakeAccount(balance=1000.0)
    report = ae.risk_manager_report(
        _params(lot=0.10, lot_min=5.0, real_lot_cap=0.001), account, {"XAUUSD": "XAUUSD"}
    )
    assert report.priority == "CRITICAL"
    assert report.recommendation["any_rejected"] is True
    assert report.recommendation["lots"]["XAUUSD"]["rejected"] is True
    assert report.confidence == 40.0
    print("test_lot_below_broker_min_rejected_critical OK")


def test_writes_shared_memory_risk_compartment():
    ae.SHARED_MEMORY._store.clear()
    account = FakeAccount(balance=1000.0)
    ae.risk_manager_report(_params(), account, {"XAUUSD": "XAUUSD"})
    envelope = ae.SHARED_MEMORY.read("risk")
    assert envelope is not None
    assert envelope["source"] == "risk_manager"
    print("test_writes_shared_memory_risk_compartment OK")


if __name__ == "__main__":
    test_no_account_is_unavailable_critical()
    test_normal_lot_within_cap_is_low_priority()
    test_lot_below_broker_min_rejected_critical()
    test_writes_shared_memory_risk_compartment()
    print("ALL TESTS PASSED")
