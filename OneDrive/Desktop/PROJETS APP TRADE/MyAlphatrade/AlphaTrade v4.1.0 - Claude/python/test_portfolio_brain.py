"""Tests pour le Portfolio Brain (v5.1.1, chantier 4 -- portfolio_brain.py).
Module pur, aucune dependance MT5 -- pas de redirection DATA_DIR necessaire."""
from portfolio_brain import basket_exposure, portfolio_risk_assessment


def _pos(direction, lot, profit):
    return {"direction": direction, "lot": lot, "profit": profit}


def test_basket_exposure_empty_positions():
    exposure = basket_exposure([], 3800.0)
    assert exposure["position_count"] == 0
    assert exposure["total_lot"] == 0.0
    assert exposure["net_direction"] == "NEUTRAL"
    assert exposure["hedged"] is False
    print("test_basket_exposure_empty_positions OK")


def test_basket_exposure_aggregates_lot_and_pnl():
    positions = [_pos("BUY", 0.10, 5.0), _pos("BUY", 0.05, -2.0)]
    exposure = basket_exposure(positions, 3800.0)
    assert exposure["position_count"] == 2
    assert exposure["buy_lot"] == 0.15
    assert exposure["sell_lot"] == 0.0
    assert exposure["total_lot"] == 0.15
    assert exposure["net_direction"] == "BUY"
    assert exposure["floating_pnl"] == 3.0
    print("test_basket_exposure_aggregates_lot_and_pnl OK")


def test_basket_exposure_detects_hedge():
    positions = [_pos("BUY", 0.10, 5.0), _pos("SELL", 0.10, -3.0)]
    exposure = basket_exposure(positions, 3800.0)
    assert exposure["hedged"] is True
    assert exposure["net_lot"] == 0.0
    assert exposure["net_direction"] == "NEUTRAL"
    print("test_basket_exposure_detects_hedge OK")


def test_basket_exposure_floating_pnl_pct_relative_to_equity():
    positions = [_pos("BUY", 0.10, -190.0)]
    exposure = basket_exposure(positions, 3800.0)
    assert exposure["floating_pnl_pct"] == -5.0
    print("test_basket_exposure_floating_pnl_pct_relative_to_equity OK")


def test_basket_exposure_zero_equity_does_not_crash():
    exposure = basket_exposure([_pos("BUY", 0.10, -50.0)], 0.0)
    assert exposure["floating_pnl_pct"] == 0.0
    print("test_basket_exposure_zero_equity_does_not_crash OK")


def _limits(**overrides):
    base = dict(max_positions=5, max_total_lot=0.0, floating_loss_warn_pct=2.0, floating_loss_critical_pct=5.0)
    base.update(overrides)
    return base


def test_risk_assessment_ok_within_limits():
    exposure = basket_exposure([_pos("BUY", 0.10, 5.0)], 3800.0)
    result = portfolio_risk_assessment(exposure, **_limits())
    assert result["priority"] == "LOW"
    assert result["action"] == "OK"
    assert result["reasons"] == []
    print("test_risk_assessment_ok_within_limits OK")


def test_risk_assessment_too_many_positions_triggers_high():
    exposure = basket_exposure([_pos("BUY", 0.10, 1.0) for _ in range(6)], 3800.0)
    result = portfolio_risk_assessment(exposure, **_limits(max_positions=5))
    assert result["priority"] == "HIGH"
    assert result["action"] == "LIMIT_NEW_ENTRIES"
    assert len(result["reasons"]) == 1
    print("test_risk_assessment_too_many_positions_triggers_high OK")


def test_risk_assessment_total_lot_cap_ignored_when_zero():
    exposure = basket_exposure([_pos("BUY", 5.0, 1.0)], 3800.0)
    result = portfolio_risk_assessment(exposure, **_limits(max_total_lot=0.0))
    assert result["priority"] == "LOW"  # 0 = pas de plafond, meme convention que max_floating_loss
    print("test_risk_assessment_total_lot_cap_ignored_when_zero OK")


def test_risk_assessment_total_lot_cap_enforced_when_positive():
    exposure = basket_exposure([_pos("BUY", 1.0, 1.0)], 3800.0)
    result = portfolio_risk_assessment(exposure, **_limits(max_total_lot=0.5))
    assert result["priority"] == "HIGH"
    assert result["action"] == "LIMIT_NEW_ENTRIES"
    print("test_risk_assessment_total_lot_cap_enforced_when_positive OK")


def test_risk_assessment_floating_loss_warn_is_medium_not_critical():
    exposure = basket_exposure([_pos("BUY", 0.10, -114.0)], 3800.0)  # -3% -- entre warn(2%) et critical(5%)
    result = portfolio_risk_assessment(exposure, **_limits())
    assert result["priority"] == "MEDIUM"
    assert result["action"] == "OK"  # pas encore d'action forcee, juste une alerte
    print("test_risk_assessment_floating_loss_warn_is_medium_not_critical OK")


def test_risk_assessment_floating_loss_critical_forces_reduce_exposure():
    exposure = basket_exposure([_pos("BUY", 0.10, -228.0)], 3800.0)  # -6% -- au-dela du seuil critique 5%
    result = portfolio_risk_assessment(exposure, **_limits())
    assert result["priority"] == "CRITICAL"
    assert result["action"] == "REDUCE_EXPOSURE"
    print("test_risk_assessment_floating_loss_critical_forces_reduce_exposure OK")


def test_risk_assessment_hedge_flagged_as_medium():
    exposure = basket_exposure([_pos("BUY", 0.10, 1.0), _pos("SELL", 0.10, -1.0)], 3800.0)
    result = portfolio_risk_assessment(exposure, **_limits())
    assert result["priority"] == "MEDIUM"
    assert any("hedge" in r.lower() or "couvert" in r.lower() for r in result["reasons"])
    print("test_risk_assessment_hedge_flagged_as_medium OK")


def test_risk_assessment_multiple_reasons_lower_confidence():
    exposure = basket_exposure([_pos("BUY", 1.0, -228.0), _pos("SELL", 1.0, 0.0)], 3800.0)
    result = portfolio_risk_assessment(exposure, **_limits(max_total_lot=0.5))
    assert len(result["reasons"]) >= 2
    assert result["confidence"] < 90.0
    print("test_risk_assessment_multiple_reasons_lower_confidence OK")


def test_risk_assessment_critical_outranks_hedge_and_lot_cap():
    exposure = basket_exposure([_pos("BUY", 1.0, -228.0), _pos("SELL", 1.0, 0.0)], 3800.0)
    result = portfolio_risk_assessment(exposure, **_limits(max_total_lot=0.5))
    assert result["priority"] == "CRITICAL"  # la perte critique doit dominer, meme avec hedge + lot cap actifs
    print("test_risk_assessment_critical_outranks_hedge_and_lot_cap OK")


if __name__ == "__main__":
    test_basket_exposure_empty_positions()
    test_basket_exposure_aggregates_lot_and_pnl()
    test_basket_exposure_detects_hedge()
    test_basket_exposure_floating_pnl_pct_relative_to_equity()
    test_basket_exposure_zero_equity_does_not_crash()
    test_risk_assessment_ok_within_limits()
    test_risk_assessment_too_many_positions_triggers_high()
    test_risk_assessment_total_lot_cap_ignored_when_zero()
    test_risk_assessment_total_lot_cap_enforced_when_positive()
    test_risk_assessment_floating_loss_warn_is_medium_not_critical()
    test_risk_assessment_floating_loss_critical_forces_reduce_exposure()
    test_risk_assessment_hedge_flagged_as_medium()
    test_risk_assessment_multiple_reasons_lower_confidence()
    test_risk_assessment_critical_outranks_hedge_and_lot_cap()
    print("ALL TESTS PASSED")
