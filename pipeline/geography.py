"""Study municipalities, analysis envelope, and derived geography artifacts.

Downstream stages must read the cached artifacts written by resolve() — do not
recompute slightly different geometry independently.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import requests
from pyproj import Transformer
from shapely import wkt as shapely_wkt
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform, unary_union

from pipeline.config import (
    ANALYSIS_BBOX_PATH,
    ANALYSIS_ENVELOPE_GEOJSON,
    BUFFER_KM,
    CITIES_GEOJSON,
    DATA_RAW,
    GEOGRAPHY_REPORT,
    ROOT,
    STUDY_AREA_LABEL,
    STUDY_MUNICIPALITIES,
    ensure_dirs,
)
from pipeline.db import connect

TIGER_COUSUB = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_25_cousub_500k.zip"
CRS_WGS84 = "EPSG:4326"
CRS_MA = "EPSG:26986"  # NAD83 / Massachusetts Mainland


def _download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with dest.open("wb") as f:
            for chunk in resp.iter_content(1024 * 256):
                if chunk:
                    f.write(chunk)
    return dest


def _shp_from_zip(zip_path: Path) -> Path:
    extract_dir = DATA_RAW / zip_path.stem
    extract_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir)
        return next(p for p in extract_dir.glob("*.shp"))


def _geom_col(con, shp: Path) -> str:
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM ST_Read('{shp.as_posix()}')").fetchall()]
    for name in ("geom", "geometry", "GEOM", "GEOMETRY"):
        if name in cols:
            return name
    return cols[-1]


def display_cousub_name(name: str) -> str:
    name = str(name).strip()
    if name.lower().endswith(" town"):
        return name[: -len(" town")].rstrip()
    return name


def _to_ma():
    return Transformer.from_crs(CRS_WGS84, CRS_MA, always_xy=True).transform


def _to_wgs84():
    return Transformer.from_crs(CRS_MA, CRS_WGS84, always_xy=True).transform


def area_m2(geom) -> float:
    return float(transform(_to_ma(), geom).area)


def load_study_municipalities(con=None) -> dict:
    """Full unclipped TIGER county-subdivision polygons for STUDY_MUNICIPALITIES."""
    own_con = con is None
    if own_con:
        con = connect()
    try:
        shp = _shp_from_zip(_download(TIGER_COUSUB, DATA_RAW / "cb_2023_25_cousub_500k.zip"))
        geom = _geom_col(con, shp)
        cities = con.execute(
            f"""
            SELECT NAME as name, ST_AsText({geom}) AS wkt
            FROM ST_Read('{shp.as_posix()}')
            """
        ).df()
    finally:
        if own_con:
            con.close()

    wanted = {name.lower(): name for name in STUDY_MUNICIPALITIES}
    geoms: dict = {}
    for row in cities.itertuples(index=False):
        name = display_cousub_name(row.name)
        key = name.lower()
        if key not in wanted:
            continue
        canonical = wanted[key]
        geom = shapely_wkt.loads(row.wkt)
        if geom.is_empty:
            continue
        geoms[canonical] = unary_union([geoms[canonical], geom]) if canonical in geoms else geom

    missing = [name for name in STUDY_MUNICIPALITIES if name not in geoms]
    if missing:
        raise RuntimeError(f"Study municipalities missing from TIGER cousubs: {missing}")
    return {name: geoms[name] for name in STUDY_MUNICIPALITIES}


def study_union_from_cities(cities: dict):
    return unary_union(list(cities.values()))


def analysis_envelope_from_union(union, buffer_km: float = BUFFER_KM):
    """WGS84 → EPSG:26986 → buffer(meters) → WGS84. Never buffer in degrees."""
    projected = transform(_to_ma(), union)
    buffered = projected.buffer(buffer_km * 1000.0)
    return transform(_to_wgs84(), buffered)


def bbox_from_envelope(envelope) -> dict[str, float]:
    minx, miny, maxx, maxy = envelope.bounds
    return {
        "xmin": round(float(minx), 6),
        "ymin": round(float(miny), 6),
        "xmax": round(float(maxx), 6),
        "ymax": round(float(maxy), 6),
    }


def read_cities_geojson() -> dict:
    if not CITIES_GEOJSON.exists():
        raise RuntimeError(f"Missing {CITIES_GEOJSON}. Run geography.resolve first.")
    fc = json.loads(CITIES_GEOJSON.read_text(encoding="utf-8"))
    return {f["properties"]["name"]: shape(f["geometry"]) for f in fc["features"]}


def study_union():
    return study_union_from_cities(read_cities_geojson())


def analysis_envelope():
    if not ANALYSIS_ENVELOPE_GEOJSON.exists():
        raise RuntimeError(f"Missing {ANALYSIS_ENVELOPE_GEOJSON}. Run geography.resolve first.")
    fc = json.loads(ANALYSIS_ENVELOPE_GEOJSON.read_text(encoding="utf-8"))
    return shape(fc["features"][0]["geometry"])


def analysis_bbox() -> dict[str, float]:
    if not ANALYSIS_BBOX_PATH.exists():
        raise RuntimeError(f"Missing {ANALYSIS_BBOX_PATH}. Run geography.resolve first.")
    return json.loads(ANALYSIS_BBOX_PATH.read_text(encoding="utf-8"))


def point_in_study(lon: float, lat: float, union=None) -> bool:
    geom = union if union is not None else study_union()
    return bool(geom.covers(Point(lon, lat)))


def point_in_envelope(lon: float, lat: float, envelope=None) -> bool:
    geom = envelope if envelope is not None else analysis_envelope()
    return bool(geom.covers(Point(lon, lat)))


def resolve() -> dict:
    """Download TIGER once, write cities / envelope / bbox artifacts + report."""
    ensure_dirs()
    cities = load_study_municipalities()
    union = study_union_from_cities(cities)
    envelope = analysis_envelope_from_union(union)
    bbox = bbox_from_envelope(envelope)

    source_area = sum(area_m2(g) for g in cities.values())
    union_area = area_m2(union)
    envelope_area = area_m2(envelope)

    cities_fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": name}, "geometry": mapping(geom)}
            for name, geom in cities.items()
        ],
    }
    CITIES_GEOJSON.write_text(json.dumps(cities_fc), encoding="utf-8")

    envelope_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "analysis_envelope", "buffer_km": BUFFER_KM},
                "geometry": mapping(envelope),
            }
        ],
    }
    ANALYSIS_ENVELOPE_GEOJSON.write_text(json.dumps(envelope_fc), encoding="utf-8")
    ANALYSIS_BBOX_PATH.write_text(json.dumps(bbox, indent=2), encoding="utf-8")

    # Re-read cached cities to confirm round-trip area matches source write.
    cached = read_cities_geojson()
    cached_area = sum(area_m2(g) for g in cached.values())

    report = {
        "study_area_label": STUDY_AREA_LABEL,
        "requested": len(STUDY_MUNICIPALITIES),
        "resolved": len(cities),
        "missing": [],
        "municipalities": list(STUDY_MUNICIPALITIES),
        "source_area_m2": round(source_area, 1),
        "cached_area_m2": round(cached_area, 1),
        "study_union_area_m2": round(union_area, 1),
        "envelope_area_m2": round(envelope_area, 1),
        "buffer_km": BUFFER_KM,
        "crs_buffer": CRS_MA,
        "bbox": bbox,
        "artifacts": {
            "cities": CITIES_GEOJSON.resolve().relative_to(ROOT.resolve()).as_posix(),
            "envelope": ANALYSIS_ENVELOPE_GEOJSON.resolve()
            .relative_to(ROOT.resolve())
            .as_posix(),
            "bbox": ANALYSIS_BBOX_PATH.resolve().relative_to(ROOT.resolve()).as_posix(),
        },
        "note": (
            "Study area is 22 complete municipalities. Demand and closable pharmacies "
            "are inside the study union only. Network extract uses the envelope bbox; "
            "context pharmacies must lie inside the true envelope polygon."
        ),
    }
    if abs(source_area - cached_area) / max(source_area, 1.0) > 1e-6:
        raise RuntimeError("Cached cities.geojson area diverged from source municipalities")
    if not envelope.covers(union):
        raise RuntimeError("Analysis envelope does not cover the study union")

    GEOGRAPHY_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return report


# Back-compat names used during the study_area → geography rename.
load_study_cities = load_study_municipalities


if __name__ == "__main__":
    resolve()
