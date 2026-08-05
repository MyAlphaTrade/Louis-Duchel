"""Tests pour le log persistant caio_decisions.jsonl (04/08/2026, suite audit
statistique complet demande par Louis) -- learning_history (shared_memory.py)
n'est qu'un instantane RAM ecrase a chaque decision, jamais une histoire :
impossible jusqu'ici de savoir retrospectivement quel trade venait de Gold
Brain plutot que de l'ancien pipeline. Verifie que chaque VRAIE tentative
(record=True dans auto_trade_step) ecrit une ligne, dans les deux issues
(GO et NO_TRADE), et que le passage d'observation (record=False) n'ecrit rien
de plus que ce qu'il ecrivait deja."""
import json
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


class _FakeTerminal:
    tradeapi_disabled = False
    trade_allowed = True


class _FakeAccount:
    balance = 10000.0
    login = 12345
    server = "Demo-Server"
    trade_mode = 0


class _FakeMT5Connected:
    """Simule un compte demo connecte et autorise -- juste assez de surface
    pour franchir tous les gates d'auto_trade_step() avant le bloc Gold Brain
    (mt5_trading_permission, is_demo_account). place_order()/gold_brain_snapshot()
    restent monkeypatches dans les tests -- on ne simule pas l'execution MT5
    elle-meme, deja couverte ailleurs, seulement le nouveau log."""
    def account_info(self):
        return _FakeAccount()

    def terminal_info(self):
        return _FakeTerminal()


def _base_params():
    params = ae.merge_params()
    params["gold_brain_enabled"] = True
    params["ai_server_enabled"] = False  # server_trade_confirmation() approuve direct
    params["symbols"]["XAUUSD"]["cadence_sec"] = 1
    return params


def _base_payload():
    return {
        "active_symbol": "XAUUSD",
        "protection": {},
        "session_access": {"XAUUSD": {"entries_allowed": True}},
        "simulated_decision": {"eligible": True, "signal": "BUY", "reason": "ok", "engine": "classic"},
        "analysis": {"XAUUSD": {}},
        "lot_safety": {"XAUUSD": {"effective_lot": 0.01}},
        "learning": {},
    }


def _read_caio_log() -> list[dict]:
    path = ae.DATA_DIR / "caio_decisions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_auto_trade_step(real_decision_snapshot, order_result=None):
    """real_decision_snapshot: renvoye uniquement pour l'appel record=True
    (la vraie tentative). L'appel d'observation (record=False, plus haut dans
    la fonction) recoit toujours un NO_TRADE neutre -- non pertinent ici."""
    ae.write_json("trading_state.json", {"enabled": True, "real_confirmed": True})

    def fake_snapshot(*args, **kwargs):
        if kwargs.get("record") is True:
            return real_decision_snapshot
        return {"decision": "NO_TRADE", "raison": "observation", "source_agent": None, "reports": {}}

    original_snapshot = ae.gold_brain_snapshot
    original_place_order = ae.place_order
    original_notify_slack = ae.notify_slack
    original_mt5 = ae.mt5
    slack_calls = []
    ae.gold_brain_snapshot = fake_snapshot
    ae.place_order = lambda *a, **k: order_result or (False, "non atteint", None)
    ae.notify_slack = lambda *a, **k: slack_calls.append((a, k))
    ae.mt5 = _FakeMT5Connected()
    try:
        state = ae.auto_trade_step(_base_params(), {"XAUUSD": "XAUUSD"}, _base_payload(), [], trades=[])
    finally:
        ae.gold_brain_snapshot = original_snapshot
        ae.place_order = original_place_order
        ae.notify_slack = original_notify_slack
        ae.mt5 = original_mt5
    return state, slack_calls


def test_no_trade_decision_is_logged():
    (ae.DATA_DIR / "caio_decisions.jsonl").unlink(missing_ok=True)
    snapshot = {
        "decision": "NO_TRADE",
        "raison": "Aucun agent ne propose de scenario exploitable -- WAIT unanime ou indisponible.",
        "source_agent": None,
        "reports": {},
    }
    _run_auto_trade_step(snapshot)
    lines = _read_caio_log()
    assert len(lines) == 1, lines
    entry = lines[0]
    assert entry["decision"] == "NO_TRADE"
    assert entry["symbol_key"] == "XAUUSD"
    assert entry["order_attempted"] is False
    assert "Aucun agent" in entry["raison"]
    print("test_no_trade_decision_is_logged OK")


def test_go_decision_with_successful_order_is_logged():
    (ae.DATA_DIR / "caio_decisions.jsonl").unlink(missing_ok=True)
    snapshot = {
        "decision": "GO",
        "order_type": "BUY_MARKET",
        "source_agent": "structure_analyst",
        "raison": "structure_analyst: cassure haussiere (confiance 80%).",
        "price": 4080.5,
        "reports": {"structure_analyst": {"confidence": 80.0}},
    }
    state, slack_calls = _run_auto_trade_step(
        snapshot, order_result=(True, "BUY 0.010 XAUUSD execute en 12 ms.", {})
    )
    lines = _read_caio_log()
    assert len(lines) == 1, lines
    entry = lines[0]
    assert entry["decision"] == "GO"
    assert entry["order_type"] == "BUY_MARKET"
    assert entry["source_agent"] == "structure_analyst"
    assert entry["confidence"] == 80.0
    assert entry["order_attempted"] is True
    assert entry["order_ok"] is True
    # confiance 80 >= slack_min_confidence (defaut 70) -> notification attendue,
    # calculee une seule fois et reutilisee (plus de duplication de calcul).
    assert len(slack_calls) == 1
    print("test_go_decision_with_successful_order_is_logged OK")


def test_go_decision_with_rejected_order_is_still_logged():
    (ae.DATA_DIR / "caio_decisions.jsonl").unlink(missing_ok=True)
    snapshot = {
        "decision": "GO",
        "order_type": "SELL_MARKET",
        "source_agent": "smart_money_analyst",
        "raison": "smart_money_analyst: liquidite balayee (confiance 75%).",
        "price": 4079.0,
        "reports": {"smart_money_analyst": {"confidence": 75.0}},
    }
    state, slack_calls = _run_auto_trade_step(
        snapshot, order_result=(False, "Ordre refuse: 10004 Requote", {})
    )
    lines = _read_caio_log()
    assert len(lines) == 1, lines
    entry = lines[0]
    assert entry["decision"] == "GO"
    assert entry["order_attempted"] is True
    assert entry["order_ok"] is False
    assert "Requote" in entry["order_message"]
    # un ordre refuse n'est pas une entree reelle -- pas de notification Slack.
    assert len(slack_calls) == 0
    print("test_go_decision_with_rejected_order_is_still_logged OK")


if __name__ == "__main__":
    test_no_trade_decision_is_logged()
    test_go_decision_with_successful_order_is_logged()
    test_go_decision_with_rejected_order_is_still_logged()
    print("ALL TESTS PASSED")
