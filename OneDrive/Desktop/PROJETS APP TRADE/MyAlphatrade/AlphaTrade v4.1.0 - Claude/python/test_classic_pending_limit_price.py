"""Tests pour le bug reel trouve le 07/08/2026 en verifiant EN EXECUTANT le
code (demande explicite de Louis : "il faut verifier ca vraiment en
profondeur"), pas visible a la simple lecture -- exactement le genre de
lacune que test_gold_brain_wiring.py/test_place_order.py documentaient deja
comme "reste a valider avec un vrai compte demo".

Root cause : place_order() exige un vrai `price_hint` pour tout ordre
LIMIT/STOP (sinon rejet immediat "Prix requis pour un ordre en attente.").
Structure/Smart Money fournissent deja un vrai niveau de zone dans leur
recommandation, mais le rapport "alphatrade_ai_classic" (le signal
indicateur classique, souvent celui qui gagne l'arbitrage CAIO) n'en avait
AUCUN. Des qu'il gagnait en mode "long_analysis" (entry_policy=pending_limit,
celui que Louis appelle "intraday"), l'ordre etait tente puis silencieusement
rejete faute de prix -- exactement le "je selectionne intraday, rien ne se
passe" signale.

Corrige : prix ancre sur un vrai repli ATR (gold_brain_snapshot())."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


class _FakeAccount:
    balance = 4283.0
    login = 12345
    server = "Demo-Server"
    trade_mode = 0


class _FakeSymbolInfo:
    point = 0.01
    volume_min = 0.01
    volume_step = 0.01
    trade_tick_size = 0.01
    trade_tick_value = 1.0
    trade_stops_level = 0
    digits = 2
    filling_mode = 3  # FOK (1) + IOC (2)
    trade_exemode = 2


class _FakeTick:
    ask = 4245.20
    bid = 4245.00


class _FakeMT5Full:
    """Assez de surface pour exercer gold_brain_snapshot() -> caio_decide()
    -> place_order() en LIMIT de bout en bout, meme discipline que
    test_lot_sizing_atr_fix.py (_FakeMT5WithCandles) -- comportement REEL
    verifie ici (pas juste la structure), contrairement a la limite deja
    documentee dans test_place_order.py (execution reelle MT5 elle-meme,
    au-dela de cette logique Python, reste hors de portee sans compte demo)."""
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TYPE_BUY_STOP = 4
    ORDER_TYPE_SELL_STOP = 5
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_PENDING = 5
    ORDER_TIME_GTC = 0
    ORDER_TIME_SPECIFIED = 1
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_PLACED = 10008
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240
    TIMEFRAME_D1 = 1440
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_RETCODE_INVALID_FILL = 10030

    def __init__(self):
        self.sent_requests: list[dict] = []

    def account_info(self):
        return _FakeAccount()

    def symbol_info(self, name):
        return _FakeSymbolInfo()

    def symbol_info_tick(self, name):
        return _FakeTick()

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        # Bougies avec un vrai range (5$) -- simple_atr() calcule un ATR non
        # nul, indispensable pour prouver que le prix calcule est un vrai
        # repli, pas juste le prix courant (qui echouerait la validation
        # LIMIT de place_order() -- doit etre STRICTEMENT du bon cote).
        base = 4245.0
        return [(i, base, base + 5.0, base - 5.0, base, 0, 0, 0) for i in range(count)]

    def order_calc_profit(self, order_type, symbol, volume, price_open, price_close):
        return (price_close - price_open) * volume * 100.0

    def order_check(self, request):
        class _Checked:
            retcode = 0
        return _Checked()

    def order_send(self, request):
        self.sent_requests.append(request)
        class _Result:
            retcode = 10009
            order = 555001
            deal = 0
        return _Result()


def _with_fake_mt5(fake, fn):
    original = ae.mt5
    ae.mt5 = fake
    try:
        return fn()
    finally:
        ae.mt5 = original


def test_classic_report_gets_a_real_limit_price_not_the_bare_market_price():
    """Le prix de alphatrade_ai_classic doit maintenant exister ET etre
    STRICTEMENT du bon cote du prix courant (repli ATR reel, pas le prix
    courant tel quel -- qui echouerait la validation LIMIT de place_order())."""
    fake = _FakeMT5Full()
    params = ae.merge_params()
    params["gold_brain_enabled"] = True

    def run():
        return ae.gold_brain_snapshot(
            params, _FakeAccount(), "XAUUSD", {"XAUUSD": "XAUUSD"},
            params.get("symbols", {}).get("XAUUSD", {}),
            {"confidence": 80.0, "close": 4245.10}, {"signal": "BUY", "confidence": 80.0, "reason": "Test"},
            {}, [], [], record=False,
        )

    snapshot = _with_fake_mt5(fake, run)
    classic = snapshot["reports"].get("alphatrade_ai_classic")
    assert classic is not None, "Le rapport alphatrade_ai_classic doit exister pour un signal BUY/SELL."
    price = classic["recommendation"].get("price")
    assert price is not None, "Root cause du bug reel : ce prix manquait completement avant le correctif."
    assert price < 4245.20, "Un signal BUY doit produire un prix de repli SOUS le prix courant (ask=4245.20)."
    print("test_classic_report_gets_a_real_limit_price_not_the_bare_market_price OK")


def test_pending_limit_mode_actually_places_a_real_pending_order():
    """Reproduit EXACTEMENT le scenario reel signale par Louis : mode
    'long_analysis' (celui qu'il appelle 'intraday', entry_policy=
    pending_limit), un signal BUY classique gagne l'arbitrage (aucun autre
    agent directionnel disponible ici) -- AVANT le correctif, ceci echouait
    silencieusement ('Prix requis pour un ordre en attente.'). Verifie
    desormais que mt5.order_send EST reellement appele avec un vrai ordre
    BUY_LIMIT (pas un rejet, pas un ordre au marche)."""
    fake = _FakeMT5Full()
    params = ae.merge_params()
    params["gold_brain_enabled"] = True
    params["strategy_mode"] = "long_analysis"  # "intraday" -- entry_policy=pending_limit
    params["economic_calendar_enabled"] = False  # isole le test du calendrier reel

    def run():
        snapshot = ae.gold_brain_snapshot(
            params, _FakeAccount(), "XAUUSD", {"XAUUSD": "XAUUSD"},
            params.get("symbols", {}).get("XAUUSD", {}),
            {"confidence": 80.0, "close": 4245.10}, {"signal": "BUY", "confidence": 80.0, "reason": "Test"},
            {}, [], [], record=False,
        )
        assert snapshot["decision"] == "GO", f"Doit atteindre GO pour tester place_order(), obtenu: {snapshot}"
        assert str(snapshot["order_type"]).endswith("LIMIT"), (
            f"entry_policy=pending_limit doit produire un ordre LIMIT, obtenu {snapshot['order_type']!r}."
        )
        lot_info = ae.lot_safety_state(params, _FakeAccount(), {"XAUUSD": "XAUUSD"}).get("XAUUSD", {})
        ok, message, event = ae.place_order(
            "XAUUSD", "XAUUSD", snapshot["order_type"], params, lot_info, {"confidence": 80.0},
            allow_real=False, price_hint=snapshot.get("price"),
        )
        return ok, message, event

    ok, message, event = _with_fake_mt5(fake, run)
    assert ok is True, f"L'ordre LIMIT doit reussir avec un vrai prix -- obtenu echec: {message!r}"
    assert len(fake.sent_requests) == 1
    sent = fake.sent_requests[0]
    assert sent["type"] == fake.ORDER_TYPE_BUY_LIMIT, "Doit envoyer un vrai BUY_LIMIT a MT5, pas un ordre au marche."
    assert sent["action"] == fake.TRADE_ACTION_PENDING
    print("test_pending_limit_mode_actually_places_a_real_pending_order OK")


def test_immediate_mode_unaffected_still_places_market_order():
    """Non-regression : le mode 'scalping' (entry_policy=immediate) doit
    continuer a placer un ordre au marche, jamais un LIMIT -- le correctif
    ne doit rien changer a ce chemin deja existant."""
    fake = _FakeMT5Full()
    params = ae.merge_params()
    params["gold_brain_enabled"] = True
    params["strategy_mode"] = "scalping_fast"
    params["economic_calendar_enabled"] = False

    def run():
        snapshot = ae.gold_brain_snapshot(
            params, _FakeAccount(), "XAUUSD", {"XAUUSD": "XAUUSD"},
            params.get("symbols", {}).get("XAUUSD", {}),
            {"confidence": 80.0, "close": 4245.10}, {"signal": "BUY", "confidence": 80.0, "reason": "Test"},
            {}, [], [], record=False,
        )
        return snapshot

    snapshot = _with_fake_mt5(fake, run)
    assert snapshot["order_type"] == "BUY_MARKET"
    print("test_immediate_mode_unaffected_still_places_market_order OK")


if __name__ == "__main__":
    test_classic_report_gets_a_real_limit_price_not_the_bare_market_price()
    test_pending_limit_mode_actually_places_a_real_pending_order()
    test_immediate_mode_unaffected_still_places_market_order()
    print("ALL TESTS PASSED")
