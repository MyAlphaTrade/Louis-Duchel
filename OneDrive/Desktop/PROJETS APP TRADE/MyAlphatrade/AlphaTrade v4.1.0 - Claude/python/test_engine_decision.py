"""Tests pour engine_decision.py (v1.1.5, Phase 1, 06/08/2026 -- demande
explicite de Louis). Module pur -- pas de MT5/reseau, pas d'ALPHATRADE_DATA_DIR
necessaire ici (contrairement aux autres fichiers de test de ce projet)."""
from engine_decision import fuse_agent_reports, build_decision_registry_entry


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


if __name__ == "__main__":
    test_fuse_agent_reports_matches_louis_example()
    test_fuse_agent_reports_sell_wins()
    test_fuse_agent_reports_wait_when_no_directional_agent()
    test_fuse_agent_reports_wait_on_strict_tie()
    test_fuse_agent_reports_accepts_order_type_actions()
    test_fuse_agent_reports_empty_input_is_wait()
    test_fuse_agent_reports_confidence_clamped_0_100()
    test_build_decision_registry_entry_matches_requested_shape()
    print("ALL TESTS PASSED")
