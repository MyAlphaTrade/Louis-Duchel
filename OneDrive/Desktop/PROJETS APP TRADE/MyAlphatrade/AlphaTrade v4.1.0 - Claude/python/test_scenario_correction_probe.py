"""Tests pour le mecanisme de "sonde" CORRECTION (06/08/2026 -- corrige le
catch-22 trouve lors de l'audit du panneau Parametres, demande explicite de
Louis "corrige tout ca"). Root cause : scenario_block_correction_regime=True
empeche TOUT scenario CORRECTION d'exister, donc scenario_threshold_
adjustments() (qui sait deja re-evaluer ce blocage des que by_trend
["CORRECTION"] contient des donnees) n'a jamais eu la moindre preuve pour le
faire -- figeant le blocage indefiniment sur l'analyse initiale de 58 jours.

Avec `correction_probe_rate` > 0, une fraction des cycles CORRECTION genere
quand meme un scenario "sonde" (is_probe=True) -- suit le meme cycle de vie/
validation/resolution que n'importe quel autre (alimente donc normalement
scenario_log.jsonl et la calibration), mais ne peut JAMAIS declencher de
position/scalp reels (garde-fou explicite dans execute_scenario_anchor()/
execute_scenario_scalp())."""
import os
import tempfile
from datetime import datetime, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae
import scenario_generator
from scenario_generator import generate_scenario
from scenario import make_scenario, activate_scenario
from agent_report import make_agent_report

NOW = datetime(2026, 8, 6, 10, 30, 0, tzinfo=timezone.utc)

CANDLES = [
    {"open": 4085.0 + i * 0.05, "high": 4086.0 + i * 0.05, "low": 4084.0 + i * 0.05, "close": 4085.5 + i * 0.05}
    for i in range(60)
]


def _structure_report(regime: str, action: str = "BUY_MARKET", confidence: float = 75.0):
    return make_agent_report(
        "structure_analyst", status="OK", confidence=confidence, priority="MEDIUM",
        recommendation={"action": action, "price": 4085.5}, arguments=["Structure test."],
        metadata={"regime": regime, "timeframe": "M5"}, now=NOW,
    )


def _smart_money_report(action: str = "BUY_MARKET", confidence: float = 70.0):
    return make_agent_report(
        "smart_money_analyst", status="OK", confidence=confidence, priority="MEDIUM",
        recommendation={"action": action}, arguments=["Smart money test."], now=NOW,
    )


def _risk_report_neutral():
    """Meme fabrique neutre que run_scenario_replay() (alphatrade_engine.py)
    -- suffisant pour franchir validate_scenario() sans solde de compte reel."""
    return make_agent_report(
        "risk_manager", status="OK", confidence=70.0, priority="LOW",
        recommendation={"action": "WAIT", "any_rejected": False},
        arguments=["Test -- risque suppose acceptable."], now=NOW,
    )


# ---------------------------------------------------------------------------
# generate_scenario() -- comportement du parametre correction_probe_rate
# ---------------------------------------------------------------------------

def test_correction_regime_still_blocked_by_default_zero_probe_rate():
    """Defaut (correction_probe_rate=0.0, non fourni) -- comportement
    HISTORIQUE inchange, aucune regression : toujours None en CORRECTION."""
    scenario = generate_scenario(
        "XAUUSD", CANDLES, 4085.5,
        _structure_report("CORRECTION"), _smart_money_report(),
        now=NOW, block_correction_regime=True,
    )
    assert scenario is None
    print("test_correction_regime_still_blocked_by_default_zero_probe_rate OK")


def test_correction_regime_generates_probe_when_rate_is_one():
    """correction_probe_rate=1.0 (deterministe pour le test) -- un scenario
    EST genere en CORRECTION, mais marque is_probe=True."""
    scenario = generate_scenario(
        "XAUUSD", CANDLES, 4085.5,
        _structure_report("CORRECTION"), _smart_money_report(),
        now=NOW, block_correction_regime=True, correction_probe_rate=1.0,
    )
    assert scenario is not None
    assert scenario.is_probe is True
    assert scenario.market_context["trend"] == "CORRECTION"  # alimente bien by_trend["CORRECTION"]
    print("test_correction_regime_generates_probe_when_rate_is_one OK")


def test_non_correction_regime_never_marked_probe_even_with_rate_one():
    """Le taux de sonde ne s'applique QU'au chemin CORRECTION -- un scenario
    UPTREND normal ne doit jamais devenir is_probe=True par effet de bord."""
    scenario = generate_scenario(
        "XAUUSD", CANDLES, 4085.5,
        _structure_report("UPTREND"), _smart_money_report(),
        now=NOW, block_correction_regime=True, correction_probe_rate=1.0,
    )
    assert scenario is not None
    assert scenario.is_probe is False
    print("test_non_correction_regime_never_marked_probe_even_with_rate_one OK")


def test_block_disabled_entirely_never_produces_a_probe():
    """block_correction_regime=False (blocage completement desactive, ex.
    deja re-autorise par la calibration reelle) -- scenario CORRECTION normal,
    jamais marque is_probe (le chemin sonde ne s'execute meme pas)."""
    scenario = generate_scenario(
        "XAUUSD", CANDLES, 4085.5,
        _structure_report("CORRECTION"), _smart_money_report(),
        now=NOW, block_correction_regime=False, correction_probe_rate=1.0,
    )
    assert scenario is not None
    assert scenario.is_probe is False
    print("test_block_disabled_entirely_never_produces_a_probe OK")


# ---------------------------------------------------------------------------
# scenario_engine_step() -- l'override explicite (utilise par
# run_scenario_replay() pour rester deterministe) doit gagner sur params
# ---------------------------------------------------------------------------

def test_scenario_engine_step_explicit_zero_override_beats_params_rate():
    """Meme si params contient un taux > 0 ET que le tirage aleatoire
    favoriserait toujours la sonde, un appelant qui force explicitement
    correction_probe_rate=0.0 (comme run_scenario_replay()) ne doit JAMAIS
    obtenir de sonde -- reste None comme avant ce correctif."""
    ae.CURRENT_SCENARIO = None
    original_random = scenario_generator.random.random
    scenario_generator.random.random = lambda: 0.0  # tirage le plus favorable possible a la sonde
    try:
        params = {"scenario_block_correction_regime": True, "scenario_correction_probe_rate": 1.0}
        scenario = ae.scenario_engine_step(
            params, "XAUUSD", CANDLES, 4085.5,
            _structure_report("CORRECTION"), _smart_money_report(), _risk_report_neutral(), None, {},
            now=NOW, log_name="scenario_replay_log.jsonl", correction_probe_rate=0.0,
        )
    finally:
        scenario_generator.random.random = original_random
        ae.CURRENT_SCENARIO = None
    assert scenario is None
    print("test_scenario_engine_step_explicit_zero_override_beats_params_rate OK")


def test_scenario_engine_step_reads_params_rate_when_not_overridden():
    """Sans override explicite (None, cycle live normal) -- lit bien
    params['scenario_correction_probe_rate']."""
    ae.CURRENT_SCENARIO = None
    original_random = scenario_generator.random.random
    scenario_generator.random.random = lambda: 0.0
    try:
        params = {"scenario_block_correction_regime": True, "scenario_correction_probe_rate": 1.0}
        scenario = ae.scenario_engine_step(
            params, "XAUUSD", CANDLES, 4085.5,
            _structure_report("CORRECTION"), _smart_money_report(), _risk_report_neutral(), None, {},
            now=NOW, log_name="scenario_log.jsonl",
        )
    finally:
        scenario_generator.random.random = original_random
        ae.CURRENT_SCENARIO = None
    assert scenario is not None
    assert scenario.is_probe is True
    print("test_scenario_engine_step_reads_params_rate_when_not_overridden OK")


# ---------------------------------------------------------------------------
# Garde-fou execution reelle -- is_probe ne doit JAMAIS ouvrir de vraie
# position/scalp, meme si toutes les autres conditions sont favorables
# ---------------------------------------------------------------------------

def _poison(*a, **k):
    raise AssertionError("Ne doit jamais etre appele -- un scenario sonde ne doit jamais executer reellement.")


def _active_probe_scenario():
    scenario = make_scenario(
        "XAUUSD_PROBE", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0},
        invalidation_price=4080.0, targets=[{"price": 4092.0, "label": "t1"}],
        anchor_plan={"entry": 4086.5}, now=NOW, is_probe=True,
    )
    scenario.transition("VALIDATED", "test", now=NOW)
    activate_scenario(scenario, now=NOW)
    return scenario


def test_execute_scenario_anchor_never_opens_for_a_probe_scenario():
    scenario = _active_probe_scenario()
    original_open_position = ae.open_position
    original_place_order = ae.place_order
    ae.open_position = _poison
    ae.place_order = _poison
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, current_price=4086.5, now=NOW,
        )
        assert scenario.anchor_status == "NONE"  # jamais tente, transitoire
    finally:
        ae.open_position = original_open_position
        ae.place_order = original_place_order
    print("test_execute_scenario_anchor_never_opens_for_a_probe_scenario OK")


def test_execute_scenario_scalp_never_opens_for_a_probe_scenario():
    scenario = _active_probe_scenario()
    scenario.scalp_allowed = True
    original_open_position = ae.open_position
    ae.open_position = _poison
    try:
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"}, 4086.5,
            None, [], {}, trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.executed_scalp_count == 0
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_scalp_never_opens_for_a_probe_scenario OK")


def test_scenario_to_dict_exposes_is_probe():
    scenario = _active_probe_scenario()
    assert scenario.to_dict()["is_probe"] is True
    normal = make_scenario(
        "XAUUSD_NORMAL", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, now=NOW,
    )
    assert normal.to_dict()["is_probe"] is False
    print("test_scenario_to_dict_exposes_is_probe OK")


if __name__ == "__main__":
    test_correction_regime_still_blocked_by_default_zero_probe_rate()
    test_correction_regime_generates_probe_when_rate_is_one()
    test_non_correction_regime_never_marked_probe_even_with_rate_one()
    test_block_disabled_entirely_never_produces_a_probe()
    test_scenario_engine_step_explicit_zero_override_beats_params_rate()
    test_scenario_engine_step_reads_params_rate_when_not_overridden()
    test_execute_scenario_anchor_never_opens_for_a_probe_scenario()
    test_execute_scenario_scalp_never_opens_for_a_probe_scenario()
    test_scenario_to_dict_exposes_is_probe()
    print("ALL TESTS PASSED")
