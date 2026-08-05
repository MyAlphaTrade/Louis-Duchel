"""Tests pour le contrat Scenario (v5.1.1, Phase 1 -- Market Scenario Engine).
Module pur (scenario.py), aucune dependance MT5. Couvre : validation du
contrat, machine a etats (transitions autorisees/refusees), fabriques
(make_scenario/activate_scenario/close_scenario), trace de raisonnement
(history/health_trajectory/reaction_count) -- les points explicitement
demandes par Louis le 04/08/2026 pour que le scenario soit une vraie memoire
de contexte, pas un simple filtre."""
from datetime import datetime, timezone

from scenario import (
    Scenario,
    ScenarioEvent,
    make_scenario,
    activate_scenario,
    close_scenario,
    STATUS_VALUES,
    ALLOWED_TRANSITIONS,
)

NOW = datetime(2026, 8, 4, 10, 30, 0, tzinfo=timezone.utc)


def _zone():
    return {"low": 4085.0, "high": 4088.0}


def test_make_scenario_defaults_to_candidate_with_history_entry():
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), scenario_confidence=68, now=NOW)
    assert s.status == "CANDIDATE"
    assert s.scenario_confidence == 68.0
    assert s.scenario_confidence_at_entry is None
    assert s.scenario_health is None
    assert len(s.history) == 1
    assert s.history[0].status == "CANDIDATE"
    print("test_make_scenario_defaults_to_candidate_with_history_entry OK")


def test_make_scenario_computes_expiry_from_maximum_validity():
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), maximum_validity_min=45, now=NOW)
    assert s.expires_at == "2026-08-04T11:15:00+00:00"
    assert s.is_expired(NOW) is False
    assert s.is_expired(datetime(2026, 8, 4, 11, 16, tzinfo=timezone.utc)) is True
    print("test_make_scenario_computes_expiry_from_maximum_validity OK")


def test_invalid_direction_rejected():
    try:
        Scenario(scenario_id="x", symbol_key="XAUUSD", direction="LONG", zone=_zone())
        assert False, "devait lever ValueError"
    except ValueError:
        pass
    print("test_invalid_direction_rejected OK")


def test_invalid_zone_rejected():
    try:
        Scenario(scenario_id="x", symbol_key="XAUUSD", direction="BUY", zone={"low": 1.0})
        assert False, "devait lever ValueError"
    except ValueError:
        pass
    print("test_invalid_zone_rejected OK")


def test_confidence_clamped_0_100():
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), scenario_confidence=150, now=NOW)
    assert s.scenario_confidence == 100.0
    print("test_confidence_clamped_0_100 OK")


def test_full_lifecycle_candidate_to_completed():
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), scenario_confidence=68, now=NOW)
    s.record_reaction()
    s.transition("VALIDATED", "Zone touchee, reaction confirmee.", now=NOW)
    assert s.reaction_count == 1
    assert s.status == "VALIDATED"

    activate_scenario(s, "CAIO active le scenario.", now=NOW)
    assert s.status == "ACTIVE"
    assert s.scenario_confidence_at_entry == 68.0
    assert s.scenario_health == 68.0
    assert s.scalp_allowed is True

    s.update_health(60, "Leger retracement, degradation mineure.", now=NOW)
    s.update_health(45, "Momentum ralentit.", now=NOW)
    s.transition("DEGRADED", "Sante sous le seuil.", now=NOW)
    assert s.scalp_allowed is True  # transition seule ne coupe pas scalp_allowed -- role du Generator/Validator (Phase 2)

    close_scenario(s, "COMPLETED", "WIN", profit=3.3, now=NOW)
    assert s.status == "COMPLETED"
    assert s.outcome == "WIN"
    assert s.outcome_profit == 3.3

    # Trace complete : creation, validation, activation, 2x update_health, degradation, cloture
    assert len(s.history) == 7
    assert s.health_trajectory() == [68.0, 60.0, 45.0, 45.0, 45.0]
    print("test_full_lifecycle_candidate_to_completed OK")


def test_transition_refused_skips_validated():
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), now=NOW)
    try:
        s.transition("ACTIVE", "Tentative de sauter VALIDATED.", now=NOW)
        assert False, "devait lever ValueError"
    except ValueError:
        pass
    assert s.status == "CANDIDATE"
    print("test_transition_refused_skips_validated OK")


def test_transition_refused_from_terminal_status():
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), now=NOW)
    s.transition("EXPIRED", "Jamais valide, expire.", now=NOW)
    try:
        s.transition("VALIDATED", "Ne devrait pas pouvoir revivre.", now=NOW)
        assert False, "devait lever ValueError"
    except ValueError:
        pass
    print("test_transition_refused_from_terminal_status OK")


def test_degraded_can_recover_to_active():
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), scenario_confidence=70, now=NOW)
    s.transition("VALIDATED", "ok", now=NOW)
    activate_scenario(s, now=NOW)
    s.transition("DEGRADED", "sante basse", now=NOW)
    s.transition("ACTIVE", "sante remontee", now=NOW)
    assert s.status == "ACTIVE"
    print("test_degraded_can_recover_to_active OK")


def test_close_scenario_rejects_non_terminal_status():
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), now=NOW)
    try:
        close_scenario(s, "ACTIVE", "WIN", now=NOW)
        assert False, "devait lever ValueError"
    except ValueError:
        pass
    print("test_close_scenario_rejects_non_terminal_status OK")


def test_all_status_values_reachable_in_allowed_transitions():
    # Chaque statut (sauf CANDIDATE, point de depart) doit etre atteignable
    # depuis au moins un autre -- protection contre un statut orphelin.
    reachable = {"CANDIDATE"}
    for targets in ALLOWED_TRANSITIONS.values():
        reachable |= targets
    assert reachable == set(STATUS_VALUES)
    print("test_all_status_values_reachable_in_allowed_transitions OK")


def test_to_dict_roundtrip_contains_all_contract_fields():
    s = make_scenario(
        "scn-1", "XAUUSD", "BUY", _zone(),
        confluences=["ancien support", "liquidity sweep"],
        scenario_confidence=68,
        market_context={"trend": "bullish", "session": "london", "atr": 18.4},
        invalidation_price=4082.0,
        targets=[{"price": 4092.0, "label": "liquidite proche"}],
        anchor_plan={"entry": 4086.5, "sl": 4082.0, "tp": 4092.0},
        now=NOW,
    )
    d = s.to_dict()
    for key in (
        "scenario_id", "symbol_key", "direction", "zone", "confluences",
        "scenario_confidence", "scenario_confidence_at_entry", "scenario_health",
        "market_context", "invalidation_price", "targets", "anchor_plan",
        "scalp_allowed", "status", "reaction_count", "outcome", "outcome_profit",
        "maximum_validity_min", "created_at", "last_evaluated_at", "expires_at", "history",
    ):
        assert key in d, f"champ manquant dans to_dict(): {key}"
    assert d["market_context"]["session"] == "london"
    assert d["targets"][0]["label"] == "liquidite proche"
    print("test_to_dict_roundtrip_contains_all_contract_fields OK")


def test_scenario_event_to_dict():
    e = ScenarioEvent(at=NOW.isoformat(), status="ACTIVE", note="test", scenario_health=79.0)
    assert e.to_dict() == {"at": NOW.isoformat(), "status": "ACTIVE", "note": "test", "scenario_health": 79.0}
    print("test_scenario_event_to_dict OK")


if __name__ == "__main__":
    test_make_scenario_defaults_to_candidate_with_history_entry()
    test_make_scenario_computes_expiry_from_maximum_validity()
    test_invalid_direction_rejected()
    test_invalid_zone_rejected()
    test_confidence_clamped_0_100()
    test_full_lifecycle_candidate_to_completed()
    test_transition_refused_skips_validated()
    test_transition_refused_from_terminal_status()
    test_degraded_can_recover_to_active()
    test_close_scenario_rejects_non_terminal_status()
    test_all_status_values_reachable_in_allowed_transitions()
    test_to_dict_roundtrip_contains_all_contract_fields()
    test_scenario_event_to_dict()
    print("ALL TESTS PASSED")
