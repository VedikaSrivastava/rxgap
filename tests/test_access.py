import unittest

import numpy as np

from pipeline.access import with_snaps


class SnapLegs(unittest.TestCase):
    def test_total_includes_both_snaps(self):
        total = with_snaps(np.array([1000.0, 2000.0]), 80.0, 120.0)
        np.testing.assert_allclose(total, [1200.0, 2200.0])

    def test_unreachable_stays_inf(self):
        total = with_snaps(np.array([np.inf, 400.0]), 250.0, 250.0)
        self.assertTrue(np.isinf(total[0]))
        self.assertAlmostEqual(total[1], 900.0)


if __name__ == "__main__":
    unittest.main()
