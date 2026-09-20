"""Tests -- survival_stats.py. Valeurs attendues calculees a la main."""
import random
import unittest

from survival_stats import (
    READING_CLAUSE, bootstrap_delta_rmst_blocks, bootstrap_delta_rmst_iid, censor_at_tau,
    describe_group, excludes_zero, h1_verdict, km_curve, km_median, logrank_test,
    percentile_interval, rmst, rmst_from_curve,
)


class TestKaplanMeierAndRmst(unittest.TestCase):
    def test_km_curve_no_censoring_hand_computed(self):
        # 3 evenements a 1, 2, 3 : S = 2/3, 1/3, 0
        curve = km_curve([1, 2, 3], [True, True, True])
        self.assertEqual([t for t, _ in curve], [0.0, 1, 2, 3])
        self.assertAlmostEqual(curve[1][1], 2 / 3)
        self.assertAlmostEqual(curve[2][1], 1 / 3)
        self.assertAlmostEqual(curve[3][1], 0.0)

    def test_rmst_no_censoring_equals_hand_value(self):
        # integrale de 0 a 3 : 1*1 + 2/3*1 + 1/3*1 = 2 = moyenne des min(T,3)
        self.assertAlmostEqual(rmst([1, 2, 3], [True, True, True], 3), 2.0)

    def test_observations_beyond_tau_are_censored_at_tau_not_infinite(self):
        # tau=3 : (1,evt), (5->3,cens), (5->3,cens) -> S=2/3 apres t=1.
        # RMST = 1*1 + 2/3*(3-1) = 7/3 = moyenne de (1, 3, 3)
        self.assertEqual(censor_at_tau([1, 5, 5], [True, True, True], 3), ([1, 3, 3], [True, False, False]))
        self.assertAlmostEqual(rmst([1, 5, 5], [True, True, True], 3), 7 / 3)

    def test_identity_with_mean_of_min_when_all_censoring_is_at_tau(self):
        # Note de verification de D2 : sans censure avant tau, RMST KM ==
        # moyenne des min(T, tau).
        rng = random.Random(1)
        tau = 60
        for _ in range(50):
            n = rng.randint(5, 40)
            times = [rng.randrange(0, 121, 15) for _ in range(n)]
            events = [rng.random() < 0.8 for _ in range(n)]
            t, e = censor_at_tau(times, events, tau)
            # censure tardive uniquement : tout non-evenement est place a tau
            t = [ti if ei else tau for ti, ei in zip(t, e)]
            mean_min = sum(t) / n
            self.assertAlmostEqual(rmst_from_curve(km_curve(t, e), tau), mean_min, places=9)

    def test_km_really_handles_early_censoring(self):
        # (2,evt), (3,cens), (5,evt), tau=6 : S=2/3 sur [2,5), 0 apres 5.
        # RMST = 2 + 2/3*3 + 0 = 4  (et PAS la moyenne des min = 10/3)
        self.assertAlmostEqual(rmst([2, 3, 5], [True, False, True], 6), 4.0)

    def test_km_median_estimable_or_not(self):
        curve = km_curve([10, 20, 30, 100, 100], [True, True, True, False, False])
        self.assertEqual(km_median(curve), 30)  # S: 0.8, 0.6, 0.4 -> premier <= 0.5 a t=30
        self.assertIsNone(km_median(km_curve([10, 100, 100, 100], [True, False, False, False])))


class TestLogRank(unittest.TestCase):
    def test_hand_computed_two_by_two(self):
        # A: evenements a 1,2 ; B: evenements a 3,4.
        # t=1: E_A=.5, V=.25 ; t=2: E_A=1/3, V=2/9 ; t=3,4: aucune contribution.
        # O_A=2 -> O-E=7/6 ; V=17/36 -> chi2 = (49/36)/(17/36) = 49/17
        r = logrank_test([1, 2], [True, True], [3, 4], [True, True])
        self.assertAlmostEqual(r["chi2"], 49 / 17, places=9)
        self.assertTrue(0.0890 < r["p_value"] < 0.0902)
        self.assertFalse(r["significant_at_0_05"])

    def test_identical_groups_give_zero_statistic(self):
        r = logrank_test([1, 2, 3], [True] * 3, [1, 2, 3], [True] * 3)
        self.assertAlmostEqual(r["chi2"], 0.0, places=12)
        self.assertAlmostEqual(r["p_value"], 1.0, places=9)

    def test_no_events_is_reported_as_not_estimable(self):
        r = logrank_test([5, 5], [False, False], [5, 5], [False, False])
        self.assertFalse(r["estimable"])
        self.assertIsNone(r["p_value"])


class TestBootstrap(unittest.TestCase):
    def test_percentile_interval_indices(self):
        vals = list(range(10000))  # 0..9999
        self.assertEqual(percentile_interval(vals), (249, 9749))  # floor(.025*9999), floor(.975*9999)

    def test_iid_is_reproducible_and_seed_dependent(self):
        a, b = [10, 20, 30, 40], [100, 200, 300, 400]
        r1 = bootstrap_delta_rmst_iid(a, b, n_boot=500, seed=7)
        r2 = bootstrap_delta_rmst_iid(a, b, n_boot=500, seed=7)
        r3 = bootstrap_delta_rmst_iid(a, b, n_boot=500, seed=8)
        self.assertEqual(r1["interval"], r2["interval"])
        self.assertNotEqual(r1["interval"], r3["interval"])

    def test_iid_constant_groups_give_degenerate_exact_interval(self):
        r = bootstrap_delta_rmst_iid([10] * 5, [100] * 7, n_boot=200, seed=1)
        self.assertEqual(r["interval"], (-90.0, -90.0))

    def test_iid_separated_groups_exclude_zero_and_overlapping_include_it(self):
        sep = bootstrap_delta_rmst_iid([10, 12, 14, 11, 13] * 6, [500, 520, 480, 510, 490] * 6, n_boot=300, seed=3)
        self.assertTrue(excludes_zero(sep["interval"]))
        same = bootstrap_delta_rmst_iid([10, 20, 30, 40, 50] * 6, [10, 20, 30, 40, 50] * 6, n_boot=300, seed=3)
        self.assertFalse(excludes_zero(same["interval"]))

    def test_empty_group_is_an_error_not_a_silent_result(self):
        with self.assertRaises(ValueError):
            bootstrap_delta_rmst_iid([], [1, 2], n_boot=10)

    def test_blocks_discard_and_count_replicates_with_an_empty_group(self):
        # 1 semaine contient seulement le groupe a, 1 seulement le groupe b :
        # une replique tirant 2 fois la meme semaine a un groupe vide.
        blocks = {"w1": [("a", 10.0)], "w2": [("b", 100.0)]}
        r = bootstrap_delta_rmst_blocks(blocks, n_boot=400, seed=5)
        self.assertEqual(r["n_valid"] + r["n_discarded"], 400)
        self.assertGreater(r["n_discarded"], 0)
        self.assertEqual(r["interval"], (-90.0, -90.0))  # les valides valent toutes 10-100

    def test_blocks_are_reproducible(self):
        blocks = {f"w{i}": [("a", float(i)), ("b", float(10 * i))] for i in range(1, 8)}
        self.assertEqual(
            bootstrap_delta_rmst_blocks(blocks, n_boot=200, seed=9)["interval"],
            bootstrap_delta_rmst_blocks(blocks, n_boot=200, seed=9)["interval"],
        )


class TestVerdictAndDescribe(unittest.TestCase):
    def test_excludes_zero_strict_on_both_sides(self):
        self.assertTrue(excludes_zero((-5, -1)))
        self.assertTrue(excludes_zero((1, 5)))
        self.assertFalse(excludes_zero((-5, 2)))
        self.assertFalse(excludes_zero((0, 5)))  # 0 inclus -> n'exclut pas 0

    def test_verdict_and_intra_week_dependence_note(self):
        self.assertTrue(h1_verdict((-5, -1))["h1_supported"])
        self.assertFalse(h1_verdict((-5, 2))["h1_supported"])
        v = h1_verdict((-5, -1), block_interval=(-6, 1))
        self.assertTrue(v["h1_supported"])  # le verdict reste celui du principal
        self.assertEqual(v["sensitivity_note"], "soutenu, non robuste a la dependance intra-semaine")
        self.assertIsNone(h1_verdict((-5, -1), block_interval=(-6, -0.5))["sensitivity_note"])

    def test_describe_group_decomposition_sums_to_rmst_hand_computed(self):
        # 3 combles a 10,20,30 ; 2 non combles (censures a tau=100) -> n=5
        # RMST = (10+20+30+100+100)/5 = 52 = 12 (combles) + 40 (non combles)
        d = describe_group([10, 20, 30, 999, 999], [True, True, True, True, False], 100)
        self.assertAlmostEqual(d["rmst"], 52.0)
        self.assertAlmostEqual(d["contribution_filled"], 12.0)
        self.assertAlmostEqual(d["contribution_not_filled"], 40.0)
        self.assertAlmostEqual(d["contribution_filled"] + d["contribution_not_filled"], d["rmst"])
        self.assertAlmostEqual(d["fill_rate_at_tau"], 0.6)
        self.assertEqual(d["median_of_filled"], 20)
        self.assertEqual(d["km_median"], 30)
        self.assertEqual((d["n_filled_by_tau"], d["n_not_filled_at_tau"]), (3, 2))

    def test_reading_clause_is_the_one_accepted_by_louis(self):
        self.assertIn("temps moyen plafonne a tau", READING_CLAUSE)
        self.assertIn("vitesse typique ou a la traine", READING_CLAUSE)


if __name__ == "__main__":
    unittest.main()
