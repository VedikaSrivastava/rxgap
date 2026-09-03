"""CI-friendly geography and artifact membership contracts."""

from __future__ import annotations

import json
import unittest

from shapely.geometry import Point, box, shape
from shapely.ops import unary_union

from pipeline.config import (
    ANALYSIS_BBOX_PATH,
    ANALYSIS_ENVELOPE_GEOJSON,
    CITIES_GEOJSON,
    GEOGRAPHY_REPORT,
    STUDY_MUNICIPALITIES,
    WEB_DATA,
)
from pipeline.geography import analysis_envelope_from_union, bbox_from_envelope, study_union_from_cities


class GeographyUnit(unittest.TestCase):
    def test_envelope_covers_union_and_bbox_is_envelope_bounds(self):
        cities = {
            "A": box(-71.1, 42.3, -71.05, 42.35),
            "B": box(-71.05, 42.3, -71.0, 42.35),
        }
        union = study_union_from_cities(cities)
        envelope = analysis_envelope_from_union(union, buffer_km=3.0)
        self.assertTrue(envelope.covers(union))
        bbox = bbox_from_envelope(envelope)
        self.assertAlmostEqual(bbox["xmin"], envelope.bounds[0], places=5)
        self.assertAlmostEqual(bbox["ymax"], envelope.bounds[3], places=5)


class GeographyArtifacts(unittest.TestCase):
    def test_committed_geography_report_matches_config(self):
        if not GEOGRAPHY_REPORT.exists():
            self.skipTest("geography.json not built yet")
        report = json.loads(GEOGRAPHY_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["requested"], 22)
        self.assertEqual(report["resolved"], 22)
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["municipalities"], list(STUDY_MUNICIPALITIES))
        self.assertAlmostEqual(report["source_area_m2"], report["cached_area_m2"], delta=1.0)
        self.assertGreater(report["envelope_area_m2"], report["study_union_area_m2"])

    def test_derived_artifacts_are_consistent(self):
        if not CITIES_GEOJSON.exists() or not ANALYSIS_ENVELOPE_GEOJSON.exists():
            self.skipTest("geography artifacts not built yet")
        cities_fc = json.loads(CITIES_GEOJSON.read_text(encoding="utf-8"))
        names = [f["properties"]["name"] for f in cities_fc["features"]]
        self.assertEqual(names, list(STUDY_MUNICIPALITIES))
        union = unary_union([shape(f["geometry"]) for f in cities_fc["features"]])
        env_fc = json.loads(ANALYSIS_ENVELOPE_GEOJSON.read_text(encoding="utf-8"))
        envelope = shape(env_fc["features"][0]["geometry"])
        self.assertTrue(envelope.covers(union))
        bbox = json.loads(ANALYSIS_BBOX_PATH.read_text(encoding="utf-8"))
        self.assertAlmostEqual(bbox["xmin"], envelope.bounds[0], places=5)
        self.assertAlmostEqual(bbox["xmax"], envelope.bounds[2], places=5)


class ArtifactMembership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = WEB_DATA / "rxgap.json"
        if not path.exists() or not CITIES_GEOJSON.exists():
            cls.data = None
            return
        cls.data = json.loads(path.read_text(encoding="utf-8"))
        cities_fc = json.loads(CITIES_GEOJSON.read_text(encoding="utf-8"))
        cls.union = unary_union([shape(f["geometry"]) for f in cities_fc["features"]])
        env_fc = json.loads(ANALYSIS_ENVELOPE_GEOJSON.read_text(encoding="utf-8"))
        cls.envelope = shape(env_fc["features"][0]["geometry"])

    def test_meta_cities_match_config(self):
        if self.data is None:
            self.skipTest("rxgap.json not built yet")
        self.assertEqual(self.data["meta"]["cities"], list(STUDY_MUNICIPALITIES))

    def test_exported_demand_points_lie_in_study_union(self):
        if self.data is None:
            self.skipTest("rxgap.json not built yet")
        for hex_row in self.data["hexes"]:
            pt = Point(float(hex_row["lon"]), float(hex_row["lat"]))
            self.assertTrue(
                self.union.covers(pt),
                f"demand point outside study union: {hex_row['h3']} {hex_row['city']}",
            )

    def test_no_demand_in_buffer_only(self):
        if self.data is None:
            self.skipTest("rxgap.json not built yet")
        for hex_row in self.data["hexes"]:
            pt = Point(float(hex_row["lon"]), float(hex_row["lat"]))
            self.assertFalse(
                self.envelope.covers(pt) and not self.union.covers(pt),
                "demand must not exist in the 3 km buffer alone",
            )

    def test_simulatable_pharmacies_in_study_union(self):
        if self.data is None:
            self.skipTest("rxgap.json not built yet")
        for p in self.data["pharmacies"]:
            if not p["simulatable"]:
                continue
            pt = Point(float(p["lon"]), float(p["lat"]))
            self.assertTrue(self.union.covers(pt), p["id"])

    def test_retained_pharmacies_in_envelope(self):
        if self.data is None:
            self.skipTest("rxgap.json not built yet")
        for p in self.data["pharmacies"]:
            pt = Point(float(p["lon"]), float(p["lat"]))
            self.assertTrue(self.envelope.covers(pt), p["id"])
            if not p["inStudyArea"]:
                self.assertTrue(self.envelope.covers(pt))
                self.assertFalse(self.union.covers(pt))


if __name__ == "__main__":
    unittest.main()
