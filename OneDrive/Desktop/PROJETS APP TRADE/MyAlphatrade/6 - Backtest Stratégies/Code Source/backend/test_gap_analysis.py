"""Tests -- gap_analysis.py (2026-09-16). Fixtures synthetiques
deterministes (valeurs connues a la main) avant de lancer sur les vraies
donnees XAUUSD/NASDAQ."""
import unittest

from gap_analysis import (
    CASH_SESSION_HOURS_ET,
    aggregate_gap_stats,
    compute_cash_session_gaps,
    compute_d1_gaps,
    find_fill_time,
)


def d1(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c}


def m15(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c}


class TestComputeD1Gaps(unittest.TestCase):
    def test_simple_up_gap_on_a_weekday(self):
        bars = [
            d1("2026-01-05T00:00:00Z", 100, 101, 99, 100),   # lundi
            d1("2026-01-06T00:00:00Z", 102, 103, 101, 102),  # mardi -- gap haussier de +2
        ]
        gaps = compute_d1_gaps(bars)
        self.assertEqual(len(gaps), 1)
        g = gaps[0]
        self.assertEqual(g["gap"], 2)
        self.assertEqual(g["direction"], "up")
        self.assertFalse(g["is_weekend_or_holiday_gap"])
        self.assertEqual(g["calendar_days_since_prev"], 1)

    def test_down_gap(self):
        bars = [d1("2026-01-05T00:00:00Z", 100, 101, 99, 100), d1("2026-01-06T00:00:00Z", 98, 99, 97, 98)]
        gaps = compute_d1_gaps(bars)
        self.assertEqual(gaps[0]["direction"], "down")
        self.assertEqual(gaps[0]["gap"], -2)

    def test_weekend_gap_detected_from_real_calendar_distance(self):
        # Vendredi -> Lundi = 3 jours calendaires, jamais suppose : deduit
        # de l'ecart reel entre les deux timestamps.
        bars = [d1("2026-01-02T00:00:00Z", 100, 101, 99, 100), d1("2026-01-05T00:00:00Z", 103, 104, 102, 103)]
        gaps = compute_d1_gaps(bars)
        self.assertTrue(gaps[0]["is_weekend_or_holiday_gap"])
        self.assertEqual(gaps[0]["calendar_days_since_prev"], 3)

    def test_no_gap_produces_flat_direction(self):
        bars = [d1("2026-01-05T00:00:00Z", 100, 101, 99, 100), d1("2026-01-06T00:00:00Z", 100, 101, 99, 100)]
        gaps = compute_d1_gaps(bars)
        self.assertEqual(gaps[0]["direction"], "flat")
        self.assertEqual(gaps[0]["gap"], 0)


class TestFindFillTime(unittest.TestCase):
    def test_up_gap_filled_when_low_touches_prev_close(self):
        gap = {"timestamp": "2026-01-06T00:00:00Z", "prev_close": 100, "direction": "up"}
        bars = [
            m15("2026-01-06T00:00:00Z", 102, 103, 101.5, 102.5),  # pas encore comble
            m15("2026-01-06T00:15:00Z", 102, 102.5, 100.0, 101),  # comble ici (low touche 100)
            m15("2026-01-06T00:30:00Z", 101, 101.5, 100.5, 101),
        ]
        result = find_fill_time(gap, bars)
        self.assertTrue(result["filled"])
        self.assertEqual(result["filled_at"], "2026-01-06T00:15:00Z")
        self.assertAlmostEqual(result["fill_minutes"], 15.0)

    def test_down_gap_filled_when_high_touches_prev_close(self):
        gap = {"timestamp": "2026-01-06T00:00:00Z", "prev_close": 100, "direction": "down"}
        bars = [
            m15("2026-01-06T00:00:00Z", 98, 98.5, 97, 98),
            m15("2026-01-06T00:45:00Z", 98, 100.2, 97.5, 99),  # comble ici (high touche 100)
        ]
        result = find_fill_time(gap, bars)
        self.assertTrue(result["filled"])
        self.assertAlmostEqual(result["fill_minutes"], 45.0)

    def test_never_filled_within_horizon_is_explicit_not_guessed(self):
        # Gap haussier : prev_close est LOIN EN DESSOUS des prix actuels --
        # aucune bougie ne redescend jusque-la, jamais comble.
        gap = {"timestamp": "2026-01-06T00:00:00Z", "prev_close": 50, "direction": "up"}
        bars = [m15("2026-01-06T00:00:00Z", 102, 103, 101, 102)]
        result = find_fill_time(gap, bars)
        self.assertFalse(result["filled"])
        self.assertIsNone(result["filled_at"])
        self.assertIsNone(result["fill_minutes"])

    def test_horizon_bars_limit_is_respected(self):
        gap = {"timestamp": "2026-01-06T00:00:00Z", "prev_close": 100, "direction": "up"}
        # Le comblement existe mais APRES la limite d'horizon -- ne doit
        # jamais etre trouve/suppose au-dela.
        bars = [m15("2026-01-06T00:00:00Z", 200, 201, 199, 200)] * 5
        bars.append(m15("2026-01-06T01:15:00Z", 102, 103, 99, 102))  # comble, mais hors horizon=2
        result = find_fill_time(gap, bars, horizon_bars=2)
        self.assertFalse(result["filled"])


class TestCashSessionGaps(unittest.TestCase):
    def test_unknown_symbol_raises_rather_than_guessing_an_hour(self):
        with self.assertRaises(ValueError):
            compute_cash_session_gaps("SYMBOLE_INCONNU", [m15("2026-01-05T14:30:00Z", 1, 1, 1, 1)])

    def test_known_symbol_is_registered_explicitly(self):
        self.assertIn("US Tech 100", CASH_SESSION_HOURS_ET)

    def test_gap_computed_between_consecutive_cash_sessions(self):
        # 9h30 NY = 14h30 UTC en hiver (EST, UTC-5).
        bars = [
            m15("2026-01-05T13:30:00Z", 100, 101, 99, 100),
            m15("2026-01-05T14:30:00Z", 100.5, 101, 100, 100.5),  # ouverture cash lundi
            m15("2026-01-05T21:00:00Z", 100, 101, 99, 100),       # cloture cash lundi (16h ET = 21h UTC)
            m15("2026-01-06T14:30:00Z", 103, 104, 102, 103),      # ouverture cash mardi -- gap +3 vs 100
        ]
        gaps = compute_cash_session_gaps("US Tech 100", bars)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0]["gap"], 3.0)
        self.assertEqual(gaps[0]["prev_close"], 100)


class TestAggregateGapStats(unittest.TestCase):
    def test_splits_by_weekday_weekend_and_direction(self):
        enriched = [
            {"direction": "up", "is_weekend_or_holiday_gap": False, "filled": True, "fill_minutes": 15},
            {"direction": "up", "is_weekend_or_holiday_gap": False, "filled": True, "fill_minutes": 45},
            {"direction": "down", "is_weekend_or_holiday_gap": True, "filled": False, "fill_minutes": None},
        ]
        stats = aggregate_gap_stats(enriched)
        self.assertEqual(stats["all"]["count"], 3)
        self.assertEqual(stats["weekday_gaps"]["count"], 2)
        self.assertEqual(stats["weekend_or_holiday_gaps"]["count"], 1)
        self.assertEqual(stats["weekend_or_holiday_gaps"]["filled_pct"], 0.0)
        self.assertEqual(stats["up_gaps"]["fill_minutes_min"], 15)
        self.assertEqual(stats["up_gaps"]["fill_minutes_max"], 45)
        self.assertEqual(stats["up_gaps"]["fill_minutes_median"], 30)

    def test_empty_subset_reports_none_rather_than_dividing_by_zero(self):
        stats = aggregate_gap_stats([])
        self.assertEqual(stats["all"]["count"], 0)
        self.assertIsNone(stats["all"]["filled_pct"])
        self.assertIsNone(stats["all"]["fill_minutes_min"])


if __name__ == "__main__":
    unittest.main()
