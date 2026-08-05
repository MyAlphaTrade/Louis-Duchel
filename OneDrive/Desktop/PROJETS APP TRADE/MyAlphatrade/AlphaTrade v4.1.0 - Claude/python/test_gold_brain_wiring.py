"""Tests isoles pour le branchement v5.1.0 dans auto_trade_step().

IMPORTANT -- auto_trade_step() appelle mt5.account_info() des sa premiere
ligne SANS garder `mt5 is None` (comportement preexistant, pas introduit par
cette passe) : dans cet environnement (mt5=None), l'appel leve directement
une AttributeError plutot que de degrader proprement. Pour verifier que le
code atteint bien "Compte MT5 indisponible." (chemin normal quand MT5 tourne
mais n'est pas connecte), on installe un faux module `mt5` minimal
(account_info() -> None) le temps de ce test, puis on le retire. Le chemin
gold_brain=True (candles/CAIO/place_order reels) reste a valider avec un
vrai compte demo -- conforme au plan de securite, aucune fonctionnalite
d'execution n'est validee sans session demo dediee."""
import json
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


class _FakeMT5Disconnected:
    """Simule un module MetaTrader5 present mais sans compte connecte --
    seule la surface utilisee tout en haut d'auto_trade_step()."""
    def account_info(self):
        return None


def _with_fake_mt5(fn):
    original = ae.mt5
    ae.mt5 = _FakeMT5Disconnected()
    try:
        return fn()
    finally:
        ae.mt5 = original


def test_gold_brain_enabled_defaults_to_false():
    assert ae.DEFAULT_PARAMS["gold_brain_enabled"] is False
    print("test_gold_brain_enabled_defaults_to_false OK")


def test_fetch_candles_empty_without_mt5():
    assert ae.fetch_candles("XAUUSD", "M5", 300) == []
    print("test_fetch_candles_empty_without_mt5 OK")


def test_auto_trade_step_accepts_trades_param_and_degrades_without_account():
    def run():
        params = ae.merge_params()
        return ae.auto_trade_step(params, {"XAUUSD": "XAUUSD"}, {}, [], trades=[])
    state = _with_fake_mt5(run)
    assert state["enabled"] is False
    assert "indisponible" in state["reason"]
    print("test_auto_trade_step_accepts_trades_param_and_degrades_without_account OK")


def test_auto_trade_step_works_without_trades_argument():
    # trades est optionnel (retro-compatibilite) -- ne doit jamais lever TypeError.
    def run():
        params = ae.merge_params()
        return ae.auto_trade_step(params, {"XAUUSD": "XAUUSD"}, {}, [])
    state = _with_fake_mt5(run)
    assert isinstance(state, dict)
    print("test_auto_trade_step_works_without_trades_argument OK")


class _FakeAccount:
    """Compte minimal pour gold_brain_snapshot() -- ae.mt5 reste None dans cet
    environnement, donc fetch_candles()/lot_safety_state() degradent deja
    proprement (voir leurs propres tests) sans qu'il faille simuler MT5."""
    balance = 1000.0
    login = 12345
    server = "Demo-Server"
    trade_mode = 0


def test_gold_brain_snapshot_degrades_gracefully_without_candles():
    # v5.1.0 -- mode observation continue : meme sans bougies (marche ferme,
    # MT5 indisponible), le snapshot ne doit jamais planter -- il "reste
    # statique" (agents UNAVAILABLE) plutot que de calculer sur du vide.
    params = ae.merge_params()
    params["gold_brain_enabled"] = True
    snapshot = ae.gold_brain_snapshot(
        params, _FakeAccount(), "XAUUSD", {"XAUUSD": "XAUUSD"},
        params.get("symbols", {}).get("XAUUSD", {}),
        {}, {}, {}, [], [], record=False,
    )
    assert snapshot["decision"] in ("GO", "NO_TRADE")
    assert snapshot["reports"]["structure_analyst"]["status"] == "UNAVAILABLE"
    assert snapshot["reports"]["smart_money_analyst"]["status"] == "UNAVAILABLE"
    print("test_gold_brain_snapshot_degrades_gracefully_without_candles OK")


def test_gold_brain_snapshot_record_false_does_not_pollute_learning_history():
    ae.SHARED_MEMORY._store.clear()
    params = ae.merge_params()
    params["gold_brain_enabled"] = True
    ae.gold_brain_snapshot(
        params, _FakeAccount(), "XAUUSD", {"XAUUSD": "XAUUSD"},
        params.get("symbols", {}).get("XAUUSD", {}),
        {}, {}, {}, [], [], record=False,
    )
    assert ae.SHARED_MEMORY.read("learning_history") is None
    print("test_gold_brain_snapshot_record_false_does_not_pollute_learning_history OK")


def test_gold_brain_snapshot_mission_state_ignores_external_positions():
    """05/08/2026 -- bug trouve en observation reelle (Louis, capture d'ecran
    a l'appui) : gold_brain_snapshot() passait payload["today_stats"]
    (jamais filtre par origine) a mission_state() -> protection_state(), qui
    ECRASE session_state.json avec un Pic/session_profit comptant les gains
    d'un AUTRE logiciel (ex: AT Global, origin EXTERNAL_AI) partageant le
    meme compte MT5, comme si c'etaient ceux d'AlphaTrade Gold. L'objectif
    d'AlphaTrade Gold ne doit refleter QUE ses propres positions (BOT/
    ALPHATRADE/ALPHAKARIS)."""
    (ae.DATA_DIR / "session_state.json").unlink(missing_ok=True)
    params = ae.merge_params()
    params["gold_brain_enabled"] = True
    external_position = {
        "ticket": 1, "symbol_key": "XAUUSD", "direction": "BUY", "origin": "EXTERNAL_AI",
        "origin_name": "AT Global", "lot": 0.01, "profit": 118.44,
    }
    bot_position = {
        "ticket": 2, "symbol_key": "XAUUSD", "direction": "BUY", "origin": "BOT",
        "origin_name": "AlphaTrade AI", "lot": 0.01, "profit": 0.0,
    }
    ae.gold_brain_snapshot(
        params, _FakeAccount(), "XAUUSD", {"XAUUSD": "XAUUSD"},
        params.get("symbols", {}).get("XAUUSD", {}),
        {}, {}, {}, [external_position, bot_position], [], record=False,
    )
    session_state = json.loads((ae.DATA_DIR / "session_state.json").read_text(encoding="utf-8"))
    assert session_state["current"] == 0.0, f"current ne doit pas inclure le flottant externe: {session_state}"
    assert session_state["daily_peak"] < 1.0, f"le pic ne doit pas inclure le flottant externe: {session_state}"
    (ae.DATA_DIR / "session_state.json").unlink(missing_ok=True)
    print("test_gold_brain_snapshot_mission_state_ignores_external_positions OK")


if __name__ == "__main__":
    test_gold_brain_enabled_defaults_to_false()
    test_fetch_candles_empty_without_mt5()
    test_auto_trade_step_accepts_trades_param_and_degrades_without_account()
    test_auto_trade_step_works_without_trades_argument()
    test_gold_brain_snapshot_degrades_gracefully_without_candles()
    test_gold_brain_snapshot_record_false_does_not_pollute_learning_history()
    test_gold_brain_snapshot_mission_state_ignores_external_positions()
    print("ALL TESTS PASSED (le chemin gold_brain=True reste a valider en demo -- voir plan de securite)")
