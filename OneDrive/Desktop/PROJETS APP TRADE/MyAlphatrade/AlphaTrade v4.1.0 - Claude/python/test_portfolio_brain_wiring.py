"""Tests pour le branchement reel du Portfolio Brain (v5.1.1, chantier 4)
dans alphatrade_engine.py : portfolio_brain_report(), compartiment
SHARED_MEMORY 'portfolio', et la garde d'observation obligatoire (ne ferme/
ne bloque jamais une position elle-meme)."""
import os
import tempfile
from datetime import datetime, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae

NOW = datetime(2026, 8, 5, 10, 30, 0, tzinfo=timezone.utc)


def _pos(direction, lot, profit):
    return {"direction": direction, "lot": lot, "profit": profit}


def test_report_shape_matches_agent_report_contract():
    report = ae.portfolio_brain_report({}, [_pos("BUY", 0.10, 5.0)], 3800.0, now=NOW)
    assert report.agent == "portfolio_brain"
    assert report.status == "OK"
    assert report.priority in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert "action" in report.recommendation
    assert "exposure" in report.recommendation
    print("test_report_shape_matches_agent_report_contract OK")


def test_report_uses_params_thresholds_not_hardcoded():
    """Meme regle que tout le reste du projet (pas de valeur en dur) --
    verifie que le seuil vient bien de params, pas d'une constante figee."""
    positions = [_pos("BUY", 6.0, 1.0)]  # 6 positions ne s'applique pas ici, on teste le lot cap
    report_no_cap = ae.portfolio_brain_report({"portfolio_max_total_lot": 0.0}, positions, 3800.0, now=NOW)
    report_with_cap = ae.portfolio_brain_report({"portfolio_max_total_lot": 1.0}, positions, 3800.0, now=NOW)
    assert report_no_cap.priority == "LOW"
    assert report_with_cap.priority == "HIGH"
    print("test_report_uses_params_thresholds_not_hardcoded OK")


def test_report_writes_to_portfolio_compartment():
    ae.SHARED_MEMORY._store.clear()
    ae.portfolio_brain_report({}, [_pos("BUY", 0.10, 5.0)], 3800.0, now=NOW)
    envelope = ae.SHARED_MEMORY.read("portfolio")
    assert envelope is not None
    assert envelope["source"] == "portfolio_brain"
    print("test_report_writes_to_portfolio_compartment OK")


def test_only_portfolio_brain_can_write_portfolio_compartment():
    ae.SHARED_MEMORY._store.clear()
    try:
        ae.SHARED_MEMORY.write("portfolio", "caio", {"x": 1}, now=NOW)
        assert False, "devait lever PermissionError"
    except PermissionError:
        pass
    print("test_only_portfolio_brain_can_write_portfolio_compartment OK")


def test_critical_priority_on_severe_floating_loss():
    positions = [_pos("BUY", 0.10, -228.0)]  # -6% de l'equite, au-dela du defaut critique 5%
    report = ae.portfolio_brain_report({}, positions, 3800.0, now=NOW)
    assert report.priority == "CRITICAL"
    assert report.recommendation["action"] == "REDUCE_EXPOSURE"
    print("test_critical_priority_on_severe_floating_loss OK")


def test_never_calls_real_execution():
    """Meme garde de securite systematique que les autres chantiers : le
    Portfolio Brain ne doit jamais appeler place_order()/open_position(),
    meme sur un panier en priorite CRITICAL."""
    original_place_order = ae.place_order
    original_open_position = ae.open_position

    def _poison(*a, **k):
        raise AssertionError("portfolio_brain_report() ne doit jamais executer d'ordre reel")

    ae.place_order = _poison
    ae.open_position = _poison
    try:
        positions = [_pos("BUY", 0.10, -228.0), _pos("SELL", 0.10, 0.0)]
        report = ae.portfolio_brain_report({}, positions, 3800.0, now=NOW)
        assert report.priority == "CRITICAL"
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
    print("test_never_calls_real_execution OK")


if __name__ == "__main__":
    test_report_shape_matches_agent_report_contract()
    test_report_uses_params_thresholds_not_hardcoded()
    test_report_writes_to_portfolio_compartment()
    test_only_portfolio_brain_can_write_portfolio_compartment()
    test_critical_priority_on_severe_floating_loss()
    test_never_calls_real_execution()
    print("ALL TESTS PASSED")
