"""Tests pour engine_decision.py (v1.1.5, Phase 1, 06/08/2026 -- demande
explicite de Louis). Module pur -- pas de MT5/reseau, pas d'ALPHATRADE_DATA_DIR
necessaire ici (contrairement aux autres fichiers de test de ce projet)."""
from engine_decision import (
    fuse_agent_reports, build_decision_registry_entry, high_conviction,
    compute_agent_reliability_weights, label_decision_outcomes,
)


def test_fuse_agent_reports_matches_louis_example():
    """Reproduit exactement l'exemple donne par Louis : Structure BUY 78%,
    Smart Money BUY 65%, Indicator SELL 52%, Scenario BUY 81% -> BUY,
    confiance = moyenne(78,65,81) = 74.67 ~ 74.7."""
    scores = {
        "structure": {"action": "BUY", "confidence": 78},
        "smart_money": {"action": "BUY", "confidence": 65},
        "indicator": {"action": "SELL", "confidence": 52},
        "scenario": {"action": "BUY", "confidence": 81},
    }
    fused = fuse_agent_reports(scores)
    assert fused["final"] == "BUY"
    assert fused["buy_total"] == 78 + 65 + 81
    assert fused["sell_total"] == 52
    assert fused["confidence"] == round((78 + 65 + 81) / 3, 1)
    print("test_fuse_agent_reports_matches_louis_example OK")


def test_fuse_agent_reports_sell_wins():
    scores = {
        "structure": {"action": "SELL", "confidence": 90},
        "indicator": {"action": "BUY", "confidence": 40},
    }
    fused = fuse_agent_reports(scores)
    assert fused["final"] == "SELL"
    assert fused["confidence"] == 90.0
    print("test_fuse_agent_reports_sell_wins OK")


def test_fuse_agent_reports_wait_when_no_directional_agent():
    scores = {
        "structure": {"action": "WAIT", "confidence": 0},
        "indicator": {"action": "WAIT", "confidence": 0},
    }
    fused = fuse_agent_reports(scores)
    assert fused["final"] == "WAIT"
    assert fused["confidence"] == 0.0
    print("test_fuse_agent_reports_wait_when_no_directional_agent OK")


def test_fuse_agent_reports_wait_on_strict_tie():
    """Une decision de trading ne doit jamais departager une egalite au
    hasard -- WAIT est le seul resultat legitime."""
    scores = {
        "structure": {"action": "BUY", "confidence": 50},
        "indicator": {"action": "SELL", "confidence": 50},
    }
    fused = fuse_agent_reports(scores)
    assert fused["final"] == "WAIT"
    print("test_fuse_agent_reports_wait_on_strict_tie OK")


def test_fuse_agent_reports_accepts_order_type_actions():
    """recommendation['action'] peut etre 'BUY_MARKET'/'SELL_LIMIT'/etc
    (forme reelle produite par les AgentReport existants), pas seulement
    'BUY'/'SELL' bruts."""
    scores = {
        "structure": {"action": "BUY_MARKET", "confidence": 70},
        "smart_money": {"action": "SELL_LIMIT", "confidence": 30},
    }
    fused = fuse_agent_reports(scores)
    assert fused["final"] == "BUY"
    print("test_fuse_agent_reports_accepts_order_type_actions OK")


def test_fuse_agent_reports_empty_input_is_wait():
    fused = fuse_agent_reports({})
    assert fused["final"] == "WAIT"
    assert fused["confidence"] == 0.0
    print("test_fuse_agent_reports_empty_input_is_wait OK")


def test_fuse_agent_reports_confidence_clamped_0_100():
    scores = {"structure": {"action": "BUY", "confidence": 250}}  # valeur aberrante
    fused = fuse_agent_reports(scores)
    assert fused["confidence"] == 100.0
    print("test_fuse_agent_reports_confidence_clamped_0_100 OK")


def test_build_decision_registry_entry_matches_requested_shape():
    scores = {
        "structure": {"action": "BUY", "confidence": 78.0},
        "indicator": {"action": "SELL", "confidence": 52.0},
    }
    fused = fuse_agent_reports(scores)
    entry = build_decision_registry_entry("XAUUSD", scores, fused, now_iso="2026-08-06T18:00:00+00:00")
    assert entry["time"] == "2026-08-06T18:00:00+00:00"
    assert entry["symbol"] == "XAUUSD"
    assert entry["agents"]["structure"] == {"action": "BUY", "confidence": 78.0}
    assert entry["agents"]["indicator"] == {"action": "SELL", "confidence": 52.0}
    assert entry["final"] == "BUY"
    assert entry["executed"] is False  # jamais execute en Phase 1 (observation pure)
    print("test_build_decision_registry_entry_matches_requested_shape OK")


def test_fuse_agent_reports_default_weights_unchanged_behavior():
    """agent_weights=None (defaut) doit produire EXACTEMENT le meme resultat
    qu'avant ce chantier -- aucune regression pour tout appelant existant."""
    scores = {
        "structure": {"action": "BUY", "confidence": 78},
        "smart_money": {"action": "BUY", "confidence": 65},
        "indicator": {"action": "SELL", "confidence": 52},
    }
    without_kwarg = fuse_agent_reports(scores)
    with_none = fuse_agent_reports(scores, agent_weights=None)
    assert without_kwarg == with_none
    print("test_fuse_agent_reports_default_weights_unchanged_behavior OK")


def test_fuse_agent_reports_weights_can_flip_the_winning_direction():
    """Un agent avec un poids appris tres superieur doit pouvoir faire
    basculer la decision meme si sa confidence brute est plus faible que la
    somme adverse -- c'est exactement le but de la ponderation par
    fiabilite prouvee (demande de Louis, 'un edge tres solide', point 3)."""
    scores = {
        "reliable_agent": {"action": "BUY", "confidence": 40},
        "unreliable_agent": {"action": "SELL", "confidence": 90},
    }
    equal = fuse_agent_reports(scores)
    assert equal["final"] == "SELL"  # sans ponderation, SELL gagne (90 > 40)
    weighted = fuse_agent_reports(scores, agent_weights={"reliable_agent": 3.0, "unreliable_agent": 0.3})
    assert weighted["final"] == "BUY"  # 40*3=120 > 90*0.3=27
    print("test_fuse_agent_reports_weights_can_flip_the_winning_direction OK")


def test_high_conviction_requires_agreement_and_margin():
    scores = {
        "structure": {"action": "BUY", "confidence": 80},
        "smart_money": {"action": "BUY", "confidence": 75},
        "indicator": {"action": "BUY", "confidence": 70},
    }
    fused = fuse_agent_reports(scores)
    assert fused["final"] == "BUY"
    assert high_conviction(scores, fused, min_agents_agree=3, min_margin=30.0) is True
    assert high_conviction(scores, fused, min_agents_agree=4, min_margin=30.0) is False  # pas assez d'agents
    print("test_high_conviction_requires_agreement_and_margin OK")


def test_high_conviction_false_on_thin_margin_even_with_agreement():
    scores = {
        "structure": {"action": "BUY", "confidence": 51},
        "smart_money": {"action": "BUY", "confidence": 50},
        "indicator": {"action": "SELL", "confidence": 95},
    }
    fused = fuse_agent_reports(scores)
    assert fused["final"] == "BUY"  # 101 > 95, mais de justesse
    assert high_conviction(scores, fused, min_agents_agree=2, min_margin=30.0) is False
    print("test_high_conviction_false_on_thin_margin_even_with_agreement OK")


def test_high_conviction_false_on_wait():
    scores = {"structure": {"action": "BUY", "confidence": 50}, "indicator": {"action": "SELL", "confidence": 50}}
    fused = fuse_agent_reports(scores)
    assert fused["final"] == "WAIT"
    assert high_conviction(scores, fused) is False
    print("test_high_conviction_false_on_wait OK")


def test_build_decision_registry_entry_includes_scenario_id_and_high_conviction():
    scores = {
        "structure": {"action": "BUY", "confidence": 80},
        "smart_money": {"action": "BUY", "confidence": 75},
        "indicator": {"action": "BUY", "confidence": 70},
    }
    fused = fuse_agent_reports(scores)
    entry = build_decision_registry_entry(
        "XAUUSD", scores, fused, now_iso="2026-08-06T18:00:00+00:00", scenario_id="XAUUSD_20260806180000",
    )
    assert entry["scenario_id"] == "XAUUSD_20260806180000"
    assert entry["high_conviction"] is True
    entry_no_scenario = build_decision_registry_entry(
        "XAUUSD", scores, fused, now_iso="2026-08-06T18:00:00+00:00",
    )
    assert entry_no_scenario["scenario_id"] is None
    print("test_build_decision_registry_entry_includes_scenario_id_and_high_conviction OK")


# ---------------------------------------------------------------------------
# label_decision_outcomes() / compute_agent_reliability_weights()
# ---------------------------------------------------------------------------

def _decision(agents: dict, scenario_id: str | None) -> dict:
    return {"agents": agents, "scenario_id": scenario_id}


def test_label_decision_outcomes_only_annotates_known_scenarios():
    entries = [
        _decision({"structure": {"action": "BUY", "confidence": 80}}, "S1"),
        _decision({"structure": {"action": "SELL", "confidence": 80}}, "S2"),
        _decision({"structure": {"action": "BUY", "confidence": 80}}, None),  # aucun scenario -- jamais annote
    ]
    labeled = label_decision_outcomes(entries, {"S1": "BUY"})  # S2 volontairement absent (non resolu)
    assert labeled[0]["outcome_direction"] == "BUY"
    assert "outcome_direction" not in labeled[1]
    assert "outcome_direction" not in labeled[2]
    print("test_label_decision_outcomes_only_annotates_known_scenarios OK")


def test_compute_agent_reliability_weights_none_below_min_samples():
    entries = [_decision({"a": {"action": "BUY", "confidence": 80}}, "S1")]
    labeled = label_decision_outcomes(entries, {"S1": "BUY"})
    assert compute_agent_reliability_weights(labeled, min_samples=20) is None
    print("test_compute_agent_reliability_weights_none_below_min_samples OK")


def test_compute_agent_reliability_weights_rewards_the_more_accurate_agent():
    """20 decisions : 'good_agent' a toujours raison, 'bad_agent' a toujours
    tort -- son poids doit finir nettement au-dessus de 1.0 (good) et
    nettement en-dessous (bad), jamais l'inverse."""
    entries = []
    for i in range(20):
        actual = "BUY" if i % 2 == 0 else "SELL"
        entries.append(_decision({
            "good_agent": {"action": actual, "confidence": 70},
            "bad_agent": {"action": "SELL" if actual == "BUY" else "BUY", "confidence": 70},
        }, f"S{i}"))
    resolved = {f"S{i}": ("BUY" if i % 2 == 0 else "SELL") for i in range(20)}
    labeled = label_decision_outcomes(entries, resolved)
    weights = compute_agent_reliability_weights(labeled, min_samples=20)
    assert weights is not None
    assert weights["good_agent"] > 1.0
    assert weights["bad_agent"] < 1.0
    assert weights["good_agent"] > weights["bad_agent"]
    print("test_compute_agent_reliability_weights_rewards_the_more_accurate_agent OK")


def test_compute_agent_reliability_weights_ignores_unresolved_entries():
    """Une entree sans outcome_direction (scenario pas encore resolu) ne
    doit ni gonfler ni fausser le denominateur -- seulement compter parmi
    les 20 REELLEMENT resolues."""
    entries = [_decision({"a": {"action": "BUY", "confidence": 80}}, f"S{i}") for i in range(20)]
    entries += [_decision({"a": {"action": "BUY", "confidence": 80}}, None) for _ in range(50)]  # jamais resolues
    resolved = {f"S{i}": "BUY" for i in range(20)}
    labeled = label_decision_outcomes(entries, resolved)
    weights = compute_agent_reliability_weights(labeled, min_samples=20)
    assert weights is not None  # 20 resolues atteint le seuil malgre 50 entrees non resolues en plus
    print("test_compute_agent_reliability_weights_ignores_unresolved_entries OK")


if __name__ == "__main__":
    test_fuse_agent_reports_matches_louis_example()
    test_fuse_agent_reports_sell_wins()
    test_fuse_agent_reports_wait_when_no_directional_agent()
    test_fuse_agent_reports_wait_on_strict_tie()
    test_fuse_agent_reports_accepts_order_type_actions()
    test_fuse_agent_reports_empty_input_is_wait()
    test_fuse_agent_reports_confidence_clamped_0_100()
    test_build_decision_registry_entry_matches_requested_shape()
    test_fuse_agent_reports_default_weights_unchanged_behavior()
    test_fuse_agent_reports_weights_can_flip_the_winning_direction()
    test_high_conviction_requires_agreement_and_margin()
    test_high_conviction_false_on_thin_margin_even_with_agreement()
    test_high_conviction_false_on_wait()
    test_build_decision_registry_entry_includes_scenario_id_and_high_conviction()
    test_label_decision_outcomes_only_annotates_known_scenarios()
    test_compute_agent_reliability_weights_none_below_min_samples()
    test_compute_agent_reliability_weights_rewards_the_more_accurate_agent()
    test_compute_agent_reliability_weights_ignores_unresolved_entries()
    print("ALL TESTS PASSED")
