"""Tests -- relations_experiment.py (2026-09-17). Valeurs attendues
calculees a la main avant d'ecrire le test, comme pour gap_analysis.py et
indicators.py."""
import unittest

from relations_experiment import (
    find_last_closed_bar, _shift_iso, _rsi_zone, _adx_zone, _ema_zone,
    _stats_for, build_observations, declared_comparisons, MIN_SAMPLE_SIZE,
)


def bar(ts, o=None, h=None, l=None, c=None):
    c = c if c is not None else 0
    return {"timestamp": ts, "open": o if o is not None else c, "high": h if h is not None else c,
            "low": l if l is not None else c, "close": c}


class TestShiftIso(unittest.TestCase):
    def test_shifts_backward_across_a_day_boundary(self):
        self.assertEqual(_shift_iso("2024-01-02T00:30:00Z", 60), "2024-01-01T23:30:00Z")


class TestFindLastClosedBar(unittest.TestCase):
    def test_worked_example_from_the_design_doc_m15_1015_h1_context_is_0900(self):
        # Bougies H1 a 08:00, 09:00, 10:00 (chacune clot 1h plus tard).
        # Evenement M15 a 10:15 -> cutoff H1 = 10:15-60min = 09:15 ->
        # derniere bougie H1 <= 09:15 est celle de 09:00 (clot a 10:00,
        # donc bien connue a 10:15). Celle de 10:00 (clot a 11:00) est
        # encore en formation a 10:15 -- exclue.
        h1_bars = [bar("2024-01-01T08:00:00Z", c=1), bar("2024-01-01T09:00:00Z", c=2), bar("2024-01-01T10:00:00Z", c=3)]
        sorted_ts = [b["timestamp"] for b in h1_bars]
        bars_by_ts = {b["timestamp"]: b for b in h1_bars}
        result = find_last_closed_bar(sorted_ts, bars_by_ts, "2024-01-01T10:15:00Z", "H1")
        self.assertEqual(result["timestamp"], "2024-01-01T09:00:00Z")

    def test_cutoff_is_inclusive_event_exactly_on_a_tf_boundary(self):
        # Evenement a 10:00 pile (aligne sur la frontiere H1) -> cutoff = 09:00
        # pile -> la bougie de 09:00 elle-meme est incluse (<=), pas exclue.
        h1_bars = [bar("2024-01-01T08:00:00Z", c=1), bar("2024-01-01T09:00:00Z", c=2)]
        sorted_ts = [b["timestamp"] for b in h1_bars]
        bars_by_ts = {b["timestamp"]: b for b in h1_bars}
        result = find_last_closed_bar(sorted_ts, bars_by_ts, "2024-01-01T10:00:00Z", "H1")
        self.assertEqual(result["timestamp"], "2024-01-01T09:00:00Z")

    def test_no_bar_before_cutoff_returns_none_not_a_guess(self):
        h1_bars = [bar("2024-01-01T10:00:00Z", c=1)]
        sorted_ts = [b["timestamp"] for b in h1_bars]
        bars_by_ts = {b["timestamp"]: b for b in h1_bars}
        result = find_last_closed_bar(sorted_ts, bars_by_ts, "2024-01-01T10:15:00Z", "H1")
        self.assertIsNone(result)


class TestZoneClassification(unittest.TestCase):
    def test_rsi_zone_boundaries(self):
        self.assertEqual(_rsi_zone(30), "survente")
        self.assertEqual(_rsi_zone(30.01), "neutre")
        self.assertEqual(_rsi_zone(70), "surachat")
        self.assertEqual(_rsi_zone(69.99), "neutre")
        self.assertEqual(_rsi_zone(None), "indisponible")

    def test_adx_zone_boundaries(self):
        self.assertEqual(_adx_zone(20), "range")
        self.assertEqual(_adx_zone(20.01), "intermediaire")
        self.assertEqual(_adx_zone(25), "tendance")
        self.assertEqual(_adx_zone(None), "indisponible")

    def test_ema_zone(self):
        self.assertEqual(_ema_zone(101, 100), "au-dessus")
        self.assertEqual(_ema_zone(99, 100), "en-dessous")
        self.assertEqual(_ema_zone(None, 100), "indisponible")
        self.assertEqual(_ema_zone(101, None), "indisponible")


def obs(filled, fill_minutes=None, censor_reason=None):
    return {"filled": filled, "fill_minutes": fill_minutes, "censor_reason": censor_reason}


class TestStatsFor(unittest.TestCase):
    def test_below_min_sample_size_is_marked_insufficient_not_computed(self):
        subset = [obs(True, 10)] * (MIN_SAMPLE_SIZE - 1)
        stats = _stats_for(subset)
        self.assertTrue(stats["insufficient"])
        self.assertEqual(stats["n"], MIN_SAMPLE_SIZE - 1)

    def test_dataset_end_censored_excluded_from_n_and_from_fill_stats(self):
        subset = [obs(True, 10)] * 29 + [obs(False, None, "dataset_end")]
        stats = _stats_for(subset)
        # 29 utilisables < 30 -> insuffisant, et l'exclu est bien compte a part.
        self.assertTrue(stats["insufficient"])
        self.assertEqual(stats["n"], 29)
        self.assertEqual(stats["n_excluded_dataset_end"], 1)

    def test_hand_computed_stats_on_a_valid_sample(self):
        filled = [obs(True, m) for m in [10, 20, 30, 40, 50]]
        never = [obs(False, None, "horizon_exhausted")] * 25
        subset = filled + never  # n=30
        stats = _stats_for(subset)
        self.assertFalse(stats["insufficient"])
        self.assertEqual(stats["n"], 30)
        self.assertEqual(stats["filled_pct"], round(5 / 30 * 100, 1))
        self.assertEqual(stats["fill_minutes_median"], 30)
        self.assertEqual(stats["fill_minutes_mean"], 30.0)
        self.assertEqual(stats["pct_never_filled_horizon_exhausted"], round(25 / 30 * 100, 1))


def m15(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c}


class TestBuildObservationsIntegration(unittest.TestCase):
    def test_insufficient_context_bars_marked_indisponible_not_guessed(self):
        # Trop peu de bougies pour RSI(14)/ADX(14)/EMA(21) -- le contexte
        # doit rester honnetement indisponible, jamais une valeur inventee.
        bars = [
            m15("2026-01-05T13:30:00Z", 100, 101, 99, 100),
            m15("2026-01-05T14:30:00Z", 100.5, 101, 100, 100.5),
            m15("2026-01-05T21:00:00Z", 100, 101, 99, 100),
            m15("2026-01-06T14:30:00Z", 103, 104, 102, 103),
        ]
        observations = build_observations(bars, bars, bars, symbol="US Tech 100")
        self.assertEqual(len(observations), 1)
        o = observations[0]
        self.assertEqual(o["t_event"], "2026-01-06T14:30:00Z")
        self.assertEqual(o["context"]["M15"]["rsi_zone"], "indisponible")
        self.assertEqual(o["context"]["H1"]["adx_zone"], "indisponible")

    def test_split_assignment_discovery_vs_oos_vs_out_of_scope(self):
        bars = [
            m15("2025-11-28T13:30:00Z", 100, 101, 99, 100),
            m15("2025-11-28T14:30:00Z", 100, 101, 99, 100),
            m15("2025-11-28T21:00:00Z", 100, 101, 99, 100),
            m15("2025-12-01T14:30:00Z", 103, 104, 102, 103),  # gap en OOS (>= 2025-12-01)
            m15("2025-12-01T21:00:00Z", 103, 104, 102, 103),
            m15("2026-09-17T14:30:00Z", 106, 107, 105, 106),  # gap APRES la fenetre OOS documentee -> hors_perimetre
        ]
        observations = build_observations(bars, bars, bars, symbol="US Tech 100")
        splits = {o["t_event"]: o["split"] for o in observations}
        self.assertEqual(splits["2025-12-01T14:30:00Z"], "oos")
        self.assertEqual(splits["2026-09-17T14:30:00Z"], "hors_perimetre")

    def test_censor_reason_distinguishes_horizon_exhausted_from_dataset_end(self):
        # Gap qui ne se comble jamais : avec un horizon minuscule (2) et
        # largement assez de bougies restantes -> horizon_exhausted.
        # Avec un horizon enorme (2000) et seulement 2 bougies restantes
        # apres le gap -> dataset_end.
        bars = [
            m15("2026-01-05T13:30:00Z", 100, 101, 99, 100),
            m15("2026-01-05T14:30:00Z", 100, 101, 99, 100),
            m15("2026-01-05T21:00:00Z", 100, 101, 99, 100),
            m15("2026-01-06T14:30:00Z", 110, 111, 109, 110),  # gap +10, jamais retouche 100 dans ces quelques bougies
            m15("2026-01-06T14:45:00Z", 110, 111, 109, 110),
            m15("2026-01-06T15:00:00Z", 110, 111, 109, 110),
        ]
        obs_small_horizon = build_observations(bars, bars, bars, horizon_bars=2)
        gap_small = [o for o in obs_small_horizon if o["t_event"] == "2026-01-06T14:30:00Z"][0]
        self.assertFalse(gap_small["filled"])
        self.assertEqual(gap_small["censor_reason"], "horizon_exhausted")

        obs_big_horizon = build_observations(bars, bars, bars, horizon_bars=2000)
        gap_big = [o for o in obs_big_horizon if o["t_event"] == "2026-01-06T14:30:00Z"][0]
        self.assertFalse(gap_big["filled"])
        self.assertEqual(gap_big["censor_reason"], "dataset_end")


class TestDeclaredComparisons(unittest.TestCase):
    def test_exactly_the_predeclared_26_keys_no_scope_creep(self):
        # 1 population totale + (3 zones RSI + 3 zones ADX + 2 zones EMA) x
        # 3 timeframes + 1 combinaison illustrative = 1 + 8*3 + 1 = 26.
        observations_by_split = {"discovery": [], "oos": []}
        result = declared_comparisons(observations_by_split)
        self.assertEqual(len(result["discovery"]), 26)
        self.assertEqual(len(result["oos"]), 26)

    def test_discovery_and_oos_never_mixed(self):
        discovery_obs = [{"context": {tf: {"rsi_zone": "neutre", "adx_zone": "range", "ema_zone": "au-dessus"} for tf in ["M15", "H1", "H4"]}, "filled": True, "fill_minutes": 10, "censor_reason": None} for _ in range(40)]
        oos_obs = [{"context": {tf: {"rsi_zone": "survente", "adx_zone": "range", "ema_zone": "au-dessus"} for tf in ["M15", "H1", "H4"]}, "filled": True, "fill_minutes": 99, "censor_reason": None} for _ in range(40)]
        result = declared_comparisons({"discovery": discovery_obs, "oos": oos_obs})
        # Le sous-groupe "survente" n'existe que dans oos, jamais mélangé
        # avec les observations "neutre" de discovery.
        self.assertTrue(result["discovery"]["RSI_M15_survente"]["insufficient"])
        self.assertEqual(result["discovery"]["RSI_M15_survente"]["n"], 0)
        self.assertFalse(result["oos"]["RSI_M15_survente"]["insufficient"])
        self.assertEqual(result["oos"]["RSI_M15_survente"]["n"], 40)


if __name__ == "__main__":
    unittest.main()
