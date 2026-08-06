"""Tests pour la "phase naissance du trade" (v5.1.1, 06/08/2026) -- demande
explicite de Louis suite a l'audit du ticket 9748487751 : une position nee
1.7 seconde plus tot, montee a +1.80$ de pic, a ete fermee par
PROFIT_TRAILING a -2.20$ (decision), executee a -4.40$ (latence MT5).
Pendant les premieres `trade_birth_phase_sec` (defaut 5s) apres l'ouverture,
aucune sortie basee sur un mouvement de prix instantane (PROFIT_TRAILING,
MOMENTUM_EXIT) n'est autorisee -- seuls les filets de securite independants
du temps restent actifs (MAX_POSITION_LOSS ici ; le stop broker et le
ratchet sont geres ailleurs, hors de position_exit_reason())."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


def _pos_params(**overrides):
    p = {
        "position_review_sec": 120,
        "confidence_min": 62,
        "signal_reversal_margin": 7,
        "rebond_enabled": False,
        "max_position_loss": 20.0,
        "max_hold_sec": 3600,
        "min_positive_exit": 0.50,
        "profit_trailing_giveback": 0.50,
        "momentum_exit_score": 55,
        "take_profit_enabled": False,
        "profit_target": 5.0,
        "emergency_loss_limit": 15.0,
        "trade_birth_phase_sec": 5.0,
    }
    p.update(overrides)
    return p


def _position(direction="BUY", profit=0.0):
    return {"direction": direction, "profit": profit}


def test_profit_trailing_suppressed_during_birth_phase():
    """Reproduit exactement le ticket 9748487751 : pic 1.80$, giveback 0.50$
    -> profit courant 1.30$ ou moins declenche PROFIT_TRAILING normalement,
    mais PAS pendant la phase naissance (age=1.7s < 5s)."""
    reason = ae.position_exit_reason(
        _position(profit=-2.20), _pos_params(), {}, "", "",
        peak=1.80, age=1.7,
    )
    assert reason != "PROFIT_TRAILING", (
        f"PROFIT_TRAILING ne doit jamais se declencher pendant la phase naissance (age=1.7s), obtenu {reason!r}."
    )
    print("test_profit_trailing_suppressed_during_birth_phase OK")


def test_profit_trailing_still_works_after_birth_phase():
    """Le meme scenario, mais apres la phase naissance (age=10s >= 5s) --
    PROFIT_TRAILING doit redevenir actif, le mecanisme n'est pas retire,
    seulement retarde."""
    reason = ae.position_exit_reason(
        _position(profit=-2.20), _pos_params(), {}, "", "",
        peak=1.80, age=10.0,
    )
    assert reason == "PROFIT_TRAILING", f"Attendu PROFIT_TRAILING apres la phase naissance, obtenu {reason!r}."
    print("test_profit_trailing_still_works_after_birth_phase OK")


def test_momentum_exit_suppressed_during_birth_phase():
    """MOMENTUM_EXIT (sortie sur mouvement instantane de l'analyse
    concurrente) doit lui aussi etre suspendu pendant la phase naissance."""
    analysis = {"score_sell": 90.0}  # position BUY -> score_sell est le score oppose
    reason_during = ae.position_exit_reason(
        _position(direction="BUY", profit=1.0), _pos_params(), analysis, "", "",
        peak=1.0, age=2.0,
    )
    reason_after = ae.position_exit_reason(
        _position(direction="BUY", profit=1.0), _pos_params(), analysis, "", "",
        peak=1.0, age=10.0,
    )
    assert reason_during != "MOMENTUM_EXIT", f"MOMENTUM_EXIT ne doit pas agir pendant la phase naissance, obtenu {reason_during!r}."
    assert reason_after == "MOMENTUM_EXIT", f"MOMENTUM_EXIT doit redevenir actif apres, obtenu {reason_after!r}."
    print("test_momentum_exit_suppressed_during_birth_phase OK")


def test_max_position_loss_still_fires_during_birth_phase():
    """Le filet de securite absolu (perte maximale par position) reste actif
    meme dans la premiere seconde -- ce n'est PAS une decision basee sur un
    mouvement instantane, c'est une limite independante du temps."""
    reason = ae.position_exit_reason(
        _position(profit=-25.0), _pos_params(max_position_loss=20.0), {}, "", "",
        peak=0.0, age=0.3,
    )
    assert reason == "MAX_POSITION_LOSS", f"MAX_POSITION_LOSS doit rester actif des l'ouverture, obtenu {reason!r}."
    print("test_max_position_loss_still_fires_during_birth_phase OK")


def test_birth_phase_duration_configurable():
    """trade_birth_phase_sec doit vraiment piloter la duree -- avec 0, plus
    aucune suppression (comportement historique preserve pour qui le
    desactive explicitement)."""
    reason = ae.position_exit_reason(
        _position(profit=-2.20), _pos_params(trade_birth_phase_sec=0.0), {}, "", "",
        peak=1.80, age=0.1,
    )
    assert reason == "PROFIT_TRAILING", f"Avec trade_birth_phase_sec=0, PROFIT_TRAILING doit agir immediatement, obtenu {reason!r}."
    print("test_birth_phase_duration_configurable OK")


if __name__ == "__main__":
    test_profit_trailing_suppressed_during_birth_phase()
    test_profit_trailing_still_works_after_birth_phase()
    test_momentum_exit_suppressed_during_birth_phase()
    test_max_position_loss_still_fires_during_birth_phase()
    test_birth_phase_duration_configurable()
    print("ALL OK")
