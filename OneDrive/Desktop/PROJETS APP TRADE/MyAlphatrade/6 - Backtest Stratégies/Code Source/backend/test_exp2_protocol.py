"""Tests -- exp2_protocol.py (D1/D2/D3). Valeurs attendues calculees a la main.

Series synthetiques M15 continues (une bougie tous les 15 min) demarrant le
2026-01-05T00:00:00Z (hiver, EST = UTC-5 : ouverture cash 14:30Z, cloture
21:00Z). Bougie d'indice i = 2026-01-05T00:00Z + 15 min * i.
  - evenement du 6 janvier : bougie de 14:30Z -> indice 96 + 58 = 154
  - evenement du 7 janvier : bougie de 14:30Z -> indice 192 + 58 = 250
"""
import hashlib
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import exp2_protocol as p
import gap_analysis

START = datetime(2026, 1, 5, tzinfo=timezone.utc)
N = 288  # 3 jours


def make_bars(price_fn, n=N):
    bars = []
    for i in range(n):
        ts = (START + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        o, h, l, c = price_fn(i)
        bars.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})
    return bars


def flat_with_step(i):
    price = 100.0 if i < 154 else 103.0    # gap +3 a l'ouverture du 6 janvier
    return price, price, price, price


def flat_with_step_then_fill(i):
    price = 100.0 if i < 154 else (103.0 if i < 160 else 99.0)  # revient sous 100 a l'indice 160
    return price, price, price, price


def trending(i):
    c = 100.0 + i
    return c, c + 0.5, c - 0.5, c


class TestObservationsFromBarsOnly(unittest.TestCase):
    def test_hand_computed_event_zone_maturity_and_real_horizon(self):
        obs = p.list_observations(make_bars(flat_with_step), horizon_bars=100)
        by_t = {o["t_event"]: o for o in obs}
        self.assertEqual(sorted(by_t), ["2026-01-06T14:30:00Z", "2026-01-07T14:30:00Z"])
        jan6 = by_t["2026-01-06T14:30:00Z"]
        self.assertEqual(jan6["zone"], "range")            # serie plate : ADX = 0
        self.assertTrue(jan6["mature"])                    # 154 + 100 = 254 <= 288
        self.assertEqual(jan6["horizon_min"], 99 * 15)     # ts[253] - ts[154] = 99 pas de 15 min
        jan7 = by_t["2026-01-07T14:30:00Z"]
        self.assertFalse(jan7["mature"])                   # 250 + 100 = 350 > 288
        self.assertIsNone(jan7["horizon_min"])

    def test_maturity_boundary_the_last_window_bar_may_be_the_last_bar_of_the_series(self):
        # evenement en indice 154, serie de 288 bougies : fenetre de 134 =
        # indices 154..287 (derniere bougie incluse) -> mure ; 135 -> non mure.
        bars = make_bars(flat_with_step)
        exact = {o["t_event"]: o for o in p.list_observations(bars, horizon_bars=134)}["2026-01-06T14:30:00Z"]
        self.assertTrue(exact["mature"])
        self.assertEqual(exact["horizon_min"], 133 * 15)
        one_more = {o["t_event"]: o for o in p.list_observations(bars, horizon_bars=135)}["2026-01-06T14:30:00Z"]
        self.assertFalse(one_more["mature"])

    def test_trending_series_gives_the_tendance_zone(self):
        obs = p.list_observations(make_bars(trending), horizon_bars=100)
        self.assertEqual({o["t_event"]: o["zone"] for o in obs}["2026-01-06T14:30:00Z"], "tendance")

    def test_select_eligible_filters_maturity_zone_and_prospective_start(self):
        obs = [
            {"t_event": "2026-09-17T14:30:00Z", "zone": "range", "mature": True, "horizon_min": 100},
            {"t_event": "2026-09-16T14:30:00Z", "zone": "range", "mature": True, "horizon_min": 100},       # avant le debut prospectif
            {"t_event": "2026-09-18T14:30:00Z", "zone": "tendance", "mature": False, "horizon_min": None},   # non mur
            {"t_event": "2026-09-19T14:30:00Z", "zone": "intermediaire", "mature": True, "horizon_min": 100},  # hors test
            {"t_event": "2026-09-20T14:30:00Z", "zone": "indisponible", "mature": True, "horizon_min": 100},
        ]
        self.assertEqual([o["t_event"] for o in p.select_eligible(obs)], ["2026-09-17T14:30:00Z"])
        self.assertEqual(len(p.select_eligible(obs, prospective_only=False)), 2)


class TestBlindCounter(unittest.TestCase):
    def test_counts_only_and_never_consults_an_outcome(self):
        bars = make_bars(flat_with_step)
        with mock.patch.object(gap_analysis, "find_fill_time", side_effect=AssertionError("issue consultee")):
            c = p.blind_counts(bars, prospective_start="2026-01-01T00:00:00Z", horizon_bars=100, minimum=1)
        self.assertEqual((c["eligible_range"], c["eligible_tendance"], c["not_mature"]), (1, 0, 1))
        for forbidden in ("filled", "fill_minutes", "median", "rmst"):
            self.assertFalse(any(forbidden in key for key in c), forbidden)
        self.assertFalse(c["trigger_reached"])  # tendance = 0

    def test_prospective_start_excludes_earlier_events_from_the_count(self):
        c = p.blind_counts(make_bars(flat_with_step), prospective_start="2026-01-07T00:00:00Z", horizon_bars=100, minimum=1)
        self.assertEqual((c["eligible_range"], c["eligible_tendance"], c["not_mature"]), (0, 0, 1))

    def test_prospective_start_itself_is_included(self):
        c = p.blind_counts(make_bars(flat_with_step), prospective_start="2026-01-06T14:30:00Z", horizon_bars=100, minimum=1)
        self.assertEqual(c["eligible_range"], 1)  # T_event == debut prospectif : inclus (>=)

    def test_trigger_needs_both_groups_at_the_minimum_inclusive(self):
        self.assertTrue(p.trigger_condition(60, 60))
        self.assertFalse(p.trigger_condition(59, 60))
        self.assertFalse(p.trigger_condition(60, 59))
        self.assertTrue(p.trigger_condition(200, 61))


class TestTauAndCanonicalList(unittest.TestCase):
    ELIGIBLE = [
        {"t_event": "2026-10-06T14:30:00Z", "zone": "tendance", "horizon_min": 43200},
        {"t_event": "2026-10-05T14:30:00Z", "zone": "range", "horizon_min": 42765},
    ]

    def test_tau_is_the_smallest_real_horizon(self):
        self.assertEqual(p.compute_tau(self.ELIGIBLE), 42765)
        with self.assertRaises(ValueError):
            p.compute_tau([])

    def test_intermediate_group_never_enters_tau_it_is_refused_not_ignored(self):
        lower = {"t_event": "2026-10-07T14:30:00Z", "zone": "intermediaire", "horizon_min": 40000}
        with self.assertRaises(ValueError):
            p.compute_tau(self.ELIGIBLE + [lower])
        with self.assertRaises(ValueError):
            p.compute_tau([{"t_event": "2026-10-07T14:30:00Z", "zone": "indisponible", "horizon_min": 40000}])

    def test_through_the_eligibility_filter_a_smaller_intermediate_horizon_does_not_lower_tau(self):
        obs = [
            {"t_event": "2026-10-05T14:30:00Z", "zone": "range", "mature": True, "horizon_min": 42765},
            {"t_event": "2026-10-06T14:30:00Z", "zone": "tendance", "mature": True, "horizon_min": 43200},
            {"t_event": "2026-10-07T14:30:00Z", "zone": "intermediaire", "mature": True, "horizon_min": 40000},
        ]
        self.assertEqual(p.compute_tau(p.select_eligible(obs, prospective_only=False)), 42765)

    def test_tau_requires_an_integer_real_horizon(self):
        for bad in (None, 1.5, True):
            with self.assertRaises(ValueError):
                p.compute_tau([{"t_event": "2026-10-05T14:30:00Z", "zone": "range", "horizon_min": bad}])

    def test_serialization_is_sorted_lf_utf8_and_matches_a_literal_hash(self):
        literal = "2026-10-05T14:30:00Z|range|42765\n2026-10-06T14:30:00Z|tendance|43200\n"
        self.assertEqual(p.serialize_eligible(self.ELIGIBLE), literal.encode("utf-8"))
        self.assertEqual(p.eligible_list_sha256(self.ELIGIBLE), hashlib.sha256(literal.encode("utf-8")).hexdigest())
        self.assertEqual(p.serialize_eligible(list(reversed(self.ELIGIBLE))), p.serialize_eligible(self.ELIGIBLE))  # ordre d'entree indifferent

    def test_ambiguous_fields_are_refused_not_coerced(self):
        for bad in (
            {"t_event": "2026-10-05 14:30:00", "zone": "range", "horizon_min": 1},      # T_event non canonique
            {"t_event": "2026-10-05T14:30:00Z", "zone": "intermediaire", "horizon_min": 1},
            {"t_event": "2026-10-05T14:30:00Z", "zone": "range", "horizon_min": 1.5},    # non entier
            {"t_event": "2026-10-05T14:30:00Z", "zone": "range", "horizon_min": True},
        ):
            with self.assertRaises(ValueError):
                p.serialize_eligible([bad])


class TestOutcomesAndPrimaryAnalysis(unittest.TestCase):
    def test_outcome_attached_only_after_selection_hand_computed(self):
        bars = make_bars(flat_with_step_then_fill)
        eligible = p.select_eligible(p.list_observations(bars, horizon_bars=100), prospective_only=False)
        jan6 = [o for o in eligible if o["t_event"] == "2026-01-06T14:30:00Z"]
        out = p.attach_outcomes(jan6, bars, horizon_bars=100)[0]
        self.assertTrue(out["filled"])
        self.assertEqual(out["fill_minutes"], (160 - 154) * 15)  # 90 min

    @staticmethod
    def synthetic_observations():
        base = datetime(2026, 10, 5, 14, 30, tzinfo=timezone.utc)
        obs = []
        for i in range(60):
            t = (base + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
            obs.append({"t_event": t, "zone": "range", "filled": i < 50, "fill_minutes": 15 if i < 50 else None})
            obs.append({"t_event": t, "zone": "tendance", "filled": i < 30, "fill_minutes": 300 if i < 30 else None})
        return obs

    def test_hand_computed_delta_and_decomposition(self):
        r = p.run_primary_analysis(self.synthetic_observations(), tau=1000, n_boot=300, master_seed=1)
        # range : (50*15 + 10*1000)/60 = 10750/60 ; tendance : (30*300 + 30*1000)/60 = 650
        self.assertAlmostEqual(r["descriptive"]["range"]["rmst"], 10750 / 60)
        self.assertAlmostEqual(r["descriptive"]["tendance"]["rmst"], 650.0)
        self.assertAlmostEqual(r["delta_rmst_range_minus_tendance"], 10750 / 60 - 650)
        self.assertAlmostEqual(r["delta_decomposition"]["not_filled_at_tau"], 10 / 60 * 1000 - 30 / 60 * 1000)
        self.assertAlmostEqual(r["delta_decomposition"]["filled_before_tau"], 12.5 - 150.0)
        self.assertAlmostEqual(
            r["delta_decomposition"]["not_filled_at_tau"] + r["delta_decomposition"]["filled_before_tau"],
            r["delta_rmst_range_minus_tendance"],
        )

    def test_verdict_statuses_and_sensitivities_are_reported(self):
        r = p.run_primary_analysis(self.synthetic_observations(), tau=1000, n_boot=300, master_seed=1)
        self.assertTrue(r["verdict"]["h1_supported"])             # IC exclut 0 (ecart tres net)
        self.assertLess(r["primary_ci_95"][1], 0)
        self.assertTrue(r["sensitivity_logrank"]["estimable"])
        self.assertTrue(r["sensitivity_logrank"]["significant_at_0_05"])
        self.assertEqual(r["sensitivity_block_bootstrap"]["n_valid"] + r["sensitivity_block_bootstrap"]["n_discarded"], 300)
        d = r["descriptive"]
        self.assertEqual((d["range"]["n_never_filled_in_horizon"], d["tendance"]["n_never_filled_in_horizon"]), (10, 30))
        self.assertEqual((d["range"]["n_filled_after_tau"], d["tendance"]["n_filled_after_tau"]), (0, 0))
        self.assertIn("vitesse typique ou a la traine", r["reading_clause"])

    def test_filled_after_tau_is_censored_at_tau_and_reported_separately(self):
        obs = self.synthetic_observations()
        obs[0] = {**obs[0], "filled": True, "fill_minutes": 1500}  # comble APRES tau=1000 : censure a tau, pas un comble
        d = p.run_primary_analysis(obs, tau=1000, n_boot=50, master_seed=1)["descriptive"]["range"]
        self.assertEqual(d["n_filled_after_tau"], 1)
        self.assertEqual(d["n_filled_by_tau"], 49)
        self.assertAlmostEqual(d["rmst"], (49 * 15 + 11 * 1000) / 60)

    def test_a_missing_group_is_an_error(self):
        only_range = [o for o in self.synthetic_observations() if o["zone"] == "range"]
        with self.assertRaises(ValueError):
            p.run_primary_analysis(only_range, tau=1000, n_boot=10)

    def test_analysis_is_reproducible_with_the_locked_seed(self):
        a = p.run_primary_analysis(self.synthetic_observations(), tau=1000, n_boot=200)
        b = p.run_primary_analysis(self.synthetic_observations(), tau=1000, n_boot=200)
        self.assertEqual(a["primary_ci_95"], b["primary_ci_95"])
        self.assertEqual(a["sensitivity_block_bootstrap"]["master_seed"], 20260918)

    def test_primary_and_block_bootstraps_use_the_two_locked_distinct_streams(self):
        r = p.run_primary_analysis(self.synthetic_observations(), tau=1000, n_boot=50)
        self.assertEqual(r["bootstrap_streams"], {"primary": "H1:iid", "blocks": "H1:blocs"})
        self.assertEqual(r["sensitivity_block_bootstrap"]["label"], "H1:blocs")


class TestAttestationAndTriggerRecord(unittest.TestCase):
    BARS = [{"timestamp": t, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0} for t in (
        "2026-09-16T00:15:00Z", "2026-09-16T00:30:00Z", "2026-09-16T00:45:00Z", "2026-09-17T00:00:00Z")]

    def test_later_bars_are_listed_one_by_one_and_flagged_not_hidden(self):
        a = p.attest_reference_state(self.BARS)
        self.assertEqual(a["last_closed_reference_bar"], "2026-09-16T00:30:00Z")
        self.assertEqual(a["later_bars"], [
            {"timestamp": "2026-09-16T00:45:00Z", "prospective": False},   # la bougie partielle : signalee, jamais masquee
            {"timestamp": "2026-09-17T00:00:00Z", "prospective": True},
        ])
        self.assertEqual((a["n_later_bars"], a["n_prospective_bars"]), (2, 1))
        self.assertFalse(a["reference"]["ok"])        # serie synthetique != reference reelle

    def test_series_used_stops_at_the_reference_and_never_includes_a_later_bar(self):
        a = p.attest_reference_state(self.BARS)
        self.assertEqual(a["series_used"]["up_to"], "2026-09-16T00:30:00Z")
        self.assertEqual(a["series_used"]["n"], 2)   # 00:15 et 00:30 seulement

    def test_attestation_never_claims_that_no_later_bar_exists(self):
        only_reference = self.BARS[:2]
        a = p.attest_reference_state(only_reference)
        self.assertEqual((a["later_bars"], a["n_later_bars"], a["n_prospective_bars"]), ([], 0, 0))

    def test_trigger_record_is_deterministic_lf_with_fixed_field_order(self):
        kwargs = dict(
            import_datetime_utc="2027-08-02T08:10:00Z", data_state_last_bar="2027-08-02T07:45:00Z",
            series_n=70000, series_sha256="ab" * 32,
            counts={"eligible_range": 61, "eligible_tendance": 104, "prospective_start": p.PROSPECTIVE_START},
            tau=42765, eligible_sha256="cd" * 32, code_commit="0123abc", journal_sha256="ef" * 32,
            reference_check={"ok": True, "n": 62521, "last_bar": "2026-09-16T00:30:00Z", "sha256": "12" * 32},
        )
        a, b = p.build_trigger_record(**kwargs), p.build_trigger_record(**kwargs)
        self.assertEqual(a, b)
        self.assertNotIn("\r", a)
        self.assertTrue(a.endswith("\n"))
        keys = [line.split(":")[0] for line in a.splitlines()]
        self.assertEqual(keys[:3], ["registre", "import_datetime_utc", "data_state_last_bar"])
        self.assertIn("tau_minutes: 42765\n", a)
        self.assertIn("reference_ok: true\n", a)
        self.assertIn("bootstrap_seed: 20260918\n", a)


if __name__ == "__main__":
    unittest.main()
