import unittest

from pipeline.validate import pair_ok, ratio, within_ratio


class ValidationRatios(unittest.TestCase):
    def test_within_ratio_accepts_modest_disagreement(self):
        self.assertTrue(within_ratio(1100, 1000))
        self.assertTrue(within_ratio(900, 1000))
        self.assertFalse(within_ratio(2000, 1000))
        self.assertFalse(within_ratio(400, 1000))

    def test_ratio_skips_missing_values(self):
        self.assertIsNone(ratio(None, 1000))
        self.assertIsNone(ratio(1000, 0))
        self.assertEqual(ratio(0, 0), 1.0)

    def test_pair_ok_ignores_osrm_when_it_detours(self):
        self.assertTrue(pair_ok(737, 686, 4224, "bridge"))
        self.assertTrue(pair_ok(736, 735, 1011, "bridge"))
        self.assertFalse(pair_ok(1500, 735, 1011, "bridge"))
        self.assertTrue(pair_ok(76, 58, 1000, "landmark"))


if __name__ == "__main__":
    unittest.main()
