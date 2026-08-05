"""Tests pour le Gold Microstructure Engine (v5.1.1, chantier 2 --
market_microstructure_gold.py). Module pur, aucune dependance MT5 -- pas de
redirection DATA_DIR necessaire, contrairement aux tests qui touchent
alphatrade_engine."""
from market_microstructure_gold import (
    candle_velocity,
    candle_acceleration,
    candle_size_trend,
    rejection_score,
    gold_microstructure_score,
)


def _flat(n=20, price=4085.0, rng=2.0):
    return [{"open": price, "high": price + rng / 2, "low": price - rng / 2, "close": price} for _ in range(n)]


def test_candle_velocity_empty_and_single_candle_is_neutral():
    assert candle_velocity([]) == 0.0
    assert candle_velocity([{"open": 1, "high": 1, "low": 1, "close": 1}]) == 0.0


def test_candle_velocity_signed():
    up = [{"open": 4085, "high": 4086, "low": 4084, "close": 4085}, {"open": 4085, "high": 4087, "low": 4085, "close": 4087}]
    down = [{"open": 4085, "high": 4086, "low": 4084, "close": 4085}, {"open": 4085, "high": 4085, "low": 4083, "close": 4083}]
    assert candle_velocity(up) == 2.0
    assert candle_velocity(down) == -2.0
    print("test_candle_velocity_signed OK")


def test_candle_acceleration_neutral_when_not_enough_candles():
    assert candle_acceleration(_flat(3), lookback=5) == 0.0
    print("test_candle_acceleration_neutral_when_not_enough_candles OK")


def test_candle_acceleration_detects_deceleration_of_a_drop():
    # Vitesse de baisse qui se reduit a chaque bougie (mouvement qui s'essouffle).
    closes = [4090.0, 4087.0, 4085.5, 4084.7, 4084.3, 4084.1]  # deltas: -3,-1.5,-0.8,-0.4,-0.2
    candles = [{"open": c, "high": c + 0.5, "low": c - 0.5, "close": c} for c in closes]
    accel = candle_acceleration(candles, lookback=5)
    assert accel > 0  # deceleration = derivee seconde positive sur un mouvement negatif
    print("test_candle_acceleration_detects_deceleration_of_a_drop OK")


def test_candle_acceleration_detects_acceleration_of_a_drop():
    # Vitesse de baisse qui grossit a chaque bougie (mouvement qui s'intensifie).
    closes = [4090.0, 4089.8, 4089.3, 4088.3, 4086.3, 4082.3]  # deltas: -0.2,-0.5,-1.0,-2.0,-4.0
    candles = [{"open": c, "high": c + 0.5, "low": c - 0.5, "close": c} for c in closes]
    accel = candle_acceleration(candles, lookback=5)
    assert accel < 0
    print("test_candle_acceleration_detects_acceleration_of_a_drop OK")


def test_candle_size_trend_neutral_when_not_enough_history():
    assert candle_size_trend(_flat(5), lookback=5) == 1.0
    print("test_candle_size_trend_neutral_when_not_enough_history OK")


def test_candle_size_trend_shrinking_below_one():
    prior = _flat(5, rng=4.0)
    recent = _flat(5, rng=1.0)
    trend = candle_size_trend(prior + recent, lookback=5)
    assert trend < 1.0
    print("test_candle_size_trend_shrinking_below_one OK")


def test_candle_size_trend_growing_above_one():
    prior = _flat(5, rng=1.0)
    recent = _flat(5, rng=4.0)
    trend = candle_size_trend(prior + recent, lookback=5)
    assert trend > 1.0
    print("test_candle_size_trend_growing_above_one OK")


def test_rejection_score_empty_is_zero():
    assert rejection_score([], "BUY") == 0.0
    print("test_rejection_score_empty_is_zero OK")


def test_rejection_score_detects_lower_wick_for_buy():
    # meche basse longue (rejet du bas), cloture haute -- favorable a BUY
    candle = {"open": 4084.9, "high": 4085.0, "low": 4084.0, "close": 4084.7}
    score = rejection_score([candle], "BUY")
    assert score > 50.0
    print("test_rejection_score_detects_lower_wick_for_buy OK")


def test_rejection_score_detects_upper_wick_for_sell():
    # meche haute longue (rejet du haut), cloture basse -- favorable a SELL
    candle = {"open": 4085.1, "high": 4086.0, "low": 4085.0, "close": 4085.3}
    score = rejection_score([candle], "SELL")
    assert score > 50.0
    print("test_rejection_score_detects_upper_wick_for_sell OK")


def test_rejection_score_low_when_wick_opposes_direction():
    # meche basse longue mais on demande le score SELL (qui regarde la meche haute) -- doit rester bas
    candle = {"open": 4084.9, "high": 4085.0, "low": 4084.0, "close": 4084.7}
    score = rejection_score([candle], "SELL")
    assert score < 50.0
    print("test_rejection_score_low_when_wick_opposes_direction OK")


def test_rejection_score_ignores_zero_range_candles():
    flat_candle = {"open": 4085.0, "high": 4085.0, "low": 4085.0, "close": 4085.0}
    assert rejection_score([flat_candle], "BUY") == 0.0
    print("test_rejection_score_ignores_zero_range_candles OK")


def test_gold_microstructure_score_bounded_and_has_all_fields():
    result = gold_microstructure_score(_flat(20), "BUY")
    assert 0.0 <= result["score"] <= 100.0
    assert set(result.keys()) == {"score", "velocity", "acceleration", "size_trend", "rejection"}
    print("test_gold_microstructure_score_bounded_and_has_all_fields OK")


def test_gold_microstructure_score_neutral_on_flat_candles():
    # Bougies parfaitement plates : ni rejet, ni acceleration, ni tendance de taille -- score proche de 50.
    result = gold_microstructure_score(_flat(20), "BUY")
    assert 40.0 <= result["score"] <= 60.0
    print("test_gold_microstructure_score_neutral_on_flat_candles OK")


def test_gold_microstructure_score_high_on_louis_rejection_example():
    """Reproduit l'exemple de Louis (04/08/2026) : prix qui descend mais dont
    la vitesse baisse, bougies qui retrecissent, rejet de meche basse -- doit
    donner un score eleve pour BUY malgre un mouvement recent baissier."""
    filler = _flat(10, price=4090.0, rng=3.0)
    recent = [
        {"open": 4085.5, "high": 4086.0, "low": 4085.0, "close": 4085.5},
        {"open": 4085.0, "high": 4085.5, "low": 4084.5, "close": 4085.0},
        {"open": 4084.9, "high": 4085.0, "low": 4084.0, "close": 4084.7},
        {"open": 4084.6, "high": 4084.8, "low": 4083.8, "close": 4084.5},
        {"open": 4084.5, "high": 4084.7, "low": 4083.7, "close": 4084.4},
    ]
    result = gold_microstructure_score(filler + recent, "BUY")
    assert result["score"] >= 60.0
    print("test_gold_microstructure_score_high_on_louis_rejection_example OK")


def test_gold_microstructure_score_direction_flips_result():
    """Le meme mouvement (baisse qui decelere + rejet bas) est favorable a BUY
    mais PAS a SELL -- le score doit differer selon `direction`."""
    filler = _flat(10, price=4090.0, rng=3.0)
    recent = [
        {"open": 4085.5, "high": 4086.0, "low": 4085.0, "close": 4085.5},
        {"open": 4085.0, "high": 4085.5, "low": 4084.5, "close": 4085.0},
        {"open": 4084.9, "high": 4085.0, "low": 4084.0, "close": 4084.7},
        {"open": 4084.6, "high": 4084.8, "low": 4083.8, "close": 4084.5},
        {"open": 4084.5, "high": 4084.7, "low": 4083.7, "close": 4084.4},
    ]
    candles = filler + recent
    buy_score = gold_microstructure_score(candles, "BUY")["score"]
    sell_score = gold_microstructure_score(candles, "SELL")["score"]
    assert buy_score > sell_score
    print("test_gold_microstructure_score_direction_flips_result OK")


if __name__ == "__main__":
    test_candle_velocity_empty_and_single_candle_is_neutral()
    test_candle_velocity_signed()
    test_candle_acceleration_neutral_when_not_enough_candles()
    test_candle_acceleration_detects_deceleration_of_a_drop()
    test_candle_acceleration_detects_acceleration_of_a_drop()
    test_candle_size_trend_neutral_when_not_enough_history()
    test_candle_size_trend_shrinking_below_one()
    test_candle_size_trend_growing_above_one()
    test_rejection_score_empty_is_zero()
    test_rejection_score_detects_lower_wick_for_buy()
    test_rejection_score_detects_upper_wick_for_sell()
    test_rejection_score_low_when_wick_opposes_direction()
    test_rejection_score_ignores_zero_range_candles()
    test_gold_microstructure_score_bounded_and_has_all_fields()
    test_gold_microstructure_score_neutral_on_flat_candles()
    test_gold_microstructure_score_high_on_louis_rejection_example()
    test_gold_microstructure_score_direction_flips_result()
    print("ALL TESTS PASSED")
