"""Tests pour le chantier du 06-07/08/2026 (demande explicite et repetee de
Louis : "les parametres manuels ne doivent plus intervenir dans le calcul
intelligent de l'IA", suite a l'audit du soir revelant 3 bugs reels
verifies en executant le code, pas juste en le lisant) :

1. merge_params() : un `null` JSON explicite pour une cle deja presente
   ecrasait silencieusement la valeur par defaut (trading_style_auto_apply_
   enabled=null a desactive l'auto-application sans qu'aucun "false"
   explicite n'ait jamais ete choisi).
2. apply_strategy_mode_if_changed() : changer de strategy_mode ne
   reappliquait pas vraiment le profil -- confidence_min/profit_target/
   cadence_sec/max_hold_sec/position_review_sec restaient bloques sur les
   valeurs du PRECEDENT mode des qu'un premier profil avait deja tourne
   une fois (l'ancienne heuristique comparait a DEFAULT_PARAMS, pas au
   dernier profil reellement applique).
3. position_exit_reason(risk_budget=...) : plancher -- le seuil de
   protection ne peut plus etre plus strict que ce que le lot a ete
   dimensionne pour tolerer.
4. position_exit_reason() max_loss_to_target_ratio : plafond -- aucune
   perte ne peut structurellement depasser N fois l'objectif de gain du
   mode actif (Finding 1 de l'audit : 84.8% de trades gagnants mais
   -8454$ net, perte moyenne ~8x le gain moyen)."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


# ---------------------------------------------------------------------------
# 1. merge_params() -- un null explicite ne doit jamais ecraser le defaut
# ---------------------------------------------------------------------------

def test_merge_params_explicit_null_does_not_override_default():
    ae.write_json("params.json", {"trading_style_auto_apply_enabled": None})
    merged = ae.merge_params()
    assert merged["trading_style_auto_apply_enabled"] is True, (
        f"Un null explicite ne doit jamais ecraser le defaut (True) -- obtenu {merged['trading_style_auto_apply_enabled']}."
    )
    print("test_merge_params_explicit_null_does_not_override_default OK")


def test_merge_params_explicit_false_is_still_respected():
    """Un null ne doit pas ecraser le defaut -- mais un VRAI False choisi
    par l'utilisateur doit, lui, rester respecte (pas confondu)."""
    ae.write_json("params.json", {"trading_style_auto_apply_enabled": False})
    merged = ae.merge_params()
    assert merged["trading_style_auto_apply_enabled"] is False
    print("test_merge_params_explicit_false_is_still_respected OK")


def test_merge_params_null_in_symbol_subdict_does_not_override_default():
    ae.write_json("params.json", {"symbols": {"XAUUSD": {"confidence_min": None, "profit_target": 7.0}}})
    merged = ae.merge_params()
    assert merged["symbols"]["XAUUSD"]["confidence_min"] == ae.DEFAULT_PARAMS["symbols"]["XAUUSD"]["confidence_min"]
    assert merged["symbols"]["XAUUSD"]["profit_target"] == 7.0  # une vraie valeur reste appliquee normalement
    print("test_merge_params_null_in_symbol_subdict_does_not_override_default OK")


# ---------------------------------------------------------------------------
# 2. apply_strategy_mode_if_changed() -- le profil s'applique VRAIMENT au
# changement de mode, meme si un profil precedent a deja tourne une fois
# ---------------------------------------------------------------------------

def test_apply_strategy_mode_reapplies_full_profile_after_prior_mode_residue():
    """Reproduit EXACTEMENT le bug reel trouve ce soir : scalping_fast
    tourne une premiere fois (laisse confidence_min=55/profit_target=3 --
    qui different tous les deux du defaut de base), PUIS on passe a
    long_analysis -- confidence_min doit vraiment devenir 65 et
    profit_target 10.0, pas rester bloque a 55/3."""
    ae.write_json("params.json", {"strategy_mode": "scalping_fast"})
    ae.apply_strategy_mode_if_changed("scalping_fast")
    saved = ae.read_json("params.json", {})
    assert saved["symbols"]["XAUUSD"]["confidence_min"] == 55
    assert saved["symbols"]["XAUUSD"]["profit_target"] == 3.00

    saved["strategy_mode"] = "long_analysis"
    ae.write_json("params.json", saved)
    ae.apply_strategy_mode_if_changed("long_analysis")
    saved = ae.read_json("params.json", {})
    assert saved["symbols"]["XAUUSD"]["confidence_min"] == 65, (
        f"confidence_min doit vraiment passer a 65 (long_analysis), obtenu {saved['symbols']['XAUUSD']['confidence_min']}."
    )
    assert saved["symbols"]["XAUUSD"]["profit_target"] == 10.0
    assert saved["symbols"]["XAUUSD"]["timeframe"] == "M15"
    assert saved["_last_applied_strategy_mode"] == "long_analysis"
    print("test_apply_strategy_mode_reapplies_full_profile_after_prior_mode_residue OK")


def test_apply_strategy_mode_skips_when_already_applied():
    """Ne doit PAS re-ecraser un ajustement manuel fait APRES l'application
    du profil, tant que le mode n'a pas change entre-temps."""
    ae.write_json("params.json", {"strategy_mode": "scalping_fast"})
    ae.apply_strategy_mode_if_changed("scalping_fast")
    saved = ae.read_json("params.json", {})
    saved["symbols"]["XAUUSD"]["confidence_min"] = 77  # ajustement manuel volontaire, meme mode
    ae.write_json("params.json", saved)
    ae.apply_strategy_mode_if_changed("scalping_fast")  # meme mode -- ne doit rien reecraser
    saved = ae.read_json("params.json", {})
    assert saved["symbols"]["XAUUSD"]["confidence_min"] == 77
    print("test_apply_strategy_mode_skips_when_already_applied OK")


def test_effective_params_for_strategy_exposes_profile_metadata():
    merged = ae.merge_params()
    merged["strategy_mode"] = "long_analysis"
    eff = ae.effective_params_for_strategy(merged)
    assert eff["strategy_profile"]["key"] == "long_analysis"
    assert eff["strategy_profile"]["label"] == "Analyse longue"
    print("test_effective_params_for_strategy_exposes_profile_metadata OK")


# ---------------------------------------------------------------------------
# 3 & 4. position_exit_reason() -- plancher risk_budget + plafond
# max_loss_to_target_ratio
# ---------------------------------------------------------------------------

BASE_PARAMS = {
    "max_position_loss": 15.0,
    "max_hold_sec": 0,  # desactive le Time Stop pour isoler MAX_POSITION_LOSS
    "position_review_sec": 3600,
    "rebond_enabled": False,
    "confidence_min": 60,
    "signal_reversal_margin": 99,
    "min_positive_exit": 0.50,
    "momentum_exit_score": 0,
    "take_profit_enabled": False,
    "profit_target": 3.0,
    "max_loss_to_target_ratio": 3.0,
    "trade_birth_phase_sec": 0,
}
ANALYSIS = {"signal": "WAIT", "confidence": 0}


def _call(profit, risk_budget=None, **param_overrides):
    params = {**BASE_PARAMS, **param_overrides}
    position = {"direction": "BUY", "profit": profit}
    return ae.position_exit_reason(position, params, ANALYSIS, "OK", "OPEN", profit, age=100.0, risk_budget=risk_budget)


def test_risk_budget_none_preserves_old_behavior_exactly():
    """Reproduit exactement le comportement d'avant ce chantier -- aucune
    regression pour tout appelant qui ne fournit pas risk_budget (plafond
    ratio desactive ici pour isoler precisement le seul comportement
    risk_budget=None, deja couvert par ses propres tests plus bas)."""
    assert _call(profit=-14.0, risk_budget=None, max_loss_to_target_ratio=0) != "MAX_POSITION_LOSS"
    assert _call(profit=-15.5, risk_budget=None, max_loss_to_target_ratio=0) == "MAX_POSITION_LOSS"
    print("test_risk_budget_none_preserves_old_behavior_exactly OK")


def test_risk_budget_floor_prevents_premature_close_on_undersized_static_threshold():
    """Reproduit le vrai trade a -20$/45s : max_position_loss configure a
    15$ mais le lot a ete dimensionne pour un risk_budget de 40$ -- la
    position ne doit PAS fermer a -20$ (bien en-dessous du vrai risque
    tolere), seulement au-dela de 40$."""
    reason_at_20 = _call(profit=-20.0, risk_budget=40.0, max_position_loss=15.0, max_loss_to_target_ratio=0)  # ratio desactive pour isoler le plancher
    assert reason_at_20 != "MAX_POSITION_LOSS", (
        "Le plancher risk_budget doit empecher une fermeture prematuree sous ce que le lot tolere reellement."
    )
    reason_at_45 = _call(profit=-45.0, risk_budget=40.0, max_position_loss=15.0, max_loss_to_target_ratio=0)
    assert reason_at_45 == "MAX_POSITION_LOSS"
    print("test_risk_budget_floor_prevents_premature_close_on_undersized_static_threshold OK")


def test_loss_to_target_ratio_ceiling_caps_a_too_loose_manual_max_position_loss():
    """Reproduit EXACTEMENT l'incident reel du soir : max_position_loss
    regle manuellement a 100$ en urgence, mais profit_target du mode actif
    n'est que 3$ -- sans plafond, une perte pourrait aller jusqu'a 100$
    pour un objectif de gain de 3$ (ratio ~33x). Avec le plafond a 3x, la
    position doit fermer bien avant 100$."""
    reason_at_9 = _call(profit=-9.0, max_position_loss=100.0, profit_target=3.0, max_loss_to_target_ratio=3.0)
    assert reason_at_9 == "MAX_POSITION_LOSS", (
        f"Le plafond (3x profit_target=3 -> 9$) doit forcer la fermeture bien avant les 100$ configures manuellement, obtenu: {reason_at_9!r}."
    )
    print("test_loss_to_target_ratio_ceiling_caps_a_too_loose_manual_max_position_loss OK")


def test_loss_to_target_ratio_ceiling_wins_over_risk_budget_floor_on_conflict():
    """Si risk_budget (plancher) et max_loss_to_target_ratio (plafond) se
    contredisent, le plafond doit toujours gagner -- c'est la garantie
    non-negociable contre l'asymetrie perte/gain (Finding 1)."""
    reason = _call(
        profit=-9.0, risk_budget=50.0,  # plancher tres genereux
        max_position_loss=100.0, profit_target=3.0, max_loss_to_target_ratio=3.0,  # plafond a 9$
    )
    assert reason == "MAX_POSITION_LOSS", (
        f"Le plafond doit gagner meme si le plancher risk_budget serait plus permissif, obtenu {reason!r}."
    )
    print("test_loss_to_target_ratio_ceiling_wins_over_risk_budget_floor_on_conflict OK")


def test_ratio_ceiling_disabled_when_max_position_loss_already_off():
    """max_position_loss=0 (protection desactivee volontairement) ne doit
    jamais etre REACTIVEE par le plafond -- 0 reste 0."""
    reason = _call(profit=-500.0, max_position_loss=0, profit_target=3.0, max_loss_to_target_ratio=3.0)
    assert reason != "MAX_POSITION_LOSS"
    print("test_ratio_ceiling_disabled_when_max_position_loss_already_off OK")


if __name__ == "__main__":
    test_merge_params_explicit_null_does_not_override_default()
    test_merge_params_explicit_false_is_still_respected()
    test_merge_params_null_in_symbol_subdict_does_not_override_default()
    test_apply_strategy_mode_reapplies_full_profile_after_prior_mode_residue()
    test_apply_strategy_mode_skips_when_already_applied()
    test_effective_params_for_strategy_exposes_profile_metadata()
    test_risk_budget_none_preserves_old_behavior_exactly()
    test_risk_budget_floor_prevents_premature_close_on_undersized_static_threshold()
    test_loss_to_target_ratio_ceiling_caps_a_too_loose_manual_max_position_loss()
    test_loss_to_target_ratio_ceiling_wins_over_risk_budget_floor_on_conflict()
    test_ratio_ceiling_disabled_when_max_position_loss_already_off()
    print("ALL TESTS PASSED")
