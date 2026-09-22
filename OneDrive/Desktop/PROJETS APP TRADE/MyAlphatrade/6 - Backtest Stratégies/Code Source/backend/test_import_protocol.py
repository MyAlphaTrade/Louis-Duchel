"""Tests -- import_protocol.py (D5). Valeurs attendues calculees a la main."""
import inspect
import json
import os
import random
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

from import_protocol import (
    KNOWN_PARTIAL_BARS, ImportAnomaly, append_journal_entry, canonical_ts, classify_candles, classify_collisions,
    compute_import_window, format_journal_entry, guarded_import, interval_report, last_closed_bar_open,
    plan_import, preflight_check, to_canonical,
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


FIELDS = ("open", "high", "low", "close", "volume", "spread")
PARTIAL = "2026-09-16T00:45:00Z"
P_OHLC = KNOWN_PARTIAL_BARS[PARTIAL]


def bar(ts, o=100.0, h=101.0, l=99.0, c=100.5, volume=10, spread=2):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": volume, "spread": spread}


def partial_bar():
    return bar(PARTIAL, P_OHLC["open"], P_OHLC["high"], P_OHLC["low"], P_OHLC["close"], volume=7)


def closed_version_of_partial():
    return bar(PARTIAL, 28997.4, 29003.0, 28990.1, 28999.2, volume=912)


def store(*bars):
    return {b["timestamp"]: dict(b) for b in bars}


def rec(old_bar, new_bar):
    return {"timestamp": old_bar["timestamp"], "old": {f: old_bar[f] for f in FIELDS}, "new": {f: new_bar[f] for f in FIELDS}}


class TestCollisions(unittest.TestCase):
    LAST = PARTIAL

    def test_only_the_identified_partial_last_bar_is_an_expected_collision(self):
        r = classify_collisions([rec(partial_bar(), closed_version_of_partial())], self.LAST)
        self.assertEqual((len(r["expected"]), r["anomalies"]), (1, []))

    def test_no_collision_at_all_is_fine(self):
        self.assertEqual(preflight_check([], self.LAST), {"expected": [], "anomalies": []})

    def test_any_earlier_bar_is_an_anomaly_and_aborts_before_writing(self):
        earlier = bar("2026-09-16T00:30:00Z")
        with self.assertRaises(ImportAnomaly) as ctx:
            preflight_check([rec(partial_bar(), closed_version_of_partial()), rec(earlier, bar(earlier["timestamp"], c=100.7))], self.LAST)
        self.assertIn("2026-09-16T00:30:00Z", str(ctx.exception))
        self.assertIn("abandonne avant ecriture", str(ctx.exception))
        self.assertIn("aucun ecrasement", str(ctx.exception))

    def test_a_collision_on_an_already_closed_last_bar_is_a_blocking_anomaly(self):
        # le cas ajoute par R1 : derniere bougie stockee, non identifiee comme partielle
        closed = bar("2026-10-01T07:45:00Z")
        with self.assertRaises(ImportAnomaly) as ctx:
            preflight_check([rec(closed, bar(closed["timestamp"], c=100.6))], closed["timestamp"])
        self.assertIn("close 100.5 -> 100.6", str(ctx.exception))

    def test_partial_identification_is_bound_to_the_stored_ohlc(self):
        # meme horodatage, mais la bougie stockee n'est plus la version partielle identifiee
        with self.assertRaises(ImportAnomaly):
            preflight_check([rec(closed_version_of_partial(), bar(PARTIAL, c=1.0))], self.LAST)

    def test_partial_identification_only_applies_to_the_last_stored_bar(self):
        with self.assertRaises(ImportAnomaly):
            preflight_check([rec(partial_bar(), closed_version_of_partial())], "2026-09-16T01:00:00Z")

    def test_report_carries_old_and_new_ohlc_and_informative_volume_and_spread(self):
        closed = bar("2026-10-01T07:45:00Z", volume=10, spread=2)
        with self.assertRaises(ImportAnomaly) as ctx:
            preflight_check([rec(closed, bar(closed["timestamp"], h=101.5, volume=11, spread=3))], closed["timestamp"])
        detail = ctx.exception.details["anomalies"][0]
        self.assertEqual((detail["old"]["high"], detail["new"]["high"]), (101.0, 101.5))
        self.assertEqual((detail["old"]["volume"], detail["new"]["volume"], detail["old"]["spread"], detail["new"]["spread"]), (10, 11, 2, 3))
        self.assertIn("informatif", str(ctx.exception))


class TestPlanImport(unittest.TestCase):
    LAST = bar("2026-10-01T07:45:00Z")
    NEW_1 = bar("2026-10-01T08:00:00Z")
    NEW_2 = bar("2026-10-01T08:15:00Z")

    def test_identical_overlap_is_unchanged_and_nothing_is_written(self):
        plan = plan_import(store(self.LAST), [dict(self.LAST), self.NEW_1, self.NEW_2], self.LAST["timestamp"])
        self.assertEqual((plan["unchanged"], plan["to_update"], plan["expected_collisions"]), (1, [], []))
        self.assertEqual([c["timestamp"] for c in plan["to_insert"]], ["2026-10-01T08:00:00Z", "2026-10-01T08:15:00Z"])

    def test_volume_or_spread_difference_alone_is_not_a_collision(self):
        plan = plan_import(store(self.LAST), [bar(self.LAST["timestamp"], volume=999, spread=9), self.NEW_1], self.LAST["timestamp"])
        self.assertEqual((plan["unchanged"], plan["to_update"]), (1, []))

    def test_a_collision_on_a_closed_bar_stops_the_import(self):
        with self.assertRaises(ImportAnomaly) as ctx:
            plan_import(store(self.LAST), [bar(self.LAST["timestamp"], c=100.6), self.NEW_1], self.LAST["timestamp"])
        self.assertEqual(ctx.exception.details["anomalies"][0]["new"]["close"], 100.6)

    def test_every_ohlc_field_alone_is_a_collision_and_there_is_no_numeric_tolerance(self):
        for field in ("open", "high", "low", "close"):
            changed = dict(self.LAST)
            changed[field] = self.LAST[field] + 1e-9
            with self.assertRaises(ImportAnomaly, msg=field):
                plan_import(store(self.LAST), [changed], self.LAST["timestamp"])

    def test_start_date_must_equal_the_last_stored_bar_earlier_or_later_is_refused(self):
        # le lot est coherent avec son propre start_date : seule la regle "start_date == derniere bougie stockee" peut refuser
        cases = (
            ("2026-10-01T07:30:00Z", [bar("2026-10-01T07:30:00Z"), dict(self.LAST)]),   # anterieur
            ("2020-01-01T00:00:00Z", [bar("2020-01-01T00:00:00Z"), dict(self.LAST)]),   # tres anterieur
            ("2026-10-01T08:00:00Z", [self.NEW_1]),                                     # posterieur : une bougie serait sautee
        )
        for start, candles in cases:
            with self.assertRaisesRegex(ImportAnomaly, "different de la derniere bougie stockee"):
                plan_import(store(self.LAST), candles, start)

    def test_start_date_is_compared_as_an_instant_not_as_text(self):
        plan = plan_import(store(self.LAST), [dict(self.LAST), self.NEW_1], "2026-10-01T07:45:00+00:00")
        self.assertEqual(plan["last_stored"], "2026-10-01T07:45:00Z")

    def test_a_candle_earlier_than_start_date_is_refused(self):
        with self.assertRaisesRegex(ImportAnomaly, "anterieure a start_date"):
            plan_import(store(self.LAST), [bar("2026-10-01T07:30:00Z"), dict(self.LAST)], self.LAST["timestamp"])

    def test_an_empty_store_is_refused(self):
        with self.assertRaises(ImportAnomaly):
            plan_import({}, [dict(self.LAST)], self.LAST["timestamp"])

    def test_keys_in_any_iso_format_are_matched_by_instant(self):
        existing = {"2026-10-01T07:45:00+00:00": dict(self.LAST)}
        plan = plan_import(existing, [dict(self.LAST), self.NEW_1], self.LAST["timestamp"])
        self.assertEqual(plan["unchanged"], 1)

    def test_first_import_exception_the_identified_partial_bar_may_be_updated(self):
        existing = store(bar("2026-09-16T00:30:00Z"), partial_bar())
        candles = [closed_version_of_partial(), bar("2026-09-16T01:00:00Z"), bar("2026-09-16T01:15:00Z")]
        plan = plan_import(existing, candles, PARTIAL)
        self.assertEqual(plan["expected_collisions"], [PARTIAL])
        self.assertEqual(plan["to_update"][0]["close"], 28999.2)
        self.assertEqual(len(plan["to_insert"]), 2)

    def test_the_exception_is_consumed_once_the_closed_version_is_stored(self):
        # apres le premier import, la bougie 00:45 stockee est la version cloturee : plus de collision admise
        existing = store(closed_version_of_partial())
        with self.assertRaises(ImportAnomaly):
            plan_import(existing, [bar(PARTIAL, c=5.0)], PARTIAL)

    def test_an_identical_refetch_of_the_partial_bar_is_simply_unchanged(self):
        plan = plan_import(store(partial_bar()), [partial_bar(), bar("2026-09-16T01:00:00Z")], PARTIAL)
        self.assertEqual((plan["unchanged"], plan["expected_collisions"]), (1, []))


class Spy:
    def __init__(self):
        self.calls = []

    def __call__(self, plan):
        self.calls.append(plan)


class TestNoWriteBeforeTheChecks(unittest.TestCase):
    LAST = bar("2026-10-01T07:45:00Z")

    def rejections(self):
        last = self.LAST["timestamp"]
        return [
            ("collision sur bougie cloturee", store(self.LAST), [bar(last, c=100.6)], last),
            ("start_date anterieur", store(self.LAST), [dict(self.LAST)], "2026-10-01T07:30:00Z"),
            ("start_date posterieur", store(self.LAST), [dict(self.LAST)], "2026-10-01T08:00:00Z"),
            ("bougie anterieure au start_date", store(self.LAST), [bar("2026-10-01T07:30:00Z"), dict(self.LAST)], last),
            ("serie vide", {}, [dict(self.LAST)], last),
            ("exception partielle deja consommee", store(closed_version_of_partial()), [bar(PARTIAL, c=5.0)], PARTIAL),
        ]

    def test_the_writer_is_never_called_when_the_import_is_refused(self):
        for name, existing, candles, start in self.rejections():
            spy = Spy()
            with self.assertRaises(ImportAnomaly, msg=name):
                guarded_import(existing, candles, start, spy)
            self.assertEqual(spy.calls, [], name)

    def test_the_writer_is_called_exactly_once_with_the_plan_after_a_valid_check(self):
        spy = Spy()
        plan = guarded_import(store(self.LAST), [dict(self.LAST), bar("2026-10-01T08:00:00Z")], self.LAST["timestamp"], spy)
        self.assertEqual(len(spy.calls), 1)
        self.assertIs(spy.calls[0], plan)

    def test_a_real_database_is_left_byte_identical_by_every_refusal(self):
        def make_db(existing):
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE TABLE bars (ts TEXT PRIMARY KEY, data TEXT)")
            for ts, data in existing.items():
                conn.execute("INSERT INTO bars VALUES (?, ?)", (canonical_ts(ts), json.dumps(data, sort_keys=True)))
            return conn

        def dump(conn):
            return conn.execute("SELECT ts, data FROM bars ORDER BY ts").fetchall()

        def writer_for(conn):
            def write(plan):
                for c in plan["to_insert"]:
                    conn.execute("INSERT INTO bars VALUES (?, ?)", (c["timestamp"], json.dumps(c, sort_keys=True)))
                for c in plan["to_update"]:
                    conn.execute("UPDATE bars SET data = ? WHERE ts = ?", (json.dumps(c, sort_keys=True), c["timestamp"]))
            return write

        for name, existing, candles, start in self.rejections():
            conn = make_db(existing)
            before = dump(conn)
            with self.assertRaises(ImportAnomaly, msg=name):
                guarded_import(existing, candles, start, writer_for(conn))
            self.assertEqual(dump(conn), before, name)
        # et un import valide, lui, ecrit bien (insertion + mise a jour de la bougie partielle identifiee)
        existing = store(partial_bar())
        conn = make_db(existing)
        before = dump(conn)
        guarded_import(existing, [closed_version_of_partial(), bar("2026-09-16T01:00:00Z")], PARTIAL, writer_for(conn))
        after = dump(conn)
        self.assertNotEqual(after, before)
        self.assertEqual(len(after), 2)
        self.assertEqual(json.loads(dict(after)[PARTIAL])["close"], 28999.2)


class TestPartialBarExceptionIsClosedByConstruction(unittest.TestCase):
    """Durcissement 2026-09-21 : l'exception 00:45 doit etre une exception
    historique UNIQUE et bornee, jamais un mecanisme general de tolerance."""

    def test_the_table_contains_exactly_the_one_locked_bar(self):
        self.assertEqual(dict(KNOWN_PARTIAL_BARS), {
            "2026-09-16T00:45:00Z": {"open": 28997.4, "high": 29001.9, "low": 28991.9, "close": 28993.65},
        })

    def test_the_table_and_its_entry_are_immutable(self):
        self.assertIsInstance(KNOWN_PARTIAL_BARS, MappingProxyType)
        self.assertIsInstance(KNOWN_PARTIAL_BARS[PARTIAL], MappingProxyType)
        with self.assertRaises(TypeError):
            KNOWN_PARTIAL_BARS["2026-10-01T00:00:00Z"] = {"open": 1, "high": 1, "low": 1, "close": 1}
        with self.assertRaises(TypeError):
            KNOWN_PARTIAL_BARS[PARTIAL]["close"] = 0.0
        with self.assertRaises(TypeError):
            del KNOWN_PARTIAL_BARS[PARTIAL]
        # rien de tout cela n'a modifie la table (verification apres coup, au cas ou l'un des appels ci-dessus aurait reussi)
        self.assertEqual(dict(KNOWN_PARTIAL_BARS), {PARTIAL: dict(P_OHLC)})

    def test_no_function_of_the_module_accepts_a_parameter_to_designate_a_partial_bar(self):
        for fn in (classify_collisions, preflight_check, plan_import, guarded_import):
            params = inspect.signature(fn).parameters
            self.assertNotIn("partial_bars", params, fn.__name__)
            self.assertNotIn("partial", " ".join(params), fn.__name__)

    def test_a_caller_cannot_widen_the_exception_via_a_keyword_argument(self):
        other = "2026-10-01T07:45:00Z"
        # meme si un appelant tente de passer une table de son cru, la signature ne l'accepte pas
        with self.assertRaises(TypeError):
            plan_import(store(bar(other)), [bar(other, c=999)], other, partial_bars={other: {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}})
        with self.assertRaises(TypeError):
            preflight_check([rec(bar(other), bar(other, c=999))], other, partial_bars={})

    def test_an_unrelated_bar_can_never_be_tolerated_through_the_default_path(self):
        other = "2026-10-01T07:45:00Z"
        with self.assertRaises(ImportAnomaly):
            plan_import(store(bar(other)), [bar(other, c=999)], other)

    def test_the_exception_stays_bound_to_the_exact_timestamp_and_exact_ohlc_after_hardening(self):
        # rejoue les 4 garanties du sondage methodologique : timestamp exact, OHLC exact,
        # doit etre la derniere bougie stockee, et l'exception se consomme une fois remplacee.
        self.assertEqual(
            plan_import(store(partial_bar()), [closed_version_of_partial()], PARTIAL)["expected_collisions"],
            [PARTIAL])
        with self.assertRaises(ImportAnomaly):
            plan_import(store(closed_version_of_partial()), [bar(PARTIAL, c=1.0)], PARTIAL)   # OHLC different -> consommee
        other = "2026-09-16T01:00:00Z"
        with self.assertRaises(ImportAnomaly):
            plan_import(store(bar(other, *P_OHLC.values())), [bar(other, c=1.0)], other)       # autre horodatage, meme OHLC


class TestParityWithTheMergeLayerOfMain(unittest.TestCase):
    def test_canonical_timestamp_is_the_same_instant_rule_as_main(self):
        import main
        for raw in ("2026-10-01T07:45:00Z", "2026-10-01T07:45:00+00:00", "2026-10-01T09:45:00+02:00",
                    "2026-10-01T07:45:00", "2026-10-01T03:45:00-04:00"):
            self.assertEqual(canonical_ts(raw), main._canonical_timestamp(raw), raw)

    def test_classification_counts_match_merge_market_data_on_random_cases(self):
        import main
        rng = random.Random(11)
        base = datetime(2026, 10, 1, tzinfo=timezone.utc)
        for _ in range(25):
            existing_bars = []
            for i in range(30):
                t = (base + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
                existing_bars.append(bar(t, o=100 + rng.random(), h=102 + rng.random(), l=98 + rng.random(), c=100 + rng.random()))
            candles = []
            for i in range(10, 45):
                t = base + timedelta(minutes=15 * i)
                text = t.strftime("%Y-%m-%dT%H:%M:%SZ") if rng.random() < 0.5 else t.isoformat()
                if i < 30:
                    src = existing_bars[i]
                    mode = rng.choice(("same", "same", "diff"))
                    candles.append(bar(text, src["open"], src["high"], src["low"], src["close"] + (0.01 if mode == "diff" else 0)))
                else:
                    candles.append(bar(text))
            existing_main = {b["timestamp"]: (f"id{i}", dict(b)) for i, b in enumerate(existing_bars)}
            to_insert, _, collisions, unchanged = main._merge_market_data(
                existing_main, "US Tech 100", "M15", [main.Candle(**c) for c in candles])
            mine_insert, mine_collisions, mine_unchanged = classify_candles(
                {canonical_ts(b["timestamp"]): b for b in existing_bars}, candles)
            self.assertEqual((len(mine_insert), len(mine_collisions), mine_unchanged), (len(to_insert), collisions, unchanged))


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
