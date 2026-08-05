"""Tests pour le Trading Style Engine (v5.1.1, chantier 3 --
trading_style_engine.py). Module pur, aucune dependance MT5 -- pas de
redirection DATA_DIR necessaire."""
from trading_style_engine import recommend_trading_style, VALID_MODES


def test_recommend_returns_a_valid_mode_for_every_branch():
    for regime in ("UPTREND", "DOWNTREND", "RANGE", "CORRECTION", None, "UNKNOWN"):
        for volatility in ("low", "medium", "high", "garbage"):
            result = recommend_trading_style(regime, volatility)
            assert result["mode"] in VALID_MODES
    print("test_recommend_returns_a_valid_mode_for_every_branch OK")


def test_high_volatility_forces_scalping_safe_regardless_of_regime():
    for regime in ("UPTREND", "DOWNTREND", "RANGE", "CORRECTION"):
        result = recommend_trading_style(regime, "high")
        assert result["mode"] == "scalping_safe"
    print("test_high_volatility_forces_scalping_safe_regardless_of_regime OK")


def test_clear_trend_without_high_volatility_recommends_long_analysis():
    assert recommend_trading_style("UPTREND", "medium")["mode"] == "long_analysis"
    assert recommend_trading_style("DOWNTREND", "low")["mode"] == "long_analysis"
    print("test_clear_trend_without_high_volatility_recommends_long_analysis OK")


def test_calm_range_recommends_scalping_fast():
    result = recommend_trading_style("RANGE", "low")
    assert result["mode"] == "scalping_fast"
    print("test_calm_range_recommends_scalping_fast OK")


def test_mixed_context_falls_back_to_combined():
    assert recommend_trading_style("CORRECTION", "medium")["mode"] == "combined"
    assert recommend_trading_style("RANGE", "medium")["mode"] == "combined"
    assert recommend_trading_style(None, "medium")["mode"] == "combined"
    print("test_mixed_context_falls_back_to_combined OK")


def test_unknown_volatility_label_treated_as_medium():
    # volatility hors {low,medium,high} -- ne doit pas planter, retombe medium.
    result = recommend_trading_style("RANGE", "n/a")
    assert result["volatility"] == "medium"
    assert result["mode"] == "combined"
    print("test_unknown_volatility_label_treated_as_medium OK")


def test_result_always_has_a_non_empty_reason():
    result = recommend_trading_style("UPTREND", "high")
    assert isinstance(result["reason"], str) and len(result["reason"]) > 10
    print("test_result_always_has_a_non_empty_reason OK")


if __name__ == "__main__":
    test_recommend_returns_a_valid_mode_for_every_branch()
    test_high_volatility_forces_scalping_safe_regardless_of_regime()
    test_clear_trend_without_high_volatility_recommends_long_analysis()
    test_calm_range_recommends_scalping_fast()
    test_mixed_context_falls_back_to_combined()
    test_unknown_volatility_label_treated_as_medium()
    test_result_always_has_a_non_empty_reason()
    print("ALL TESTS PASSED")
