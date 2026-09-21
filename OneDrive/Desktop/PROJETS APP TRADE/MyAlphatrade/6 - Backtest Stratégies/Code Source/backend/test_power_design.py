"""Tests -- power_design.py (D7). Valeurs attendues calculees a la main ; les
flux sont rejoues par une implementation INDEPENDANTE ecrite dans le test."""
import ast
import hashlib
import inspect
import random
import unittest
from unittest import mock

import power_design as pd
import survival_stats

MASTER = 20260918


def independent_rng(label, master=MASTER):
    digest = hashlib.sha256(f"{master}|{label}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest, "big"))


class SeqRng:
    """Generateur scripte : renvoie des indices predefinis (ordre des tirages verifiable)."""

    def __init__(self, values):
        self.values = list(values)

    def randrange(self, n):
        v = self.values.pop(0)
        assert 0 <= v < n
        return v


TAU = 500
POPULATION = [
    {"t_event": "2025-01-10T14:30:00Z", "filled": True, "fill_minutes": 15},     # e=1, u=15
    {"t_event": "2025-01-09T14:30:00Z", "filled": True, "fill_minutes": 1000},   # comble apres tau -> e=0, u=500
    {"t_event": "2025-01-11T14:30:00Z", "filled": False, "fill_minutes": None},  # jamais comble -> e=0, u=500
    {"t_event": "2025-01-12T14:30:00Z", "filled": True, "fill_minutes": 500},    # comble a t == tau -> e=1, u=500
]
EXPECTED_RESERVOIR = (
    ("2025-01-09T14:30:00Z", 500, 0),
    ("2025-01-10T14:30:00Z", 15, 1),
    ("2025-01-11T14:30:00Z", 500, 0),
    ("2025-01-12T14:30:00Z", 500, 1),
)


class TestReservoir(unittest.TestCase):
    def test_hand_computed_reservoir_sorted_by_t_event(self):
        self.assertEqual(pd.build_reservoir(POPULATION, TAU), EXPECTED_RESERVOIR)

    def test_boundary_filled_exactly_at_tau_is_an_event_filled_after_tau_is_censored(self):
        r = {t: (u, e) for t, u, e in pd.build_reservoir(POPULATION, TAU)}
        self.assertEqual(r["2025-01-12T14:30:00Z"], (500, 1))
        self.assertEqual(r["2025-01-09T14:30:00Z"], (500, 0))

    def test_the_group_is_neither_read_nor_kept(self):
        with_groups = [{**o, "zone": "range" if i % 2 else "tendance"} for i, o in enumerate(POPULATION)]
        swapped = [{**o, "zone": "tendance" if i % 2 else "range"} for i, o in enumerate(POPULATION)]
        self.assertEqual(pd.build_reservoir(with_groups, TAU), pd.build_reservoir(swapped, TAU))
        self.assertEqual(pd.build_reservoir(with_groups, TAU), pd.build_reservoir(POPULATION, TAU))
        for row in pd.build_reservoir(with_groups, TAU):
            self.assertEqual(len(row), 3)   # (T_event, u, e) : pas de groupe

    def test_invalid_inputs_are_refused(self):
        dup = POPULATION + [dict(POPULATION[0])]
        for bad_pop in (
            dup,
            [{"t_event": "2025-01-10 14:30:00", "filled": False, "fill_minutes": None}],
            [{"t_event": "2025-01-10T14:30:00Z", "filled": True, "fill_minutes": -1}],
            [{"t_event": "2025-01-10T14:30:00Z", "filled": True, "fill_minutes": 1.5}],
            [{"t_event": "2025-01-10T14:30:00Z", "filled": True, "fill_minutes": True}],
        ):
            with self.assertRaises(ValueError):
                pd.build_reservoir(bad_pop, TAU)
        for bad_tau in (0, -5, 500.0, True):
            with self.assertRaises(ValueError):
                pd.build_reservoir(POPULATION, bad_tau)

    def test_a_whole_float_duration_as_stored_by_the_gap_analysis_is_accepted_as_an_integer(self):
        pop = [{"t_event": "2025-01-10T14:30:00Z", "filled": True, "fill_minutes": 15.0}]
        (row,) = pd.build_reservoir(pop, TAU)
        self.assertEqual(row, ("2025-01-10T14:30:00Z", 15, 1))
        self.assertIsInstance(row[1], int)
        self.assertEqual(pd.reservoir_bytes((row,)), b"2025-01-10T14:30:00Z|15|1\n")   # jamais "15.0"

    def test_serialization_and_fingerprint_match_hand_written_literals(self):
        literal = (
            "2025-01-09T14:30:00Z|500|0\n"
            "2025-01-10T14:30:00Z|15|1\n"
            "2025-01-11T14:30:00Z|500|0\n"
            "2025-01-12T14:30:00Z|500|1\n"
        )
        res = pd.build_reservoir(POPULATION, TAU)
        self.assertEqual(pd.reservoir_bytes(res), literal.encode("utf-8"))
        self.assertNotIn(b"\r", pd.reservoir_bytes(res))
        self.assertEqual(pd.reservoir_sha256(res), hashlib.sha256(literal.encode("utf-8")).hexdigest())
        self.assertEqual(pd.reservoir_sha256(pd.build_reservoir(list(reversed(POPULATION)), TAU)), pd.reservoir_sha256(res))

    def test_a_changed_value_changes_the_fingerprint(self):
        other = [{**POPULATION[0], "fill_minutes": 16}] + POPULATION[1:]
        self.assertNotEqual(
            pd.reservoir_sha256(pd.build_reservoir(other, TAU)),
            pd.reservoir_sha256(pd.build_reservoir(POPULATION, TAU)),
        )

    def test_the_simulator_receives_only_u_and_e(self):
        self.assertEqual(pd.to_pairs(EXPECTED_RESERVOIR), ((500, 0), (15, 1), (500, 0), (500, 1)))


PAIRS = ((500, 0), (15, 1), (500, 0), (500, 1))   # meme reservoir, tau = 500


class TestPooledSummaryAndEffect(unittest.TestCase):
    def test_hand_computed_pooled_outputs(self):
        s = pd.pooled_summary(PAIRS, TAU)
        self.assertEqual((s["n"], s["n_censored"], s["censored_share"]), (4, 2, 0.5))
        self.assertAlmostEqual(s["rmst_pooled"], (500 + 15 + 500 + 500) / 4)   # 378.75
        self.assertAlmostEqual(s["c_filled_contribution"], (15 + 500) / 4)      # 128.75

    def test_true_effect_is_minus_delta_times_c_in_minutes_and_percent_of_pooled_rmst(self):
        e = pd.true_effect(PAIRS, TAU, 20)
        self.assertAlmostEqual(e["delta_true_minutes"], -0.2 * 128.75)          # -25.75
        self.assertAlmostEqual(e["delta_true_pct_of_pooled_rmst"], 100 * -25.75 / 378.75)
        self.assertEqual(pd.true_effect(PAIRS, TAU, 0)["delta_true_minutes"], 0.0)

    def test_a_tuple_carrying_extra_information_is_refused_explicitly_as_not_a_pair(self):
        for bad in (((500, 0, "2025-01-09T14:30:00Z"),), ((500, 0, "range"),)):
            with self.assertRaisesRegex(ValueError, "paires"):
                pd.pooled_summary(bad, TAU)

    def test_the_simulator_refuses_anything_but_valid_pairs(self):
        for bad in (
            (),
            ((500, 0, "2025-01-09T14:30:00Z"),),   # 3-uplet : information de T_event refusee
            ((500, 0, "range"),),                    # 3-uplet : information de groupe refusee
            ((400, 0),),                             # e = 0 doit valoir EXACTEMENT tau
            ((501, 1),),                             # u > tau
            ((15, 2),),
            ((15, True),),
        ):
            with self.assertRaises(ValueError):
                pd.pooled_summary(bad, TAU)


class TestTransformationAndCensoring(unittest.TestCase):
    def test_hand_computed_transformation_censoring_stays_exactly_at_tau(self):
        pairs = ((15, 1), (500, 0), (300, 1))
        rng = SeqRng([0, 1, 2, 2, 1, 0])   # range : indices 0,1,2 ; tendance : 2,1,0
        tr, er, tt, et = pd.draw_dataset(pairs, 3, 3, 20, rng, TAU)
        self.assertEqual(tr, [0.8 * 15, 500.0, 0.8 * 300])   # 12.0, 500.0 (PAS 400), 240.0
        self.assertEqual(er, [True, False, True])
        self.assertEqual(tt, [300.0, 500.0, 15.0])
        self.assertEqual(et, [True, False, True])
        self.assertEqual(tr[1], 500.0)   # le defaut evite : une censure n'est jamais reduite

    def test_range_draws_come_before_tendance_draws(self):
        pairs = ((15, 1), (500, 0), (300, 1))
        tr, _, tt, _ = pd.draw_dataset(pairs, 2, 2, 0, SeqRng([0, 0, 2, 2]), TAU)
        self.assertEqual((tr, tt), ([15.0, 15.0], [300.0, 300.0]))

    def test_delta_zero_is_the_identity(self):
        pairs = ((15, 1), (500, 0), (300, 1), (7, 1))
        tr, er, tt, et = pd.draw_dataset(pairs, 4, 4, 0, SeqRng([0, 1, 2, 3, 0, 1, 2, 3]), TAU)
        self.assertEqual((tr, er), (tt, et))
        self.assertEqual(tr, [15.0, 500.0, 300.0, 7.0])

    def test_no_rounding_is_applied(self):
        tr, _, _, _ = pd.draw_dataset(((7, 1),), 1, 1, 15, SeqRng([0, 0]), TAU)
        self.assertEqual(tr, [(1.0 - 0.15) * 7])
        self.assertNotEqual(tr[0], round(tr[0]))

    def test_streams_are_replayed_exactly_by_an_independent_implementation(self):
        pairs = PAIRS
        label = pd.data_label(20, 5, 3, 7)
        self.assertEqual(label, "D7:data:δ=20:n=5/3:sim=7")
        indep = independent_rng(label)
        idx_r = [indep.randrange(4) for _ in range(5)]
        idx_t = [indep.randrange(4) for _ in range(3)]
        tr, er, tt, et = pd.draw_dataset(pairs, 5, 3, 20, survival_stats.derive_rng(label), TAU)
        self.assertEqual(er, [bool(pairs[i][1]) for i in idx_r])
        self.assertEqual(tr, [0.8 * pairs[i][0] if pairs[i][1] else 500.0 for i in idx_r])
        self.assertEqual(tt, [float(pairs[i][0]) for i in idx_t])


class TestInvariants(unittest.TestCase):
    def check(self, times, events, source, cap=500.0):
        pd.check_group(times, events, source, TAU, cap)

    def test_a_valid_group_passes(self):
        self.check([12.0, 500.0], [True, False], [True, False])

    def test_a_censored_observation_reduced_below_tau_is_refused_the_flaw_that_was_found(self):
        with self.assertRaises(pd.InvariantViolation):
            self.check([12.0, 400.0], [True, False], [True, False])   # 500 * 0.8 : censure devenue < tau

    def test_a_flipped_event_indicator_is_refused(self):
        with self.assertRaises(pd.InvariantViolation):
            self.check([12.0, 400.0], [True, True], [True, False])    # censure transformee en evenement

    def test_a_time_above_tau_is_refused(self):
        with self.assertRaises(pd.InvariantViolation):
            self.check([500.5], [True], [True])

    def test_an_event_time_outside_its_bounds_is_refused(self):
        with self.assertRaises(pd.InvariantViolation):
            self.check([-1.0], [True], [True])
        with self.assertRaises(pd.InvariantViolation):
            self.check([450.0], [True], [True], cap=400.0)            # au-dessus de (1 - delta) * tau

    def test_kaplan_meier_must_equal_the_mean_of_the_times(self):
        with mock.patch.object(pd, "rmst", return_value=999.0):
            with self.assertRaises(pd.InvariantViolation):
                self.check([12.0, 500.0], [True, False], [True, False])

    def test_the_identity_km_equals_mean_holds_on_real_draws(self):
        for k in range(20):
            tr, er, tt, et = pd.draw_dataset(PAIRS, 30, 50, 30, survival_stats.derive_rng(f"T:inv:{k}"), TAU)
            for times, events in ((tr, er), (tt, et)):
                self.assertAlmostEqual(survival_stats.rmst(times, events, TAU), sum(times) / len(times), places=9)


class TestSimulateCell(unittest.TestCase):
    def test_no_effect_when_everything_is_censored_censorship_is_never_turned_into_an_event(self):
        # Reservoir entierement censure a tau : meme avec delta = 30 %, AUCUN effet, AUCUNE exclusion de 0.
        pairs = ((TAU, 0),) * 5
        r = pd.simulate_cell(pairs, TAU, 30, 10, 17, n_sims=25, n_boot=50)
        self.assertEqual(r["n_excluding_zero"], 0)
        self.assertEqual(r["delta_true_minutes"], 0.0)
        self.assertEqual(r["median_delta_hat"], 0.0)

    def test_degenerate_pool_gives_an_exact_hand_computed_effect(self):
        pairs = ((100, 1),) * 4   # tous combles a 100 min ; range devient 80, tendance reste 100
        r = pd.simulate_cell(pairs, TAU, 20, 6, 9, n_sims=15, n_boot=40)
        self.assertEqual((r["n_excluding_zero"], r["n_excluding_negative_side"], r["n_excluding_positive_side"]), (15, 15, 0))
        self.assertEqual(r["rate_excluding_zero"], 1.0)
        self.assertEqual(r["share_correct_sign_among_exclusions"], 1.0)
        self.assertAlmostEqual(r["median_delta_hat"], -20.0)
        self.assertAlmostEqual(r["delta_true_minutes"], -20.0)                       # -0.2 * C, C = 100
        self.assertAlmostEqual(r["delta_true_pct_of_pooled_rmst"], -20.0)            # RMST poole = 100
        self.assertEqual(r["median_ci_half_width"], 0.0)

    def test_delta_zero_is_a_calibration_row_with_no_correct_sign(self):
        r = pd.simulate_cell(((100, 1),) * 4, TAU, 0, 6, 9, n_sims=10, n_boot=40)
        self.assertEqual(r["n_excluding_zero"], 0)
        self.assertIsNone(r["share_correct_sign_among_exclusions"])
        self.assertEqual(r["delta_true_minutes"], 0.0)

    def test_cell_is_reproducible_and_counts_are_consistent(self):
        a = pd.simulate_cell(PAIRS, TAU, 15, 6, 10, n_sims=30, n_boot=60)
        b = pd.simulate_cell(PAIRS, TAU, 15, 6, 10, n_sims=30, n_boot=60)
        self.assertEqual(a, b)
        self.assertEqual(a["n_excluding_zero"], a["n_excluding_negative_side"] + a["n_excluding_positive_side"])
        self.assertEqual(a["n_sims"], 30)

    def test_master_seed_changes_the_stream(self):
        a = pd.simulate_cell(PAIRS, TAU, 15, 6, 10, n_sims=30, n_boot=60, master_seed=1)
        b = pd.simulate_cell(PAIRS, TAU, 15, 6, 10, n_sims=30, n_boot=60, master_seed=2)
        self.assertNotEqual(a["median_delta_hat"], b["median_delta_hat"])

    def test_bootstrap_of_each_simulation_uses_its_own_dedicated_stream(self):
        seen = []
        original = survival_stats.bootstrap_delta_rmst_iid

        def spy(a, b, label, **kw):
            seen.append(label)
            return original(a, b, label, **kw)

        with mock.patch.object(pd, "bootstrap_delta_rmst_iid", side_effect=spy):
            pd.simulate_cell(PAIRS, TAU, 5, 6, 10, n_sims=3, n_boot=20)
        self.assertEqual(seen, [pd.boot_label(5, 6, 10, k) for k in range(3)])
        self.assertEqual(seen[0], "D7:boot:δ=5:n=6/10:sim=0")


class TestGridAndLabels(unittest.TestCase):
    def test_locked_parameters(self):
        self.assertEqual(pd.DELTAS_PCT, (0, 5, 10, 15, 20, 30))
        self.assertEqual(pd.SCENARIOS, ((60, 102), (80, 136), (100, 170)))
        self.assertEqual((pd.N_SIMS, pd.N_BOOT), (1000, 1000))

    def test_every_label_of_the_full_grid_is_unique_and_none_collides_with_h1_or_d4(self):
        labels = pd.all_labels()
        self.assertEqual(len(labels), 6 * 3 * 1000 * 2)
        self.assertEqual(len(set(labels)), len(labels))
        self.assertTrue(all(l.startswith("D7:") for l in labels))
        self.assertFalse({"H1:iid", "H1:blocs"} & set(labels))
        self.assertEqual(labels[0], "D7:data:δ=0:n=60/102:sim=0")
        self.assertEqual(labels[1], "D7:boot:δ=0:n=60/102:sim=0")

    def test_grid_is_reproducible_and_independent_of_the_way_cells_are_mapped(self):
        kwargs = dict(deltas=(0, 10), scenarios=((5, 8), (6, 9)), n_sims=6, n_boot=30)
        a = pd.run_grid(PAIRS, TAU, **kwargs)
        b = pd.run_grid(PAIRS, TAU, map_fn=lambda f, xs: [f(x) for x in reversed(list(xs))][::-1], **kwargs)
        self.assertEqual(a, b)
        self.assertEqual([(c["n_range"], c["delta_pct"]) for c in a], [(5, 0), (5, 10), (6, 0), (6, 10)])


class TestBlindness(unittest.TestCase):
    def test_module_imports_only_the_standard_library_and_survival_stats(self):
        tree = ast.parse(inspect.getsource(pd))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported, {"hashlib", "re", "statistics", "survival_stats"})

    def test_the_simulator_code_never_mentions_group_or_t_event(self):
        for fn in (pd.draw_dataset, pd.simulate_cell, pd.check_group, pd._validate_pairs, pd.pooled_summary,
                   pd.true_effect, pd.to_pairs):
            source = inspect.getsource(fn).lower()
            code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
            for forbidden in ("zone", "t_event", "range_group", "tendance_group"):
                self.assertNotIn(forbidden, code.replace('"""', ""), f"{fn.__name__}: {forbidden}")

    def test_build_reservoir_never_reads_a_group_key(self):
        self.assertNotIn("zone", inspect.getsource(pd.build_reservoir))
        # une observation SANS cle de groupe est acceptee
        self.assertEqual(len(pd.build_reservoir(POPULATION, TAU)), 4)


class TestStatement(unittest.TestCase):
    def test_power_is_declared_conditional_and_limits_are_written(self):
        self.assertIn("propriete conditionnelle", pd.POWER_STATEMENT)
        self.assertIn("ni une estimation de la puissance reelle de H1", pd.POWER_STATEMENT)
        self.assertIn("probabilite de detection", pd.POWER_STATEMENT)
        text = " ".join(pd.LIMITS)
        for needle in ("independantes", "intra-semaine", "conservateur sur la queue", "B = 1000", "10 000"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
