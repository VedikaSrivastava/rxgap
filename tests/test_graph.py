import json
import unittest

from pipeline.config import WALKABLE_CLASSES
from pipeline.graph import build_graph, keep_segment, parse_connectors
import pandas as pd


def _seg(sid, connectors, wkt, name=""):
    return {
        "id": sid,
        "name": name,
        "subtype": "road",
        "class": "residential",
        "access_json": None,
        "connectors_json": json.dumps(connectors),
        "wkt": wkt,
    }


class ConnectorTopology(unittest.TestCase):
    def test_parse_sorted_by_at(self):
        raw = json.dumps(
            [
                {"connector_id": "C", "at": 1.0},
                {"connector_id": "A", "at": 0.0},
                {"connector_id": "B", "at": 0.4},
            ]
        )
        self.assertEqual([c[0] for c in parse_connectors(raw)], ["A", "B", "C"])

    def test_shared_connector_joins_segments(self):
        segs = pd.DataFrame(
            [
                _seg(
                    "s1",
                    [{"connector_id": "A", "at": 0}, {"connector_id": "B", "at": 1}],
                    "LINESTRING (-71.10 42.35, -71.09 42.35)",
                ),
                _seg(
                    "s2",
                    [{"connector_id": "B", "at": 0}, {"connector_id": "C", "at": 1}],
                    "LINESTRING (-71.09 42.35, -71.08 42.35)",
                ),
            ]
        )
        pack = build_graph(segs, {})
        self.assertEqual(pack["graph"].shape[0], 3)
        self.assertGreater(pack["n_edges"], 0)
        g = pack["graph"]
        self.assertGreater(g[0, 1], 0)
        self.assertGreater(g[1, 2], 0)

    def test_coincident_geometry_does_not_join(self):
        wkt = "LINESTRING (-71.10 42.35, -71.09 42.35)"
        segs = pd.DataFrame(
            [
                _seg(
                    "s1",
                    [{"connector_id": "A", "at": 0}, {"connector_id": "B", "at": 1}],
                    wkt,
                ),
                _seg(
                    "s2",
                    [{"connector_id": "D", "at": 0}, {"connector_id": "E", "at": 1}],
                    wkt,
                ),
            ]
        )
        pack = build_graph(segs, {})
        g = pack["graph"]
        # Four nodes, two disjoint edges. No A–D or B–E join from shared coordinates.
        self.assertEqual(pack["graph"].shape[0], 4)
        self.assertEqual(pack["n_edges"], 2)
        self.assertEqual(g[0, 2], 0)
        self.assertEqual(g[1, 3], 0)


class WalkNetwork(unittest.TestCase):
    def test_trunk_is_not_walkable_except_named_bridges(self):
        self.assertNotIn("trunk", WALKABLE_CLASSES)
        self.assertNotIn("motorway", WALKABLE_CLASSES)
        self.assertTrue(keep_segment("trunk", "Longfellow Bridge"))
        self.assertTrue(keep_segment("trunk", "Boston University Bridge"))
        self.assertFalse(keep_segment("trunk", "Memorial Drive"))
        self.assertTrue(keep_segment("residential", "Memorial Drive"))


if __name__ == "__main__":
    unittest.main()
