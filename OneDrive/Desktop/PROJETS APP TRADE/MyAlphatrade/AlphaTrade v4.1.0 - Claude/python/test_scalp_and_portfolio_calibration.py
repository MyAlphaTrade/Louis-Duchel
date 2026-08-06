"""Tests pour tasks #173/#174 (06/08/2026, demande explicite de Louis :
"construire le suivi maintenant" plutot que de laisser le calibrage scalp/
Portfolio Brain comme un module mort). Couvre : le suivi (ticket reel de
scalp correle au P&L reel ; pire perte flottante journaliere correlee au
P&L reel de fin de journee) et la calibration bornee/reversible qui en
decoule -- meme discipline que test_scenario_wiring.py/test_scenario_generator.py."""
import json
import os
import tempfile
from datetime import datetime, timezone

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae
from scenario_generator import scalp_learning_stats, scalp_threshold_adjustments
from portfolio_brain import floating_loss_learning_stats, floating_loss_threshold_adjustments

NOW = datetime(2026, 8, 6, 10, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# scalp_learning_stats() / scalp_threshold_adjustments() (task #173) -- purs
# ---------------------------------------------------------------------------

def _scalp_entry(scalp_index, cooldown, profit):
    return {"scalp_index": scalp_index, "cooldown_actual_sec": cooldown, "profit": profit}


def test_scalp_learning_stats_ignores_unresolved_and_small_samples():
    entries = [_scalp_entry(1, 40, 5.0) for _ in range(5)] + [{"scalp_index": 2, "cooldown_actual_sec": 40, "profit": None}]
    stats = scalp_learning_stats(entries, min_samples=10)
    assert stats["n_resolved"] == 5  # l'entree sans profit (position pas encore fermee) est exclue
    assert stats["by_scalp_index"] == {}  # 5 < min_samples=10 -- aucune case ne doit apparaitre
    print("test_scalp_learning_stats_ignores_unresolved_and_small_samples OK")


def test_scalp_learning_stats_computes_winrate_per_index_and_cooldown_band():
    entries = (
        [_scalp_entry(1, 20.0, 3.0) for _ in range(9)] + [_scalp_entry(1, 20.0, -2.0)]  # index 1: 9/10 wins
        + [_scalp_entry(3, 20.0, -4.0) for _ in range(10)]  # index 3: 0/10 wins -- rang perdant
    )
    stats = scalp_learning_stats(entries, min_samples=10)
    assert stats["n_resolved"] == 20
    assert stats["by_scalp_index"]["1"] == {"samples": 10, "winrate": 90.0, "avg_profit": 2.5}
    assert stats["by_scalp_index"]["3"] == {"samples": 10, "winrate": 0.0, "avg_profit": -4.0}
    assert stats["by_cooldown_band"]["0-30"]["samples"] == 20
    print("test_scalp_learning_stats_computes_winrate_per_index_and_cooldown_band OK")


def test_scalp_threshold_adjustments_lowers_max_count_when_late_index_loses():
    stats = {
        "overall_winrate": 60.0,
        "by_scalp_index": {
            "1": {"samples": 15, "winrate": 70.0, "avg_profit": 2.0},
            "2": {"samples": 12, "winrate": 65.0, "avg_profit": 1.0},
            "3": {"samples": 10, "winrate": 20.0, "avg_profit": -3.0},  # nettement perdant -- edge 40 >= min_edge 10
        },
        "by_cooldown_band": {},
    }
    current = {"scenario_scalp_max_count": 3, "scenario_scalp_cooldown_sec": 45.0}
    adjustments = scalp_threshold_adjustments(stats, current)
    assert adjustments["scenario_scalp_max_count"] == 2  # s'arrete juste avant le rang 3 (perdant)
    assert "scenario_scalp_cooldown_sec" not in adjustments  # aucune donnee cooldown -- ne rien toucher
    print("test_scalp_threshold_adjustments_lowers_max_count_when_late_index_loses OK")


def test_scalp_threshold_adjustments_bounded_step_never_jumps():
    stats = {
        "overall_winrate": 60.0,
        # Rang 2 nettement perdant -- la cible ideale (max_count=1) est tres
        # loin du reglage actuel (10), mais le pas ne doit jamais depasser 1.
        "by_scalp_index": {"2": {"samples": 15, "winrate": 5.0, "avg_profit": -5.0}},
        "by_cooldown_band": {},
    }
    current = {"scenario_scalp_max_count": 10, "scenario_scalp_cooldown_sec": 45.0}
    adjustments = scalp_threshold_adjustments(stats, current, max_count_step=1)
    assert adjustments["scenario_scalp_max_count"] == 9  # jamais plus de +/-1 par cycle, meme si la cible ideale est loin
    print("test_scalp_threshold_adjustments_bounded_step_never_jumps OK")


def test_scalp_threshold_adjustments_moves_cooldown_toward_safe_band():
    stats = {
        "overall_winrate": 60.0,
        "by_scalp_index": {},
        "by_cooldown_band": {
            "0-30": {"samples": 12, "winrate": 20.0, "avg_profit": -2.0},  # cooldown court -- nettement perdant
            "30-60": {"samples": 15, "winrate": 65.0, "avg_profit": 1.5},  # cooldown moyen -- ne chute pas sous la moyenne
        },
    }
    current = {"scenario_scalp_max_count": 3, "scenario_scalp_cooldown_sec": 45.0}
    adjustments = scalp_threshold_adjustments(stats, current, max_cooldown_step=15.0)
    # target = plancher de "30-60" = 30.0, current = 45.0 -> pas de -15 (borne atteinte, deja au max)
    assert adjustments["scenario_scalp_cooldown_sec"] == 30.0
    print("test_scalp_threshold_adjustments_moves_cooldown_toward_safe_band OK")


def test_scalp_threshold_adjustments_never_touches_lot_ratio():
    """scenario_scalp_lot_ratio reste hors calibration automatique -- meme
    avec un signal fort ailleurs, jamais dans les cles retournees."""
    stats = {
        "overall_winrate": 60.0,
        "by_scalp_index": {"3": {"samples": 20, "winrate": 5.0, "avg_profit": -5.0}},
        "by_cooldown_band": {"0-30": {"samples": 20, "winrate": 10.0, "avg_profit": -3.0}},
    }
    current = {"scenario_scalp_max_count": 3, "scenario_scalp_cooldown_sec": 45.0}
    adjustments = scalp_threshold_adjustments(stats, current)
    assert "scenario_scalp_lot_ratio" not in adjustments
    print("test_scalp_threshold_adjustments_never_touches_lot_ratio OK")


def test_scalp_threshold_adjustments_no_signal_no_change():
    stats = {
        "overall_winrate": 55.0,
        "by_scalp_index": {"1": {"samples": 20, "winrate": 57.0, "avg_profit": 0.5}},  # proche de la moyenne
        "by_cooldown_band": {},
    }
    current = {"scenario_scalp_max_count": 3, "scenario_scalp_cooldown_sec": 45.0}
    adjustments = scalp_threshold_adjustments(stats, current)
    assert adjustments == {}
    print("test_scalp_threshold_adjustments_no_signal_no_change OK")


# ---------------------------------------------------------------------------
# floating_loss_learning_stats() / floating_loss_threshold_adjustments()
# (task #174) -- purs
# ---------------------------------------------------------------------------

def test_floating_loss_learning_stats_only_uses_days_present_in_both_dicts():
    worst_by_day = {"2026-08-01": -1.0, "2026-08-02": -3.0, "2026-08-03": -6.0}
    daily_pnl_by_day = {"2026-08-01": 10.0, "2026-08-02": -5.0}  # 08-03 absent -- session en cours, pas resolue
    stats = floating_loss_learning_stats(worst_by_day, daily_pnl_by_day, min_samples=1)
    assert stats["n_days"] == 2
    print("test_floating_loss_learning_stats_only_uses_days_present_in_both_dicts OK")


def test_floating_loss_learning_stats_computes_bad_day_rate_per_band():
    worst_by_day = {}
    daily_pnl_by_day = {}
    for i in range(10):
        day = f"2026-07-{i+1:02d}"
        worst_by_day[day] = -1.0  # bande "0-2", peu profonde
        daily_pnl_by_day[day] = 10.0 if i < 8 else -5.0  # 2/10 mauvaises journees
    for i in range(10):
        day = f"2026-06-{i+1:02d}"
        worst_by_day[day] = -7.0  # bande "5-10", profonde
        daily_pnl_by_day[day] = -5.0 if i < 8 else 10.0  # 8/10 mauvaises journees
    stats = floating_loss_learning_stats(worst_by_day, daily_pnl_by_day, min_samples=10)
    assert stats["n_days"] == 20
    assert stats["by_depth_band"]["0-2"]["bad_day_rate"] == 20.0
    assert stats["by_depth_band"]["5-10"]["bad_day_rate"] == 80.0
    print("test_floating_loss_learning_stats_computes_bad_day_rate_per_band OK")


def test_floating_loss_threshold_adjustments_warn_pct_only_observational():
    """WARN seul ne bloque rien (voir portfolio_risk_assessment()) -- signal
    purement observationnel, on peut donc calibrer sans reserve causale."""
    stats = {
        "overall_bad_day_rate": 20.0,
        "by_depth_band": {
            "0-2": {"samples": 15, "bad_day_rate": 25.0, "avg_day_profit": 5.0},  # proche moyenne -- pas de signal
            "2-5": {"samples": 15, "bad_day_rate": 80.0, "avg_day_profit": -30.0},  # nettement pire -- edge 60 >= 20
        },
    }
    current = {"portfolio_floating_loss_warn_pct": 1.0, "portfolio_floating_loss_critical_pct": 5.0}
    adjustments = floating_loss_threshold_adjustments(stats, current)
    assert adjustments["portfolio_floating_loss_warn_pct"] == 1.5  # avance vers le plancher de la bande "2-5" (2.0), +0.5 max
    print("test_floating_loss_threshold_adjustments_warn_pct_only_observational OK")


def test_floating_loss_threshold_adjustments_critical_never_crosses_warn():
    """Garde-fou explicite : critical_pct doit toujours rester strictement
    au-dela du NOUVEAU warn_pct, jamais les deux qui se croisent."""
    stats = {
        "overall_bad_day_rate": 10.0,
        "by_depth_band": {
            "2-5": {"samples": 15, "bad_day_rate": 90.0, "avg_day_profit": -30.0},  # edge tres fort -- preuve x2 aussi
        },
    }
    current = {"portfolio_floating_loss_warn_pct": 2.0, "portfolio_floating_loss_critical_pct": 2.4}  # deja tres proches
    adjustments = floating_loss_threshold_adjustments(stats, current, max_warn_step=0.5, max_critical_step=0.5)
    new_warn = adjustments.get("portfolio_floating_loss_warn_pct", current["portfolio_floating_loss_warn_pct"])
    if "portfolio_floating_loss_critical_pct" in adjustments:
        assert adjustments["portfolio_floating_loss_critical_pct"] > new_warn
    print("test_floating_loss_threshold_adjustments_critical_never_crosses_warn OK")


def test_floating_loss_threshold_adjustments_no_signal_no_change():
    stats = {
        "overall_bad_day_rate": 30.0,
        "by_depth_band": {"2-5": {"samples": 15, "bad_day_rate": 32.0, "avg_day_profit": -2.0}},  # proche moyenne
    }
    current = {"portfolio_floating_loss_warn_pct": 2.0, "portfolio_floating_loss_critical_pct": 5.0}
    adjustments = floating_loss_threshold_adjustments(stats, current)
    assert adjustments == {}
    print("test_floating_loss_threshold_adjustments_no_signal_no_change OK")


# ---------------------------------------------------------------------------
# Cote alphatrade_engine.py -- suivi (tickets/fichiers) + jointure DB
# ---------------------------------------------------------------------------

def _fake_position(ticket, symbol_key="XAUUSD", direction="BUY", comment="AlphaTrade 5.1.1 SCENARIO_SCALP", open_timestamp=1000):
    return {
        "ticket": ticket, "symbol_key": symbol_key, "symbol": "XAUUSD", "direction": direction,
        "origin": "BOT", "origin_name": "AlphaTrade", "origin_type": "INTERNAL_BOT", "origin_magic": 0,
        "lot": 0.01, "open_price": 4086.5, "current_price": 4086.5, "profit": 0.0,
        "open_timestamp": open_timestamp, "open_time": "2026-08-06T10:00:00", "comment": comment,
    }


def test_find_scenario_anchor_position_never_matches_a_scalp_comment():
    """Correctif du 06/08/2026 (trouve en construisant ce chantier) : "SCENARIO"
    est une sous-chaine de "SCENARIO_SCALP" -- un scalp ne doit jamais etre
    pris pour l'ancrage, meme s'il est le plus recent des deux."""
    from scenario import make_scenario, activate_scenario
    scenario = make_scenario(
        "XAUUSD_X", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0},
        invalidation_price=4080.0, targets=[{"price": 4092.0, "label": "t1"}],
        anchor_plan={"entry": 4086.5}, now=NOW,
    )
    scenario.transition("VALIDATED", "t", now=NOW)
    activate_scenario(scenario, now=NOW)
    original_live_positions = ae.live_positions
    # Seul un SCALP existe (comment se terminant par SCENARIO_SCALP) -- pas d'ancrage reel.
    ae.live_positions = lambda symbol_names, params=None: [
        _fake_position(999, comment="AlphaTrade 5.1.1 SCENARIO_SCALP", open_timestamp=9999),
    ]
    try:
        position = ae._find_scenario_anchor_position(scenario, {"XAUUSD": "XAUUSD"}, {})
        assert position is None  # ne doit surtout pas retourner le scalp
    finally:
        ae.live_positions = original_live_positions
    print("test_find_scenario_anchor_position_never_matches_a_scalp_comment OK")


def test_record_scalp_open_event_writes_ticket_and_cooldown():
    from scenario import make_scenario, activate_scenario
    scenario = make_scenario(
        "XAUUSD_Y", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0},
        invalidation_price=4080.0, targets=[{"price": 4092.0, "label": "t1"}],
        anchor_plan={"entry": 4086.5}, now=NOW,
    )
    scenario.transition("VALIDATED", "t", now=NOW)
    activate_scenario(scenario, now=NOW)
    scenario.executed_scalp_count = 2
    (ae.DATA_DIR / "scenario_scalp_events.jsonl").unlink(missing_ok=True)
    original_live_positions = ae.live_positions
    ae.live_positions = lambda symbol_names, params=None: [
        _fake_position(555100, comment="AlphaTrade 5.1.1 SCENARIO_SCALP", open_timestamp=5000),
    ]
    try:
        previous_at = (NOW.replace(minute=0)).isoformat()
        ae._record_scalp_open_event(scenario, {"XAUUSD": "XAUUSD"}, {}, previous_at, NOW)
    finally:
        ae.live_positions = original_live_positions
    lines = (ae.DATA_DIR / "scenario_scalp_events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["ticket"] == 555100
    assert event["scalp_index"] == 2
    assert event["cooldown_actual_sec"] == 1800.0  # NOW moins previous_at (minute remise a 0) = 30 min
    print("test_record_scalp_open_event_writes_ticket_and_cooldown OK")


def test_record_scalp_open_event_skips_already_known_tickets():
    from scenario import make_scenario, activate_scenario
    scenario = make_scenario(
        "XAUUSD_Z", "XAUUSD", "BUY", {"low": 4085.0, "high": 4088.0},
        invalidation_price=4080.0, targets=[{"price": 4092.0, "label": "t1"}],
        anchor_plan={"entry": 4086.5}, now=NOW,
    )
    scenario.transition("VALIDATED", "t", now=NOW)
    activate_scenario(scenario, now=NOW)
    (ae.DATA_DIR / "scenario_scalp_events.jsonl").unlink(missing_ok=True)
    ae.append_jsonl("scenario_scalp_events.jsonl", {
        "ticket": 555200, "scenario_id": "old", "scalp_index": 1, "cooldown_actual_sec": None, "opened_at": NOW.isoformat(),
    })
    original_live_positions = ae.live_positions
    # Le seul candidat vivant est DEJA connu -- ne doit rien re-ecrire.
    ae.live_positions = lambda symbol_names, params=None: [
        _fake_position(555200, comment="AlphaTrade 5.1.1 SCENARIO_SCALP", open_timestamp=5000),
    ]
    try:
        ae._record_scalp_open_event(scenario, {"XAUUSD": "XAUUSD"}, {}, None, NOW)
    finally:
        ae.live_positions = original_live_positions
    lines = (ae.DATA_DIR / "scenario_scalp_events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1  # toujours une seule ligne -- rien ajoute
    print("test_record_scalp_open_event_skips_already_known_tickets OK")


def test_scalp_correlated_entries_joins_jsonl_with_real_trades_db():
    (ae.DATA_DIR / "scenario_scalp_events.jsonl").unlink(missing_ok=True)
    ae.append_jsonl("scenario_scalp_events.jsonl", {
        "ticket": 777301, "scenario_id": "s1", "scalp_index": 1, "cooldown_actual_sec": 40.0, "opened_at": NOW.isoformat(),
    })
    ae.append_jsonl("scenario_scalp_events.jsonl", {
        "ticket": 777302, "scenario_id": "s1", "scalp_index": 2, "cooldown_actual_sec": 90.0, "opened_at": NOW.isoformat(),
    })
    ae.append_jsonl("scenario_scalp_events.jsonl", {
        "ticket": 777303, "scenario_id": "s1", "scalp_index": 3, "cooldown_actual_sec": 20.0, "opened_at": NOW.isoformat(),
    })  # jamais fermee -- ne doit pas apparaitre dans le resultat correle
    conn = ae.db_conn()
    try:
        conn.execute(
            "INSERT INTO trades (id, ticket, symbol, direction, lot, profit, status) VALUES (?,?,?,?,?,?,?)",
            ("t1", 777301, "XAUUSD", "BUY", 0.01, 3.5, "CLOSED"),
        )
        conn.execute(
            "INSERT INTO trades (id, ticket, symbol, direction, lot, profit, status) VALUES (?,?,?,?,?,?,?)",
            ("t2", 777302, "XAUUSD", "BUY", 0.01, -1.2, "CLOSED"),
        )
        conn.commit()
        correlated = ae._scalp_correlated_entries(conn)
    finally:
        conn.close()
    assert len(correlated) == 2  # le ticket 777303 (jamais ferme) est absent
    by_index = {e["scalp_index"]: e["profit"] for e in correlated}
    assert by_index[1] == 3.5
    assert by_index[2] == -1.2
    print("test_scalp_correlated_entries_joins_jsonl_with_real_trades_db OK")


def test_record_portfolio_floating_loss_keeps_worst_value_per_day():
    (ae.DATA_DIR / "portfolio_floating_loss_daily.json").unlink(missing_ok=True)
    ae._record_portfolio_floating_loss(-1.5, NOW)
    ae._record_portfolio_floating_loss(-3.2, NOW)  # pire -- doit remplacer
    ae._record_portfolio_floating_loss(-0.5, NOW)  # moins pire -- ne doit PAS remplacer
    data = ae.read_json("portfolio_floating_loss_daily.json", {})
    assert data["2026-08-06"] == -3.2
    print("test_record_portfolio_floating_loss_keeps_worst_value_per_day OK")


# ---------------------------------------------------------------------------
# calibrate_scenario_thresholds() -- les 3 blocs restent independants
# ---------------------------------------------------------------------------

def test_calibrate_scenario_thresholds_scalp_block_independent_of_scenario_block():
    """Le bloc scalp doit pouvoir s'appliquer meme quand le bloc scenario
    (bloc 1, min_samples=20) n'a pas assez de scenarios resolus -- 3 gates
    independants, pas un seul gate global (task #173/#174)."""
    (ae.DATA_DIR / "scenario_log.jsonl").unlink(missing_ok=True)
    (ae.DATA_DIR / "scenario_replay_log.jsonl").unlink(missing_ok=True)  # bloc 1: 0 scenario resolu
    (ae.DATA_DIR / "scenario_scalp_events.jsonl").unlink(missing_ok=True)
    (ae.DATA_DIR / "portfolio_floating_loss_daily.json").unlink(missing_ok=True)
    ae.write_json("params.json", {})

    conn = ae.db_conn()
    try:
        for i in range(10):
            ticket = 888000 + i
            ae.append_jsonl("scenario_scalp_events.jsonl", {
                "ticket": ticket, "scenario_id": "s", "scalp_index": 3, "cooldown_actual_sec": 40.0,
                "opened_at": NOW.isoformat(),
            })
            conn.execute(
                "INSERT INTO trades (id, ticket, symbol, direction, lot, profit, status) VALUES (?,?,?,?,?,?,?)",
                (f"scalp{i}", ticket, "XAUUSD", "BUY", 0.01, -4.0, "CLOSED"),
            )
        # index 1 largement gagnant, sert de reference haute pour que l'index 3 ressorte comme perdant
        for i in range(10):
            ticket = 889000 + i
            ae.append_jsonl("scenario_scalp_events.jsonl", {
                "ticket": ticket, "scenario_id": "s", "scalp_index": 1, "cooldown_actual_sec": 40.0,
                "opened_at": NOW.isoformat(),
            })
            conn.execute(
                "INSERT INTO trades (id, ticket, symbol, direction, lot, profit, status) VALUES (?,?,?,?,?,?,?)",
                (f"scalp1_{i}", ticket, "XAUUSD", "BUY", 0.01, 5.0, "CLOSED"),
            )
        conn.commit()
    finally:
        conn.close()

    params = {**ae.merge_params(), "scenario_scalp_max_count": 3, "scenario_scalp_learning_min_samples": 10}
    ae.calibrate_scenario_thresholds(params, min_samples=20, now=NOW)
    saved = ae.read_json("params.json", {})
    assert saved.get("scenario_scalp_max_count") == 2  # le bloc scalp a bien tourne malgre 0 scenario resolu
    print("test_calibrate_scenario_thresholds_scalp_block_independent_of_scenario_block OK")


if __name__ == "__main__":
    test_scalp_learning_stats_ignores_unresolved_and_small_samples()
    test_scalp_learning_stats_computes_winrate_per_index_and_cooldown_band()
    test_scalp_threshold_adjustments_lowers_max_count_when_late_index_loses()
    test_scalp_threshold_adjustments_bounded_step_never_jumps()
    test_scalp_threshold_adjustments_moves_cooldown_toward_safe_band()
    test_scalp_threshold_adjustments_never_touches_lot_ratio()
    test_scalp_threshold_adjustments_no_signal_no_change()
    test_floating_loss_learning_stats_only_uses_days_present_in_both_dicts()
    test_floating_loss_learning_stats_computes_bad_day_rate_per_band()
    test_floating_loss_threshold_adjustments_warn_pct_only_observational()
    test_floating_loss_threshold_adjustments_critical_never_crosses_warn()
    test_floating_loss_threshold_adjustments_no_signal_no_change()
    test_find_scenario_anchor_position_never_matches_a_scalp_comment()
    test_record_scalp_open_event_writes_ticket_and_cooldown()
    test_record_scalp_open_event_skips_already_known_tickets()
    test_scalp_correlated_entries_joins_jsonl_with_real_trades_db()
    test_record_portfolio_floating_loss_keeps_worst_value_per_day()
    test_calibrate_scenario_thresholds_scalp_block_independent_of_scenario_block()
    print("ALL TESTS PASSED")
