"""Tests isoles pour risk_manager_report() (alphatrade_engine.py, v5.1.0).

06/08/2026 -- mis a jour suite au retrait de real_lot_cap/demo_lot_cap du
chemin de decision actif (lot_safety_state(), meme mecanisme que
AlphaTrade Global -- demande explicite de Louis). Ces tests mockent
desormais un MT5 factice (meme pattern que test_lot_auto_calc.py) pour
exercer le vrai calcul de risque plutot que le degrade "aucun MT5" (qui
rejette systematiquement, voir test_no_account_is_unavailable_critical et
test_lot_below_broker_min_rejected_critical ci-dessous, tous deux
volontairement sans MT5)."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


class FakeAccount:
    def __init__(self, balance=1000.0, server="Broker-Demo", trade_mode=0):
        self.balance = balance
        self.server = server
        self.trade_mode = trade_mode


class _FakeSymbolInfo:
    point = 0.01
    volume_min = 0.01
    volume_step = 0.01
    trade_tick_size = 0.01
    trade_tick_value = 1.0
    trade_stops_level = 0
    digits = 2


class _FakeTick:
    ask = 4000.0
    bid = 3999.8


class _FakeMT5:
    """order_calc_profit lineaire ($100 par point par lot) -- meme fake que
    test_lot_auto_calc.py, suffisant pour verifier la proportionnalite."""
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1

    def symbol_info(self, name):
        return _FakeSymbolInfo()

    def symbol_info_tick(self, name):
        return _FakeTick()

    def order_calc_profit(self, order_type, symbol, volume, price_open, price_close):
        return (price_close - price_open) * volume * 100.0


def _with_fake_mt5(fn):
    original = ae.mt5
    ae.mt5 = _FakeMT5()
    try:
        return fn()
    finally:
        ae.mt5 = original


def _params(lot=0.10, lot_min=0.01, risk_pct=0.35):
    # 06/08/2026 -- real_lot_cap/demo_lot_cap gardes ici uniquement pour
    # verifier explicitement (test_normal_lot_within_cap_is_low_priority)
    # qu'ils n'influencent plus rien, jamais pour piloter le test.
    return {
        "real_lot_cap": 0.10,
        "demo_lot_cap": 0.10,
        "risk_pct": risk_pct,
        "symbols": {"XAUUSD": {"lot": lot, "lot_min": lot_min, "emergency_loss_limit": 3.0}},
    }


def test_no_account_is_unavailable_critical():
    report = ae.risk_manager_report(_params(), None, {"XAUUSD": "XAUUSD"})
    assert report.status == "UNAVAILABLE"
    assert report.priority == "CRITICAL"
    assert report.confidence == 0
    print("test_no_account_is_unavailable_critical OK")


def test_normal_lot_within_cap_is_low_priority():
    """Lot calcule par le risque, largement au-dela de l'ancien
    real_lot_cap=0.10 (demande de Louis : plus aucun plafond manuel actif,
    comme AlphaTrade Global) -- doit quand meme rester LOW/OK tant que le
    broker l'accepte."""
    def run():
        account = FakeAccount(balance=1000.0)
        return ae.risk_manager_report(_params(), account, {"XAUUSD": "XAUUSD"})
    report = _with_fake_mt5(run)
    assert report.status == "OK"
    assert report.priority == "LOW"
    assert report.recommendation["any_rejected"] is False
    lot = report.recommendation["lots"]["XAUUSD"]
    assert lot["effective_lot"] > 0.10, (
        "Le lot calcule par le risque doit pouvoir depasser l'ancien real_lot_cap (0.10) -- "
        f"obtenu {lot['effective_lot']}."
    )
    print("test_normal_lot_within_cap_is_low_priority OK")


def test_lot_below_broker_min_rejected_critical():
    # Sans MT5, aucun prix reel -> risk_lot_cap reste 0 -> rejete (lot_min
    # exige > 0). Meme mecanisme que test_lot_zero_when_no_mt5_data
    # (test_lot_auto_calc.py) : plus de repli sur une valeur manuelle.
    account = FakeAccount(balance=1000.0)
    report = ae.risk_manager_report(
        _params(lot=0.10, lot_min=5.0), account, {"XAUUSD": "XAUUSD"}
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
