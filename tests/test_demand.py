import unittest

import pandas as pd

from pipeline.demand import allocate_households


class DemandAllocation(unittest.TestCase):
    def test_prefers_residential_per_block_group_and_preserves_mass(self):
        bgs = pd.DataFrame(
            [
                {"geoid": "a", "city": "Boston", "lat": 1.0, "lon": 1.0, "no_vehicle": 10.0},
                {"geoid": "b", "city": "Boston", "lat": 2.0, "lon": 2.0, "no_vehicle": 20.0},
                {"geoid": "c", "city": "Cambridge", "lat": 3.0, "lon": 3.0, "no_vehicle": 30.0},
            ]
        )
        mapped = pd.DataFrame(
            [
                {"id": "home", "lat": 1.0, "lon": 1.0, "weight": 2.0, "residential": True, "geoid": "a", "city": "Boston"},
                {"id": "shop", "lat": 1.1, "lon": 1.1, "weight": 8.0, "residential": False, "geoid": "a", "city": "Boston"},
                {"id": "unknown", "lat": 2.0, "lon": 2.0, "weight": 4.0, "residential": False, "geoid": "b", "city": "Boston"},
            ]
        )

        out = allocate_households(mapped, bgs)

        self.assertNotIn("shop", set(out["id"]))
        self.assertIn("unknown", set(out["id"]))
        self.assertIn("block-group:c", set(out["id"]))
        self.assertAlmostEqual(out["hh"].sum(), 60.0)


if __name__ == "__main__":
    unittest.main()
