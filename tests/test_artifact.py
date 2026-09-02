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
            "artifact should include every licensed pharmacy in the bbox",
        )
        self.assertGreater(len(study), 90, "study-area pharmacies should be exported")
        self.assertTrue(any(not p["inStudyArea"] for p in data["pharmacies"]))
        self.assertTrue(any(not p["simulatable"] for p in data["pharmacies"]))

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
