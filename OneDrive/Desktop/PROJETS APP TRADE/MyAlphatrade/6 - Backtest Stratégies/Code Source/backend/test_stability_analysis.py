"""Tests -- stability_analysis.py (D4). Valeurs attendues calculees a la main."""
import inspect
import unittest
from datetime import datetime, timedelta, timezone

import exp2_protocol
import stability_analysis as sa
from test_exp2_protocol import make_bars

UTC = timezone.utc


def p_list_observations(bars):
    return exp2_protocol.list_observations(bars, horizon_bars=100)


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def obs(start, i, zone, filled, fill_minutes):
    return {"t_event": ts(start + timedelta(days=i)), "zone": zone, "filled": filled, "fill_minutes": fill_minutes}


def group(start, zone, n, n_filled, fill_minutes):
    return [obs(start, i, zone, i < n_filled, fill_minutes if i < n_filled else None) for i in range(n)]


S1_2025 = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
S2_2024 = datetime(2024, 7, 2, 14, 30, tzinfo=UTC)


class TestPeriods(unittest.TestCase):
    def test_semester_boundaries_utc(self):
        self.assertEqual(sa.period_of("2024-01-22T14:30:00Z"), "2024-S1")
        self.assertEqual(sa.period_of("2024-06-30T23:59:59Z"), "2024-S1")
        self.assertEqual(sa.period_of("2024-07-01T00:00:00Z"), "2024-S2")
        self.assertEqual(sa.period_of("2025-12-31T23:59:59Z"), "2025-S2")
        self.assertEqual(sa.period_of("2026-01-01T00:00:00Z"), "2026-S1")
        self.assertEqual(sa.period_of("2026-08-14T13:30:00Z"), "2026-S2")

    def test_dates_outside_the_six_fixed_periods_or_non_canonical_are_refused(self):
        for bad in ("2023-12-31T23:59:59Z", "2027-01-01T00:00:00Z", "2025-01-02 14:30:00", "2025-01-02T14:30:00+00:00"):
            with self.assertRaises(ValueError):
                sa.period_of(bad)

    def test_the_six_periods_are_the_locked_ones(self):
        self.assertEqual(sa.PERIODS, ("2024-S1", "2024-S2", "2025-S1", "2025-S2", "2026-S1", "2026-S2"))
        self.assertEqual(sa.MIN_N_PER_GROUP, 30)


class TestReadability(unittest.TestCase):
    def test_threshold_is_inclusive_on_each_group(self):
        pop = group(S2_2024, "range", 30, 20, 15) + group(S2_2024, "tendance", 30, 10, 300)
        c = sa.period_counts(pop)
        self.assertEqual(c["2024-S2"], {"range": 30, "tendance": 30})
        self.assertTrue(sa.is_readable(c["2024-S2"]))
        short = group(S2_2024, "range", 29, 20, 15) + group(S2_2024, "tendance", 60, 10, 300)
        self.assertFalse(sa.is_readable(sa.period_counts(short)["2024-S2"]))

    def test_all_six_periods_are_always_present_in_the_counts(self):
        c = sa.period_counts([])
        self.assertEqual(list(c), list(sa.PERIODS))
        self.assertTrue(all(v == {"range": 0, "tendance": 0} for v in c.values()))

    def test_an_unreadable_period_yields_counts_only_and_no_statistic(self):
        pop = group(S1_2025, "range", 29, 20, 15) + group(S1_2025, "tendance", 60, 10, 300)
        r = sa.run_stability_analysis(pop, tau=1000, n_boot=50)
        self.assertEqual(r["periods"]["2025-S1"], {"readable": False, "n_range": 29, "n_tendance": 60})
        self.assertTrue(all(v["readable"] is False for v in r["periods"].values()))

    def test_readability_is_a_rule_not_a_selection_a_period_never_borrows_from_another(self):
        # 20 + 20 dans deux semestres voisins : aucune fusion, aucune des deux n'est lisible.
        pop = (group(S2_2024, "range", 20, 10, 15) + group(S2_2024, "tendance", 40, 10, 300)
               + group(S1_2025, "range", 20, 10, 15) + group(S1_2025, "tendance", 40, 10, 300))
        r = sa.run_stability_analysis(pop, tau=1000, n_boot=50)["periods"]
        self.assertFalse(r["2024-S2"]["readable"])
        self.assertFalse(r["2025-S1"]["readable"])


class TestReadablePeriod(unittest.TestCase):
    @staticmethod
    def population():
        # range : 24 combles a 15 min, 6 jamais combles ; tendance : 15 combles a 300 min, 15 jamais
        return group(S1_2025, "range", 30, 24, 15) + group(S1_2025, "tendance", 30, 15, 300)

    def test_hand_computed_delta_decomposition_and_rates(self):
        r = sa.run_stability_analysis(self.population(), tau=1000, n_boot=100)["periods"]["2025-S1"]
        # RMST range = (24*15 + 6*1000)/30 = 212 ; tendance = (15*300 + 15*1000)/30 = 650
        self.assertAlmostEqual(r["descriptive"]["range"]["rmst"], 212.0)
        self.assertAlmostEqual(r["descriptive"]["tendance"]["rmst"], 650.0)
        self.assertAlmostEqual(r["delta_rmst_range_minus_tendance"], -438.0)
        self.assertAlmostEqual(r["delta_decomposition"]["not_filled_at_tau"], 6 / 30 * 1000 - 15 / 30 * 1000)  # -300
        self.assertAlmostEqual(r["delta_decomposition"]["filled_before_tau"], 12.0 - 150.0)                    # -138
        self.assertAlmostEqual(r["descriptive"]["range"]["fill_rate_at_tau"], 0.8)
        self.assertAlmostEqual(r["descriptive"]["tendance"]["fill_rate_at_tau"], 0.5)
        self.assertEqual(r["descriptive"]["range"]["n_never_filled_in_horizon"], 6)
        self.assertEqual(r["descriptive"]["tendance"]["n_never_filled_in_horizon"], 15)
        self.assertEqual((r["n_range"], r["n_tendance"]), (30, 30))

    def test_filled_after_tau_is_censored_and_counted_separately(self):
        pop = self.population()
        pop[0] = {**pop[0], "filled": True, "fill_minutes": 1500}   # comble apres tau=1000
        d = sa.run_stability_analysis(pop, tau=1000, n_boot=50)["periods"]["2025-S1"]["descriptive"]["range"]
        self.assertEqual(d["n_filled_after_tau"], 1)
        self.assertAlmostEqual(d["rmst"], (23 * 15 + 7 * 1000) / 30)

    def test_each_readable_period_uses_its_own_locked_label(self):
        pop = self.population() + group(S2_2024, "range", 30, 24, 15) + group(S2_2024, "tendance", 30, 15, 300)
        r = sa.run_stability_analysis(pop, tau=1000, n_boot=50)["periods"]
        self.assertEqual((r["2024-S2"]["label"], r["2025-S1"]["label"]), ("D4:2024-S2", "D4:2025-S1"))

    def test_the_analysis_is_reproducible(self):
        a = sa.run_stability_analysis(self.population(), tau=1000, n_boot=100)["periods"]["2025-S1"]["ci_95"]
        b = sa.run_stability_analysis(self.population(), tau=1000, n_boot=100)["periods"]["2025-S1"]["ci_95"]
        self.assertEqual(a, b)


class TestNothingBeyondD46(unittest.TestCase):
    def test_outputs_are_exactly_the_locked_list_no_pvalue_no_aggregate(self):
        r = sa.run_stability_analysis(TestReadablePeriod.population(), tau=1000, n_boot=50)
        self.assertEqual(set(r), {"label", "tau_hist_minutes", "periods", "reading_clause"})
        self.assertEqual(r["label"], "stabilite -- non probante")
        self.assertEqual(set(r["periods"]["2025-S1"]), {
            "readable", "n_range", "n_tendance", "delta_rmst_range_minus_tendance", "ci_95", "label",
            "delta_decomposition", "descriptive"})
        self.assertEqual(set(r["periods"]["2025-S1"]["descriptive"]["range"]),
                         {"rmst", "fill_rate_at_tau", "n_filled_after_tau", "n_never_filled_in_horizon"})

    def test_the_module_does_not_even_import_logrank_or_block_bootstrap(self):
        source = inspect.getsource(sa)
        for forbidden in ("logrank_test", "bootstrap_delta_rmst_blocks", "p_value", "km_median", "median("):
            self.assertNotIn(forbidden, source, forbidden)


class TestD4NeverTouchesTheTriggerMachinery(unittest.TestCase):
    def test_no_blind_counter_no_trigger_no_registry_in_the_module(self):
        source = inspect.getsource(sa)
        for forbidden in ("blind_counts", "trigger_condition", "build_trigger_record", "attest_reference_state"):
            self.assertNotIn(forbidden, source, forbidden)


class TestProspectiveObservationsAreRefused(unittest.TestCase):
    def test_a_prospective_observation_stops_the_analysis(self):
        pop = TestReadablePeriod.population() + [
            {"t_event": "2026-09-17T13:30:00Z", "zone": "range", "filled": True, "fill_minutes": 15}]
        with self.assertRaises(ValueError):
            sa.run_stability_analysis(pop, tau=1000, n_boot=50)


class TestHistoricalPopulationIsFrozenAtTheReference(unittest.TestCase):
    N = 288
    REF = "2026-01-07T23:45:00Z"   # derniere bougie de la serie de base (indice 287)

    @staticmethod
    def base():
        from test_exp2_protocol import flat_with_step
        return make_bars(flat_with_step, 288)

    def extended(self, extra):
        """Meme debut, plus `extra` bougies posterieures a la reference, de prix tres differents."""
        return make_bars(lambda i: (100.0, 100.0, 100.0, 100.0) if i < 154 else ((103.0,) * 4 if i < 288 else (500.0 + i, 900.0, 1.0, 700.0)),
                         288 + extra)

    def test_later_bars_never_change_the_population_maturity_or_exclusions(self):
        ref_run = sa.historical_population(self.base(), reference_last_bar=self.REF, horizon_bars=100)
        for extra in (1, 20, 200):
            run = sa.historical_population(self.extended(extra), reference_last_bar=self.REF, horizon_bars=100)
            self.assertEqual(run["population"], ref_run["population"])
            self.assertEqual(run["excluded_not_mature"], ref_run["excluded_not_mature"])
            self.assertEqual((run["n_series"], run["last_bar"]), (288, self.REF))

    def test_an_event_not_mature_at_the_reference_stays_excluded_even_when_later_bars_would_mature_it(self):
        # evenement du 7 janvier (indice 250) : 250 + 100 = 350 > 288 -> non mur a la reference
        run = sa.historical_population(self.extended(200), reference_last_bar=self.REF, horizon_bars=100)
        self.assertEqual([e["t_event"] for e in run["excluded_not_mature"]], ["2026-01-07T14:30:00Z"])
        # le groupe de l'evenement exclu est celui calcule sur la serie de base (jamais influence par les bougies posterieures)
        base_zone = {o["t_event"]: o["zone"] for o in p_list_observations(self.base())}["2026-01-07T14:30:00Z"]
        self.assertEqual(run["excluded_not_mature"][0]["zone"], base_zone)
        # sans troncature, la meme serie rendrait cet evenement mature
        untruncated = sa.historical_population(self.extended(200), reference_last_bar="2099-01-01T00:00:00Z", horizon_bars=100)
        self.assertNotIn("2026-01-07T14:30:00Z", [e["t_event"] for e in untruncated["excluded_not_mature"]])

    def test_population_keeps_only_range_and_tendance_and_tau_ignores_the_rest(self):
        run = sa.historical_population(self.base(), reference_last_bar=self.REF, horizon_bars=100)
        self.assertEqual([o["t_event"] for o in run["population"]], ["2026-01-06T14:30:00Z"])
        self.assertEqual(sa.tau_hist(run["population"]), 99 * 15)

    def test_a_prospective_event_in_the_truncated_series_is_an_inconsistency(self):
        with self.assertRaises(ValueError):
            sa.historical_population(self.base(), reference_last_bar=self.REF, prospective_start="2026-01-01T00:00:00Z",
                                     horizon_bars=100)


if __name__ == "__main__":
    unittest.main()
