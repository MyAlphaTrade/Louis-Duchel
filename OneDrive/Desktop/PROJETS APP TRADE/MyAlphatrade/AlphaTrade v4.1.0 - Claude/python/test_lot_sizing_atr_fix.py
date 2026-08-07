"""Tests pour le correctif du 06/08/2026 (root cause des deux incidents reels
sur le compte live : positions XAUUSD fermees par MAX_POSITION_LOSS/
MAX_FLOATING_LOSS en 0.7 et 3.3 secondes, tickets 9749678638/9749701356,
-54.32$ et -25.65$).

Root cause confirmee sur les vrais chiffres du compte (risk_pct=0.35,
max_position_loss=emergency_loss_limit=15$, solde ~4283$) : l'ancienne
formule de lot_safety_state() calculait la distance de stop utilisee pour
DIMENSIONNER le lot AVEC emergency_loss_limit lui-meme (a un volume de
reference fixe de 1.0 lot), puis remesurait la perte d'1.0 lot a EXACTEMENT
cette meme distance -- operation circulaire qui redonnait TOUJOURS
loss_per_lot ~= emergency_loss_limit, quelle que soit la vraie volatilite du
marche. Resultat : risk_lot_cap = risk_budget / emergency_loss_limit ~= 1.0
lot des que les deux valeurs sont proches (comme ici) -- a un tel volume, un
mouvement de prix normal de quelques secondes suffit a consommer les 15$ de
max_position_loss.

Corrige : la distance de stop vient maintenant d'un ATR reel (simple_atr(),
meme fonction que le Scenario Engine), independante des seuils de
protection $. Ces tests verifient (a) que le lot resultant est desormais
coherent avec une vraie distance de marche (largement < 1.0 lot avec un ATR
gold realiste), (b) que le repli vers l'ancien calcul reste disponible et
degrade proprement quand aucune bougie n'est disponible, (c) que le cache
ATR (30s) evite un aller-retour MT5 a chaque appel."""
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
    ask = 4245.18
    bid = 4244.98


class _FakeMT5NoCandles:
    """Reproduit EXACTEMENT les fakes de test_lot_auto_calc.py (pas de
    copy_rates_from_pos) -- verifie que le repli vers l'ancien calcul
    fonctionne toujours quand aucune bougie reelle n'est disponible."""
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240
    TIMEFRAME_D1 = 1440

    def symbol_info(self, name):
        return _FakeSymbolInfo()

    def symbol_info_tick(self, name):
        return _FakeTick()

    def order_calc_profit(self, order_type, symbol, volume, price_open, price_close):
        # Meme echelle que les vrais incidents : ~3.58$ par $1 de mouvement
        # de prix pour 1.0 lot XAUUSD (deduit des donnees reelles de
        # l'incident 2 : sl_distance=5.52 pour 0.95 lot / cible 18.75$).
        return (price_close - price_open) * volume * 3.58


class _FakeMT5WithCandles(_FakeMT5NoCandles):
    """Ajoute copy_rates_from_pos avec un ATR gold realiste (~8$, coherent
    avec une volatilite XAUUSD intraday normale) -- permet de verifier que
    le nouveau calcul base sur l'ATR produit un lot radicalement different
    (et sain) par rapport a l'ancien calcul circulaire."""
    def __init__(self, atr_dollars=8.0):
        self.candle_fetch_count = 0
        self._atr_dollars = atr_dollars

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.candle_fetch_count += 1
        # 15 bougies avec un range constant = atr_dollars -> simple_atr()
        # (moyenne des (high-low) sur les 14 dernieres) retombe exactement
        # sur atr_dollars.
        base = 4245.0
        rates = []
        for i in range(count):
            high = base + self._atr_dollars / 2
            low = base - self._atr_dollars / 2
            rates.append((i, base, high, low, base, 0, 0, 0))
        return rates


def _base_params(risk_pct=0.35, max_position_loss=15.0, emergency_loss_limit=15.0):
    p = ae.merge_params()
    p["risk_pct"] = risk_pct
    p["symbols"] = {
        "XAUUSD": {
            "lot_min": 0.0,
            "max_position_loss": max_position_loss,
            "emergency_loss_limit": emergency_loss_limit,
            "timeframe": "M5",
        }
    }
    return p


def _with_fake_mt5(fake, fn):
    original = ae.mt5
    ae.mt5 = fake
    try:
        return fn()
    finally:
        ae.mt5 = original


def test_old_circular_fallback_reproduces_the_real_incident_lot():
    """Sans bougies disponibles (repli), on doit retrouver EXACTEMENT le
    comportement degenere observe en production : lot proche de 1.0 avec
    les vrais chiffres du compte (risk_budget ~= emergency_loss_limit).
    Preuve que ce test capture bien le vrai bug avant correctif, et que le
    repli reste un comportement connu/documente (pas une regression
    silencieuse) plutot qu'un crash."""
    ae._LOT_SIZING_ATR_CACHE.clear()
    account = _FakeAccount(4283.0)  # solde reel de l'incident
    params = _base_params(risk_pct=0.35, max_position_loss=15.0, emergency_loss_limit=15.0)
    result = _with_fake_mt5(
        _FakeMT5NoCandles(),
        lambda: ae.lot_safety_state(params, account, {"XAUUSD": "XAUUSD"}),
    )
    lot = result["XAUUSD"]["effective_lot"]
    assert result["XAUUSD"]["stop_distance_source"] == "emergency_loss_limit_fallback"
    assert 0.9 <= lot <= 1.0, (
        f"Le repli doit reproduire le lot degenere observe en production (~0.95-1.0), obtenu {lot}."
    )
    print("test_old_circular_fallback_reproduces_the_real_incident_lot OK")


def test_atr_based_stop_distance_produces_a_sane_smaller_lot():
    """Avec un ATR gold realiste (8$, volatilite intraday normale) et les
    MEMES parametres $ que l'incident reel, le lot doit desormais etre
    RADICALEMENT plus petit que l'ancien lot degenere (~1.0) -- preuve
    directe que le correctif dimensionne le lot sur une vraie distance de
    marche plutot que sur un artefact circulaire."""
    ae._LOT_SIZING_ATR_CACHE.clear()
    account = _FakeAccount(4283.0)
    params = _base_params(risk_pct=0.35, max_position_loss=15.0, emergency_loss_limit=15.0)
    result = _with_fake_mt5(
        _FakeMT5WithCandles(atr_dollars=8.0),
        lambda: ae.lot_safety_state(params, account, {"XAUUSD": "XAUUSD"}),
    )
    lot = result["XAUUSD"]["effective_lot"]
    assert result["XAUUSD"]["stop_distance_source"] == "atr"
    assert lot < 0.6, (
        f"Avec un ATR realiste (8$), le lot doit etre nettement plus petit que le lot "
        f"degenere de l'ancien calcul circulaire (~1.0), obtenu {lot}."
    )
    assert lot > 0, "Le lot ne doit pas etre rejete a zero avec un compte/risque normaux."
    print("test_atr_based_stop_distance_produces_a_sane_smaller_lot OK")


def test_larger_atr_produces_smaller_lot_than_smaller_atr():
    """Verifie le sens physique : plus la volatilite reelle (ATR) est
    grande, plus le stop est loin, donc plus le lot risk-size doit etre
    petit pour respecter le meme risk_budget -- preuve que le lot suit
    desormais une vraie logique de marche, pas un artefact fixe."""
    ae._LOT_SIZING_ATR_CACHE.clear()
    account = _FakeAccount(4283.0)
    params = _base_params()
    tight = _with_fake_mt5(
        _FakeMT5WithCandles(atr_dollars=3.0),
        lambda: ae.lot_safety_state(params, account, {"XAUUSD": "XAUUSD"}),
    )
    ae._LOT_SIZING_ATR_CACHE.clear()
    wide = _with_fake_mt5(
        _FakeMT5WithCandles(atr_dollars=15.0),
        lambda: ae.lot_safety_state(params, account, {"XAUUSD": "XAUUSD"}),
    )
    assert wide["XAUUSD"]["effective_lot"] < tight["XAUUSD"]["effective_lot"], (
        "Un ATR plus large (marche plus volatil) doit produire un lot plus petit, "
        f"obtenu tight={tight['XAUUSD']['effective_lot']} wide={wide['XAUUSD']['effective_lot']}."
    )
    print("test_larger_atr_produces_smaller_lot_than_smaller_atr OK")


def test_atr_is_cached_within_ttl_no_repeated_mt5_calls():
    """Deux appels successifs a lot_safety_state() dans la fenetre de cache
    (30s) ne doivent PAS re-interroger MT5 pour les bougies -- evite une
    regression de latence sur le cycle principal (deja corrigee une fois
    cette session, voir feedback_workflow)."""
    ae._LOT_SIZING_ATR_CACHE.clear()
    account = _FakeAccount(4283.0)
    params = _base_params()
    fake = _FakeMT5WithCandles(atr_dollars=8.0)

    def run():
        ae.lot_safety_state(params, account, {"XAUUSD": "XAUUSD"})
        ae.lot_safety_state(params, account, {"XAUUSD": "XAUUSD"})

    _with_fake_mt5(fake, run)
    assert fake.candle_fetch_count == 1, (
        f"Le deuxieme appel doit reutiliser l'ATR en cache (TTL 30s), pas re-fetcher -- "
        f"obtenu {fake.candle_fetch_count} appels a copy_rates_from_pos."
    )
    print("test_atr_is_cached_within_ttl_no_repeated_mt5_calls OK")


def test_atr_unavailable_falls_back_gracefully_without_crash():
    """copy_rates_from_pos existe mais renvoie None (deconnexion MT5
    momentanee) -- doit degrader vers l'ancien calcul sans exception."""
    ae._LOT_SIZING_ATR_CACHE.clear()

    class _FakeMT5NoneRates(_FakeMT5NoCandles):
        def copy_rates_from_pos(self, symbol, timeframe, start, count):
            return None

    account = _FakeAccount(4283.0)
    params = _base_params()
    result = _with_fake_mt5(
        _FakeMT5NoneRates(),
        lambda: ae.lot_safety_state(params, account, {"XAUUSD": "XAUUSD"}),
    )
    assert result["XAUUSD"]["stop_distance_source"] == "emergency_loss_limit_fallback"
    assert result["XAUUSD"]["effective_lot"] >= 0.0
    print("test_atr_unavailable_falls_back_gracefully_without_crash OK")


if __name__ == "__main__":
    test_old_circular_fallback_reproduces_the_real_incident_lot()
    test_atr_based_stop_distance_produces_a_sane_smaller_lot()
    test_larger_atr_produces_smaller_lot_than_smaller_atr()
    test_atr_is_cached_within_ttl_no_repeated_mt5_calls()
    test_atr_unavailable_falls_back_gracefully_without_crash()
    print("ALL TESTS PASSED")
