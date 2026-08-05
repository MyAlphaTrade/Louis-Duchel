"""Tests pour le calcul automatique du lot (v5.1.1, 05/08/2026) -- demande
explicite et repetee de Louis : "les parametres manuel ne doivent plus du
tout impacter ces decisions" (lot). lot_safety_state() calcule desormais le
lot PUREMENT depuis le capital et le risque (capital x risk_pct / distance
de stop), comme AlphaTrade Global (EA_Bridge/local_functions.py
calculate_lot()) -- l'ancien champ manuel "lot" (Paramètres > Renfort &
Rebond > "Lot fixe") n'a plus aucune influence, retire de l'UI dans le
meme commit."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


class _FakeAccount:
    def __init__(self, balance):
        self.balance = balance
        self.login = 12345
        self.server = "Demo-Server"
        self.trade_mode = 0


class _FakeSymbolInfo:
    point = 0.01
    volume_min = 0.01
    volume_step = 0.01
    trade_tick_size = 0.01
    trade_tick_value = 1.0
    trade_stops_level = 0
    digits = 2


class _FakeTick:
    ask = 4000.0
    bid = 3999.8


class _FakeMT5:
    """order_calc_profit lineaire ($100 par point par lot) -- suffisant pour
    verifier la PROPORTIONNALITE du lot au capital/risque, pas besoin de
    reproduire la vraie formule de marge XAUUSD."""
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1

    def symbol_info(self, name):
        return _FakeSymbolInfo()

    def symbol_info_tick(self, name):
        return _FakeTick()

    def order_calc_profit(self, order_type, symbol, volume, price_open, price_close):
        return (price_close - price_open) * volume * 100.0


def _base_params(lot_manual=0.05, risk_pct=0.35, emergency_loss_limit=3.0):
    p = ae.merge_params()
    p["risk_pct"] = risk_pct
    p["real_lot_cap"] = 10.0  # plafond de securite large, pour isoler le calcul de risque dans ces tests
    p["demo_lot_cap"] = 10.0
    p["symbols"] = {"XAUUSD": {"lot": lot_manual, "lot_min": 0.0, "emergency_loss_limit": emergency_loss_limit}}
    return p


def _with_fake_mt5(fn):
    original = ae.mt5
    ae.mt5 = _FakeMT5()
    try:
        return fn()
    finally:
        ae.mt5 = original


def test_lot_scales_with_capital_not_with_manual_lot_param():
    """Le lot calcule doit changer avec le capital -- et NE DOIT PAS changer
    quand seul le champ manuel 'lot' change (capital et risque identiques)."""
    def run():
        small = ae.lot_safety_state(_base_params(lot_manual=0.01), _FakeAccount(1000.0), {"XAUUSD": "XAUUSD"})
        large = ae.lot_safety_state(_base_params(lot_manual=0.01), _FakeAccount(10000.0), {"XAUUSD": "XAUUSD"})
        manual_low = ae.lot_safety_state(_base_params(lot_manual=0.001), _FakeAccount(5000.0), {"XAUUSD": "XAUUSD"})
        manual_high = ae.lot_safety_state(_base_params(lot_manual=5.0), _FakeAccount(5000.0), {"XAUUSD": "XAUUSD"})
        return small, large, manual_low, manual_high
    small, large, manual_low, manual_high = _with_fake_mt5(run)

    assert large["XAUUSD"]["effective_lot"] > small["XAUUSD"]["effective_lot"], (
        "Un capital 10x plus grand doit produire un lot plus grand (calcul reel, pas une valeur figee)."
    )
    # Meme capital (5000$), meme risk_pct -- seul "lot" manuel differe (0.001 vs 5.0) -> AUCUN effet.
    assert manual_low["XAUUSD"]["effective_lot"] == manual_high["XAUUSD"]["effective_lot"], (
        "Le champ manuel 'lot' ne doit plus du tout influencer le lot calcule -- "
        f"obtenu {manual_low['XAUUSD']['effective_lot']} vs {manual_high['XAUUSD']['effective_lot']}."
    )
    print("test_lot_scales_with_capital_not_with_manual_lot_param OK")


def test_lot_respects_account_cap_as_safety_ceiling():
    """Le plafond de compte (Securite) reste un vrai filet de securite absolu
    -- meme avec un capital enorme, le lot calcule ne doit jamais le depasser."""
    def run():
        params = _base_params(lot_manual=0.01, risk_pct=50.0)  # risque volontairement excessif
        params["real_lot_cap"] = 0.05
        params["demo_lot_cap"] = 0.05
        return ae.lot_safety_state(params, _FakeAccount(1_000_000.0), {"XAUUSD": "XAUUSD"})
    result = _with_fake_mt5(run)
    assert result["XAUUSD"]["effective_lot"] <= 0.05 + 1e-9, (
        f"Le plafond de compte doit rester une limite absolue, obtenu {result['XAUUSD']['effective_lot']}."
    )
    print("test_lot_respects_account_cap_as_safety_ceiling OK")


def test_lot_zero_when_no_mt5_data():
    """Sans mt5 (donc sans prix reel), aucun lot ne peut etre calcule -- doit
    etre rejete (0.0), jamais un repli sur une valeur manuelle."""
    original = ae.mt5
    ae.mt5 = None
    try:
        result = ae.lot_safety_state(_base_params(lot_manual=1.0), _FakeAccount(10000.0), {"XAUUSD": "XAUUSD"})
    finally:
        ae.mt5 = original
    assert result["XAUUSD"]["effective_lot"] == 0.0
    assert result["XAUUSD"]["rejected"] is True
    print("test_lot_zero_when_no_mt5_data OK")


if __name__ == "__main__":
    test_lot_scales_with_capital_not_with_manual_lot_param()
    test_lot_respects_account_cap_as_safety_ceiling()
    test_lot_zero_when_no_mt5_data()
    print("ALL OK")
