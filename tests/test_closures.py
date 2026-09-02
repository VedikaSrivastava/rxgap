import unittest

import pandas as pd

from pipeline.pharmacies import assert_known_closures_absent, is_walk_in_storefront, known_closed_hits


class KnownClosures(unittest.TestCase):
    def test_must_not_be_active(self):
        bad = pd.DataFrame(
            [
                {"name": "Walgreens #17257", "address": "90 River St", "city": "Mattapan"},
                {"name": "Walgreens #19067", "address": "1329 Hyde Park Ave", "city": "Hyde Park"},
                {"name": "Walgreens 9538", "address": "2275 Washington St", "city": "Roxbury"},
                {"name": "Walgreens 3016", "address": "416 Warren St", "city": "Roxbury"},
            ]
        )
        self.assertEqual(len(known_closed_hits(bad)), 4)
        with self.assertRaises(RuntimeError):
            assert_known_closures_absent(bad)

    def test_open_store_is_fine(self):
        ok = pd.DataFrame(
            [{"name": "CVS Pharmacy #01002", "address": "36 White St", "city": "Cambridge"}]
        )
        assert_known_closures_absent(ok)
        self.assertEqual(len(known_closed_hits(ok)), 0)

    def test_genoa_back_office_is_not_storefront(self):
        row = pd.Series(
            {
                "name": "Genoa Healthcare LLC",
                "address": "66 Canal Street Room P",
                "taxonomy_codes": "332B00000X,333600000X,3336C0003X,3336L0003X",
            }
        )
        self.assertFalse(is_walk_in_storefront(row))

    def test_nan_taxonomy_is_treated_as_unknown(self):
        row = pd.Series({"name": "CVS 669", "address": "1 Main St", "taxonomy_codes": float("nan")})
        self.assertTrue(is_walk_in_storefront(row))

    def test_cvs_storefront_stays(self):
        row = pd.Series(
            {
                "name": "CVS PHARMACY# 04666",
                "address": "101 Canal Street",
                "taxonomy_codes": "332B00000X,333600000X,3336C0003X",
            }
        )
        self.assertTrue(is_walk_in_storefront(row))


if __name__ == "__main__":
    unittest.main()
