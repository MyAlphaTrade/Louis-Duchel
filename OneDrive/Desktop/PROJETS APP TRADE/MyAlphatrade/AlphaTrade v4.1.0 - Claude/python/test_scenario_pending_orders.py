"""Tests pour task #170 (06/08/2026, demande de Louis) -- Scenario Engine :
ordres en attente (limite/stop) quand le prix s'est eloigne de la zone
d'entree ideale, et mode intraday (scenario_engine_timeframe M15/H1) avec
duree de validite deduite automatiquement du timeframe choisi. Meme
discipline/harnais que test_scenario_wiring.py (fakes minimalistes,
open_position()/place_order()/live_positions() remplaces temporairement)."""
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae
from agent_report import make_agent_report
from scenario import make_scenario, activate_scenario

NOW = datetime(2026, 8, 6, 10, 30, 0, tzinfo=timezone.utc)


def _active_buy_scenario():
    """Meme fixture que test_scenario_wiring.py::_active_scenario() -- zone
    [4085, 4088], entree ideale 4086.5 (demi-largeur de zone: 1.5)."""
    scenario = make_scenario(
        "XAUUSD_ACTIVE", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0},
        scenario_confidence=80.0, market_context={"atr": 2.0}, invalidation_price=4080.0,
        targets=[{"price": 4092.0, "label": "t1"}, {"price": 4098.0, "label": "t2"}],
        anchor_plan={"entry": 4086.5, "sl": 4080.0, "tp": 4092.0}, now=NOW,
    )
    scenario.transition("VALIDATED", "test", now=NOW)
    activate_scenario(scenario, now=NOW)
    return scenario


def _active_sell_scenario():
    scenario = make_scenario(
        "XAUUSD_ACTIVE_SELL", "XAUUSD", "SELL", {"low": 4085.0, "high": 4088.0},
        scenario_confidence=80.0, market_context={"atr": 2.0}, invalidation_price=4093.0,
        targets=[{"price": 4080.0, "label": "t1"}, {"price": 4074.0, "label": "t2"}],
        anchor_plan={"entry": 4086.5, "sl": 4093.0, "tp": 4080.0}, now=NOW,
    )
    scenario.transition("VALIDATED", "test", now=NOW)
    activate_scenario(scenario, now=NOW)
    return scenario


def _fake_position(ticket, symbol_key="XAUUSD", direction="BUY", comment="AlphaTrade 5.1.1 SCENARIO", open_timestamp=1000):
    return {
        "ticket": ticket, "symbol_key": symbol_key, "symbol": "XAUUSD", "direction": direction,
        "origin": "BOT", "origin_name": "AlphaTrade", "origin_type": "INTERNAL_BOT", "origin_magic": 0,
        "lot": 0.01, "open_price": 4086.5, "current_price": 4086.5, "profit": 0.0,
        "open_timestamp": open_timestamp, "open_time": "2026-08-06T10:00:00", "comment": comment,
    }


def _poison(*a, **k):
    raise AssertionError("Cette fonction ne doit pas etre appelee dans ce scenario de test.")


# ---------------------------------------------------------------------------
# Decision LIMIT/STOP/MARKET selon la distance prix courant <-> entree ideale
# ---------------------------------------------------------------------------

def test_execute_scenario_anchor_places_buy_limit_when_price_ran_above_zone():
    """BUY, entree ideale 4086.5, demi-largeur zone 1.5 -- prix reparti a
    4090 (> 4088) : le marche a depasse la zone vers le haut, on attend un
    repli via BUY_LIMIT plutot que d'acheter plus cher que prevu."""
    scenario = _active_buy_scenario()
    calls = []

    def _fake_place_order(symbol_key, symbol, order_type, params, lot_info, analysis, allow_real, **kwargs):
        calls.append((order_type, kwargs.get("price_hint")))
        return True, "BUY_LIMIT 0.010 XAUUSD pose a 4086.50 en 12 ms.", {"order_ticket": 777001}

    original_place_order = ae.place_order
    original_open_position = ae.open_position
    original_lot_safety = ae.lot_safety_state
    ae.place_order = _fake_place_order
    ae.open_position = _poison
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.01, "reason": ""}}
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4090.0, now=NOW,
        )
        assert scenario.anchor_status == "PENDING"
        assert scenario.pending_order_ticket == 777001
        assert scenario.anchor_ticket is None
        assert len(calls) == 1
        assert calls[0] == ("BUY_LIMIT", 4086.5)
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
        ae.lot_safety_state = original_lot_safety
    print("test_execute_scenario_anchor_places_buy_limit_when_price_ran_above_zone OK")


def test_execute_scenario_anchor_places_buy_stop_when_price_still_below_zone():
    """BUY, entree ideale 4086.5 -- prix encore a 4083 (< 4085) : l'entree
    prevue est une cassure vers le haut, on attend sa confirmation via
    BUY_STOP plutot que d'acheter trop tot."""
    scenario = _active_buy_scenario()
    calls = []

    def _fake_place_order(symbol_key, symbol, order_type, params, lot_info, analysis, allow_real, **kwargs):
        calls.append((order_type, kwargs.get("price_hint")))
        return True, "BUY_STOP pose.", {"order_ticket": 777002}

    original_place_order = ae.place_order
    original_open_position = ae.open_position
    original_lot_safety = ae.lot_safety_state
    ae.place_order = _fake_place_order
    ae.open_position = _poison
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.01, "reason": ""}}
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4083.0, now=NOW,
        )
        assert scenario.anchor_status == "PENDING"
        assert scenario.pending_order_ticket == 777002
        assert calls[0] == ("BUY_STOP", 4086.5)
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
        ae.lot_safety_state = original_lot_safety
    print("test_execute_scenario_anchor_places_buy_stop_when_price_still_below_zone OK")


def test_execute_scenario_anchor_sell_limit_and_sell_stop_symmetric():
    """SELL, entree ideale 4086.5. Coherent avec les memes regles MT5 que
    place_order() (SELL_LIMIT: prix pose AU-DESSUS du marche courant --
    attendre un rallye avant de vendre plus cher ; SELL_STOP: prix pose
    EN-DESSOUS -- attendre la confirmation d'une cassure baissiere) : prix
    reparti tres au-dessus de la zone (4090) -> l'entree ideale (4086.5) est
    maintenant SOUS le marche -> SELL_STOP (attendre que la cassure se
    confirme). Prix reparti tres en-dessous (4083) -> l'entree ideale est
    AU-DESSUS du marche -> SELL_LIMIT (attendre un rebond vers ce niveau)."""
    original_place_order = ae.place_order
    original_open_position = ae.open_position
    original_lot_safety = ae.lot_safety_state
    ae.open_position = _poison
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.01, "reason": ""}}
    try:
        calls = []
        ae.place_order = lambda sk, s, ot, p, li, a, ar, **k: (calls.append((ot, k.get("price_hint"))) or (True, "ok", {"order_ticket": 1}))
        scenario_up = _active_sell_scenario()
        ae.execute_scenario_anchor(
            scenario_up, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4090.0, now=NOW,
        )
        assert scenario_up.anchor_status == "PENDING"
        assert calls[-1] == ("SELL_STOP", 4086.5)

        scenario_down = _active_sell_scenario()
        ae.execute_scenario_anchor(
            scenario_down, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4083.0, now=NOW,
        )
        assert scenario_down.anchor_status == "PENDING"
        assert calls[-1] == ("SELL_LIMIT", 4086.5)
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
        ae.lot_safety_state = original_lot_safety
    print("test_execute_scenario_anchor_sell_limit_and_sell_stop_symmetric OK")


def test_execute_scenario_anchor_uses_market_when_price_still_in_zone():
    """Prix encore proche de l'entree ideale (dans la demi-largeur de zone) :
    comportement historique inchange -- entree immediate au marche, jamais
    d'ordre en attente."""
    scenario = _active_buy_scenario()
    calls = []

    def _fake_open_position(symbol_key, symbol, direction, params, lot_info, analysis, allow_real, **kwargs):
        calls.append(direction)
        return True, "BUY 0.010 XAUUSD execute en 40 ms.", {"ok": True}

    original_open_position = ae.open_position
    original_place_order = ae.place_order
    original_lot_safety = ae.lot_safety_state
    original_live_positions = ae.live_positions
    ae.open_position = _fake_open_position
    ae.place_order = _poison
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.01, "reason": ""}}
    ae.live_positions = lambda symbol_names, params=None: [_fake_position(555001)]
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4086.7, now=NOW,
        )
        assert scenario.anchor_status == "OPEN"
        assert scenario.anchor_ticket == 555001
        assert calls == ["BUY"]
    finally:
        ae.open_position = original_open_position
        ae.place_order = original_place_order
        ae.lot_safety_state = original_lot_safety
        ae.live_positions = original_live_positions
    print("test_execute_scenario_anchor_uses_market_when_price_still_in_zone OK")


def test_execute_scenario_anchor_default_current_price_preserves_market_behavior():
    """current_price non fourni (0.0 par defaut) -- aucune regression pour un
    appelant existant (anciens tests/integrations) : toujours MARKET."""
    scenario = _active_buy_scenario()
    original_open_position = ae.open_position
    original_place_order = ae.place_order
    original_lot_safety = ae.lot_safety_state
    original_live_positions = ae.live_positions
    ae.open_position = lambda *a, **k: (True, "ok", {"ok": True})
    ae.place_order = _poison
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.01, "reason": ""}}
    ae.live_positions = lambda symbol_names, params=None: [_fake_position(555002)]
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "OPEN"
    finally:
        ae.open_position = original_open_position
        ae.place_order = original_place_order
        ae.lot_safety_state = original_lot_safety
        ae.live_positions = original_live_positions
    print("test_execute_scenario_anchor_default_current_price_preserves_market_behavior OK")


def test_execute_scenario_anchor_marks_failed_when_pending_order_rejected():
    scenario = _active_buy_scenario()
    original_place_order = ae.place_order
    original_open_position = ae.open_position
    original_lot_safety = ae.lot_safety_state
    ae.place_order = lambda *a, **k: (False, "Ordre refuse: 10004 Requote", {"order_ticket": None})
    ae.open_position = _poison
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.01, "reason": ""}}
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4090.0, now=NOW,
        )
        assert scenario.anchor_status == "FAILED"
        assert scenario.pending_order_ticket is None
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
        ae.lot_safety_state = original_lot_safety
    print("test_execute_scenario_anchor_marks_failed_when_pending_order_rejected OK")


# ---------------------------------------------------------------------------
# Surveillance d'un ordre PENDING (declenchement / toujours en attente)
# ---------------------------------------------------------------------------

def test_execute_scenario_anchor_detects_pending_order_fill():
    scenario = _active_buy_scenario()
    scenario.anchor_status = "PENDING"
    scenario.pending_order_ticket = 777001
    original_live_positions = ae.live_positions
    original_open_position = ae.open_position
    original_place_order = ae.place_order
    ae.live_positions = lambda symbol_names, params=None: [_fake_position(555003)]
    ae.open_position = _poison
    ae.place_order = _poison
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4086.5, now=NOW,
        )
        assert scenario.anchor_status == "OPEN"
        assert scenario.anchor_ticket == 555003
        assert scenario.pending_order_ticket is None
    finally:
        ae.live_positions = original_live_positions
        ae.open_position = original_open_position
        ae.place_order = original_place_order
    print("test_execute_scenario_anchor_detects_pending_order_fill OK")


def test_execute_scenario_anchor_pending_order_still_waiting_when_no_fill():
    scenario = _active_buy_scenario()
    scenario.anchor_status = "PENDING"
    scenario.pending_order_ticket = 777001
    original_live_positions = ae.live_positions
    original_open_position = ae.open_position
    original_place_order = ae.place_order
    ae.live_positions = lambda symbol_names, params=None: []  # rien encore declenche
    ae.open_position = _poison
    ae.place_order = _poison
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4086.5, now=NOW,
        )
        assert scenario.anchor_status == "PENDING"
        assert scenario.anchor_ticket is None
        assert scenario.pending_order_ticket == 777001
    finally:
        ae.live_positions = original_live_positions
        ae.open_position = original_open_position
        ae.place_order = original_place_order
    print("test_execute_scenario_anchor_pending_order_still_waiting_when_no_fill OK")


def test_execute_scenario_anchor_pending_monitoring_ignores_transient_gates():
    """Un ordre PENDING deja pose sur le broker doit rester surveille meme si
    trading_enabled devient False ou si la protection de session s'active
    entre-temps -- ces gates ne bloquent que la pose d'un NOUVEL ordre."""
    scenario = _active_buy_scenario()
    scenario.anchor_status = "PENDING"
    scenario.pending_order_ticket = 777001
    original_live_positions = ae.live_positions
    ae.live_positions = lambda symbol_names, params=None: [_fake_position(555004)]
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "HARD_LOCK"},
            trading_enabled=False, allow_real=False, current_price=4086.5, now=NOW,
        )
        assert scenario.anchor_status == "OPEN"
        assert scenario.anchor_ticket == 555004
    finally:
        ae.live_positions = original_live_positions
    print("test_execute_scenario_anchor_pending_monitoring_ignores_transient_gates OK")


# ---------------------------------------------------------------------------
# Annulation d'un ordre PENDING a la cloture du scenario
# ---------------------------------------------------------------------------

def test_close_scenario_anchor_if_needed_cancels_pending_order_on_terminal_status():
    scenario = _active_buy_scenario()
    scenario.anchor_status = "PENDING"
    scenario.pending_order_ticket = 777001
    scenario.transition("INVALIDATED", "test", now=NOW)
    calls = []

    def _fake_cancel(symbol, ticket):
        calls.append((symbol, ticket))
        return True, f"Ordre en attente {ticket} annule."

    original_cancel = ae.cancel_pending_order
    ae.cancel_pending_order = _fake_cancel
    try:
        ae.close_scenario_anchor_if_needed(scenario, [], now=NOW)
        assert scenario.anchor_status == "CLOSED"
        assert scenario.pending_order_ticket is None
        assert calls == [("XAUUSD", 777001)]
    finally:
        ae.cancel_pending_order = original_cancel
    print("test_close_scenario_anchor_if_needed_cancels_pending_order_on_terminal_status OK")


def test_close_scenario_anchor_if_needed_noop_pending_while_still_active():
    scenario = _active_buy_scenario()
    scenario.anchor_status = "PENDING"
    scenario.pending_order_ticket = 777001
    original_cancel = ae.cancel_pending_order
    ae.cancel_pending_order = _poison
    try:
        ae.close_scenario_anchor_if_needed(scenario, [], now=NOW)
        assert scenario.anchor_status == "PENDING"  # scenario toujours ACTIVE -- rien a annuler
        assert scenario.pending_order_ticket == 777001
    finally:
        ae.cancel_pending_order = original_cancel
    print("test_close_scenario_anchor_if_needed_noop_pending_while_still_active OK")


def test_close_scenario_anchor_if_needed_pending_cancel_failure_keeps_pending():
    """Annulation refusee (deja declenche/expire cote broker entre-temps) :
    ne boucle pas en erreur, reste PENDING pour re-verification au prochain
    cycle (execute_scenario_anchor() detectera alors soit le declenchement,
    soit une nouvelle tentative d'annulation reussira)."""
    scenario = _active_buy_scenario()
    scenario.anchor_status = "PENDING"
    scenario.pending_order_ticket = 777001
    scenario.transition("EXPIRED", "test", now=NOW)
    original_cancel = ae.cancel_pending_order
    ae.cancel_pending_order = lambda symbol, ticket: (False, "Ordre introuvable (deja declenche).")
    try:
        ae.close_scenario_anchor_if_needed(scenario, [], now=NOW)
        assert scenario.anchor_status == "PENDING"
        assert scenario.pending_order_ticket == 777001
    finally:
        ae.cancel_pending_order = original_cancel
    print("test_close_scenario_anchor_if_needed_pending_cancel_failure_keeps_pending OK")


# ---------------------------------------------------------------------------
# Mode intraday (scenario_engine_timeframe) -- duree de validite deduite
# ---------------------------------------------------------------------------

def test_scenario_validity_minutes_by_timeframe_default_matches_historical_45min():
    assert ae.SCENARIO_VALIDITY_MINUTES_BY_TIMEFRAME["M5"] == 45
    print("test_scenario_validity_minutes_by_timeframe_default_matches_historical_45min OK")


def test_scenario_validity_minutes_by_timeframe_intraday_longer_than_default():
    assert ae.SCENARIO_VALIDITY_MINUTES_BY_TIMEFRAME["M15"] > ae.SCENARIO_VALIDITY_MINUTES_BY_TIMEFRAME["M5"]
    assert ae.SCENARIO_VALIDITY_MINUTES_BY_TIMEFRAME["H1"] > ae.SCENARIO_VALIDITY_MINUTES_BY_TIMEFRAME["M15"]
    print("test_scenario_validity_minutes_by_timeframe_intraday_longer_than_default OK")


def test_scenario_engine_step_uses_intraday_timeframe_for_longer_validity():
    """params['scenario_engine_timeframe']='H1' -> le scenario genere doit
    expirer ~720 min plus tard (au lieu de 45 min par defaut)."""
    ae.CURRENT_SCENARIO = None
    candles = [{"open": 4085, "high": 4086, "low": 4084, "close": 4085, "time": i} for i in range(60)]
    structure = make_agent_report(
        "structure_analyst", status="OK", confidence=82.0, priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": 4086.5},
        arguments=["Regime UPTREND."], metadata={"regime": "UPTREND", "timeframe": "H1"}, now=NOW,
    )
    smart_money = make_agent_report(
        "smart_money_analyst", status="OK", confidence=78.0, priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": 4086.0}, arguments=["Sweep bullish."], now=NOW,
    )
    risk = make_agent_report(
        "risk_manager", status="OK", confidence=90.0, priority="LOW",
        recommendation={"action": "WAIT", "any_rejected": False}, now=NOW,
    )
    scenario = ae.scenario_engine_step(
        {"scenario_engine_timeframe": "H1"}, "XAUUSD", candles, 4085.0,
        structure, smart_money, risk, None, {}, now=NOW,
    )
    assert scenario is not None
    expires_at = datetime.fromisoformat(scenario.expires_at)
    delta_minutes = (expires_at - NOW).total_seconds() / 60.0
    assert delta_minutes > 700  # ~720 min (H1), tres au-dessus des 45 min par defaut
    print("test_scenario_engine_step_uses_intraday_timeframe_for_longer_validity OK")


if __name__ == "__main__":
    test_execute_scenario_anchor_places_buy_limit_when_price_ran_above_zone()
    test_execute_scenario_anchor_places_buy_stop_when_price_still_below_zone()
    test_execute_scenario_anchor_sell_limit_and_sell_stop_symmetric()
    test_execute_scenario_anchor_uses_market_when_price_still_in_zone()
    test_execute_scenario_anchor_default_current_price_preserves_market_behavior()
    test_execute_scenario_anchor_marks_failed_when_pending_order_rejected()
    test_execute_scenario_anchor_detects_pending_order_fill()
    test_execute_scenario_anchor_pending_order_still_waiting_when_no_fill()
    test_execute_scenario_anchor_pending_monitoring_ignores_transient_gates()
    test_close_scenario_anchor_if_needed_cancels_pending_order_on_terminal_status()
    test_close_scenario_anchor_if_needed_noop_pending_while_still_active()
    test_close_scenario_anchor_if_needed_pending_cancel_failure_keeps_pending()
    test_scenario_validity_minutes_by_timeframe_default_matches_historical_45min()
    test_scenario_validity_minutes_by_timeframe_intraday_longer_than_default()
    test_scenario_engine_step_uses_intraday_timeframe_for_longer_validity()
    print("ALL TESTS PASSED")
