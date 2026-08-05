"""Tests pour Scenario Generator + Scenario Validator + Dynamic Position
Manager -- fonctions pures (v5.1.1, Phases 2 et 4). Module pur
(scenario_generator.py), aucune dependance MT5 -- construit des AgentReport
synthetiques comme test_structure_smart_money.py/test_caio_v1.py."""
from datetime import datetime, timezone

from agent_report import make_agent_report
from scenario import make_scenario, activate_scenario
from scenario_generator import (
    generate_scenario,
    validate_scenario,
    evaluate_scenario_health,
    evaluate_scalp_opportunity,
    scenario_learning_stats,
    scenario_weight_adjustments,
    session_label,
    simple_atr,
    volatility_score,
    scenario_confidence_score,
    SCENARIO_WEIGHTS,
)

NOW = datetime(2026, 8, 4, 10, 0, 0, tzinfo=timezone.utc)  # 10h UTC -> session "london"


def _candles(n=60, base=4085.0, rng=1.0):
    # Bougies synthetiques avec un range regulier -- suffisant pour simple_atr.
    out = []
    price = base
    for i in range(n):
        out.append({"open": price, "high": price + rng, "low": price - rng, "close": price, "time": i})
    return out


def _buy_structure(confidence=82.0, price=4086.5, institutional_zones=1):
    return make_agent_report(
        "structure_analyst", status="OK", confidence=confidence, priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": price},
        arguments=["Regime UPTREND, zone demand a 4086.50."],
        metadata={"regime": "UPTREND", "timeframe": "M5", "institutional_zones": institutional_zones},
        now=NOW,
    )


def _buy_smart_money(confidence=78.0, price=4086.0):
    return make_agent_report(
        "smart_money_analyst", status="OK", confidence=confidence, priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": price},
        arguments=["Sweep de liquidite (bullish) sur 4086.00."],
        now=NOW,
    )


def _sell_smart_money(confidence=78.0, price=4086.0):
    return make_agent_report(
        "smart_money_analyst", status="OK", confidence=confidence, priority="MEDIUM",
        recommendation={"action": "SELL_LIMIT", "price": price},
        arguments=["CHOCH bearish confirme."],
        now=NOW,
    )


def _wait_report(agent):
    return make_agent_report(
        agent, status="OK", confidence=50.0, priority="LOW", recommendation={"action": "WAIT"}, now=NOW,
    )


def _ok_risk(rejected=False):
    return make_agent_report(
        "risk_manager", status="OK", confidence=90.0,
        priority="CRITICAL" if rejected else "LOW",
        recommendation={"action": "WAIT", "any_rejected": rejected}, now=NOW,
    )


def _ok_econ(rejected=False):
    return make_agent_report(
        "economic_calendar", status="OK", confidence=100.0,
        priority="CRITICAL" if rejected else "LOW",
        recommendation={"action": "WAIT", "any_rejected": rejected}, now=NOW,
    )


def test_session_label_boundaries():
    assert session_label(datetime(2026, 8, 4, 3, 0, tzinfo=timezone.utc)) == "asian"
    assert session_label(datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)) == "london"
    assert session_label(datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)) == "london_ny_overlap"
    assert session_label(datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)) == "new_york"
    assert session_label(datetime(2026, 8, 4, 22, 0, tzinfo=timezone.utc)) == "off_hours"
    print("test_session_label_boundaries OK")


def test_simple_atr_and_volatility_score():
    candles = _candles(60, rng=1.0)
    assert simple_atr(candles) == 2.0  # high-low = 2.0 constant
    assert volatility_score(candles) == 50.0  # meme range recent que baseline -> neutre
    print("test_simple_atr_and_volatility_score OK")


def test_scenario_confidence_score_within_bounds():
    s = _buy_structure()
    sm = _buy_smart_money()
    score = scenario_confidence_score(s, sm, zone_history_score=50, volatility=50, momentum=50, session=50)
    assert 0 <= score <= 100
    print("test_scenario_confidence_score_within_bounds OK")


def test_generate_scenario_returns_none_on_contradiction():
    scenario = generate_scenario(
        "XAUUSD", _candles(), 4086.5, _buy_structure(), _sell_smart_money(), {}, now=NOW,
    )
    assert scenario is None
    print("test_generate_scenario_returns_none_on_contradiction OK")


def test_generate_scenario_returns_none_when_no_direction():
    scenario = generate_scenario(
        "XAUUSD", _candles(), 4086.5, _wait_report("structure_analyst"), _wait_report("smart_money_analyst"), {}, now=NOW,
    )
    assert scenario is None
    print("test_generate_scenario_returns_none_when_no_direction OK")


def test_generate_scenario_buy_consensus():
    scenario = generate_scenario(
        "XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {"score_gap": 42.1}, now=NOW,
    )
    assert scenario is not None
    assert scenario.direction == "BUY"
    assert scenario.status == "CANDIDATE"
    assert scenario.zone["low"] < scenario.zone["high"]
    assert scenario.invalidation_price < scenario.zone["low"]
    assert scenario.targets[0]["price"] > scenario.anchor_plan["entry"]
    assert scenario.targets[1]["price"] > scenario.targets[0]["price"]
    assert scenario.market_context["session"] == "london"
    assert scenario.market_context["trend"] == "UPTREND"
    assert 0 <= scenario.scenario_confidence <= 100
    print("test_generate_scenario_buy_consensus OK")


def _correction_structure(confidence=82.0, price=4086.5):
    return make_agent_report(
        "structure_analyst", status="OK", confidence=confidence, priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": price},
        arguments=["Regime CORRECTION, zone demand a 4086.50."],
        metadata={"regime": "CORRECTION", "timeframe": "M5", "institutional_zones": 1},
        now=NOW,
    )


def test_generate_scenario_blocks_correction_regime_by_default():
    """v5.1.1 -- analyse du Scenario Replay 58j du 05/08/2026 : CORRECTION a
    une esperance negative (-0,13R/scenario, winrate 38,5% BUY comme SELL).
    Defaut : aucun scenario genere dans ce regime."""
    scenario = generate_scenario(
        "XAUUSD", _candles(), 4086.5, _correction_structure(), _buy_smart_money(), {"score_gap": 42.1}, now=NOW,
    )
    assert scenario is None
    print("test_generate_scenario_blocks_correction_regime_by_default OK")


def test_generate_scenario_correction_regime_allowed_when_flag_false():
    scenario = generate_scenario(
        "XAUUSD", _candles(), 4086.5, _correction_structure(), _buy_smart_money(), {"score_gap": 42.1},
        now=NOW, block_correction_regime=False,
    )
    assert scenario is not None
    assert scenario.market_context["trend"] == "CORRECTION"
    print("test_generate_scenario_correction_regime_allowed_when_flag_false OK")


def test_generate_scenario_other_regimes_unaffected_by_correction_filter():
    scenario = generate_scenario(
        "XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {"score_gap": 42.1}, now=NOW,
    )
    assert scenario is not None  # UPTREND -- jamais bloque par ce filtre
    print("test_generate_scenario_other_regimes_unaffected_by_correction_filter OK")


def test_generate_scenario_sell_direction_mirrors_invalidation():
    structure_sell = make_agent_report(
        "structure_analyst", status="OK", confidence=82.0, priority="MEDIUM",
        recommendation={"action": "SELL_LIMIT", "price": 4086.5},
        arguments=["Regime DOWNTREND."], metadata={"regime": "DOWNTREND", "timeframe": "M5"}, now=NOW,
    )
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, structure_sell, _sell_smart_money(), {}, now=NOW)
    assert scenario.direction == "SELL"
    assert scenario.invalidation_price > scenario.zone["high"]
    assert scenario.targets[0]["price"] < scenario.anchor_plan["entry"]
    print("test_generate_scenario_sell_direction_mirrors_invalidation OK")


def test_validate_scenario_all_pass_transitions_to_validated():
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, now=NOW)
    checks = validate_scenario(scenario, 4086.6, _buy_smart_money(), _ok_risk(), _ok_econ(), now=NOW)
    assert all(checks.values())
    assert scenario.status == "VALIDATED"
    assert scenario.reaction_count == 1
    assert scenario.last_validation == checks
    print("test_validate_scenario_all_pass_transitions_to_validated OK")


def test_validate_scenario_zone_not_touched_stays_candidate():
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, now=NOW)
    # 4080 -- clairement sous la zone (BUY, "pas encore retombe dedans"), mais
    # sous la derniere cible aussi (targets au-dessus de l'entree pour un BUY)
    # -- isole bien "zone pas touchee" de la nouvelle regle _price_beyond_final_target
    # (05/08/2026), qui a une priorite differente et ne doit pas se declencher ici.
    checks = validate_scenario(scenario, 4080.0, _buy_smart_money(), _ok_risk(), _ok_econ(), now=NOW)
    assert checks["zone_touched"] is False
    assert scenario.status == "CANDIDATE"
    assert scenario.reaction_count == 0
    print("test_validate_scenario_zone_not_touched_stays_candidate OK")


def test_validate_scenario_zone_touched_stays_sticky_after_price_moves_away():
    """05/08/2026 -- bug trouve en observation reelle : un BUY dont le prix a
    fortement depasse la zone restait bloque avec zone_touched=False en
    permanence, meme si la zone AVAIT ete touchee au depart. Cycle 1 :
    zone touchee mais Smart Money pas encore aligne (reste CANDIDATE).
    Cycle 2 : prix reparti hors zone (mais pas au-dela de la derniere cible),
    Smart Money desormais aligne -- zone_touched doit rester vrai (sticky)."""
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, now=NOW)
    checks1 = validate_scenario(scenario, 4086.6, _sell_smart_money(), _ok_risk(), _ok_econ(), now=NOW)
    assert checks1["zone_touched"] is True
    assert checks1["reaction"] is False  # Smart Money oppose -- pas encore de reaction
    assert scenario.status == "CANDIDATE"
    assert scenario.reaction_count == 1

    checks2 = validate_scenario(scenario, 4092.0, _buy_smart_money(), _ok_risk(), _ok_econ(), now=NOW)
    assert checks2["zone_touched"] is True  # sticky -- prix pourtant hors zone a ce cycle
    assert all(checks2.values())
    assert scenario.status == "VALIDATED"
    assert scenario.reaction_count == 1  # pas incremente au 2e cycle -- pas une touche fraiche
    print("test_validate_scenario_zone_touched_stays_sticky_after_price_moves_away OK")


def test_validate_scenario_expires_immediately_when_price_beyond_final_target():
    """05/08/2026 -- demande de Louis : un scenario dont le prix a deja
    depasse la derniere cible sans jamais avoir ete valide ne doit pas
    attendre les 45 min d'expiration normales -- il doit se liberer
    immediatement pour qu'une nouvelle analyse puisse se faire."""
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, now=NOW)
    final_target = scenario.targets[-1]["price"]
    checks = validate_scenario(scenario, final_target + 1.0, _buy_smart_money(), _ok_risk(), _ok_econ(), now=NOW)
    assert checks["zone_touched"] is False  # jamais touchee -- le prix est passe tout droit
    assert scenario.status == "EXPIRED"
    assert scenario.outcome is None  # pas de resultat simule -- jamais active, juste libere
    print("test_validate_scenario_expires_immediately_when_price_beyond_final_target OK")


def test_validate_scenario_expires_beyond_final_target_even_when_validated():
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, now=NOW)
    scenario.transition("VALIDATED", "test", now=NOW)
    final_target = scenario.targets[-1]["price"]
    validate_scenario(scenario, final_target + 1.0, _buy_smart_money(), _ok_risk(), _ok_econ(), now=NOW)
    assert scenario.status == "EXPIRED"
    print("test_validate_scenario_expires_beyond_final_target_even_when_validated OK")


def test_validate_scenario_risk_critical_blocks_validation():
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, now=NOW)
    checks = validate_scenario(scenario, 4086.6, _buy_smart_money(), _ok_risk(rejected=True), _ok_econ(), now=NOW)
    assert checks["risk_ok"] is False
    assert scenario.status == "CANDIDATE"
    print("test_validate_scenario_risk_critical_blocks_validation OK")


def test_validate_scenario_economic_calendar_critical_blocks_validation():
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, now=NOW)
    checks = validate_scenario(scenario, 4086.6, _buy_smart_money(), _ok_risk(), _ok_econ(rejected=True), now=NOW)
    assert checks["market_ok"] is False
    assert scenario.status == "CANDIDATE"
    print("test_validate_scenario_economic_calendar_critical_blocks_validation OK")


def test_validate_scenario_none_economic_report_is_ok():
    scenario = generate_scenario("XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, now=NOW)
    checks = validate_scenario(scenario, 4086.6, _buy_smart_money(), _ok_risk(), None, now=NOW)
    assert checks["market_ok"] is True
    print("test_validate_scenario_none_economic_report_is_ok OK")


def test_validate_scenario_expires_validated_scenario_never_activated():
    """Regression -- bug trouve par le Scenario Replay du 04/08/2026 : un
    scenario VALIDATED dont la confiance reste sous caio_min_confidence
    restait bloque indefiniment (aucun chemin d'expiration ne couvrait ce
    statut), empechant tout nouveau scenario d'etre genere ensuite."""
    scenario = generate_scenario(
        "XAUUSD", _candles(), 4086.5, _buy_structure(confidence=61), _buy_smart_money(confidence=61),
        maximum_validity_min=10, now=NOW,
    )
    validate_scenario(scenario, 4086.6, _buy_smart_money(), _ok_risk(), _ok_econ(), now=NOW)
    assert scenario.status == "VALIDATED"
    later = datetime(2026, 8, 4, 10, 25, tzinfo=timezone.utc)  # 25 min plus tard, > 10 min de validite
    validate_scenario(scenario, 4086.6, _buy_smart_money(), _ok_risk(), _ok_econ(), now=later)
    assert scenario.status == "EXPIRED"
    print("test_validate_scenario_expires_validated_scenario_never_activated OK")


def test_validate_scenario_expires_when_never_validated_in_time():
    scenario = generate_scenario(
        "XAUUSD", _candles(), 4086.5, _buy_structure(), _buy_smart_money(), {}, maximum_validity_min=10, now=NOW,
    )
    later = datetime(2026, 8, 4, 10, 25, tzinfo=timezone.utc)  # 25 min plus tard, > 10 min de validite
    checks = validate_scenario(scenario, 4200.0, _buy_smart_money(), _ok_risk(), _ok_econ(), now=later)
    assert checks["zone_touched"] is False
    assert scenario.status == "EXPIRED"
    print("test_validate_scenario_expires_when_never_validated_in_time OK")


def _active_scenario(confidence=80.0):
    scenario = make_scenario(
        "XAUUSD_A", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0},
        scenario_confidence=confidence,
        market_context={"atr": 2.0},
        invalidation_price=4080.0,
        targets=[{"price": 4092.0, "label": "t1"}, {"price": 4098.0, "label": "t2"}],
        anchor_plan={"entry": 4086.5, "sl": 4080.0, "tp": 4092.0},
        now=NOW,
    )
    scenario.transition("VALIDATED", "test", now=NOW)
    activate_scenario(scenario, now=NOW)
    return scenario


def test_evaluate_scenario_health_matches_composite_when_reports_agree():
    scenario = _active_scenario()
    health = evaluate_scenario_health(scenario, _buy_structure(), _buy_smart_money(), _candles(), {}, now=NOW)
    assert 0 <= health <= 100
    print("test_evaluate_scenario_health_matches_composite_when_reports_agree OK")


def test_evaluate_scenario_health_capped_when_smart_money_reverses():
    scenario = _active_scenario()
    health = evaluate_scenario_health(scenario, _buy_structure(), _sell_smart_money(), _candles(), {}, now=NOW)
    assert health <= 35.0
    print("test_evaluate_scenario_health_capped_when_smart_money_reverses OK")


def test_evaluate_scenario_health_keeps_last_value_when_reports_unavailable():
    scenario = _active_scenario()
    scenario.scenario_health = 62.0
    unavailable = make_agent_report(
        "structure_analyst", status="UNAVAILABLE", confidence=0, priority="LOW", recommendation={"action": "WAIT"}, now=NOW,
    )
    health = evaluate_scenario_health(scenario, unavailable, _buy_smart_money(), _candles(), {}, now=NOW)
    assert health == 62.0
    print("test_evaluate_scenario_health_keeps_last_value_when_reports_unavailable OK")


def test_evaluate_scalp_opportunity_all_conditions_pass():
    scenario = _active_scenario()
    checks = evaluate_scalp_opportunity(scenario, 4086.6, _ok_risk(), {"score_gap": 50.0}, now=NOW)
    assert all(checks.values())
    print("test_evaluate_scalp_opportunity_all_conditions_pass OK")


def test_evaluate_scalp_opportunity_blocked_when_scalp_not_allowed():
    scenario = _active_scenario()
    scenario.scalp_allowed = False
    checks = evaluate_scalp_opportunity(scenario, 4086.6, _ok_risk(), {"score_gap": 50.0}, now=NOW)
    assert checks["scenario_active"] is False
    print("test_evaluate_scalp_opportunity_blocked_when_scalp_not_allowed OK")


def test_evaluate_scalp_opportunity_blocked_on_low_momentum():
    scenario = _active_scenario()
    checks = evaluate_scalp_opportunity(scenario, 4086.6, _ok_risk(), {"score_gap": 5.0}, now=NOW)
    assert checks["micro_opportunity"] is False
    print("test_evaluate_scalp_opportunity_blocked_on_low_momentum OK")


def test_evaluate_scalp_opportunity_blocked_on_risk_critical():
    scenario = _active_scenario()
    checks = evaluate_scalp_opportunity(scenario, 4086.6, _ok_risk(rejected=True), {"score_gap": 50.0}, now=NOW)
    assert checks["risk_panier_ok"] is False
    print("test_evaluate_scalp_opportunity_blocked_on_risk_critical OK")


def _resolved_entry(session="london", trend="UPTREND", volatility="medium", direction="BUY", win=True):
    return {
        "outcome": "WIN_SIMULATED" if win else "LOSS_SIMULATED",
        "market_context": {"session": session, "trend": trend, "volatility": volatility},
        "direction": direction,
    }


def test_scenario_learning_stats_ignores_unresolved_and_small_samples():
    entries = [_resolved_entry(win=True) for _ in range(5)] + [{"status": "EXPIRED", "outcome": None}]
    stats = scenario_learning_stats(entries, min_samples=20)
    assert stats["n_resolved"] == 5  # les EXPIRED sans outcome sont exclus
    assert stats["by_session"] == {}  # 5 < min_samples=20, aucune case publiee
    print("test_scenario_learning_stats_ignores_unresolved_and_small_samples OK")


def test_scenario_learning_stats_computes_winrate_per_bucket():
    entries = (
        [_resolved_entry(session="london", win=True) for _ in range(18)]
        + [_resolved_entry(session="london", win=False) for _ in range(2)]
        + [_resolved_entry(session="asian", win=False) for _ in range(20)]
    )
    stats = scenario_learning_stats(entries, min_samples=20)
    assert stats["n_resolved"] == 40
    assert stats["by_session"]["london"] == {"samples": 20, "winrate": 90.0}
    assert stats["by_session"]["asian"] == {"samples": 20, "winrate": 0.0}
    print("test_scenario_learning_stats_computes_winrate_per_bucket OK")


def test_scenario_weight_adjustments_bounded_and_directionally_sensible():
    entries = (
        [_resolved_entry(session="london_ny_overlap", win=True) for _ in range(30)]
        + [_resolved_entry(session="off_hours", win=False) for _ in range(30)]
    )
    stats = scenario_learning_stats(entries, min_samples=20)
    adjusted = scenario_weight_adjustments(stats, SCENARIO_WEIGHTS, max_delta=0.05)
    assert adjusted["session"] > SCENARIO_WEIGHTS["session"]  # la session performante pousse le poids a la hausse
    assert all(abs(adjusted[k] - SCENARIO_WEIGHTS[k]) <= 0.05 + 1e-9 for k in SCENARIO_WEIGHTS)  # jamais hors bornes
    assert set(adjusted) == set(SCENARIO_WEIGHTS)  # aucun facteur perdu ou ajoute
    print("test_scenario_weight_adjustments_bounded_and_directionally_sensible OK")


def test_scenario_weight_adjustments_neutral_when_no_signal():
    entries = [_resolved_entry(session="london", win=(i % 2 == 0)) for i in range(40)]  # 50/50, aucun signal
    stats = scenario_learning_stats(entries, min_samples=20)
    adjusted = scenario_weight_adjustments(stats, SCENARIO_WEIGHTS)
    assert adjusted["session"] == SCENARIO_WEIGHTS["session"]
    print("test_scenario_weight_adjustments_neutral_when_no_signal OK")


if __name__ == "__main__":
    test_session_label_boundaries()
    test_simple_atr_and_volatility_score()
    test_scenario_confidence_score_within_bounds()
    test_generate_scenario_returns_none_on_contradiction()
    test_generate_scenario_returns_none_when_no_direction()
    test_generate_scenario_buy_consensus()
    test_generate_scenario_blocks_correction_regime_by_default()
    test_generate_scenario_correction_regime_allowed_when_flag_false()
    test_generate_scenario_other_regimes_unaffected_by_correction_filter()
    test_generate_scenario_sell_direction_mirrors_invalidation()
    test_validate_scenario_all_pass_transitions_to_validated()
    test_validate_scenario_zone_not_touched_stays_candidate()
    test_validate_scenario_zone_touched_stays_sticky_after_price_moves_away()
    test_validate_scenario_expires_immediately_when_price_beyond_final_target()
    test_validate_scenario_expires_beyond_final_target_even_when_validated()
    test_validate_scenario_risk_critical_blocks_validation()
    test_validate_scenario_economic_calendar_critical_blocks_validation()
    test_validate_scenario_none_economic_report_is_ok()
    test_validate_scenario_expires_when_never_validated_in_time()
    test_validate_scenario_expires_validated_scenario_never_activated()
    test_evaluate_scenario_health_matches_composite_when_reports_agree()
    test_evaluate_scenario_health_capped_when_smart_money_reverses()
    test_evaluate_scenario_health_keeps_last_value_when_reports_unavailable()
    test_evaluate_scalp_opportunity_all_conditions_pass()
    test_evaluate_scalp_opportunity_blocked_when_scalp_not_allowed()
    test_evaluate_scalp_opportunity_blocked_on_low_momentum()
    test_evaluate_scalp_opportunity_blocked_on_risk_critical()
    test_scenario_learning_stats_ignores_unresolved_and_small_samples()
    test_scenario_learning_stats_computes_winrate_per_bucket()
    test_scenario_weight_adjustments_bounded_and_directionally_sensible()
    test_scenario_weight_adjustments_neutral_when_no_signal()
    print("ALL TESTS PASSED")
