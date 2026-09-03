import json
import unittest

from pipeline.config import WEB_DATA
from pipeline.pharmacies import assert_known_closures_absent, storefront_identity
import pandas as pd


class ArtifactContract(unittest.TestCase):
    def test_generated_pharmacies_exclude_known_closures(self):
        path = WEB_DATA / "rxgap.json"
        if not path.exists():
            self.skipTest("rxgap.json not built yet")
        data = json.loads(path.read_text(encoding="utf-8"))
        df = pd.DataFrame(data["pharmacies"])
        assert_known_closures_absent(df)
        self.assertTrue(any(p["inStudyArea"] for p in data["pharmacies"]))
        self.assertIn("simulatable", data["pharmacies"][0])
        study = [p for p in data["pharmacies"] if p["inStudyArea"]]
        processed = pd.read_csv("data/processed/pharmacies.csv", dtype=str)
        self.assertEqual(
            len(data["pharmacies"]),
            len(processed),
            "artifact should include every licensed pharmacy in the analysis envelope",
        )
        self.assertGreater(len(study), 90, "study-area pharmacies should be exported")
        self.assertTrue(any(not p["simulatable"] for p in data["pharmacies"]))
        hex_cities = {row["city"] for row in data["hexes"]}
        for name in ("Brookline", "Somerville", "Chelsea"):
            self.assertIn(name, hex_cities, f"demand should include {name}")
        self.assertTrue(
            any(p["simulatable"] and "Somerville" in str(p["city"]) for p in data["pharmacies"])
        )
        self.assertTrue(
            any(p["simulatable"] and "Brookline" in str(p["city"]) for p in data["pharmacies"])
        )
        known = {
            "DS90294": (42.3656965, -71.0617268),
            "DS2636": (42.3620776, -71.0656249),
            "DS89764": (42.3654203, -71.0608938),
        }
        by_id = {p["id"]: p for p in data["pharmacies"]}
        for license_id, (lat, lon) in known.items():
            p = by_id[license_id]
            meters = ((p["lat"] - lat) ** 2 + (p["lon"] - lon) ** 2) ** 0.5 * 111_000
            self.assertLess(meters, 50, f"{license_id} plotted {meters:.0f} m from storefront")

    def test_generated_demand_conserves_households(self):
        path = WEB_DATA / "rxgap.json"
        if not path.exists():
            self.skipTest("rxgap.json not built yet")
        data = json.loads(path.read_text(encoding="utf-8"))
        allocated = sum(float(row["households"]) for row in data["hexes"])
        self.assertAlmostEqual(allocated, float(data["meta"]["noVehicleHouseholds"]), delta=1.0)

    def test_routing_has_one_license_per_storefront_identity(self):
        pharmacies = pd.read_csv("data/processed/pharmacies_snapped.csv", dtype=str)
        routable = pharmacies[pharmacies["routable"].str.lower().eq("true")].copy()
        identities = routable.apply(storefront_identity, axis=1).dropna()
        self.assertFalse(identities.duplicated().any())

    def test_build_reports_pass_validity_checks(self):
        data = json.loads((WEB_DATA / "rxgap.json").read_text(encoding="utf-8"))
        reports = data["meta"]["reports"]
        self.assertTrue(reports["graph"]["all_pass"])
        self.assertTrue(reports["buildings_demand"]["mass_conserved"])
        self.assertEqual(reports["pharmacies"]["local_geocode_unresolved"], [])
        if "validation" in reports:
            self.assertIn("pairs", reports["validation"])
            self.assertGreaterEqual(len(reports["validation"]["pairs"]), 5)
