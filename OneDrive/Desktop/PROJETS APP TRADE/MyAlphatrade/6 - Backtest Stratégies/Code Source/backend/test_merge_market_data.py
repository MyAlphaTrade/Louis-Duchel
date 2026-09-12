"""
Tests de non-regression -- Phase 1 Strategy Lab, import non destructif.
Aucune dependance externe (stdlib unittest uniquement) : `_merge_market_data`
est une fonction pure, testable sans base de donnees ni serveur FastAPI.

Lancer : python test_merge_market_data.py
"""
import unittest

from main import Candle, _merge_market_data


def candle(ts, o=1.0, h=1.0, l=1.0, c=1.0, spread=10.0):
    return Candle(timestamp=ts, open=o, high=h, low=l, close=c, volume=100, spread=spread)


class TestMergeMarketData(unittest.TestCase):
    def test_import_into_empty_history_inserts_everything(self):
        candles = [candle("2026-06-01T00:00:00Z"), candle("2026-06-01T00:15:00Z")]
        to_insert, to_update, collisions, unchanged = _merge_market_data({}, "XAUUSD", "M15", candles)
        self.assertEqual(len(to_insert), 2)
        self.assertEqual(len(to_update), 0)
        self.assertEqual(collisions, 0)
        self.assertEqual(unchanged, 0)

    def test_reimport_partial_period_does_not_touch_untouched_history(self):
        """Coeur du bug corrige : importer seulement une partie de la periode
        ne doit JAMAIS faire disparaitre les bougies deja presentes hors de
        cette periode -- elles ne sont meme pas dans `existing_by_timestamp`
        transmis pour cet appel-ci, donc `_merge_market_data` ne peut ni les
        voir ni les supprimer (la fonction n'a aucune notion de "supprimer",
        contrairement a l'ancien DELETE global)."""
        existing = {
            "2026-06-01T00:00:00Z": ("id-old-1", {"timestamp": "2026-06-01T00:00:00Z", "open": 1, "high": 1, "low": 1, "close": 1}),
        }
        new_candles = [candle("2026-07-01T00:00:00Z")]  # periode differente, aucun chevauchement
        to_insert, to_update, collisions, unchanged = _merge_market_data(existing, "XAUUSD", "M15", new_candles)
        self.assertEqual(len(to_insert), 1)
        self.assertEqual(to_insert[0]["timestamp"], "2026-07-01T00:00:00Z")
        self.assertEqual(len(to_update), 0)  # la bougie de juin n'est JAMAIS touchee
        self.assertEqual(collisions, 0)

    def test_identical_reimport_is_a_noop(self):
        existing = {
            "2026-06-01T00:00:00Z": ("id-1", {"timestamp": "2026-06-01T00:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}),
        }
        same = [candle("2026-06-01T00:00:00Z", 1.0, 1.0, 1.0, 1.0)]
        to_insert, to_update, collisions, unchanged = _merge_market_data(existing, "XAUUSD", "M15", same)
        self.assertEqual(len(to_insert), 0)
        self.assertEqual(len(to_update), 0)
        self.assertEqual(collisions, 0)
        self.assertEqual(unchanged, 1)

    def test_conflicting_reimport_is_reported_as_a_collision_not_silent(self):
        existing = {
            "2026-06-01T00:00:00Z": ("id-1", {"timestamp": "2026-06-01T00:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}),
        }
        different = [candle("2026-06-01T00:00:00Z", 2.0, 2.0, 2.0, 2.0)]  # meme instant, valeurs differentes
        to_insert, to_update, collisions, unchanged = _merge_market_data(existing, "XAUUSD", "M15", different)
        self.assertEqual(len(to_insert), 0)
        self.assertEqual(len(to_update), 1)
        self.assertEqual(to_update[0][0], "id-1")
        self.assertEqual(collisions, 1)
        self.assertEqual(unchanged, 0)

    def test_spread_column_is_preserved(self):
        candles = [candle("2026-06-01T00:00:00Z", spread=15.0)]
        to_insert, _, _, _ = _merge_market_data({}, "XAUUSD", "M15", candles)
        self.assertEqual(to_insert[0]["spread"], 15.0)

    def test_spread_absent_is_none_not_a_crash(self):
        c = Candle(timestamp="2026-06-01T00:00:00Z", open=1, high=1, low=1, close=1, volume=1)
        to_insert, _, _, _ = _merge_market_data({}, "XAUUSD", "M15", [c])
        self.assertIsNone(to_insert[0]["spread"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
