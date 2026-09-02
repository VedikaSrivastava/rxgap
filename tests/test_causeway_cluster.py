import unittest

import pandas as pd
from scipy.sparse.csgraph import dijkstra

from pipeline.graph import load_graph, nearest_reachable_node


class CausewayCluster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = __import__("pathlib").Path("data/processed/pharmacies_snapped.csv")
        if not path.exists():
            raise unittest.SkipTest("processed pharmacies not built")
        cls.snapped = pd.read_csv(path, dtype=str)

    def test_star_market_snaps_to_main_component(self):
        graph, coords = load_graph()
        star = self.snapped[self.snapped["license"] == "DS90294"].iloc[0]
        node, snap_m = nearest_reachable_node(
            graph, coords, float(star.lat), float(star.lon), max_m=250
        )
        self.assertLessEqual(snap_m, 250)
        cvs = self.snapped[self.snapped["license"] == "DS89764"].iloc[0]
        cvs_node = int(cvs.node)
        meters = dijkstra(graph, directed=False, indices=cvs_node, unweighted=False)[node]
        self.assertTrue(meters < float("inf"))

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
