import unittest

from pipeline.pharmacies import (
    clean_address,
    mark_duplicate_licenses,
    match_overture,
    overture_address_backfill,
    refine_coordinates,
    storefront_name_match,
)
import pandas as pd


class PharmacyGeo(unittest.TestCase):
    def test_clean_address_strips_manager_name(self):
        raw = "Steve Sungkyun Jung 101 Canal Street, Suffolk"
        self.assertEqual(clean_address(raw), "101 Canal Street")

    def test_clean_address_keeps_suite(self):
        raw = "160 Canal St Ste 1"
        self.assertIn("160", clean_address(raw))

    def test_storefront_name_match(self):
        self.assertTrue(storefront_name_match("Star Market #3696", "Star Market Pharmacy"))
        self.assertTrue(storefront_name_match("CVS #11201", "CVS Pharmacy"))
        self.assertFalse(storefront_name_match("CVS #11201", "Walgreens"))

    def test_refine_coordinates_prefers_overture_when_chain_matches(self):
        df = pd.DataFrame(
            [
                {
                    "name": "Star Market #3696",
                    "lat": 42.3643,
                    "lon": -71.0634,
                    "overture_lat": 42.3665,
                    "overture_lon": -71.0615,
                    "overture_m": 116.0,
                    "overture_name": "Star Market Pharmacy",
                }
            ]
        )
        out = refine_coordinates(df)
        self.assertAlmostEqual(out.iloc[0].lat, 42.3665, places=4)
        self.assertEqual(out.iloc[0].loc_source, "overture")

    def test_refine_coordinates_rejects_unrelated_place(self):
        df = pd.DataFrame(
            [
                {
                    "name": "CVS Pharmacy #11200",
                    "lat": 42.35,
                    "lon": -71.08,
                    "overture_lat": 42.3501,
                    "overture_lon": -71.0801,
                    "overture_m": 8.0,
                    "overture_name": "Walgreens #2933",
                }
            ]
        )
        out = refine_coordinates(df)
        self.assertEqual(out.iloc[0].loc_source, "census")
        self.assertAlmostEqual(out.iloc[0].lat, 42.35)

    def test_overture_match_skips_nearer_competitor(self):
        rows = pd.DataFrame([{"name": "CVS #10", "lat": 42.35, "lon": -71.08}])
        places = pd.DataFrame(
            [
                {"id": "wrong", "name": "Walgreens", "lat": 42.35001, "lon": -71.08},
                {"id": "right", "name": "CVS Pharmacy", "lat": 42.3501, "lon": -71.08},
            ]
        )
        out = match_overture(rows, places)
        self.assertEqual(out.iloc[0].overture_id, "right")

    def test_duplicate_license_keeps_newest_as_routable_identity(self):
        rows = pd.DataFrame(
            [
                {
                    "license": "old",
                    "npi": "1234567890",
                    "name": "CVS Pharmacy #10",
                    "Issue Date": "01/01/2000",
                },
                {
                    "license": "new",
                    "npi": "1234567890",
                    "name": "CVS PHARMACY #10",
                    "Issue Date": "01/01/2020",
                },
            ]
        )
        out = mark_duplicate_licenses(rows)
        self.assertEqual(out.loc[0, "duplicate_of"], "new")
        self.assertIsNone(out.loc[1, "duplicate_of"])

    def test_address_backfill_prefers_pharmacy_category(self):
        rows = pd.DataFrame(
            [
                {
                    "name": "CVS Pharmacy #1199",
                    "address": "647 VFW Parkway",
                    "zip": "02467",
                    "lat": None,
                    "lon": None,
                }
            ]
        )
        places = pd.DataFrame(
            [
                {
                    "name": "CVS Pharmacy",
                    "addresses_json": "647 VFW Pkwy, Chestnut Hill MA 02467",
                    "category_primary": "shopping",
                    "confidence": 0.99,
                    "lat": 1.0,
                    "lon": 1.0,
                },
                {
                    "name": "CVS Pharmacy",
                    "addresses_json": "647 VFW Pkwy, Chestnut Hill MA 02467",
                    "category_primary": "pharmacy",
                    "confidence": 0.8,
                    "lat": 2.0,
                    "lon": 2.0,
                },
            ]
        )
        out = overture_address_backfill(rows, places)
        self.assertEqual(out.iloc[0].lat, 2.0)


if __name__ == "__main__":
    unittest.main()
