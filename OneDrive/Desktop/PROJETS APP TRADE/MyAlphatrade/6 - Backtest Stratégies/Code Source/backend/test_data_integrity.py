"""Tests -- data_integrity.py. L'oracle de chaque empreinte est une chaine
LITTERALE ecrite a la main dans le test, jamais recalculee par le module."""
import hashlib
import os
import tempfile
import unittest

from data_integrity import (
    REFERENCE_LAST_BAR, REFERENCE_N, REFERENCE_SHA256, bars_fingerprint, file_sha256_lf,
    reference_series, sha256_lf_normalized, sidecar_text, verify_reference,
)


def bar(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c}


BARS = [
    bar("2026-01-01T00:00:00Z", 1.0, 2.0, 0.5, 1.5),
    bar("2026-01-01T00:15:00Z", 1.5, 2.5, 1.0, 2.0),
]
LINE_1 = "2026-01-01T00:00:00Z|1.0|2.0|0.5|1.5\n"
LINE_2 = "2026-01-01T00:15:00Z|1.5|2.5|1.0|2.0\n"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestFingerprint(unittest.TestCase):
    def test_matches_a_hand_written_literal(self):
        self.assertEqual(bars_fingerprint(BARS), (2, sha(LINE_1 + LINE_2)))

    def test_upper_bound_is_inclusive(self):
        self.assertEqual(bars_fingerprint(BARS, up_to_ts="2026-01-01T00:00:00Z"), (1, sha(LINE_1)))

    def test_a_single_changed_value_changes_the_hash(self):
        changed = [BARS[0], bar("2026-01-01T00:15:00Z", 1.5, 2.5, 1.0, 2.1)]
        self.assertNotEqual(bars_fingerprint(changed)[1], bars_fingerprint(BARS)[1])

    def test_unsorted_or_duplicate_bars_are_refused(self):
        with self.assertRaises(ValueError):
            bars_fingerprint([BARS[1], BARS[0]])
        with self.assertRaises(ValueError):
            bars_fingerprint([BARS[0], BARS[0]])

    def test_the_abandoned_partial_bar_reference_is_not_the_current_one(self):
        self.assertNotEqual(REFERENCE_SHA256, "bc66e254a2e0c5cd63a4214c2f710a6c4598822607864c4fd16c9cf39a92b8c2")
        self.assertEqual((REFERENCE_N, REFERENCE_LAST_BAR), (62521, "2026-09-16T00:30:00Z"))


class TestVerifyReference(unittest.TestCase):
    def test_ok_only_when_count_last_bar_and_hash_all_match(self):
        good = verify_reference(BARS, expected_n=2, expected_last="2026-01-01T00:15:00Z", expected_sha256=sha(LINE_1 + LINE_2))
        self.assertTrue(good["ok"])
        bad_hash = verify_reference(BARS, expected_n=2, expected_last="2026-01-01T00:15:00Z", expected_sha256="0" * 64)
        self.assertFalse(bad_hash["ok"])
        bad_n = verify_reference(BARS, expected_n=3, expected_last="2026-01-01T00:15:00Z", expected_sha256=sha(LINE_1 + LINE_2))
        self.assertFalse(bad_n["ok"])

    def test_only_the_covered_historical_portion_matters_new_bars_do_not_break_it(self):
        extended = BARS + [bar("2026-01-01T00:30:00Z", 2.0, 3.0, 1.5, 2.5)]
        r = verify_reference(extended, expected_n=2, expected_last="2026-01-01T00:15:00Z", expected_sha256=sha(LINE_1 + LINE_2))
        self.assertTrue(r["ok"])  # l'ajout d'une bougie posterieure ne casse pas la reference

    def test_a_modified_historical_bar_is_detected(self):
        tampered = [BARS[0], bar("2026-01-01T00:15:00Z", 1.5, 2.5, 1.0, 9.9)]
        r = verify_reference(tampered, expected_n=2, expected_last="2026-01-01T00:15:00Z", expected_sha256=sha(LINE_1 + LINE_2))
        self.assertFalse(r["ok"])


class TestReferenceSeries(unittest.TestCase):
    def test_keeps_bars_up_to_the_reference_inclusive_and_nothing_after(self):
        bars = BARS + [bar("2026-01-01T00:30:00Z", 9.0, 9.0, 9.0, 9.0)]
        self.assertEqual(reference_series(bars, last_bar="2026-01-01T00:15:00Z"), BARS)

    def test_a_partial_later_bar_never_reaches_the_series_and_never_changes_its_fingerprint(self):
        partial = bar("2026-01-01T00:30:00Z", 2.0, 2.2, 1.9, 2.1)        # bougie posterieure stockee partielle
        rewritten = bar("2026-01-01T00:30:00Z", 2.0, 3.0, 1.5, 2.9)      # meme bougie, OHLC final apres import
        f1 = bars_fingerprint(reference_series(BARS + [partial], last_bar="2026-01-01T00:15:00Z"))
        f2 = bars_fingerprint(reference_series(BARS + [rewritten], last_bar="2026-01-01T00:15:00Z"))
        self.assertEqual(f1, f2)
        self.assertEqual(f1, (2, sha(LINE_1 + LINE_2)))

    def test_default_bound_is_the_locked_reference_bar(self):
        late = bar("2026-09-16T00:45:00Z", 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(reference_series([late]), [])


class TestLfNormalizedHash(unittest.TestCase):
    def test_crlf_and_lf_give_the_same_probative_hash(self):
        lf, crlf = b"a\nb\n", b"a\r\nb\r\n"
        self.assertEqual(sha256_lf_normalized(crlf), sha256_lf_normalized(lf))
        self.assertEqual(sha256_lf_normalized(lf), hashlib.sha256(lf).hexdigest())
        self.assertNotEqual(hashlib.sha256(crlf).hexdigest(), hashlib.sha256(lf).hexdigest())  # le piege reel

    def test_file_hash_ignores_working_copy_line_endings(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.md")
            with open(p, "wb") as f:
                f.write(b"ligne1\r\nligne2\r\n")
            self.assertEqual(file_sha256_lf(p), hashlib.sha256(b"ligne1\nligne2\n").hexdigest())

    def test_sidecar_format(self):
        self.assertEqual(sidecar_text("ab" * 32, "PREREG_001_ADX_M15.md"), "ab" * 32 + "  PREREG_001_ADX_M15.md\n")


if __name__ == "__main__":
    unittest.main()
