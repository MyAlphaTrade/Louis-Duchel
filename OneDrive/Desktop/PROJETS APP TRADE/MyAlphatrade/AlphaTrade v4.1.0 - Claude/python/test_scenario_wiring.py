"""Tests pour le branchement reel du Market Scenario Engine (v5.1.1,
Phases 1-4) dans alphatrade_engine.py : compartiment SHARED_MEMORY
'active_scenarios', persistance scenario_log.jsonl, orchestration
scenario_engine_step() (Generator + Validator + CAIO + Dynamic Position
Manager), et la garde d'observation obligatoire (aucun appel reel a
place_order()/open_position() a aucune des 4 phases)."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae
from agent_report import make_agent_report
from scenario import make_scenario, activate_scenario

NOW = datetime(2026, 8, 4, 10, 30, 0, tzinfo=timezone.utc)


def _zone():
    return {"low": 4085.0, "high": 4088.0}


def test_scenario_generator_can_write_active_scenarios_compartment():
    ae.SHARED_MEMORY._store.clear()
    s = make_scenario("scn-1", "XAUUSD", "BUY", _zone(), scenario_confidence=68, now=NOW)
    envelope = ae.SHARED_MEMORY.write("active_scenarios", "scenario_generator", s.to_dict(), confidence=68, now=NOW)
    assert envelope["source"] == "scenario_generator"
    read_back = ae.SHARED_MEMORY.read_payload("active_scenarios")
    assert read_back["scenario_id"] == "scn-1"
    assert read_back["status"] == "CANDIDATE"
    print("test_scenario_generator_can_write_active_scenarios_compartment OK")


def test_other_source_cannot_write_active_scenarios_compartment():
    ae.SHARED_MEMORY._store.clear()
    try:
        ae.SHARED_MEMORY.write("active_scenarios", "caio", {"x": 1}, now=NOW)
        assert False, "devait lever PermissionError"
    except PermissionError:
        pass
    print("test_other_source_cannot_write_active_scenarios_compartment OK")


def test_log_scenario_event_appends_to_scenario_log_jsonl():
    log_path = ae.DATA_DIR / "scenario_log.jsonl"
    log_path.unlink(missing_ok=True)
    s = make_scenario("scn-2", "XAUUSD", "SELL", {"low": 4090.0, "high": 4093.0}, scenario_confidence=74, now=NOW)
    ae.log_scenario_event(s)
    s.transition("VALIDATED", "Zone touchee, reaction confirmee.", now=NOW)
    ae.log_scenario_event(s)
    activate_scenario(s, now=NOW)
    ae.log_scenario_event(s)

    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    assert [l["status"] for l in lines] == ["CANDIDATE", "VALIDATED", "ACTIVE"]
    assert lines[0]["scenario_id"] == "scn-2"
    assert lines[2]["scenario_confidence_at_entry"] == 74.0
    # history complet present a chaque ligne, pas seulement le dernier etat
    assert len(lines[2]["history"]) == 3
    print("test_log_scenario_event_appends_to_scenario_log_jsonl OK")


def _buy_structure():
    return make_agent_report(
        "structure_analyst", status="OK", confidence=82.0, priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": 4086.5},
        arguments=["Regime UPTREND."], metadata={"regime": "UPTREND", "timeframe": "M5"}, now=NOW,
    )


def _buy_smart_money():
    return make_agent_report(
        "smart_money_analyst", status="OK", confidence=78.0, priority="MEDIUM",
        recommendation={"action": "BUY_LIMIT", "price": 4086.0}, arguments=["Sweep bullish."], now=NOW,
    )


def _sell_smart_money():
    return make_agent_report(
        "smart_money_analyst", status="OK", confidence=78.0, priority="MEDIUM",
        recommendation={"action": "SELL_LIMIT", "price": 4086.0}, arguments=["CHOCH bearish."], now=NOW,
    )


def _candles_dpm():
    return [{"open": 4085, "high": 4086, "low": 4084, "close": 4085, "time": i} for i in range(60)]


def _candles_scalp_opportunity():
    """Bougies avec un vrai motif de rejet (v5.1.1 chantier 2) : mouvement
    BAISSIER (contraire au scenario BUY) qui decelere + bougies qui
    retrecissent + rejet de meche basse sur les 3 dernieres -- exemple de
    Louis (04/08/2026) reproduit dans un fixture, cense donner un score
    Gold Microstructure >= 60 (score reel ~70) pour reellement declencher
    `micro_opportunity` via gold_microstructure_score(), pas via l'ancien
    proxy score_gap."""
    filler = [{"open": 4090.0, "high": 4091.5, "low": 4088.5, "close": 4090.0, "time": i} for i in range(10)]
    recent = [
        {"open": 4085.5, "high": 4086.0, "low": 4085.0, "close": 4085.5, "time": 10},
        {"open": 4085.0, "high": 4085.5, "low": 4084.5, "close": 4085.0, "time": 11},
        {"open": 4084.9, "high": 4085.0, "low": 4084.0, "close": 4084.7, "time": 12},
        {"open": 4084.6, "high": 4084.8, "low": 4083.8, "close": 4084.5, "time": 13},
        {"open": 4084.5, "high": 4084.7, "low": 4083.7, "close": 4084.4, "time": 14},
    ]
    return filler + recent


def _ok_risk():
    return make_agent_report(
        "risk_manager", status="OK", confidence=90.0, priority="LOW",
        recommendation={"action": "WAIT", "any_rejected": False}, now=NOW,
    )


def test_scenario_engine_step_creates_and_validates_without_caio_activation():
    ae.CURRENT_SCENARIO = None
    ae.SHARED_MEMORY._store.clear()
    (ae.DATA_DIR / "scenario_log.jsonl").unlink(missing_ok=True)
    candles = [{"open": 4085, "high": 4086, "low": 4084, "close": 4085, "time": i} for i in range(60)]
    # Seuil CAIO volontairement hors de portee -- isole Generator+Validator
    # (Phase 2) de l'arbitrage CAIO (Phase 3), teste separement plus bas.
    params = {"scenario_caio_min_confidence": 999}

    scenario = ae.scenario_engine_step(
        params, "XAUUSD", candles, 4086.5, _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=NOW,
    )
    assert scenario is not None
    assert scenario.status == "VALIDATED"  # zone touchee + reaction + risk_ok + market_ok des le 1er appel
    assert ae.CURRENT_SCENARIO is scenario
    assert ae.SHARED_MEMORY.read_payload("active_scenarios")["scenario_id"] == scenario.scenario_id

    # Deuxieme appel, meme scenario reutilise (pas recree) -- deja VALIDATED,
    # confiance toujours sous le seuil CAIO -> aucun nouveau log.
    scenario2 = ae.scenario_engine_step(
        params, "XAUUSD", candles, 4086.5, _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=NOW,
    )
    assert scenario2 is scenario
    assert scenario2.status == "VALIDATED"

    lines = [json.loads(l) for l in (ae.DATA_DIR / "scenario_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2  # creation (CANDIDATE) + transition (VALIDATED), rien de plus au 2e appel
    assert lines[0]["status"] == "CANDIDATE"
    assert lines[1]["status"] == "VALIDATED"
    print("test_scenario_engine_step_creates_and_validates_without_caio_activation OK")


def test_scenario_engine_step_caio_activates_scenario_when_confidence_sufficient():
    ae.CURRENT_SCENARIO = None
    ae.SHARED_MEMORY._store.clear()
    (ae.DATA_DIR / "scenario_log.jsonl").unlink(missing_ok=True)
    candles = [{"open": 4085, "high": 4086, "low": 4084, "close": 4085, "time": i} for i in range(60)]
    # garanti atteint -- isole le comportement d'activation. NOW tombe en session
    # londres (voir session_label()) -- scenario_london_min_confidence doit aussi
    # etre neutralise, sinon ce test isole par erreur le seuil Londres (05/08/2026).
    params = {"scenario_caio_min_confidence": 1, "scenario_london_min_confidence": 1}

    scenario = ae.scenario_engine_step(
        params, "XAUUSD", candles, 4086.5, _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=NOW,
    )
    assert scenario.status == "ACTIVE"
    assert scenario.scenario_confidence_at_entry == scenario.scenario_confidence
    assert scenario.scenario_health == scenario.scenario_confidence
    assert scenario.scalp_allowed is True

    lines = [json.loads(l) for l in (ae.DATA_DIR / "scenario_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [l["status"] for l in lines] == ["CANDIDATE", "VALIDATED", "ACTIVE"]
    print("test_scenario_engine_step_caio_activates_scenario_when_confidence_sufficient OK")


def test_scenario_engine_step_throttles_dpm_reevaluation_within_interval():
    """05/08/2026 -- bug trouve en observation reelle : sans throttle,
    dynamic_position_manager_step() se relancait a chaque tick (0,1-0,5s),
    recalculant scenario_health depuis une bougie encore en formation --
    oscillation ACTIVE<->DEGRADED plusieurs fois par seconde. Deux appels
    rapproches (meme `now`) doivent produire UNE seule reevaluation DPM."""
    ae.CURRENT_SCENARIO = None
    ae.LAST_DPM_EVAL_AT = None
    ae.SHARED_MEMORY._store.clear()
    (ae.DATA_DIR / "scenario_log.jsonl").unlink(missing_ok=True)
    candles = _candles_dpm()
    params = {
        "scenario_caio_min_confidence": 1, "scenario_london_min_confidence": 1,
        "scenario_health_reeval_interval_sec": 3.0,
    }

    ae.scenario_engine_step(
        params, "XAUUSD", candles, 4086.5, _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=NOW,
    )
    assert ae.LAST_DPM_EVAL_AT == NOW  # premiere reevaluation, LAST_DPM_EVAL_AT etait None
    lines_after_first = len(
        [l for l in (ae.DATA_DIR / "scenario_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    )

    just_after = NOW + timedelta(seconds=1)  # sous scenario_health_reeval_interval_sec (3.0)
    ae.scenario_engine_step(
        params, "XAUUSD", candles, 4086.6, _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=just_after,
    )
    assert ae.LAST_DPM_EVAL_AT == NOW  # inchange -- 2e appel throttle, DPM pas relance
    lines_after_second = len(
        [l for l in (ae.DATA_DIR / "scenario_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    )
    assert lines_after_second == lines_after_first  # aucune nouvelle ligne (DPM seul source d'ecriture a ce stade)
    print("test_scenario_engine_step_throttles_dpm_reevaluation_within_interval OK")


def test_scenario_engine_step_reevaluates_dpm_after_interval_elapsed():
    ae.CURRENT_SCENARIO = None
    ae.LAST_DPM_EVAL_AT = None
    ae.SHARED_MEMORY._store.clear()
    (ae.DATA_DIR / "scenario_log.jsonl").unlink(missing_ok=True)
    candles = _candles_dpm()
    params = {
        "scenario_caio_min_confidence": 1, "scenario_london_min_confidence": 1,
        "scenario_health_reeval_interval_sec": 3.0,
    }

    ae.scenario_engine_step(
        params, "XAUUSD", candles, 4086.5, _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=NOW,
    )
    assert ae.LAST_DPM_EVAL_AT == NOW

    later = NOW + timedelta(seconds=5)  # au-dela de scenario_health_reeval_interval_sec (3.0)
    ae.scenario_engine_step(
        params, "XAUUSD", candles, 4086.6, _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=later,
    )
    assert ae.LAST_DPM_EVAL_AT == later  # reevalue, throttle expire
    print("test_scenario_engine_step_reevaluates_dpm_after_interval_elapsed OK")


def test_run_scenario_replay_resets_dpm_throttle():
    """Un rejeu ne doit jamais heriter (ni laisser fuiter vers le direct) un
    throttle DPM issu d'un autre contexte -- meme garde que CURRENT_SCENARIO,
    reinitialise a la fois au debut et a la fin de run_scenario_replay()."""
    (ae.DATA_DIR / "scenario_log.jsonl").unlink(missing_ok=True)
    (ae.DATA_DIR / "scenario_replay_log.jsonl").unlink(missing_ok=True)
    ae.CURRENT_SCENARIO = None
    ae.LAST_DPM_EVAL_AT = NOW  # simule un throttle actif issu d'un cycle live precedent

    original_fetch_range = ae.fetch_candles_range
    ae.fetch_candles_range = lambda *a, **k: _synthetic_historical_candles()
    try:
        params = {"active_symbol": "XAUUSD", "symbols": {"XAUUSD": {"timeframe": "M5"}}, "scenario_caio_min_confidence": 1}
        ae.run_scenario_replay(params, {"XAUUSD": "XAUUSD"}, days=7, step_candles=20)
    finally:
        ae.fetch_candles_range = original_fetch_range
        ae.CURRENT_SCENARIO = None

    assert ae.LAST_DPM_EVAL_AT is None  # jamais laisse fuiter vers le prochain cycle live
    print("test_run_scenario_replay_resets_dpm_throttle OK")


def test_caio_decide_scenario_waits_when_not_validated():
    scenario = make_scenario("XAUUSD_1", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, scenario_confidence=90, now=NOW)
    result = ae.caio_decide_scenario(scenario, {"scenario_caio_min_confidence": 1}, now=NOW)
    assert result["decision"] == "WAIT"
    assert scenario.status == "CANDIDATE"
    print("test_caio_decide_scenario_waits_when_not_validated OK")


def test_caio_decide_scenario_waits_below_threshold():
    scenario = make_scenario("XAUUSD_2", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, scenario_confidence=50, now=NOW)
    scenario.transition("VALIDATED", "test", now=NOW)
    result = ae.caio_decide_scenario(scenario, {"scenario_caio_min_confidence": 75}, now=NOW)
    assert result["decision"] == "WAIT"
    assert scenario.status == "VALIDATED"  # reste VALIDATED, pas d'activation
    print("test_caio_decide_scenario_waits_below_threshold OK")


def test_caio_decide_scenario_activates_above_threshold():
    scenario = make_scenario("XAUUSD_3", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, scenario_confidence=80, now=NOW)
    scenario.transition("VALIDATED", "test", now=NOW)
    result = ae.caio_decide_scenario(scenario, {"scenario_caio_min_confidence": 75}, now=NOW)
    assert result["decision"] == "GO"
    assert scenario.status == "ACTIVE"
    print("test_caio_decide_scenario_activates_above_threshold OK")


def _london_scenario(confidence):
    scenario = make_scenario(
        "XAUUSD_LDN", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, scenario_confidence=confidence,
        market_context={"session": "london", "trend": "UPTREND", "volatility": "medium"}, now=NOW,
    )
    scenario.transition("VALIDATED", "test", now=NOW)
    return scenario


def test_caio_decide_scenario_london_requires_higher_confidence():
    """05/08/2026 -- analyse Scenario Replay 58j : winrate Londres monte
    nettement au-dessus de 70 de confiance (33-35% en dessous, 47-50% au-dessus).
    scenario_caio_min_confidence seul (60) ne doit PAS suffire en session londres."""
    scenario = _london_scenario(65)  # au-dessus du seuil general (60), en dessous du seuil londres (70)
    result = ae.caio_decide_scenario(scenario, {"scenario_caio_min_confidence": 60}, now=NOW)
    assert result["decision"] == "WAIT"
    assert scenario.status == "VALIDATED"
    print("test_caio_decide_scenario_london_requires_higher_confidence OK")


def test_caio_decide_scenario_london_activates_above_its_own_threshold():
    scenario = _london_scenario(75)
    result = ae.caio_decide_scenario(scenario, {"scenario_caio_min_confidence": 60}, now=NOW)
    assert result["decision"] == "GO"
    assert scenario.status == "ACTIVE"
    print("test_caio_decide_scenario_london_activates_above_its_own_threshold OK")


def test_caio_decide_scenario_london_threshold_never_lowers_general_threshold():
    """Si scenario_caio_min_confidence est deja plus haut que le seuil londres,
    ce dernier ne doit jamais l'abaisser (max(), pas remplacement)."""
    scenario = _london_scenario(72)  # au-dessus du seuil londres (70), en dessous d'un seuil general de 80
    result = ae.caio_decide_scenario(
        scenario, {"scenario_caio_min_confidence": 80, "scenario_london_min_confidence": 60}, now=NOW,
    )
    assert result["decision"] == "WAIT"
    assert scenario.status == "VALIDATED"
    print("test_caio_decide_scenario_london_threshold_never_lowers_general_threshold OK")


def test_caio_decide_scenario_non_london_session_unaffected_by_london_threshold():
    scenario = make_scenario(
        "XAUUSD_NY", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, scenario_confidence=65,
        market_context={"session": "new_york", "trend": "UPTREND", "volatility": "medium"}, now=NOW,
    )
    scenario.transition("VALIDATED", "test", now=NOW)
    result = ae.caio_decide_scenario(
        scenario, {"scenario_caio_min_confidence": 60, "scenario_london_min_confidence": 70}, now=NOW,
    )
    assert result["decision"] == "GO"  # 65 >= 60 (seuil general), le seuil londres ne s'applique pas hors londres
    assert scenario.status == "ACTIVE"
    print("test_caio_decide_scenario_non_london_session_unaffected_by_london_threshold OK")


def test_caio_decide_scenario_never_calls_real_execution():
    """Garde de securite explicite (Louis, 04/08/2026) : l'arbitrage CAIO sur
    un scenario ne doit JAMAIS ouvrir de position reelle en Phase 3. Empoisonne
    place_order()/open_position() (leve si appele) et confirme qu'ils ne le
    sont pas, meme sur une activation reussie."""
    original_place_order = ae.place_order
    original_open_position = ae.open_position

    def _poison(*a, **k):
        raise AssertionError("caio_decide_scenario() ne doit jamais executer d'ordre reel")

    ae.place_order = _poison
    ae.open_position = _poison
    try:
        scenario = make_scenario("XAUUSD_4", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, scenario_confidence=90, now=NOW)
        scenario.transition("VALIDATED", "test", now=NOW)
        result = ae.caio_decide_scenario(scenario, {"scenario_caio_min_confidence": 1}, now=NOW)
        assert result["decision"] == "GO"
        assert scenario.status == "ACTIVE"
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
    print("test_caio_decide_scenario_never_calls_real_execution OK")


def _active_scenario():
    scenario = make_scenario(
        "XAUUSD_ACTIVE", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0},
        scenario_confidence=80.0, market_context={"atr": 2.0}, invalidation_price=4080.0,
        targets=[{"price": 4092.0, "label": "t1"}, {"price": 4098.0, "label": "t2"}],
        anchor_plan={"entry": 4086.5, "sl": 4080.0, "tp": 4092.0}, now=NOW,
    )
    scenario.transition("VALIDATED", "test", now=NOW)
    activate_scenario(scenario, now=NOW)
    return scenario


def test_dynamic_position_manager_closes_on_invalidation():
    scenario = _active_scenario()
    ae.dynamic_position_manager_step(
        scenario, {}, 4079.0, _buy_structure(), _buy_smart_money(), _ok_risk(), _candles_dpm(), {}, now=NOW,
    )
    assert scenario.status == "INVALIDATED"
    assert scenario.outcome == "LOSS_SIMULATED"
    assert scenario.outcome_profit < 0
    print("test_dynamic_position_manager_closes_on_invalidation OK")


def test_dynamic_position_manager_closes_on_target_reached():
    scenario = _active_scenario()
    ae.dynamic_position_manager_step(
        scenario, {}, 4099.0, _buy_structure(), _buy_smart_money(), _ok_risk(), _candles_dpm(), {}, now=NOW,
    )
    assert scenario.status == "COMPLETED"
    assert scenario.outcome == "WIN_SIMULATED"
    assert scenario.outcome_profit > 0
    print("test_dynamic_position_manager_closes_on_target_reached OK")


def test_dynamic_position_manager_closes_on_expiry():
    scenario = _active_scenario()
    later = datetime(2026, 8, 4, 11, 30, tzinfo=timezone.utc)  # bien au-dela des 45 min par defaut
    ae.dynamic_position_manager_step(
        scenario, {}, 4086.5, _buy_structure(), _buy_smart_money(), _ok_risk(), _candles_dpm(), {}, now=later,
    )
    assert scenario.status == "EXPIRED"
    print("test_dynamic_position_manager_closes_on_expiry OK")


def test_dynamic_position_manager_degrades_on_smart_money_reversal():
    scenario = _active_scenario()
    params = {"scenario_health_degradation_threshold": 45.0}
    ae.dynamic_position_manager_step(
        scenario, params, 4086.5, _buy_structure(), _sell_smart_money(), _ok_risk(), _candles_dpm(), {}, now=NOW,
    )
    assert scenario.status == "DEGRADED"
    assert scenario.scalp_allowed is False
    print("test_dynamic_position_manager_degrades_on_smart_money_reversal OK")


def test_dynamic_position_manager_recovers_from_degraded():
    scenario = _active_scenario()
    scenario.status = "DEGRADED"
    scenario.scalp_allowed = False
    params = {"scenario_health_degradation_threshold": 1.0}  # garanti franchi
    ae.dynamic_position_manager_step(
        scenario, params, 4086.5, _buy_structure(), _buy_smart_money(), _ok_risk(), _candles_dpm(), {}, now=NOW,
    )
    assert scenario.status == "ACTIVE"
    assert scenario.scalp_allowed is True
    print("test_dynamic_position_manager_recovers_from_degraded OK")


def test_dynamic_position_manager_detects_scalp_opportunity():
    scenario = _active_scenario()
    params = {"scenario_health_degradation_threshold": 1.0}
    ae.dynamic_position_manager_step(
        scenario, params, 4086.6, _buy_structure(), _buy_smart_money(), _ok_risk(), _candles_scalp_opportunity(), {"score_gap": 50.0}, now=NOW,
    )
    assert scenario.simulated_scalp_count == 1
    print("test_dynamic_position_manager_detects_scalp_opportunity OK")


def test_dynamic_position_manager_noop_on_non_active_status():
    scenario = make_scenario("XAUUSD_CAND", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, now=NOW)
    ae.dynamic_position_manager_step(
        scenario, {}, 4086.5, _buy_structure(), _buy_smart_money(), _ok_risk(), _candles_dpm(), {}, now=NOW,
    )
    assert scenario.status == "CANDIDATE"  # aucune modification, statut ineligible
    print("test_dynamic_position_manager_noop_on_non_active_status OK")


def test_dynamic_position_manager_never_calls_real_execution():
    """Meme garde de securite que le CAIO scenario (Phase 3), etendue au
    Dynamic Position Manager (Phase 4) -- ni la gestion de sante/degradation,
    ni la detection de scalp, ni la cloture simulee n'appellent jamais
    place_order()/open_position()."""
    original_place_order = ae.place_order
    original_open_position = ae.open_position

    def _poison(*a, **k):
        raise AssertionError("dynamic_position_manager_step() ne doit jamais executer d'ordre reel")

    ae.place_order = _poison
    ae.open_position = _poison
    try:
        scenario = _active_scenario()
        params = {"scenario_health_degradation_threshold": 1.0}
        # Un cycle "opportunite de scalp" (le chemin le plus a risque de finir
        # par vouloir executer un ordre, s'il y avait une regression).
        ae.dynamic_position_manager_step(
            scenario, params, 4086.6, _buy_structure(), _buy_smart_money(), _ok_risk(), _candles_scalp_opportunity(), {"score_gap": 50.0}, now=NOW,
        )
        assert scenario.simulated_scalp_count == 1
    finally:
        ae.place_order = original_place_order
        ae.open_position = original_open_position
    print("test_dynamic_position_manager_never_calls_real_execution OK")


def _synthetic_historical_candles(n=2000, base=4085.0):
    """Serie synthetique avec une derive legere + oscillation, pour donner au
    Scenario Generator quelque chose a analyser (pas juste du bruit plat).
    'time' en secondes Unix croissantes (M5 ~ 300s/bougie)."""
    import math
    start = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
    out = []
    price = base
    for i in range(n):
        price += math.sin(i / 40.0) * 0.8 + (0.02 if i % 3 == 0 else -0.01)
        out.append({
            "open": price, "high": price + 1.2, "low": price - 1.2, "close": price,
            "time": start + i * 300,
        })
    return out


def test_run_scenario_replay_writes_only_to_replay_log_never_real_execution():
    (ae.DATA_DIR / "scenario_log.jsonl").unlink(missing_ok=True)
    (ae.DATA_DIR / "scenario_replay_log.jsonl").unlink(missing_ok=True)
    ae.CURRENT_SCENARIO = None

    original_fetch_range = ae.fetch_candles_range
    original_place_order = ae.place_order
    original_open_position = ae.open_position

    def _poison(*a, **k):
        raise AssertionError("run_scenario_replay() ne doit jamais executer d'ordre reel")

    ae.fetch_candles_range = lambda *a, **k: _synthetic_historical_candles()
    ae.place_order = _poison
    ae.open_position = _poison
    try:
        params = {"active_symbol": "XAUUSD", "symbols": {"XAUUSD": {"timeframe": "M5"}}, "scenario_caio_min_confidence": 1}
        ae.run_scenario_replay(params, {"XAUUSD": "XAUUSD"}, days=7, step_candles=20)
    finally:
        ae.fetch_candles_range = original_fetch_range
        ae.place_order = original_place_order
        ae.open_position = original_open_position
        ae.CURRENT_SCENARIO = None

    assert not (ae.DATA_DIR / "scenario_log.jsonl").exists()  # jamais melange avec l'observation live
    replay_path = ae.DATA_DIR / "scenario_replay_log.jsonl"
    assert replay_path.exists()
    lines = [json.loads(l) for l in replay_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) > 0
    print("test_run_scenario_replay_writes_only_to_replay_log_never_real_execution OK")


def test_run_scenario_replay_handles_insufficient_history_gracefully():
    ae.CURRENT_SCENARIO = None
    original_fetch_range = ae.fetch_candles_range
    ae.fetch_candles_range = lambda *a, **k: _synthetic_historical_candles(n=50)  # < 360, insuffisant
    try:
        params = {"active_symbol": "XAUUSD", "symbols": {"XAUUSD": {"timeframe": "M5"}}}
        ae.run_scenario_replay(params, {"XAUUSD": "XAUUSD"}, days=1)  # ne doit pas lever
    finally:
        ae.fetch_candles_range = original_fetch_range
    print("test_run_scenario_replay_handles_insufficient_history_gracefully OK")


def test_load_scenario_weights_falls_back_to_default_when_file_absent():
    (ae.DATA_DIR / "scenario_learned_weights.json").unlink(missing_ok=True)
    assert ae.load_scenario_weights() == ae.SCENARIO_WEIGHTS
    print("test_load_scenario_weights_falls_back_to_default_when_file_absent OK")


def test_load_scenario_weights_returns_learned_weights_when_valid():
    ae.write_json("scenario_learned_weights.json", {
        "learned_weights": {**ae.SCENARIO_WEIGHTS, "session": 0.15},
    })
    weights = ae.load_scenario_weights()
    assert weights["session"] == 0.15
    (ae.DATA_DIR / "scenario_learned_weights.json").unlink(missing_ok=True)
    print("test_load_scenario_weights_returns_learned_weights_when_valid OK")


def test_load_scenario_weights_falls_back_when_keys_incomplete():
    ae.write_json("scenario_learned_weights.json", {"learned_weights": {"structure": 0.3}})
    assert ae.load_scenario_weights() == ae.SCENARIO_WEIGHTS
    (ae.DATA_DIR / "scenario_learned_weights.json").unlink(missing_ok=True)
    print("test_load_scenario_weights_falls_back_when_keys_incomplete OK")


def test_generate_scenario_uses_injected_weights_via_scenario_engine_step():
    """Verifie le branchement bout-en-bout : scenario_engine_step() charge
    load_scenario_weights() et l'injecte reellement dans generate_scenario()
    -- pas seulement que le parametre existe, qu'il change le resultat."""
    ae.CURRENT_SCENARIO = None
    candles = [{"open": 4085, "high": 4086, "low": 4084, "close": 4085, "time": i} for i in range(60)]
    skewed = dict(ae.SCENARIO_WEIGHTS)
    skewed["structure"] = 0.0
    skewed["smart_money"] = 0.0  # neutralise les 2 plus gros facteurs -> confiance forcement plus basse

    ae.write_json("scenario_learned_weights.json", {"learned_weights": skewed})
    try:
        with_skewed = ae.scenario_engine_step(
            {"scenario_caio_min_confidence": 999}, "XAUUSD", candles, 4086.5,
            _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=NOW,
        )
    finally:
        (ae.DATA_DIR / "scenario_learned_weights.json").unlink(missing_ok=True)
    ae.CURRENT_SCENARIO = None
    with_default = ae.scenario_engine_step(
        {"scenario_caio_min_confidence": 999}, "XAUUSD", candles, 4086.5,
        _buy_structure(), _buy_smart_money(), _ok_risk(), None, {}, now=NOW,
    )
    assert with_skewed.scenario_confidence < with_default.scenario_confidence
    print("test_generate_scenario_uses_injected_weights_via_scenario_engine_step OK")


def test_run_scenario_learning_writes_recommendation_without_touching_default_weights():
    (ae.DATA_DIR / "scenario_learned_weights.json").unlink(missing_ok=True)
    (ae.DATA_DIR / "scenario_replay_log.jsonl").unlink(missing_ok=True)  # isolation vs les tests replay precedents
    log_path = ae.DATA_DIR / "scenario_log.jsonl"
    log_path.unlink(missing_ok=True)
    with log_path.open("w", encoding="utf-8") as f:
        for i in range(30):
            f.write(json.dumps({
                "scenario_id": f"s{i}",
                "outcome": "WIN_SIMULATED" if i % 2 == 0 else "LOSS_SIMULATED",
                "market_context": {"session": "london", "trend": "UPTREND", "volatility": "medium"},
                "direction": "BUY",
            }) + "\n")
    ae.run_scenario_learning(min_samples=20)
    assert (ae.DATA_DIR / "scenario_learned_weights.json").exists()
    assert ae.SCENARIO_WEIGHTS == {
        "structure": 0.25, "smart_money": 0.25, "zone_history": 0.15, "volatility": 0.15,
        "momentum": 0.05, "session": 0.05, "microstructure": 0.10,
    }
    (ae.DATA_DIR / "scenario_learned_weights.json").unlink(missing_ok=True)
    log_path.unlink(missing_ok=True)
    print("test_run_scenario_learning_writes_recommendation_without_touching_default_weights OK")


def test_run_scenario_learning_logs_real_adaptation_when_weights_change():
    """v5.1.1, 05/08/2026 -- historique reel des adaptations (section 6,
    demande explicite de Louis). Seed un "avant" tres different du resultat
    reel calcule, pour garantir un ecart > 0.01 sur au moins un facteur."""
    (ae.DATA_DIR / "scenario_learned_weights.json").unlink(missing_ok=True)
    (ae.DATA_DIR / "scenario_replay_log.jsonl").unlink(missing_ok=True)
    (ae.DATA_DIR / "ai_adaptations_log.jsonl").unlink(missing_ok=True)
    log_path = ae.DATA_DIR / "scenario_log.jsonl"
    log_path.unlink(missing_ok=True)
    with log_path.open("w", encoding="utf-8") as f:
        for i in range(30):
            f.write(json.dumps({
                "scenario_id": f"s{i}",
                "outcome": "WIN_SIMULATED" if i % 2 == 0 else "LOSS_SIMULATED",
                "market_context": {"session": "london", "trend": "UPTREND", "volatility": "medium"},
                "direction": "BUY",
            }) + "\n")
    # "avant" artificiel, tres eloigne de tout resultat plausible -- garantit
    # un ecart detecte quel que soit le calcul reel de scenario_weight_adjustments().
    ae.write_json("scenario_learned_weights.json", {
        "computed_at": NOW.isoformat(), "n_resolved": 20, "overall_winrate": 50.0,
        "base_weights": ae.SCENARIO_WEIGHTS,
        "learned_weights": {k: 0.0 for k in ae.SCENARIO_WEIGHTS},
        "stats": {},
    })
    ae.run_scenario_learning(min_samples=20)
    lines = [json.loads(l) for l in (ae.DATA_DIR / "ai_adaptations_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) > 0
    assert all(l["module"] == "scenario_learning" for l in lines)
    assert all(l["parameter"].startswith("scenario_weight.") for l in lines)
    assert all(l["old_value"] == 0.0 for l in lines)
    (ae.DATA_DIR / "scenario_learned_weights.json").unlink(missing_ok=True)
    (ae.DATA_DIR / "ai_adaptations_log.jsonl").unlink(missing_ok=True)
    log_path.unlink(missing_ok=True)
    print("test_run_scenario_learning_logs_real_adaptation_when_weights_change OK")


def test_scenario_engine_step_returns_none_without_candles():
    ae.CURRENT_SCENARIO = None
    result = ae.scenario_engine_step(
        {}, "XAUUSD", [], 0.0,
        make_agent_report("structure_analyst", status="UNAVAILABLE", confidence=0, priority="LOW", recommendation={"action": "WAIT"}, now=NOW),
        make_agent_report("smart_money_analyst", status="UNAVAILABLE", confidence=0, priority="LOW", recommendation={"action": "WAIT"}, now=NOW),
        _ok_risk(), None, {}, now=NOW,
    )
    assert result is None
    assert ae.CURRENT_SCENARIO is None
    print("test_scenario_engine_step_returns_none_without_candles OK")


class _FakeTerminal:
    tradeapi_disabled = False
    trade_allowed = True


class _FakeAccount:
    balance = 10000.0
    login = 12345
    server = "Demo-Server"
    trade_mode = 0


class _FakeMT5Connected:
    """Meme surface minimale que test_caio_decisions_log.py -- suffisant pour
    franchir les gates d'auto_trade_step() jusqu'au bloc d'observation
    Scenario Engine. fetch_candles() degrade proprement sans copy_rates_from_pos
    (deja teste ailleurs), donc le Scenario Engine doit degrader tout aussi
    proprement en aval, sans exception."""
    def account_info(self):
        return _FakeAccount()

    def terminal_info(self):
        return _FakeTerminal()


def test_auto_trade_step_wires_scenario_engine_observation_without_crashing():
    ae.write_json("trading_state.json", {"enabled": True, "real_confirmed": True})
    params = ae.merge_params()
    params["scenario_engine_enabled"] = True
    params["gold_brain_enabled"] = False
    params["ai_server_enabled"] = False
    original_mt5 = ae.mt5
    ae.mt5 = _FakeMT5Connected()
    ae.CURRENT_SCENARIO = None
    try:
        state = ae.auto_trade_step(
            params, {"XAUUSD": "XAUUSD"},
            {
                "active_symbol": "XAUUSD",
                "protection": {},
                "session_access": {"XAUUSD": {"entries_allowed": False}},  # coupe le cycle juste apres, pas de bruit
                "simulated_decision": {"eligible": False, "reason": "test"},
                "analysis": {"XAUUSD": {}},
            },
            [], trades=[],
        )
    finally:
        ae.mt5 = original_mt5
    assert isinstance(state, dict)
    assert state.get("scenario") is None  # pas de candles reels -> degrade proprement, meme logique que gold_brain
    print("test_auto_trade_step_wires_scenario_engine_observation_without_crashing OK")


def _fake_position(ticket, symbol_key="XAUUSD", direction="BUY", comment="AlphaTrade 5.1.1 SCENARIO", open_timestamp=1000):
    return {
        "ticket": ticket, "symbol_key": symbol_key, "symbol": "XAUUSD", "direction": direction,
        "origin": "BOT", "origin_name": "AlphaTrade", "origin_type": "INTERNAL_BOT", "origin_magic": 0,
        "lot": 0.01, "open_price": 4086.5, "current_price": 4086.5, "profit": 0.0,
        "open_timestamp": open_timestamp, "open_time": "2026-08-05T10:00:00", "comment": comment,
    }


def _poison_open_position(*a, **k):
    raise AssertionError("open_position() ne doit pas etre appele dans ce scenario de test")


def test_execute_scenario_anchor_opens_real_position_when_all_gates_pass():
    """Coeur de l'activation reelle (05/08/2026, demande explicite de Louis).
    Tous les garde-fous sont verts : la position d'ancrage doit reellement
    s'ouvrir, avec le SL/TP du scenario (pas le TP fixe classique), et le
    ticket reel doit etre retrouve via le tag SCENARIO du commentaire."""
    scenario = _active_scenario()
    calls = []

    def _fake_open_position(symbol_key, symbol, direction, params, lot_info, analysis, allow_real, **kwargs):
        calls.append((symbol_key, symbol, direction, allow_real, kwargs))
        return True, "BUY 0.010 XAUUSD execute en 42 ms.", {"ok": True}

    original_open_position = ae.open_position
    original_lot_safety = ae.lot_safety_state
    original_live_positions = ae.live_positions
    ae.open_position = _fake_open_position
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.01, "reason": ""}}
    ae.live_positions = lambda symbol_names, params=None: [_fake_position(555001)]
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "OPEN"
        assert scenario.anchor_ticket == 555001
        assert len(calls) == 1
        symbol_key, symbol, direction, allow_real, kwargs = calls[0]
        assert symbol_key == "XAUUSD" and symbol == "XAUUSD" and direction == "BUY"
        assert kwargs["sl_price"] == scenario.invalidation_price
        assert kwargs["tp_price"] == scenario.targets[-1]["price"]
        assert kwargs["position_type"] == "SCENARIO"
    finally:
        ae.open_position = original_open_position
        ae.lot_safety_state = original_lot_safety
        ae.live_positions = original_live_positions
    print("test_execute_scenario_anchor_opens_real_position_when_all_gates_pass OK")


def test_execute_scenario_anchor_skipped_when_execution_flag_disabled():
    scenario = _active_scenario()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_anchor(
            scenario, {"scenario_engine_execution_enabled": False}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "NONE"
        assert scenario.anchor_ticket is None
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_anchor_skipped_when_execution_flag_disabled OK")


def test_execute_scenario_anchor_transient_skip_when_trading_not_enabled():
    """Bouton Demarrer pas encore clique -- blocage TRANSITOIRE, pas un
    echec definitif : anchor_status doit rester NONE (retentable)."""
    scenario = _active_scenario()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=False, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "NONE"
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_anchor_transient_skip_when_trading_not_enabled OK")


def test_execute_scenario_anchor_transient_skip_when_protection_blocks():
    scenario = _active_scenario()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        for blocking_state in ("WARNING", "HARD_LOCK", "TARGET_REACHED"):
            scenario.anchor_status = "NONE"
            ae.execute_scenario_anchor(
                scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": blocking_state},
                trading_enabled=True, allow_real=False, now=NOW,
            )
            assert scenario.anchor_status == "NONE", f"devait rester NONE pour {blocking_state}"
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_anchor_transient_skip_when_protection_blocks OK")


def test_execute_scenario_anchor_transient_skip_when_portfolio_brain_blocks():
    """v5.1.1, 05/08/2026 -- Portfolio Brain applique reellement un blocage
    (demande explicite de Louis), expose via protection['portfolio_blocks'],
    distinct de protection['state']."""
    scenario = _active_scenario()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED", "portfolio_blocks": True},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "NONE"
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_anchor_transient_skip_when_portfolio_brain_blocks OK")


def test_execute_scenario_anchor_permanent_fail_when_symbol_missing():
    """Symbole introuvable dans symbol_names : blocage DEFINITIF pour ce
    scenario (pas une question de timing, retenter ne changerait rien)."""
    scenario = _active_scenario()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {}, None, {"state": "ARMED"}, trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "FAILED"
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_anchor_permanent_fail_when_symbol_missing OK")


def test_execute_scenario_anchor_marks_failed_when_order_rejected():
    scenario = _active_scenario()
    original_open_position = ae.open_position
    original_lot_safety = ae.lot_safety_state
    ae.open_position = lambda *a, **k: (False, "Ordre refuse: 10004 Requote", None)
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.01, "reason": ""}}
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "FAILED"
        assert scenario.anchor_ticket is None
    finally:
        ae.open_position = original_open_position
        ae.lot_safety_state = original_lot_safety
    print("test_execute_scenario_anchor_marks_failed_when_order_rejected OK")


def test_execute_scenario_anchor_never_reattempts_once_resolved():
    """Une seule tentative par scenario, quel que soit le resultat -- jamais
    de boucle de re-essai a chaque cycle."""
    scenario = _active_scenario()
    scenario.anchor_status = "OPEN"
    scenario.anchor_ticket = 999001
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "OPEN"
        assert scenario.anchor_ticket == 999001
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_anchor_never_reattempts_once_resolved OK")


def test_close_scenario_anchor_if_needed_closes_real_position_on_terminal_status():
    scenario = _active_scenario()
    scenario.anchor_status = "OPEN"
    scenario.anchor_ticket = 555001
    scenario.transition("INVALIDATED", "test", now=NOW)  # ACTIVE -> INVALIDATED autorise
    calls = []

    def _fake_close(position, reason):
        calls.append((position["ticket"], reason))
        return True, f"Fermeture {position['ticket']} OK."

    original_close = ae.close_bot_position
    ae.close_bot_position = _fake_close
    try:
        ae.close_scenario_anchor_if_needed(scenario, [_fake_position(555001)], now=NOW)
        assert scenario.anchor_status == "CLOSED"
        assert len(calls) == 1 and calls[0][0] == 555001
    finally:
        ae.close_bot_position = original_close
    print("test_close_scenario_anchor_if_needed_closes_real_position_on_terminal_status OK")


def test_close_scenario_anchor_if_needed_noop_when_not_open():
    scenario = _active_scenario()
    scenario.transition("INVALIDATED", "test", now=NOW)
    original_close = ae.close_bot_position
    ae.close_bot_position = _poison_open_position
    try:
        ae.close_scenario_anchor_if_needed(scenario, [_fake_position(555001)], now=NOW)
        assert scenario.anchor_status == "NONE"  # jamais ouvert -- rien a fermer
    finally:
        ae.close_bot_position = original_close
    print("test_close_scenario_anchor_if_needed_noop_when_not_open OK")


def test_close_scenario_anchor_if_needed_noop_while_scenario_still_active():
    scenario = _active_scenario()
    scenario.anchor_status = "OPEN"
    scenario.anchor_ticket = 555001
    original_close = ae.close_bot_position
    ae.close_bot_position = _poison_open_position
    try:
        ae.close_scenario_anchor_if_needed(scenario, [_fake_position(555001)], now=NOW)
        assert scenario.anchor_status == "OPEN"  # toujours ACTIVE -- pas encore a fermer
    finally:
        ae.close_bot_position = original_close
    print("test_close_scenario_anchor_if_needed_noop_while_scenario_still_active OK")


def test_close_scenario_anchor_if_needed_marks_closed_when_position_already_gone():
    """SL/TP broker deja declenche avant que le logiciel n'ait le temps de
    reagir -- la position n'apparait plus dans `positions`."""
    scenario = _active_scenario()
    scenario.anchor_status = "OPEN"
    scenario.anchor_ticket = 555001
    scenario.transition("COMPLETED", "test", now=NOW)
    original_close = ae.close_bot_position
    ae.close_bot_position = _poison_open_position
    try:
        ae.close_scenario_anchor_if_needed(scenario, [], now=NOW)  # plus aucune position ouverte
        assert scenario.anchor_status == "CLOSED"
    finally:
        ae.close_bot_position = original_close
    print("test_close_scenario_anchor_if_needed_marks_closed_when_position_already_gone OK")


def test_close_scenario_anchor_if_needed_retries_when_close_fails():
    scenario = _active_scenario()
    scenario.anchor_status = "OPEN"
    scenario.anchor_ticket = 555001
    scenario.transition("EXPIRED", "test", now=NOW)
    original_close = ae.close_bot_position
    ae.close_bot_position = lambda position, reason: (False, "Fermeture refusee: en attente.")
    try:
        ae.close_scenario_anchor_if_needed(scenario, [_fake_position(555001)], now=NOW)
        assert scenario.anchor_status == "OPEN"  # retente au prochain cycle
    finally:
        ae.close_bot_position = original_close
    print("test_close_scenario_anchor_if_needed_retries_when_close_fails OK")


def test_execute_scenario_scalp_opens_real_position_when_all_gates_pass():
    scenario = _active_scenario()
    calls = []

    def _fake_open_position(symbol_key, symbol, direction, params, lot_info, analysis, allow_real, **kwargs):
        calls.append((direction, lot_info["effective_lot"], kwargs))
        return True, "BUY 0.005 XAUUSD execute.", {"ok": True}

    original_open_position = ae.open_position
    original_lot_safety = ae.lot_safety_state
    ae.open_position = _fake_open_position
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.02, "reason": ""}}
    try:
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"}, 4086.6, _ok_risk(),
            _candles_scalp_opportunity(), {"score_gap": 50.0},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.executed_scalp_count == 1
        assert scenario.last_scalp_executed_at == NOW.isoformat()
        assert scenario.simulated_scalp_count == 0  # inchange -- compteur distinct, jamais touche ici
        assert len(calls) == 1
        direction, lot, kwargs = calls[0]
        assert direction == "BUY"
        assert abs(lot - 0.01) < 1e-9  # 0.02 * ratio par defaut 0.5
        assert kwargs["sl_price"] == scenario.invalidation_price
        assert kwargs["tp_price"] == scenario.targets[0]["price"]  # cible la PLUS PROCHE, pas la derniere
        assert kwargs["position_type"] == "SCENARIO_SCALP"
    finally:
        ae.open_position = original_open_position
        ae.lot_safety_state = original_lot_safety
    print("test_execute_scenario_scalp_opens_real_position_when_all_gates_pass OK")


def test_execute_scenario_scalp_respects_cooldown():
    scenario = _active_scenario()
    scenario.last_scalp_executed_at = NOW.isoformat()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        soon_after = NOW + timedelta(seconds=10)  # sous les 45s par defaut
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"}, 4086.6, _ok_risk(),
            _candles_scalp_opportunity(), {"score_gap": 50.0},
            trading_enabled=True, allow_real=False, now=soon_after,
        )
        assert scenario.executed_scalp_count == 0
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_scalp_respects_cooldown OK")


def test_execute_scenario_scalp_opens_again_after_cooldown_elapsed():
    scenario = _active_scenario()
    scenario.last_scalp_executed_at = NOW.isoformat()
    original_open_position = ae.open_position
    original_lot_safety = ae.lot_safety_state
    ae.open_position = lambda *a, **k: (True, "ok", {"ok": True})
    ae.lot_safety_state = lambda params, account, symbol_names: {"XAUUSD": {"effective_lot": 0.02, "reason": ""}}
    try:
        later = NOW + timedelta(seconds=46)  # au-dela des 45s par defaut
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"}, 4086.6, _ok_risk(),
            _candles_scalp_opportunity(), {"score_gap": 50.0},
            trading_enabled=True, allow_real=False, now=later,
        )
        assert scenario.executed_scalp_count == 1
    finally:
        ae.open_position = original_open_position
        ae.lot_safety_state = original_lot_safety
    print("test_execute_scenario_scalp_opens_again_after_cooldown_elapsed OK")


def test_execute_scenario_scalp_respects_max_count_cap():
    scenario = _active_scenario()
    scenario.executed_scalp_count = 3  # deja au plafond par defaut
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"}, 4086.6, _ok_risk(),
            _candles_scalp_opportunity(), {"score_gap": 50.0},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.executed_scalp_count == 3  # inchange, jamais retente
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_scalp_respects_max_count_cap OK")


def test_execute_scenario_scalp_transient_skip_when_gates_block():
    scenario = _active_scenario()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"}, 4086.6, _ok_risk(),
            _candles_scalp_opportunity(), {"score_gap": 50.0},
            trading_enabled=False, allow_real=False, now=NOW,
        )
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "HARD_LOCK"}, 4086.6, _ok_risk(),
            _candles_scalp_opportunity(), {"score_gap": 50.0},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.executed_scalp_count == 0
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_scalp_transient_skip_when_gates_block OK")


def test_execute_scenario_scalp_transient_skip_when_portfolio_brain_blocks():
    scenario = _active_scenario()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED", "portfolio_blocks": True}, 4086.6, _ok_risk(),
            _candles_scalp_opportunity(), {"score_gap": 50.0},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.executed_scalp_count == 0
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_scalp_transient_skip_when_portfolio_brain_blocks OK")


def test_execute_scenario_scalp_noop_when_conditions_not_all_met():
    """Prix hors zone favorable -- une des 4 conditions echoue, aucun ordre."""
    scenario = _active_scenario()
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_scalp(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"}, 4200.0, _ok_risk(),
            _candles_scalp_opportunity(), {"score_gap": 50.0},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.executed_scalp_count == 0
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_scalp_noop_when_conditions_not_all_met OK")


def test_run_auto_backtest_if_due_skips_when_recently_run():
    """v5.1.1, 05/08/2026 -- section 7. Throttle persiste (auto_backtest_state.json),
    survit au redemarrage -- pas de rejeu couteux tant que l'intervalle n'est pas ecoule."""
    from datetime import timedelta
    ae.write_json("auto_backtest_state.json", {"last_run_at": NOW.isoformat()})
    original_replay = ae.run_scenario_replay

    def _poison(*a, **k):
        raise AssertionError("run_scenario_replay() ne doit pas etre appele si pas encore du")

    ae.run_scenario_replay = _poison
    try:
        soon_after = NOW + timedelta(hours=1)  # sous les 24h par defaut
        ae.run_auto_backtest_if_due({}, {"XAUUSD": "XAUUSD"}, now=soon_after)
    finally:
        ae.run_scenario_replay = original_replay
        (ae.DATA_DIR / "auto_backtest_state.json").unlink(missing_ok=True)
    print("test_run_auto_backtest_if_due_skips_when_recently_run OK")


def test_run_auto_backtest_if_due_noop_when_disabled():
    original_replay = ae.run_scenario_replay
    ae.run_scenario_replay = lambda *a, **k: (_ for _ in ()).throw(AssertionError("ne doit pas etre appele"))
    try:
        ae.run_auto_backtest_if_due({"scenario_auto_backtest_enabled": False}, {"XAUUSD": "XAUUSD"}, now=NOW)
    finally:
        ae.run_scenario_replay = original_replay
    print("test_run_auto_backtest_if_due_noop_when_disabled OK")


def test_run_auto_backtest_if_due_writes_result_after_replay():
    (ae.DATA_DIR / "auto_backtest_state.json").unlink(missing_ok=True)
    (ae.DATA_DIR / "auto_backtest_result.json").unlink(missing_ok=True)
    (ae.DATA_DIR / "scenario_replay_log.jsonl").unlink(missing_ok=True)
    with (ae.DATA_DIR / "scenario_replay_log.jsonl").open("w", encoding="utf-8") as f:
        for i in range(25):
            f.write(json.dumps({
                "scenario_id": f"r{i}",
                "outcome": "WIN_SIMULATED" if i % 3 else "LOSS_SIMULATED",
                "outcome_profit": 1.5 if i % 3 else -1.0,
                "created_at": f"2026-07-{(i % 28) + 1:02d}T10:00:00+00:00",
                "market_context": {"session": "london" if i % 2 else "new_york", "trend": "UPTREND", "volatility": "medium"},
                "direction": "BUY",
            }) + "\n")
    original_replay = ae.run_scenario_replay
    ae.run_scenario_replay = lambda *a, **k: None  # le fichier existe deja, simule un rejeu qui ne le touche pas
    try:
        ae.run_auto_backtest_if_due({"scenario_learning_min_samples": 10}, {"XAUUSD": "XAUUSD"}, now=NOW)
        assert (ae.DATA_DIR / "auto_backtest_state.json").exists()
        result = json.loads((ae.DATA_DIR / "auto_backtest_result.json").read_text(encoding="utf-8"))
        assert result["n_trades"] == 25
        assert "winrate" in result and "max_drawdown_points" in result
    finally:
        ae.run_scenario_replay = original_replay
        (ae.DATA_DIR / "auto_backtest_state.json").unlink(missing_ok=True)
        (ae.DATA_DIR / "auto_backtest_result.json").unlink(missing_ok=True)
        (ae.DATA_DIR / "scenario_replay_log.jsonl").unlink(missing_ok=True)
    print("test_run_auto_backtest_if_due_writes_result_after_replay OK")


def test_execute_scenario_anchor_noop_when_scenario_not_active():
    scenario = make_scenario("XAUUSD_CAND2", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0}, now=NOW)
    original_open_position = ae.open_position
    ae.open_position = _poison_open_position
    try:
        ae.execute_scenario_anchor(
            scenario, {}, {"XAUUSD": "XAUUSD"}, None, {"state": "ARMED"},
            trading_enabled=True, allow_real=False, now=NOW,
        )
        assert scenario.anchor_status == "NONE"
    finally:
        ae.open_position = original_open_position
    print("test_execute_scenario_anchor_noop_when_scenario_not_active OK")


if __name__ == "__main__":
    test_scenario_generator_can_write_active_scenarios_compartment()
    test_other_source_cannot_write_active_scenarios_compartment()
    test_log_scenario_event_appends_to_scenario_log_jsonl()
    test_scenario_engine_step_creates_and_validates_without_caio_activation()
    test_scenario_engine_step_caio_activates_scenario_when_confidence_sufficient()
    test_caio_decide_scenario_waits_when_not_validated()
    test_caio_decide_scenario_waits_below_threshold()
    test_caio_decide_scenario_activates_above_threshold()
    test_caio_decide_scenario_london_requires_higher_confidence()
    test_caio_decide_scenario_london_activates_above_its_own_threshold()
    test_caio_decide_scenario_london_threshold_never_lowers_general_threshold()
    test_caio_decide_scenario_non_london_session_unaffected_by_london_threshold()
    test_caio_decide_scenario_never_calls_real_execution()
    test_dynamic_position_manager_closes_on_invalidation()
    test_dynamic_position_manager_closes_on_target_reached()
    test_dynamic_position_manager_closes_on_expiry()
    test_dynamic_position_manager_degrades_on_smart_money_reversal()
    test_dynamic_position_manager_recovers_from_degraded()
    test_dynamic_position_manager_detects_scalp_opportunity()
    test_dynamic_position_manager_noop_on_non_active_status()
    test_dynamic_position_manager_never_calls_real_execution()
    test_run_scenario_replay_writes_only_to_replay_log_never_real_execution()
    test_scenario_engine_step_throttles_dpm_reevaluation_within_interval()
    test_scenario_engine_step_reevaluates_dpm_after_interval_elapsed()
    test_run_scenario_replay_resets_dpm_throttle()
    test_run_scenario_replay_handles_insufficient_history_gracefully()
    test_load_scenario_weights_falls_back_to_default_when_file_absent()
    test_load_scenario_weights_returns_learned_weights_when_valid()
    test_load_scenario_weights_falls_back_when_keys_incomplete()
    test_generate_scenario_uses_injected_weights_via_scenario_engine_step()
    test_run_scenario_learning_writes_recommendation_without_touching_default_weights()
    test_run_scenario_learning_logs_real_adaptation_when_weights_change()
    test_scenario_engine_step_returns_none_without_candles()
    test_auto_trade_step_wires_scenario_engine_observation_without_crashing()
    test_execute_scenario_anchor_opens_real_position_when_all_gates_pass()
    test_execute_scenario_anchor_skipped_when_execution_flag_disabled()
    test_execute_scenario_anchor_transient_skip_when_trading_not_enabled()
    test_execute_scenario_anchor_transient_skip_when_protection_blocks()
    test_execute_scenario_anchor_permanent_fail_when_symbol_missing()
    test_execute_scenario_anchor_marks_failed_when_order_rejected()
    test_execute_scenario_anchor_never_reattempts_once_resolved()
    test_execute_scenario_anchor_noop_when_scenario_not_active()
    test_close_scenario_anchor_if_needed_closes_real_position_on_terminal_status()
    test_close_scenario_anchor_if_needed_noop_when_not_open()
    test_close_scenario_anchor_if_needed_noop_while_scenario_still_active()
    test_close_scenario_anchor_if_needed_marks_closed_when_position_already_gone()
    test_close_scenario_anchor_if_needed_retries_when_close_fails()
    test_execute_scenario_scalp_opens_real_position_when_all_gates_pass()
    test_execute_scenario_scalp_respects_cooldown()
    test_execute_scenario_scalp_opens_again_after_cooldown_elapsed()
    test_execute_scenario_scalp_respects_max_count_cap()
    test_execute_scenario_scalp_transient_skip_when_gates_block()
    test_execute_scenario_scalp_noop_when_conditions_not_all_met()
    test_execute_scenario_anchor_transient_skip_when_portfolio_brain_blocks()
    test_execute_scenario_scalp_transient_skip_when_portfolio_brain_blocks()
    test_run_auto_backtest_if_due_skips_when_recently_run()
    test_run_auto_backtest_if_due_noop_when_disabled()
    test_run_auto_backtest_if_due_writes_result_after_replay()
    print("ALL TESTS PASSED")
