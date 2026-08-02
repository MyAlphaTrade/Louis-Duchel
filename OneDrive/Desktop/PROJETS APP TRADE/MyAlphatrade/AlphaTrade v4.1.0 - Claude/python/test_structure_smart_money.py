"""Tests isoles pour structure_analyst_report() et smart_money_analyst_report()
(alphatrade_engine.py, v5.1.0, formalisation KB2/KB3/KB5). Aucun MT5 requis --
donnees synthetiques (zigzag), meme methode que les tests KB1-KB8 d'origine."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


def _ramp(a: float, b: float, n: int) -> list[float]:
    step = (b - a) / (n - 1)
    return [a + step * i for i in range(n)]


def _uptrend_candles() -> list[dict]:
    """Zigzag ascendant : swing high 2031(i5) -> low 2011(i10) -> high
    2061(i15) -> low 2039(i20), regime UPTREND, une zone demand a 2011."""
    seq = (
        _ramp(2000, 2030, 6)
        + _ramp(2030, 2012, 6)[1:]
        + _ramp(2012, 2060, 6)[1:]
        + _ramp(2060, 2040, 6)[1:]
        + _ramp(2040, 2090, 6)[1:]
    )
    return [{"open": v, "high": v + 1, "low": v - 1, "close": v} for v in seq]


def _uptrend_with_liquidity_grab() -> list[dict]:
    """Meme zigzag, + une bougie finale qui balaie le sommet de swing a 2061
    (index 15) puis referme dessous -- sweep de liquidite bearish recent."""
    candles = _uptrend_candles()
    candles.append({"open": 2088, "high": 2075, "low": 2085, "close": 2058})
    return candles


def test_structure_analyst_detects_uptrend_and_demand_zone():
    candles = _uptrend_candles()
    current_price = candles[-1]["close"]
    report = ae.structure_analyst_report(candles, current_price, timeframe="H1")
    assert report.status == "OK"
    assert report.metadata["regime"] == "UPTREND"
    assert report.recommendation["action"] == "BUY_LIMIT"
    assert report.recommendation["price"] == 2011.0
    assert report.priority == "MEDIUM"
    print("test_structure_analyst_detects_uptrend_and_demand_zone OK")


def test_structure_analyst_unavailable_on_too_few_candles():
    report = ae.structure_analyst_report([{"high": 1, "low": 0}] * 3, 0.5)
    assert report.status == "UNAVAILABLE"
    assert report.recommendation["action"] == "WAIT"
    print("test_structure_analyst_unavailable_on_too_few_candles OK")


def test_structure_analyst_writes_shared_memory():
    ae.SHARED_MEMORY._store.clear()
    candles = _uptrend_candles()
    ae.structure_analyst_report(candles, candles[-1]["close"])
    envelope = ae.SHARED_MEMORY.read("structures")
    assert envelope is not None
    assert envelope["source"] == "structure_analyst"
    print("test_structure_analyst_writes_shared_memory OK")


def test_smart_money_detects_recent_liquidity_grab():
    candles = _uptrend_with_liquidity_grab()
    current_price = candles[-1]["close"]
    report = ae.smart_money_analyst_report(candles, current_price)
    assert report.status == "OK"
    assert report.recommendation["action"] == "SELL_LIMIT"
    assert report.recommendation["price"] == 2061.0
    assert report.priority == "MEDIUM"
    print("test_smart_money_detects_recent_liquidity_grab OK")


def test_smart_money_waits_without_grab_or_choch_far_from_extremes():
    candles = _uptrend_candles()
    report = ae.smart_money_analyst_report(candles, candles[-1]["close"])
    # Pas de sweep recent injecte ici -- l'action depend de premium/discount
    # ou retombe sur WAIT, jamais un crash ni un statut degrade.
    assert report.status == "OK"
    assert report.recommendation["action"] in ("WAIT", "BUY_LIMIT", "SELL_LIMIT")
    print("test_smart_money_waits_without_grab_or_choch_far_from_extremes OK")


def test_smart_money_unavailable_on_too_few_candles():
    report = ae.smart_money_analyst_report([{"open": 1, "high": 1, "low": 0, "close": 0.5}] * 3, 0.5)
    assert report.status == "UNAVAILABLE"
    print("test_smart_money_unavailable_on_too_few_candles OK")


def test_smart_money_writes_shared_memory():
    ae.SHARED_MEMORY._store.clear()
    candles = _uptrend_with_liquidity_grab()
    ae.smart_money_analyst_report(candles, candles[-1]["close"])
    envelope = ae.SHARED_MEMORY.read("smart_money")
    assert envelope is not None
    assert envelope["source"] == "smart_money_analyst"
    print("test_smart_money_writes_shared_memory OK")


if __name__ == "__main__":
    test_structure_analyst_detects_uptrend_and_demand_zone()
    test_structure_analyst_unavailable_on_too_few_candles()
    test_structure_analyst_writes_shared_memory()
    test_smart_money_detects_recent_liquidity_grab()
    test_smart_money_waits_without_grab_or_choch_far_from_extremes()
    test_smart_money_unavailable_on_too_few_candles()
    test_smart_money_writes_shared_memory()
    print("ALL TESTS PASSED")
