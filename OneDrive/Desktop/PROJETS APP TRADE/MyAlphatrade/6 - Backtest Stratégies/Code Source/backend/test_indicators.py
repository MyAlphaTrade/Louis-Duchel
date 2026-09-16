"""Tests -- indicators.py (2026-09-16/17). Toutes les valeurs attendues
sont calculees a la main (methode de Wilder pour RSI/ADX, EMA classique)
AVANT d'etre comparees a la sortie du module -- jamais copiees depuis la
sortie elle-meme."""
import unittest

from indicators import (
    compute_rsi, summarize_rsi,
    compute_adx, summarize_adx,
    compute_ema, summarize_ema,
)


def bar(ts, o=None, h=None, l=None, c=None):
    c = c if c is not None else 0
    return {"timestamp": ts, "open": o if o is not None else c, "high": h if h is not None else c,
            "low": l if l is not None else c, "close": c}


class TestRSI(unittest.TestCase):
    def test_hand_computed_example_period_3(self):
        # closes = [44, 44.25, 44.5, 43.75, 44.65] -- variations : +0.25,
        # +0.25, -0.75, +0.90. Premiere moyenne (3 premieres variations) :
        # gain=1/6, perte=1/4 -> RS=2/3 -> RSI=100-60=40.0 exactement.
        # Deuxieme (lissage Wilder) : gain=37/90, perte=1/6 -> RSI=71.1538...
        bars = [bar(f"t{i}", c=c) for i, c in enumerate([44, 44.25, 44.5, 43.75, 44.65])]
        rsi = compute_rsi(bars, period=3)
        self.assertEqual(len(rsi), 2)
        self.assertAlmostEqual(rsi[0]["value"], 40.0, places=4)
        self.assertEqual(rsi[0]["timestamp"], "t3")
        self.assertAlmostEqual(rsi[1]["value"], 71.1538, places=4)
        self.assertEqual(rsi[1]["timestamp"], "t4")

    def test_no_losses_gives_rsi_100_never_a_division_by_zero(self):
        bars = [bar(f"t{i}", c=c) for i, c in enumerate([1, 2, 3, 4])]
        rsi = compute_rsi(bars, period=2)
        self.assertEqual([p["value"] for p in rsi], [100.0, 100.0])

    def test_no_movement_at_all_gives_rsi_50_by_explicit_convention(self):
        bars = [bar(f"t{i}", c=c) for i, c in enumerate([5, 5, 5, 5])]
        rsi = compute_rsi(bars, period=2)
        self.assertEqual([p["value"] for p in rsi], [50.0, 50.0])

    def test_insufficient_data_returns_empty_list_not_a_guess(self):
        bars = [bar(f"t{i}", c=c) for i, c in enumerate([1, 2, 3])]
        self.assertEqual(compute_rsi(bars, period=14), [])
        self.assertEqual(compute_rsi(bars, period=3), [])  # exactement period+1=4 requis, on n'a que 3


class TestRSISummary(unittest.TestCase):
    def test_descriptive_stats_use_conventional_70_30_zones(self):
        series = [{"timestamp": f"t{i}", "value": v} for i, v in enumerate([80, 75, 50, 20, 15])]
        stats = summarize_rsi(series)
        self.assertEqual(stats["count"], 5)
        self.assertEqual(stats["pct_overbought"], 40.0)  # 80,75 >= 70
        self.assertEqual(stats["pct_oversold"], 40.0)    # 20,15 <= 30
        self.assertEqual(stats["pct_neutral"], 20.0)     # 50
        self.assertEqual(stats["last"], 15)

    def test_empty_series_is_explicit_not_a_fake_stat_block(self):
        self.assertEqual(summarize_rsi([]), {"insufficient_data": True})


class TestADX(unittest.TestCase):
    def test_clean_uptrend_gives_adx_100_hand_computed(self):
        # 5 bougies, +1 sur high/low/close a chaque pas -- +DM=1/-DM=0/TR=1.5
        # partout -> DX=100 partout -> ADX=100 (periode=2, minimum 2*2+1=5).
        closes = [9.5, 10.5, 11.5, 12.5, 13.5]
        bars = [bar(f"t{i}", h=c + 0.5, l=c - 0.5, c=c) for i, c in enumerate(closes)]
        adx = compute_adx(bars, period=2)
        self.assertEqual(len(adx), 2)
        self.assertAlmostEqual(adx[0]["value"], 100.0, places=4)
        self.assertAlmostEqual(adx[0]["plus_di"], 66.6667, places=4)
        self.assertAlmostEqual(adx[0]["minus_di"], 0.0, places=4)
        self.assertEqual(adx[0]["timestamp"], "t3")
        self.assertAlmostEqual(adx[1]["value"], 100.0, places=4)
        self.assertEqual(adx[1]["timestamp"], "t4")

    def test_zigzag_hand_computed_period_2(self):
        # Alternance haut/bas stricte -- valeurs calculees a la main :
        # dx = [0.0, 50.0, 25.0] -> adx = [25.0, 25.0].
        highs_lows_closes = [(10, 9, 9.5), (11, 10, 10.5), (10, 9, 9.5), (11, 10, 10.5), (10, 9, 9.5)]
        bars = [bar(f"t{i}", h=h, l=l, c=c) for i, (h, l, c) in enumerate(highs_lows_closes)]
        adx = compute_adx(bars, period=2)
        self.assertEqual(len(adx), 2)
        self.assertAlmostEqual(adx[0]["value"], 25.0, places=4)
        self.assertAlmostEqual(adx[1]["value"], 25.0, places=4)

    def test_insufficient_data_returns_empty_list(self):
        bars = [bar(f"t{i}", h=1, l=0, c=0.5) for i in range(4)]
        self.assertEqual(compute_adx(bars, period=2), [])  # il faut 2*2+1=5


class TestADXSummary(unittest.TestCase):
    def test_descriptive_stats_use_conventional_25_20_zones(self):
        series = [{"timestamp": f"t{i}", "value": v, "plus_di": 0, "minus_di": 0} for i, v in enumerate([30, 26, 18, 15])]
        stats = summarize_adx(series)
        self.assertEqual(stats["pct_trending"], 50.0)  # 30,26 >= 25
        self.assertEqual(stats["pct_ranging"], 50.0)   # 18,15 <= 20

    def test_empty_series_is_explicit(self):
        self.assertEqual(summarize_adx([]), {"insufficient_data": True})


class TestEMA(unittest.TestCase):
    def test_hand_computed_uptrend_period_3(self):
        # SMA(10,11,12)=11 amorce l'EMA ; multiplicateur 2/(3+1)=0.5.
        closes = [10, 11, 12, 13, 14, 15]
        bars = [bar(f"t{i}", c=c) for i, c in enumerate(closes)]
        ema = compute_ema(bars, period=3)
        self.assertEqual([p["value"] for p in ema], [11.0, 12.0, 13.0, 14.0])
        self.assertEqual(ema[0]["timestamp"], "t2")

    def test_insufficient_data_returns_empty_list(self):
        bars = [bar(f"t{i}", c=c) for i, c in enumerate([1, 2])]
        self.assertEqual(compute_ema(bars, period=3), [])


class TestEMASummary(unittest.TestCase):
    def test_descriptive_stats_price_always_above_rising_ema_no_crossing(self):
        closes = [10, 11, 12, 13, 14, 15]
        bars = [bar(f"t{i}", c=c) for i, c in enumerate(closes)]
        ema = compute_ema(bars, period=3)
        stats = summarize_ema(bars, ema, period=3)
        self.assertEqual(stats["pct_price_above"], 100.0)
        self.assertEqual(stats["pct_price_below"], 0.0)
        self.assertEqual(stats["pct_rising"], 100.0)
        self.assertEqual(stats["crossings"], 0)
        self.assertEqual(stats["last"], 14.0)

    def test_a_real_crossing_is_counted_exactly_once(self):
        # Prix qui passe sous l'EMA puis repasse au-dessus : une seule
        # traversee entre chaque paire consecutive de bougies concernee.
        closes = [10, 11, 12, 8, 20]
        bars = [bar(f"t{i}", c=c) for i, c in enumerate(closes)]
        ema = compute_ema(bars, period=3)
        stats = summarize_ema(bars, ema, period=3)
        self.assertEqual(stats["crossings"], 2)

    def test_empty_series_is_explicit(self):
        self.assertEqual(summarize_ema([], [], period=3), {"insufficient_data": True})


if __name__ == "__main__":
    unittest.main()
