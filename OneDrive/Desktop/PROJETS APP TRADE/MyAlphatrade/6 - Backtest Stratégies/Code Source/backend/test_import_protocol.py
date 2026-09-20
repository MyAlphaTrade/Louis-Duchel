"""Tests -- import_protocol.py (D5). Valeurs attendues calculees a la main."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from import_protocol import (
    ImportAnomaly, append_journal_entry, classify_collisions, compute_import_window,
    format_journal_entry, interval_report, last_closed_bar_open, preflight_check, to_canonical,
)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class TestLastClosedBar(unittest.TestCase):
    def test_partial_quarter_hour_goes_back_to_the_previous_closed_bar(self):
        # 09:07:30 -> la bougie 09:00 est en formation ; la derniere close ouvre a 08:45
        self.assertEqual(last_closed_bar_open(utc(2026, 10, 1, 9, 7, 30)), utc(2026, 10, 1, 8, 45))

    def test_exactly_on_a_boundary_the_bar_that_just_closed_counts(self):
        # 09:15:00 pile : la bougie 09:00 vient de clore
        self.assertEqual(last_closed_bar_open(utc(2026, 10, 1, 9, 15, 0)), utc(2026, 10, 1, 9, 0))

    def test_the_real_incident_at_0047_would_have_excluded_the_0045_bar(self):
        # 16/09 a 00:47:17 : la bougie 00:45 etait en formation -> derniere close = 00:30
        self.assertEqual(last_closed_bar_open(utc(2026, 9, 16, 0, 47, 17)), utc(2026, 9, 16, 0, 30))

    def test_naive_datetime_is_refused(self):
        with self.assertRaises(ValueError):
            last_closed_bar_open(datetime(2026, 10, 1, 9, 7))

    def test_non_utc_offset_is_converted(self):
        tz2 = timezone(timedelta(hours=2))
        self.assertEqual(last_closed_bar_open(datetime(2026, 10, 1, 11, 7, tzinfo=tz2)), utc(2026, 10, 1, 8, 45))


class TestImportWindow(unittest.TestCase):
    def test_window_starts_at_the_last_stored_bar_and_ends_at_the_last_closed_bar(self):
        w = compute_import_window("2026-09-16T00:45:00Z", utc(2026, 10, 1, 8, 10))
        self.assertEqual(w["start_date"], "2026-09-16T00:45:00+00:00")
        self.assertEqual(w["end_date"], "2026-10-01T07:45:00+00:00")  # 08:00 - 15 min

    def test_nothing_to_import_is_an_error_not_an_empty_default(self):
        with self.assertRaises(ValueError):
            compute_import_window("2026-10-01T08:00:00Z", utc(2026, 10, 1, 8, 10))  # derniere close = 07:45

    def test_refreshing_only_the_last_bar_is_allowed(self):
        w = compute_import_window("2026-10-01T07:45:00Z", utc(2026, 10, 1, 8, 10))
        self.assertEqual(w["start_date"], w["end_date"])

    def test_dates_are_never_naive(self):
        w = compute_import_window("2026-09-16T00:45:00Z", utc(2026, 10, 1, 8, 10))
        for v in w.values():
            self.assertTrue(v.endswith("+00:00"))


class TestCollisions(unittest.TestCase):
    LAST = "2026-09-16T00:45:00Z"

    def test_only_the_last_stored_bar_is_an_expected_collision(self):
        r = classify_collisions([self.LAST], self.LAST)
        self.assertEqual((r["expected"], r["anomalies"]), ([self.LAST], []))

    def test_no_collision_at_all_is_fine(self):
        self.assertEqual(preflight_check([], self.LAST), {"expected": [], "anomalies": []})

    def test_any_earlier_bar_is_an_anomaly_and_aborts_before_writing(self):
        with self.assertRaises(ImportAnomaly) as ctx:
            preflight_check([self.LAST, "2026-09-16T00:30:00Z"], self.LAST)
        self.assertIn("2026-09-16T00:30:00Z", str(ctx.exception))
        self.assertIn("abandonne avant ecriture", str(ctx.exception))


class TestIntervalReport(unittest.TestCase):
    def test_weekend_gap_is_listed_and_regular_steps_are_not(self):
        bars = [{"timestamp": t} for t in (
            "2026-09-11T21:45:00Z", "2026-09-11T22:00:00Z",   # +15
            "2026-09-13T22:00:00Z",                          # +2880 (48 h)
            "2026-09-13T22:15:00Z",                          # +15
        )]
        r = interval_report(bars)
        self.assertEqual(r["max_interval_minutes"], 2880)
        self.assertEqual(r["intervals_over_threshold"], [("2026-09-11T22:00:00Z", "2026-09-13T22:00:00Z", 2880)])

    def test_exactly_60_minutes_is_not_over_the_threshold(self):
        bars = [{"timestamp": "2026-09-11T10:00:00Z"}, {"timestamp": "2026-09-11T11:00:00Z"}]
        self.assertEqual(interval_report(bars)["intervals_over_threshold"], [])


ENTRY_KWARGS = dict(
    import_datetime_utc="2026-10-01T08:10:00Z", symbol="US Tech 100", timeframe="M15",
    requested_start="2026-09-16T00:45:00+00:00", requested_end="2026-10-01T07:45:00+00:00",
    inserted=1434, updated=1, unchanged=0, collision_timestamps=["2026-09-16T00:45:00Z"],
    first_bar="2024-01-22T10:30:00Z", last_bar="2026-10-01T07:45:00Z", series_n=63955,
    series_sha256="ab" * 32, reference_check={"ok": True, "sha256": "cd" * 32},
    intervals={"max_interval_minutes": 2880, "threshold_minutes": 60,
               "intervals_over_threshold": [("2026-09-18T21:45:00Z", "2026-09-20T22:00:00Z", 2895)]},
)


class TestJournal(unittest.TestCase):
    def test_entry_is_deterministic_lf_only_with_the_locked_fields_in_order(self):
        a, b = format_journal_entry(**ENTRY_KWARGS), format_journal_entry(**ENTRY_KWARGS)
        self.assertEqual(a, b)
        self.assertNotIn("\r", a)
        keys = [line.split(":")[0] for line in a.splitlines() if line and not line.startswith(("=", " "))]
        self.assertEqual(keys, [
            "import_datetime_utc", "symbol", "timeframe", "requested_start", "requested_end", "inserted",
            "updated", "unchanged", "collisions", "first_stored_bar", "last_stored_bar", "series_n",
            "series_sha256", "reference_ok", "reference_sha256", "max_interval_minutes", "intervals_over_60min",
        ])
        self.assertIn("collisions: 1 [2026-09-16T00:45:00Z]", a)
        self.assertIn("  - 2026-09-18T21:45:00Z -> 2026-09-20T22:00:00Z (2895 min)", a)

    def test_append_never_rewrites_previous_entries(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "journal.txt")
            first = format_journal_entry(**ENTRY_KWARGS)
            append_journal_entry(p, first)
            before = open(p, "rb").read()
            append_journal_entry(p, format_journal_entry(**{**ENTRY_KWARGS, "import_datetime_utc": "2026-11-02T08:10:00Z"}))
            after = open(p, "rb").read()
            self.assertTrue(after.startswith(before))          # entree precedente intacte, octet pour octet
            self.assertEqual(after.count(b"=== IMPORT ==="), 2)
            self.assertNotIn(b"\r", after)

    def test_append_refuses_crlf_and_ambiguous_existing_journal(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "journal.txt")
            with self.assertRaises(ValueError):
                append_journal_entry(p, "abc\r\n")
            with open(p, "wb") as f:
                f.write(b"sans saut de ligne final")
            with self.assertRaises(ValueError):
                append_journal_entry(p, "ok\n")


class TestCanonical(unittest.TestCase):
    def test_canonical_utc_form(self):
        self.assertEqual(to_canonical(utc(2026, 10, 1, 7, 45)), "2026-10-01T07:45:00Z")


if __name__ == "__main__":
    unittest.main()
