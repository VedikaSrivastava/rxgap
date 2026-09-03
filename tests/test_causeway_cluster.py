import json
import unittest

import pandas as pd


class CausewayCluster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = __import__("pathlib").Path("data/processed/pharmacies_snapped.csv")
        if not path.exists():
            raise unittest.SkipTest("processed pharmacies not built")
        cls.snapped = pd.read_csv(path, dtype=str)

    def test_star_market_is_routable(self):
        star = self.snapped[self.snapped["license"] == "DS90294"].iloc[0]
        self.assertTrue(str(star.routable).lower() in {"true", "1"})
        self.assertLessEqual(float(star.snap_m), 250)

    def test_star_market_is_reachable_from_nearby_hexes(self):
        access = pd.read_csv("data/processed/access.csv", dtype=str)
        used = (access["nearest_id"] == "DS90294") | (access["second_id"] == "DS90294")
        self.assertTrue(used.any())

    def test_graph_validation_passed(self):
        with open("data/reports/graph.json") as f:
            report = json.load(f)
        self.assertEqual(report["topology"], "overture_connector_id")
        self.assertTrue(report["all_pass"])

    def test_genoa_shown_but_not_routed(self):
        genoa = self.snapped[self.snapped["license"] == "DS90422"]
        self.assertFalse(genoa.empty)
        self.assertFalse(str(genoa.iloc[0].walk_in).lower() in {"true", "1"})
        self.assertFalse(str(genoa.iloc[0].routable).lower() in {"true", "1"})
        access = pd.read_csv("data/processed/access.csv", dtype=str)
        self.assertFalse((access["nearest_id"] == "DS90422").any())
        self.assertFalse((access["second_id"] == "DS90422").any())


if __name__ == "__main__":
    unittest.main()
