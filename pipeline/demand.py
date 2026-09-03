"""ACS no-vehicle households, dasymetric buildings, H3 demand cells."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import requests
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping
from shapely.ops import unary_union
from shapely.prepared import prep

from pipeline.config import (
    DATA_PROCESSED,
    DATA_RAW,
    DATA_REPORTS,
    H3_RESOLUTION,
    STUDY_AREA_LABEL,
    bbox_polygon,
    ensure_dirs,
)
from pipeline.db import connect

TIGER_COUSUB = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_25_cousub_500k.zip"
TIGER_BG = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_25_bg_500k.zip"
ACS_B25044 = "https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/acsdt5y2023-b25044.dat"


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
        shp = next(p for p in extract_dir.glob("*.shp"))
    return shp


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


def assign_city(geom, cities: dict) -> str | None:
    """Prefer the municipality containing the centroid; else largest overlap."""
    centroid = geom.centroid
    for name, city_geom in cities.items():
        if centroid.within(city_geom) or centroid.within(city_geom.buffer(0.0001)):
            return name
    best_name, best_area = None, 0.0
    for name, city_geom in cities.items():
        if not geom.intersects(city_geom):
            continue
        area = geom.intersection(city_geom).area
        if area > best_area:
            best_name, best_area = name, area
    return best_name


def load_cities(con) -> dict:
    """MA cities/towns that intersect the analysis bbox, clipped to that bbox."""
    shp = _shp_from_zip(_download(TIGER_COUSUB, DATA_RAW / "cb_2023_25_cousub_500k.zip"))
    geom = _geom_col(con, shp)
    cities = con.execute(
        f"""
        SELECT NAME as name, ST_AsText({geom}) AS wkt
        FROM ST_Read('{shp.as_posix()}')
        """
    ).df()
    frame = bbox_polygon()
    geoms: dict = {}
    for row in cities.itertuples(index=False):
        name = display_cousub_name(row.name)
        if not name or "not defined" in name.lower():
            continue
        geom = shapely_wkt.loads(row.wkt)
        if not geom.intersects(frame):
            continue
        clipped = geom.intersection(frame)
        if clipped.is_empty:
            continue
        geoms[name] = unary_union([geoms[name], clipped]) if name in geoms else clipped
    if not geoms:
        raise RuntimeError("No county subdivisions intersect the analysis bbox")
    print(f"Study municipalities in bbox: {len(geoms)} ({', '.join(sorted(geoms))})", flush=True)
    return geoms


def load_acs() -> pd.DataFrame:
    dest = DATA_RAW / "acsdt5y2023-b25044.dat"
    _download(ACS_B25044, dest)
    df = pd.read_csv(
        dest,
        sep="|",
        dtype=str,
        usecols=["GEO_ID", "B25044_E001", "B25044_M001", "B25044_E003", "B25044_M003", "B25044_E010", "B25044_M010"],
    )
    df = df[df["GEO_ID"].str.startswith("1500000US25", na=False)].copy()
    df["geoid"] = df["GEO_ID"].str.replace("1500000US", "", regex=False)
    df["households"] = pd.to_numeric(df["B25044_E001"], errors="coerce").fillna(0)
    owner = pd.to_numeric(df["B25044_E003"], errors="coerce").fillna(0)
    renter = pd.to_numeric(df["B25044_E010"], errors="coerce").fillna(0)
    owner_moe = pd.to_numeric(df["B25044_M003"], errors="coerce").fillna(0)
    renter_moe = pd.to_numeric(df["B25044_M010"], errors="coerce").fillna(0)
    df["no_vehicle"] = owner + renter
    df["no_vehicle_moe"] = np.sqrt(owner_moe**2 + renter_moe**2)
    print(f"ACS block groups in MA: {len(df)}", flush=True)
    return df[["geoid", "households", "no_vehicle", "no_vehicle_moe"]]


def load_block_groups(con, cities: dict) -> pd.DataFrame:
    shp = _shp_from_zip(_download(TIGER_BG, DATA_RAW / "cb_2023_25_bg_500k.zip"))
    geom = _geom_col(con, shp)
    bgs = con.execute(
        f"""
        SELECT GEOID as geoid, ST_AsText({geom}) AS wkt
        FROM ST_Read('{shp.as_posix()}')
        """
    ).df()
    union = unary_union(list(cities.values()))
    hits = prep(union)
    keep = []
    for rec in bgs.itertuples(index=False):
        geom = shapely_wkt.loads(rec.wkt)
        if not hits.intersects(geom):
            continue
        inter = geom.intersection(union)
        if inter.is_empty:
            continue
        city = assign_city(geom, cities)
        if city is None:
            continue
        point = inter.representative_point()
        keep.append(
            {
                "geoid": rec.geoid,
                "city": city,
                "wkt": inter.wkt,
                "area": inter.area,
                "orig_area": geom.area,
                "clip_ratio": (inter.area / geom.area) if geom.area else 1.0,
                "lat": point.y,
                "lon": point.x,
            }
        )
    return pd.DataFrame(keep)


def load_buildings(con, union_wkt: str) -> pd.DataFrame:
    path = DATA_RAW / "buildings.parquet"
    con.execute("CREATE OR REPLACE TABLE city_union AS SELECT ST_GeomFromText(?) AS geom", [union_wkt])
    return con.execute(
        f"""
        SELECT id, subtype, class, height, num_floors,
               ST_X(ST_Centroid(geometry)) AS lon,
               ST_Y(ST_Centroid(geometry)) AS lat,
               ST_Area(geometry) AS area_m2
        FROM read_parquet('{path.as_posix()}')
        WHERE ST_Intersects(ST_Centroid(geometry), (SELECT geom FROM city_union))
        """
    ).df()


def is_residential(row: pd.Series) -> bool:
    raw = row.get("subtype")
    subtype = "" if pd.isna(raw) else str(raw).lower()
    klass = "" if pd.isna(row.get("class")) else str(row.get("class")).lower()
    if subtype in {"", "unknown", "none", "null", "nan"}:
        tokens = klass
    else:
        tokens = f"{subtype} {klass}"
    if subtype == "residential" or any(t in tokens for t in ("apartment", "house", "dwell", "residential", "dorm")):
        return True
    return False


def allocate_households(mapped: pd.DataFrame, bgs: pd.DataFrame) -> pd.DataFrame:
    """Prefer residential buildings per block group and preserve every ACS household."""
    if mapped.empty:
        selected = mapped.copy()
    else:
        has_residential = mapped.groupby("geoid")["residential"].transform("any")
        selected = mapped[mapped["residential"] | ~has_residential].copy()

    missing = bgs[~bgs["geoid"].isin(selected.get("geoid", []))]
    if len(missing):
        fallback = missing[["geoid", "city", "lat", "lon"]].copy()
        fallback["id"] = "block-group:" + fallback["geoid"].astype(str)
        fallback["weight"] = 1.0
        fallback["residential"] = False
        selected = pd.concat([selected, fallback[selected.columns]], ignore_index=True)

    weights = selected.groupby("geoid")["weight"].sum().rename("bg_weight")
    selected = selected.merge(weights, on="geoid").merge(
        bgs[["geoid", "no_vehicle"]], on="geoid", how="left", validate="many_to_one"
    )
    selected["hh"] = selected["no_vehicle"] * selected["weight"] / selected["bg_weight"]

    expected = float(bgs["no_vehicle"].sum())
    allocated = float(selected["hh"].sum())
    if not np.isclose(allocated, expected, rtol=0, atol=0.01):
        raise RuntimeError(f"Demand allocation lost households: {allocated:.3f} of {expected:.3f}")
    return selected


PARTIAL_CLIP = 0.99
MATERIAL_OUTSIDE = 0.01


def clip_stats(bgs: pd.DataFrame) -> dict:
    """How much ACS mass sits in block groups that are only partly in the study union."""
    ratio = bgs["clip_ratio"].fillna(1).clip(lower=0, upper=1)
    partial = ratio < PARTIAL_CLIP
    nv = bgs["no_vehicle"].fillna(0)
    moe = bgs["no_vehicle_moe"].fillna(0)
    outside = float((nv * (1 - ratio)).sum())
    total = float(nv.sum())
    return {
        "block_groups": int(len(bgs)),
        "partial_clip_block_groups": int(partial.sum()),
        "partial_clip_share": round(float(partial.mean()), 4) if len(bgs) else 0.0,
        "no_vehicle_in_partial": round(float(nv[partial].sum()), 1),
        "estimated_no_vehicle_outside_by_area": round(outside, 1),
        "estimated_outside_share": round(outside / total, 4) if total else 0.0,
        "min_clip_ratio": round(float(ratio.min()), 4) if len(bgs) else 1.0,
        "no_vehicle_moe": round(float(np.sqrt((moe ** 2).sum())), 1),
    }


def apply_inside_allocation(bgs: pd.DataFrame, stats: dict) -> pd.DataFrame:
    """If the clipped-away share is material, keep only the inside ACS share."""
    out = bgs.copy()
    if stats["estimated_outside_share"] >= MATERIAL_OUTSIDE:
        ratio = out["clip_ratio"].fillna(1).clip(lower=0, upper=1)
        out["no_vehicle"] = out["no_vehicle"] * ratio
        out["no_vehicle_moe"] = out["no_vehicle_moe"] * ratio
        stats["allocated_by_clip_ratio"] = True
    else:
        stats["allocated_by_clip_ratio"] = False
    return out


def run() -> pd.DataFrame:
    ensure_dirs()
    con = connect()
    cities = load_cities(con)
    union = unary_union(list(cities.values()))
    acs = load_acs()
    bgs = load_block_groups(con, cities).merge(acs, on="geoid", how="left")
    bgs["no_vehicle"] = bgs["no_vehicle"].fillna(0)
    bgs["no_vehicle_moe"] = bgs["no_vehicle_moe"].fillna(0)
    bgs["households"] = bgs["households"].fillna(0)
    clips = clip_stats(bgs)
    clips["residential_building_weight_outside_extract"] = 0.0
    clips["note"] = (
        "Buildings are extracted inside the study union, so residential weight "
        "outside the window is unobserved. Area-based ACS share is the proxy."
    )
    bgs = apply_inside_allocation(bgs, clips)

    buildings = load_buildings(con, union.wkt)
    buildings["residential"] = buildings.apply(is_residential, axis=1)
    floors = pd.to_numeric(buildings["num_floors"], errors="coerce").to_numpy(dtype="float64")
    height = pd.to_numeric(buildings["height"], errors="coerce").to_numpy(dtype="float64")
    area = pd.to_numeric(buildings["area_m2"], errors="coerce").to_numpy(dtype="float64")
    floors = np.where(np.isnan(floors), np.where(np.isnan(height), 1.0, np.maximum(height / 3.1, 1.0)), floors)
    floors = np.clip(floors, 1.0, None)
    area = np.where(np.isnan(area) | (area <= 0), 80.0, area)
    buildings["weight"] = area * floors

    con.register("building_pts", buildings[["id", "lat", "lon", "weight", "residential"]])
    con.execute("CREATE OR REPLACE TABLE bgs_geom (geoid VARCHAR, city VARCHAR, geom GEOMETRY)")
    for rec in bgs.itertuples(index=False):
        con.execute(
            "INSERT INTO bgs_geom VALUES (?, ?, ST_GeomFromText(?))",
            [rec.geoid, rec.city, rec.wkt],
        )
    mapped = con.execute(
        """
        SELECT b.id, b.lat, b.lon, b.weight, b.residential, g.geoid, g.city
        FROM building_pts b
        JOIN bgs_geom g ON ST_Contains(g.geom, ST_Point(b.lon, b.lat))
        """
    ).df()
    res = allocate_households(mapped, bgs)

    res["h3"] = [h3.latlng_to_cell(lat, lon, H3_RESOLUTION) for lat, lon in zip(res["lat"], res["lon"])]
    hexes = (
        res.groupby(["h3", "city"], as_index=False)
        .agg(no_vehicle=("hh", "sum"), buildings=("id", "count"), lat=("lat", "mean"), lon=("lon", "mean"))
        .sort_values("no_vehicle", ascending=False)
    )

    coverage = {
        "study_area_label": STUDY_AREA_LABEL,
        "cities": sorted(cities),
        "buildings_in_cities": int(len(buildings)),
        "residential_buildings": int(buildings["residential"].sum()) if "residential" in buildings.columns else int(len(res)),
        "residential_share": round(float(buildings["residential"].mean()), 3) if len(buildings) else 0,
        "num_floors_nonnull": round(float(pd.to_numeric(buildings["num_floors"], errors="coerce").notna().mean()), 3) if len(buildings) else 0,
        "height_nonnull": round(float(pd.to_numeric(buildings["height"], errors="coerce").notna().mean()), 3) if len(buildings) else 0,
        "block_groups": int(len(bgs)),
        "no_vehicle_households": round(float(res["hh"].sum()), 1),
        "no_vehicle_moe": round(float(np.sqrt((bgs["no_vehicle_moe"] ** 2).sum())), 1),
        "fallback_block_groups": int(res["id"].astype(str).str.startswith("block-group:").sum()),
        "mass_conserved": True,
        "hexes": int(len(hexes)),
        "dasymetric_ok": bool(pd.to_numeric(buildings["num_floors"], errors="coerce").notna().mean() > 0.2 or pd.to_numeric(buildings["height"], errors="coerce").notna().mean() > 0.4),
        "boundary_clip": clips,
    }
    hexes.to_csv(DATA_PROCESSED / "hexes.csv", index=False)
    bgs.to_csv(DATA_PROCESSED / "block_groups.csv", index=False)
    outlines = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"name": name}, "geometry": mapping(geom)}
            for name, geom in cities.items()
        ],
    }
    (DATA_PROCESSED / "cities.geojson").write_text(json.dumps(outlines), encoding="utf-8")
    (DATA_REPORTS / "buildings_demand.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    print(json.dumps(coverage, indent=2), flush=True)
    return hexes


if __name__ == "__main__":
    run()
