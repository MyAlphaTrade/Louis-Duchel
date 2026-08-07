"""Tests pour le chantier "un edge tres solide" (06/08/2026, demande
explicite de Louis) :
1. Confirmation walk-forward de calibrate_scenario_thresholds() (Bloc 1
   scenario + Bloc 3 Portfolio Brain) -- un ajustement qui ne tient que sur
   l'ensemble complet mais disparait des qu'on le teste independamment sur
   une portion ancienne ET une portion recente ne doit jamais s'appliquer.
2. calibrate_decision_engine_weights()/load_decision_engine_weights() --
   pipeline complet de bout en bout (decision_registry.jsonl + resolution
   scenario reelle -> poids appris -> lu au prochain cycle)."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae

NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)


def _reset_files():
    for name in (
        "scenario_log.jsonl", "scenario_replay_log.jsonl", "decision_registry.jsonl",
        "portfolio_floating_loss_daily.json", "calendar_data.json",
        "decision_engine_learned_weights.json",
    ):
        (ae.DATA_DIR / name).unlink(missing_ok=True)
    ae.write_json("params.json", {})


def _scenario_entry(scenario_id: str, confidence: float, win: bool, created_at: datetime) -> dict:
    return {
        "scenario_id": scenario_id,
        "symbol_key": "XAUUSD",
        "direction": "BUY",
        "scenario_confidence_at_entry": confidence,
        "scenario_health": confidence,
        "health_curve": [confidence],
        "outcome": "WIN_SIMULATED" if win else "LOSS_SIMULATED",
        "outcome_profit": 2.0 if win else -2.0,
        "market_context": {"session": "ny", "trend": "UPTREND"},
        "created_at": created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Bloc 1 (seuils Scenario Engine) -- confirmation walk-forward
# ---------------------------------------------------------------------------

def test_walk_forward_rejects_signal_that_only_exists_pooled():
    """Bande 70-80 : 22 echantillons au total (tous gagnants) -- juste assez
    pour depasser min_samples=20 sur l'ENSEMBLE complet et proposer un
    ajustement, mais bien EN-DESSOUS de 20 une fois coupee en calibration
    (~70%) et hold-out (~30%) -- le signal ne doit survivre dans AUCUNE des
    deux moities, donc etre rejete."""
    _reset_files()
    base = NOW - timedelta(days=30)
    for i in range(22):
        ae.append_jsonl(
            "scenario_log.jsonl",
            _scenario_entry(f"HOT_{i}", 75.0, True, base + timedelta(hours=i)),
        )
    # Bande de reference (baseline ~50%) -- assez d'echantillons pour rester
    # presente dans les deux moities et fournir un vrai point de comparaison.
    for i in range(40):
        ae.append_jsonl(
            "scenario_log.jsonl",
            _scenario_entry(f"BASE_{i}", 55.0, i % 2 == 0, base + timedelta(hours=i, minutes=30)),
        )
    params = {**ae.merge_params(), "scenario_caio_min_confidence": 60.0}
    ae.calibrate_scenario_thresholds(params, min_samples=20, now=NOW)
    saved = ae.read_json("params.json", {})
    assert saved.get("scenario_caio_min_confidence") is None, (
        "Un signal qui ne survit dans AUCUNE moitie independante ne doit jamais etre applique -- "
        f"obtenu {saved.get('scenario_caio_min_confidence')}."
    )
    print("test_walk_forward_rejects_signal_that_only_exists_pooled OK")


def test_walk_forward_confirms_signal_present_in_both_halves():
    """Bande 70-80 : 80 echantillons (tous gagnants), repartis UNIFORMEMENT
    dans le temps (entrelaces avec la bande de reference) -- assez pour
    rester au-dessus de min_samples=20 aussi bien en calibration qu'en
    hold-out. Le signal doit survivre et s'appliquer."""
    _reset_files()
    base = NOW - timedelta(days=60)
    for i in range(120):
        if i % 3 != 0:  # 2/3 des cycles -- bande chaude, toujours gagnante
            entry = _scenario_entry(f"HOT_{i}", 75.0, True, base + timedelta(hours=i))
        else:  # 1/3 des cycles -- bande de reference, 50/50
            entry = _scenario_entry(f"BASE_{i}", 55.0, i % 6 == 0, base + timedelta(hours=i))
        ae.append_jsonl("scenario_log.jsonl", entry)
    params = {**ae.merge_params(), "scenario_caio_min_confidence": 60.0}
    ae.calibrate_scenario_thresholds(params, min_samples=20, now=NOW)
    saved = ae.read_json("params.json", {})
    assert saved.get("scenario_caio_min_confidence") == 65.0, (
        f"Un signal present independamment dans les deux moities doit s'appliquer (65.0 attendu), "
        f"obtenu {saved.get('scenario_caio_min_confidence')}."
    )
    print("test_walk_forward_confirms_signal_present_in_both_halves OK")


def test_walk_forward_skipped_when_not_enough_data_for_a_clean_split():
    """Sous 2x min_samples au total -- comportement HISTORIQUE inchange
    (single-pass, pas de gate walk-forward qui bloquerait toute calibration
    naissante faute de donnees)."""
    _reset_files()
    base = NOW - timedelta(days=10)
    for i in range(22):  # 22 samples -- suffisant pour la bande seule (>=20)
        entry = _scenario_entry(f"HOT_{i}", 75.0, True, base + timedelta(hours=i))
        ae.append_jsonl("scenario_log.jsonl", entry)
    for i in range(14):  # total 36 < 2*min_samples(20)=40 -- pas assez pour un decoupage propre
        entry = _scenario_entry(f"BASE_{i}", 55.0, i % 2 == 0, base + timedelta(hours=i, minutes=30))
        ae.append_jsonl("scenario_log.jsonl", entry)
    params = {**ae.merge_params(), "scenario_caio_min_confidence": 60.0}
    ae.calibrate_scenario_thresholds(params, min_samples=20, now=NOW)
    saved = ae.read_json("params.json", {})
    assert saved.get("scenario_caio_min_confidence") == 65.0, (
        "Sous le seuil de decoupage propre, le comportement historique (single-pass) doit s'appliquer."
    )
    print("test_walk_forward_skipped_when_not_enough_data_for_a_clean_split OK")


# ---------------------------------------------------------------------------
# Bloc 3 (Portfolio Brain) -- meme confirmation walk-forward
# ---------------------------------------------------------------------------

def test_walk_forward_block3_rejects_thin_pooled_only_signal():
    _reset_files()
    worst_by_day: dict[str, float] = {}
    daily_pnl_by_day: dict[str, float] = {}
    base_day = datetime(2026, 6, 1)
    # 22 journees "profondes" (bande 2-5) toutes mauvaises -- juste assez
    # pour le seuil global, pas assez une fois coupe en deux.
    for i in range(22):
        day = (base_day + timedelta(days=i)).strftime("%Y-%m-%d")
        worst_by_day[day] = -3.0
        daily_pnl_by_day[day] = -10.0
    for i in range(30):
        day = (base_day + timedelta(days=22 + i)).strftime("%Y-%m-%d")
        worst_by_day[day] = -1.0
        daily_pnl_by_day[day] = 5.0 if i % 2 == 0 else -1.0
    ae.write_json("portfolio_floating_loss_daily.json", worst_by_day)
    ae.write_json("calendar_data.json", {"daily": {d: {"profit": p} for d, p in daily_pnl_by_day.items()}})
    params = {**ae.merge_params(), "portfolio_floating_loss_warn_pct": 2.0, "portfolio_floating_loss_critical_pct": 5.0}
    ae.calibrate_scenario_thresholds(params, min_samples=20, now=NOW)
    saved = ae.read_json("params.json", {})
    assert saved.get("portfolio_floating_loss_warn_pct") is None, (
        f"Signal Portfolio Brain non confirme sur les deux moities -- doit rester inchange, "
        f"obtenu {saved.get('portfolio_floating_loss_warn_pct')}."
    )
    print("test_walk_forward_block3_rejects_thin_pooled_only_signal OK")


# ---------------------------------------------------------------------------
# calibrate_decision_engine_weights() / load_decision_engine_weights() --
# pipeline complet
# ---------------------------------------------------------------------------

def test_calibrate_decision_engine_weights_end_to_end():
    _reset_files()
    base = NOW - timedelta(days=5)
    for i in range(20):
        scenario_id = f"S{i}"
        actual = "BUY" if i % 2 == 0 else "SELL"
        ae.append_jsonl(
            "scenario_log.jsonl",
            _scenario_entry(scenario_id, 75.0, True, base + timedelta(hours=i))
            | {"direction": actual},  # WIN_SIMULATED -> valide bien `actual`
        )
        ae.append_jsonl("decision_registry.jsonl", {
            "time": (base + timedelta(hours=i)).isoformat(),
            "symbol": "XAUUSD",
            "agents": {
                "good_agent": {"action": actual, "confidence": 70.0},
                "bad_agent": {"action": "SELL" if actual == "BUY" else "BUY", "confidence": 70.0},
            },
            "final": actual, "confidence": 70.0, "high_conviction": False,
            "scenario_id": scenario_id, "executed": False,
        })
    assert ae.load_decision_engine_weights() is None  # rien calcule encore -- poids egaux
    ae.calibrate_decision_engine_weights(min_samples=20, now=NOW)
    weights = ae.load_decision_engine_weights()
    assert weights is not None
    assert weights["good_agent"] > 1.0
    assert weights["bad_agent"] < 1.0
    print("test_calibrate_decision_engine_weights_end_to_end OK")


def test_calibrate_decision_engine_weights_below_min_samples_writes_nothing():
    _reset_files()
    ae.append_jsonl("scenario_log.jsonl", _scenario_entry("S1", 75.0, True, NOW))
    ae.append_jsonl("decision_registry.jsonl", {
        "time": NOW.isoformat(), "symbol": "XAUUSD",
        "agents": {"a": {"action": "BUY", "confidence": 70.0}},
        "final": "BUY", "confidence": 70.0, "high_conviction": False,
        "scenario_id": "S1", "executed": False,
    })
    ae.calibrate_decision_engine_weights(min_samples=20, now=NOW)
    assert not (ae.DATA_DIR / "decision_engine_learned_weights.json").exists()
    assert ae.load_decision_engine_weights() is None
    print("test_calibrate_decision_engine_weights_below_min_samples_writes_nothing OK")


def test_load_decision_engine_weights_missing_file_returns_none():
    _reset_files()
    assert ae.load_decision_engine_weights() is None
    print("test_load_decision_engine_weights_missing_file_returns_none OK")


if __name__ == "__main__":
    test_walk_forward_rejects_signal_that_only_exists_pooled()
    test_walk_forward_confirms_signal_present_in_both_halves()
    test_walk_forward_skipped_when_not_enough_data_for_a_clean_split()
    test_walk_forward_block3_rejects_thin_pooled_only_signal()
    test_calibrate_decision_engine_weights_end_to_end()
    test_calibrate_decision_engine_weights_below_min_samples_writes_nothing()
    test_load_decision_engine_weights_missing_file_returns_none()
    print("ALL TESTS PASSED")
