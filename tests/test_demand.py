from types import SimpleNamespace
import unittest

import pandas as pd
from shapely.geometry import Point, box

from pipeline.demand import allocate_households, assign_city, display_cousub_name
from pipeline.export import in_study_area

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


class CityAssignment(unittest.TestCase):
    def test_prefers_municipality_containing_centroid(self):
        cities = {"Boston": box(0, 0, 2, 2), "Brookline": box(2, 0, 4, 2)}
        self.assertEqual(assign_city(Point(1, 1).buffer(0.1), cities), "Boston")
        self.assertEqual(assign_city(Point(3, 1).buffer(0.1), cities), "Brookline")

    def test_falls_back_to_largest_overlap(self):
        cities = {"Boston": box(0, 0, 1, 1), "Brookline": box(2, 0, 3, 1)}
        gap_spanning = box(0.8, 0.2, 2.6, 0.8)
        self.assertEqual(assign_city(gap_spanning, cities), "Brookline")

    def test_strips_census_town_suffix(self):
        self.assertEqual(display_cousub_name("Watertown Town"), "Watertown")
        self.assertEqual(display_cousub_name("Boston"), "Boston")


class StudyAreaNames(unittest.TestCase):
    def test_abutting_municipalities_count_as_study_area(self):
        for city in ("Brookline", "Somerville", "Chelsea", "Quincy", "Newton"):
            row = SimpleNamespace(city=city, lon=-71.1, lat=42.35)
            self.assertTrue(in_study_area(row, None), city)


if __name__ == "__main__":
    unittest.main()
