"""Tests isoles pour place_order() (alphatrade_engine.py, v5.1.0).

IMPORTANT -- place_order() touche mt5.order_send : au-dela de la structure
verifiee ici (mapping des 6 types, garde-fou sur type inconnu), le
comportement reel (calcul SL/TP, rejet de prix incoherent, envoi MT5) ne peut
etre teste sans un compte demo connecte (mt5=None dans cet environnement).
Conforme au plan de securite de la Proposition Technique v5.1.0 : aucune
fonctionnalite d'execution n'est validee sans session demo dediee -- ce test
verifie ce qui peut l'etre sans MT5, pas plus."""
import os
import tempfile

os.environ["ALPHATRADE_DATA_DIR"] = tempfile.mkdtemp(prefix="alphatrade_test_")

import alphatrade_engine as ae


def test_order_type_kind_covers_six_types():
    expected = {"BUY_MARKET", "SELL_MARKET", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
    assert set(ae.ORDER_TYPE_KIND) == expected
    for order_type, (direction, kind) in ae.ORDER_TYPE_KIND.items():
        assert direction in ("BUY", "SELL")
        assert kind in (None, "LIMIT", "STOP")
        assert (kind is None) == order_type.endswith("MARKET")
    print("test_order_type_kind_covers_six_types OK")


def test_unknown_order_type_rejected_before_touching_mt5():
    ok, reason, event = ae.place_order("XAUUSD", "XAUUSD", "BUY_TELEPORT", {}, {}, {}, allow_real=False)
    assert ok is False
    assert "inconnu" in reason
    assert event is None
    print("test_unknown_order_type_rejected_before_touching_mt5 OK")


if __name__ == "__main__":
    test_order_type_kind_covers_six_types()
    test_unknown_order_type_rejected_before_touching_mt5()
    print("ALL TESTS PASSED (structure only -- comportement reel a valider en demo, voir plan de securite)")
