"""Tests pour Phase 0.1 (06/08/2026, demande explicite de Louis) -- porte
unique de comptage de positions. L'audit du meme jour a confirme
structurellement (lecture du code, aucune modification) que Rebond
(should_open_rebond()) et le Scenario Engine (execute_scenario_anchor()/
execute_scenario_scalp()) pouvaient ouvrir une position sans jamais voir
combien l'entree principale/Renfort (auto_trade_step(), Porte 1) avait deja
ouvertes sur le meme symbole -- sauf si portfolio_brain_enabled est active,
ce qui n'est pas le cas par defaut. Ces tests verifient le correctif :
hard_position_cap_reached() (nouvelle porte unique, reutilise
HARD_AUTO_POSITION_CAP) desormais consultee par les 3 mecanismes, avec
non-regression garantie pour tout appelant qui ne fournit pas `positions`
(defaut None -- ancien comportement inchange, voir chaque docstring)."""
import os
import tempfile
from datetime import datetime, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae
from scenario import make_scenario, activate_scenario

NOW = datetime(2026, 8, 6, 10, 30, 0, tzinfo=timezone.utc)


def _position(ticket, symbol_key="XAUUSD", origin="BOT"):
    return {"ticket": ticket, "symbol_key": symbol_key, "symbol": "XAUUSD", "origin": origin, "direction": "BUY", "lot": 0.01}


# ---------------------------------------------------------------------------
# total_bot_positions_open() / hard_position_cap_reached() -- purs
# ---------------------------------------------------------------------------

def test_total_bot_positions_open_counts_only_matching_symbol_and_bot_origin():
    positions = [
        _position(1, symbol_key="XAUUSD", origin="BOT"),
        _position(2, symbol_key="XAUUSD", origin="ALPHATRADE"),
        _position(3, symbol_key="XAUUSD", origin="ALPHAKARIS"),
        _position(4, symbol_key="XAUUSD", origin="EXTERNAL_AI"),  # pas BOT -- exclu
        _position(5, symbol_key="AUTRE_SYMBOLE", origin="BOT"),  # autre symbole -- exclu
    ]
    assert ae.total_bot_positions_open("XAUUSD", positions) == 3
    print("test_total_bot_positions_open_counts_only_matching_symbol_and_bot_origin OK")


def test_hard_position_cap_reached_true_at_and_above_cap():
    positions_below = [_position(i) for i in range(ae.HARD_AUTO_POSITION_CAP - 1)]
    positions_at = [_position(i) for i in range(ae.HARD_AUTO_POSITION_CAP)]
    assert ae.hard_position_cap_reached("XAUUSD", positions_below) is False
    assert ae.hard_position_cap_reached("XAUUSD", positions_at) is True
    print("test_hard_position_cap_reached_true_at_and_above_cap OK")


# ---------------------------------------------------------------------------
# should_open_rebond() -- doit desormais refuser au plafond dur, meme si
# son PROPRE compteur (rebond_max_active) serait encore favorable
# ---------------------------------------------------------------------------

def test_should_open_rebond_blocked_by_hard_cap_even_with_room_in_own_counter():
    ae.REBOND_STATES.clear()
    ae.REBOND_META.clear()
    # Beaucoup de positions BOT deja ouvertes -- venues d'ailleurs (entree
    # principale/Renfort ou Scenario Engine), pas de Rebond -- devraient a
    # elles seules atteindre le plafond dur.
    positions = [_position(i) for i in range(ae.HARD_AUTO_POSITION_CAP)]
    params = {"rebond_max_active": 3}  # son propre compteur serait large (0/3)
    ok, reason, info = ae.should_open_rebond("XAUUSD", "XAUUSD", positions, {}, params)
    assert ok is False
    assert "Plafond absolu" in reason
    assert info is None
    print("test_should_open_rebond_blocked_by_hard_cap_even_with_room_in_own_counter OK")


def test_should_open_rebond_not_blocked_when_room_available():
    """Verifie que le nouveau garde-fou ne bloque PAS a tort quand il reste
    de la place -- doit continuer jusqu'a ses propres verifications
    (main_profit absent ici -> refuse plus loin pour une autre raison, mais
    PAS 'Plafond absolu')."""
    ae.REBOND_STATES.clear()
    ae.REBOND_META.clear()
    positions = [_position(1)]  # tres loin du plafond (8)
    params = {"rebond_max_active": 3}
    ok, reason, info = ae.should_open_rebond("XAUUSD", "XAUUSD", positions, {}, params)
    assert "Plafond absolu" not in reason
    print("test_should_open_rebond_not_blocked_when_room_available OK")


# ---------------------------------------------------------------------------
# execute_scenario_anchor() -- transitoire au plafond dur, jamais FAILED
# ---------------------------------------------------------------------------

def _active_scenario():
    scenario = make_scenario(
        "XAUUSD_CAP", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0},
        invalidation_price=4080.0, targets=[{"price": 4092.0, "label": "t1"}],
        anchor_plan={"entry": 4086.5}, now=NOW,
    )
    scenario.transition("VALIDATED", "test", now=NOW)
    activate_scenario(scenario, now=NOW)
    return scenario


def _poison(*a, **k):
    raise AssertionError("Ne doit pas etre appele -- le plafond dur doit bloquer avant.")


def test_execute_scenario_anchor_blocked_by_hard_cap_when_positions_provided():
    scenario = _active_scenario()
    original_open_position = ae.open_position
    original_place_order = ae.place_order
    ae.open_position = _poison
    ae.place_order = _poison
    try:
        positions = [_position(i) for i in range(ae.HARD_AUTO_POSITION_CAP)]
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4086.5, positions=positions, now=NOW,
        )
        assert scenario.anchor_status == "NONE"  # transitoire -- jamais FAILED, retente au prochain cycle
    finally:
        ae.open_position = original_open_position
        ae.place_order = original_place_order
    print("test_execute_scenario_anchor_blocked_by_hard_cap_when_positions_provided OK")


def test_execute_scenario_anchor_default_none_preserves_old_behavior():
    """Sans `positions` (defaut None, anciens appels/tests) -- le nouveau
    garde-fou reste desactive, comportement historique inchange."""
    scenario = _active_scenario()
    original_open_position = ae.open_position
    original_live_positions = ae.live_positions
    ae.open_position = lambda *a, **k: (True, "ok", {"ok": True})
    ae.live_positions = lambda symbol_names, params=None: [
        {"ticket": 999, "symbol_key": "XAUUSD", "symbol": "XAUUSD", "direction": "BUY",
         "comment": "AlphaTrade 1.1.5 SCENARIO", "open_timestamp": 1000},
    ]
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4086.5, now=NOW,
        )
        assert scenario.anchor_status == "OPEN"  # inchange -- pas de regression
    finally:
        ae.open_position = original_open_position
        ae.live_positions = original_live_positions
    print("test_execute_scenario_anchor_default_none_preserves_old_behavior OK")


# ---------------------------------------------------------------------------
# execute_scenario_scalp() -- meme garde-fou
# ---------------------------------------------------------------------------

def test_execute_scenario_scalp_blocked_by_hard_cap_when_positions_provided():
    scenario = _active_scenario()
    scenario.scalp_allowed = True
    original_open_position = ae.open_position
    ae.open_position = _poison
    try:
        positions = [_position(i) for i in range(ae.HARD_AUTO_POSITION_CAP)]
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"}, 4086.5,
            None, [], {}, trading_enabled=True, allow_real=False, positions=positions, now=NOW,
        )
        assert scenario.executed_scalp_count == 0
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_scalp_blocked_by_hard_cap_when_positions_provided OK")


if __name__ == "__main__":
    test_total_bot_positions_open_counts_only_matching_symbol_and_bot_origin()
    test_hard_position_cap_reached_true_at_and_above_cap()
    test_should_open_rebond_blocked_by_hard_cap_even_with_room_in_own_counter()
    test_should_open_rebond_not_blocked_when_room_available()
    test_execute_scenario_anchor_blocked_by_hard_cap_when_positions_provided()
    test_execute_scenario_anchor_default_none_preserves_old_behavior()
    test_execute_scenario_scalp_blocked_by_hard_cap_when_positions_provided()
    print("ALL TESTS PASSED")
