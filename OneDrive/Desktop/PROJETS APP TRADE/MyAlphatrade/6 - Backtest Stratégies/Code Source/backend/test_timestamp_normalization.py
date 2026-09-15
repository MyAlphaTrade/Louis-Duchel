"""Test cible -- correctif du bug de doublons trouve en Phase 3, etape 5
(2026-09-15).

Bug reel : `_merge_market_data` comparait les timestamps par egalite de
CHAINE exacte -- "2026-06-01T00:00:00Z" et "2026-06-01T00:00:00+00:00"
representent le meme instant UTC mais n'etaient jamais reconnus comme
identiques, produisant des doublons silencieux (3400 constates lors d'un
backfill MT5 chevauchant un import CSV existant).

Corrige dans la couche commune de fusion (_canonical_timestamp,
_candle_data, _merge_market_data), pas seulement dans le chemin d'import
MT5 -- ce fichier verifie precisement cette garantie, avec les scenarios
explicitement demandes par Louis.
"""
import json
import unittest

from main import Candle, _canonical_timestamp, _merge_market_data


def _candle(timestamp, o=100.0, h=101.0, l=99.0, c=100.5, v=10.0, spread=1.0):
    return Candle(timestamp=timestamp, open=o, high=h, low=l, close=c, volume=v, spread=spread)


class TestCanonicalTimestamp(unittest.TestCase):
    """Unite sur la fonction de normalisation elle-meme."""

    def test_z_suffix_and_utc_offset_normalize_to_the_same_value(self):
        self.assertEqual(
            _canonical_timestamp("2026-06-01T00:00:00Z"),
            _canonical_timestamp("2026-06-01T00:00:00+00:00"),
        )

    def test_non_utc_offset_is_correctly_converted_to_utc(self):
        # 14:00 a +02:00 == 12:00 UTC. Verifie une VRAIE conversion de
        # fuseau horaire, pas juste un remplacement de suffixe.
        self.assertEqual(
            _canonical_timestamp("2026-06-01T14:00:00+02:00"),
            "2026-06-01T12:00:00Z",
        )

    def test_negative_offset_is_correctly_converted_to_utc(self):
        # 08:00 a -05:00 == 13:00 UTC.
        self.assertEqual(
            _canonical_timestamp("2026-06-01T08:00:00-05:00"),
            "2026-06-01T13:00:00Z",
        )

    def test_naive_timestamp_without_offset_is_assumed_utc(self):
        # Comportement historique inchange -- jamais devine differemment.
        self.assertEqual(
            _canonical_timestamp("2026-06-01T00:00:00"),
            "2026-06-01T00:00:00Z",
        )

    def test_genuinely_different_instants_remain_different(self):
        self.assertNotEqual(
            _canonical_timestamp("2026-06-01T00:00:00Z"),
            _canonical_timestamp("2026-06-01T00:15:00Z"),
        )

    def test_invalid_format_raises_rather_than_being_silently_absorbed(self):
        with self.assertRaises(ValueError):
            _canonical_timestamp("pas-un-timestamp")


class TestMergeRecognizesSameInstantAcrossFormats(unittest.TestCase):
    """Scenarios demandes explicitement par Louis."""

    def test_z_vs_plus_00_00_is_recognized_as_the_same_candle(self):
        existing = {"2026-06-01T00:00:00Z": ("id-1", {
            "symbol": "XAUUSD", "timeframe": "M15", "timestamp": "2026-06-01T00:00:00Z",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        })}
        candles = [_candle("2026-06-01T00:00:00+00:00", o=100.0, h=101.0, l=99.0, c=100.5)]

        to_insert, to_update, collisions, unchanged = _merge_market_data(
            existing, "XAUUSD", "M15", candles
        )
        self.assertEqual(to_insert, [])
        self.assertEqual(collisions, 0)
        self.assertEqual(unchanged, 1)

    def test_same_timestamp_imported_twice_produces_no_duplicate(self):
        existing = {}
        first_pass, _, _, _ = _merge_market_data(existing, "XAUUSD", "M15", [_candle("2026-06-01T00:00:00Z")])
        for data in first_pass:
            existing[data["timestamp"]] = ("id-1", data)

        second_pass, to_update, collisions, unchanged = _merge_market_data(
            existing, "XAUUSD", "M15", [_candle("2026-06-01T00:00:00Z")]
        )
        self.assertEqual(second_pass, [])
        self.assertEqual(collisions, 0)
        self.assertEqual(unchanged, 1)
        self.assertEqual(len(existing), 1)  # toujours une seule bougie, jamais deux

    def test_csv_then_mt5_overlapping_range_creates_no_duplicate(self):
        # "CSV" : timestamps suffixes "Z" (convention historique csvImport.js).
        csv_candles = [_candle(f"2026-06-01T00:{m:02d}:00Z") for m in (0, 15, 30, 45)]
        existing = {}
        inserted, _, _, _ = _merge_market_data(existing, "XAUUSD", "M15", csv_candles)
        for data in inserted:
            existing[data["timestamp"]] = (f"id-{data['timestamp']}", data)
        self.assertEqual(len(existing), 4)

        # "MT5" : memes instants, mais suffixe "+00:00" (Candle.isoformat()).
        mt5_candles = [_candle(f"2026-06-01T00:{m:02d}:00+00:00") for m in (0, 15, 30, 45)]

        to_insert, to_update, collisions, unchanged = _merge_market_data(
            existing, "XAUUSD", "M15", mt5_candles
        )
        self.assertEqual(to_insert, [])  # rien de "nouveau" -- tout deja present sous un autre format
        self.assertEqual(collisions, 0)  # memes valeurs OHLC -> jamais une collision
        self.assertEqual(unchanged, 4)   # les 4 bougies reconnues comme deja existantes
        self.assertEqual(len(existing), 4)  # toujours 4, jamais 8

    def test_mt5_then_csv_overlapping_range_creates_no_duplicate(self):
        # Ordre inverse du test precedent -- la normalisation doit etre
        # symetrique, peu importe quel format arrive en premier.
        mt5_candles = [_candle(f"2026-06-01T00:{m:02d}:00+00:00") for m in (0, 15, 30, 45)]
        existing = {}
        inserted, _, _, _ = _merge_market_data(existing, "XAUUSD", "M15", mt5_candles)
        for data in inserted:
            existing[data["timestamp"]] = (f"id-{data['timestamp']}", data)
        self.assertEqual(len(existing), 4)

        csv_candles = [_candle(f"2026-06-01T00:{m:02d}:00Z") for m in (0, 15, 30, 45)]
        to_insert, to_update, collisions, unchanged = _merge_market_data(
            existing, "XAUUSD", "M15", csv_candles
        )
        self.assertEqual(to_insert, [])
        self.assertEqual(collisions, 0)
        self.assertEqual(unchanged, 4)
        self.assertEqual(len(existing), 4)

    def test_genuinely_different_instants_are_two_distinct_candles(self):
        existing = {}
        inserted, _, _, _ = _merge_market_data(existing, "XAUUSD", "M15", [_candle("2026-06-01T00:00:00Z")])
        for data in inserted:
            existing[data["timestamp"]] = ("id-1", data)

        to_insert, to_update, collisions, unchanged = _merge_market_data(
            existing, "XAUUSD", "M15", [_candle("2026-06-01T00:15:00+00:00")]
        )
        self.assertEqual(len(to_insert), 1)  # vraiment une nouvelle bougie, pas un doublon
        self.assertEqual(unchanged, 0)

    def test_utc_offset_overlap_is_also_recognized(self):
        # Le meme instant que 12:00 UTC, exprime avec un offset non nul.
        existing = {"2026-06-01T12:00:00Z": ("id-1", {
            "symbol": "XAUUSD", "timeframe": "M15", "timestamp": "2026-06-01T12:00:00Z",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        })}
        candles = [_candle("2026-06-01T14:00:00+02:00", o=100.0, h=101.0, l=99.0, c=100.5)]
        to_insert, to_update, collisions, unchanged = _merge_market_data(
            existing, "XAUUSD", "M15", candles
        )
        self.assertEqual(to_insert, [])
        self.assertEqual(collisions, 0)
        self.assertEqual(unchanged, 1)


class TestFrozenPilotSurvivesOverlappingReimport(unittest.TestCase):
    """Rejoue precisement le scenario reel qui a revele le bug : le
    dataset pilote XAUUSD M15 REEL (3400 bougies, deja stocke au format
    "Z" -- voir test_fixtures/xauusd_m15_frozen_pilot.json, etape 3) recoit
    un reimport chevauchant au format "+00:00" (comme le ferait
    /market-data/import-mt5). Doit rester EXACTEMENT 3400 bougies, avec
    `unchanged` qui les reconnait toutes, jamais un doublon."""

    @classmethod
    def setUpClass(cls):
        with open("test_fixtures/xauusd_m15_frozen_pilot.json", encoding="utf-8") as f:
            cls.fixture = json.load(f)

    def test_reimporting_the_real_pilot_with_plus_00_00_format_creates_zero_duplicates(self):
        # Etat existant = exactement le pilote fige, tel que reellement
        # stocke (timestamps "Z", format historique de l'import CSV).
        existing = {
            row["timestamp"]: (f"id-{i}", row)
            for i, row in enumerate(self.fixture["candles"])
        }
        self.assertEqual(len(existing), 3400)

        # Reimport chevauchant : les 500 premieres bougies du meme
        # pilote, memes valeurs OHLC, mais serialisees comme le ferait
        # Candle.timestamp via datetime.isoformat() (suffixe "+00:00").
        overlapping = [
            Candle(
                timestamp=row["timestamp"].replace("Z", "+00:00"),
                open=row["open"], high=row["high"], low=row["low"], close=row["close"],
                volume=row.get("volume") or 0, spread=row.get("spread"),
            )
            for row in self.fixture["candles"][:500]
        ]

        to_insert, to_update, collisions, unchanged = _merge_market_data(
            existing, self.fixture["symbol"], self.fixture["timeframe"], overlapping
        )

        self.assertEqual(to_insert, [])       # rien de "nouveau" -- tout deja present
        self.assertEqual(collisions, 0)       # memes valeurs OHLC -> jamais une collision
        self.assertEqual(unchanged, 500)      # les 500 bougies chevauchantes reconnues
        self.assertEqual(len(existing), 3400)  # TOUJOURS 3400 -- pas 3900, pas de doublon

        # Aucune valeur OHLC/volume/spread des bougies existantes n'a ete
        # alteree -- `existing` n'est mute par aucun code de ce test
        # (_merge_market_data ne touche jamais a `existing` lui-meme, elle
        # ne fait que le lire), donc une egalite stricte avec le fixture
        # d'origine prouve l'absence de toute alteration.
        restored = sorted((v[1] for v in existing.values()), key=lambda d: d["timestamp"])
        original = sorted(self.fixture["candles"], key=lambda d: d["timestamp"])
        self.assertEqual(restored, original)


if __name__ == "__main__":
    unittest.main()
