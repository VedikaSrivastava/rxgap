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

from pipeline.config import (
    DATA_PROCESSED,
    DATA_RAW,
    DATA_REPORTS,
    H3_RESOLUTION,
    ensure_dirs,
)
from pipeline.db import connect

TIGER_PLACE = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_25_place_500k.zip"
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


def load_cities(con) -> dict:
    shp = _shp_from_zip(_download(TIGER_PLACE, DATA_RAW / "cb_2023_25_place_500k.zip"))
    geom = _geom_col(con, shp)
    cities = con.execute(
        f"""
        SELECT NAME as name, ST_AsText({geom}) AS wkt
        FROM ST_Read('{shp.as_posix()}')
        WHERE NAME IN ('Boston', 'Cambridge')
        """
    ).df()
    geoms = {row["name"]: shapely_wkt.loads(row["wkt"]) for _, row in cities.iterrows()}
    return geoms


def load_acs() -> pd.DataFrame:
    dest = DATA_RAW / "acsdt5y2023-b25044.dat"
    _download(ACS_B25044, dest)
    df = pd.read_csv(dest, sep="|", dtype=str, usecols=["GEO_ID", "B25044_E001", "B25044_E003", "B25044_E010"])
    df = df[df["GEO_ID"].str.startswith("1500000US25", na=False)].copy()
    df["geoid"] = df["GEO_ID"].str.replace("1500000US", "", regex=False)
    df["households"] = pd.to_numeric(df["B25044_E001"], errors="coerce").fillna(0)
    df["no_vehicle"] = (
        pd.to_numeric(df["B25044_E003"], errors="coerce").fillna(0)
        + pd.to_numeric(df["B25044_E010"], errors="coerce").fillna(0)
    )
    print(f"ACS block groups in MA: {len(df)}", flush=True)
    return df[["geoid", "households", "no_vehicle"]]


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
    keep = []
    for rec in bgs.itertuples(index=False):
        geom = shapely_wkt.loads(rec.wkt)
        if not geom.intersects(union):
            continue
        inter = geom.intersection(union)
        if inter.is_empty:
            continue
        city = "Boston" if geom.centroid.within(cities["Boston"]) or (
            geom.centroid.within(cities["Boston"].buffer(0.0001))
        ) else None
        if city is None and geom.intersects(cities["Cambridge"]):
            if geom.centroid.within(cities["Cambridge"]) or geom.intersection(cities["Cambridge"]).area >= geom.intersection(cities["Boston"]).area:
                city = "Cambridge"
            else:
                city = "Boston"
        if city is None and geom.intersects(cities["Boston"]):
            city = "Boston"
        if city is None:
            continue
        keep.append({"geoid": rec.geoid, "city": city, "wkt": rec.wkt, "area": geom.area})
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
    if any(t in tokens for t in ("industrial", "commercial", "retail", "warehouse", "parking", "garage", "utility", "hospital", "school")):
        return False
    return True


def run() -> pd.DataFrame:
    ensure_dirs()
    con = connect()
    cities = load_cities(con)
    union = unary_union(list(cities.values()))
    acs = load_acs()
    bgs = load_block_groups(con, cities).merge(acs, on="geoid", how="left")
    bgs["no_vehicle"] = bgs["no_vehicle"].fillna(0)
    bgs["households"] = bgs["households"].fillna(0)

    buildings = load_buildings(con, union.wkt)
    buildings["residential"] = buildings.apply(is_residential, axis=1)
    res = buildings[buildings["residential"]].copy()
    if len(res) < 500:
        res = buildings.copy()
        res["residential"] = True

    floors = pd.to_numeric(res["num_floors"], errors="coerce").to_numpy(dtype="float64")
    height = pd.to_numeric(res["height"], errors="coerce").to_numpy(dtype="float64")
    area = pd.to_numeric(res["area_m2"], errors="coerce").to_numpy(dtype="float64")
    floors = np.where(np.isnan(floors), np.where(np.isnan(height), 1.0, np.maximum(height / 3.1, 1.0)), floors)
    floors = np.clip(floors, 1.0, None)
    area = np.where(np.isnan(area) | (area <= 0), 80.0, area)
    res = res.copy()
    res["weight"] = area * floors

    con.register("res_pts", res[["id", "lat", "lon", "weight"]])
    con.execute("CREATE OR REPLACE TABLE bgs_geom (geoid VARCHAR, city VARCHAR, geom GEOMETRY)")
    for rec in bgs.itertuples(index=False):
        con.execute(
            "INSERT INTO bgs_geom VALUES (?, ?, ST_GeomFromText(?))",
            [rec.geoid, rec.city, rec.wkt],
        )
    res = con.execute(
        """
        SELECT r.id, r.lat, r.lon, r.weight, g.geoid, g.city
        FROM res_pts r
        JOIN bgs_geom g ON ST_Contains(g.geom, ST_Point(r.lon, r.lat))
        """
    ).df()
    bg_weight = res.groupby("geoid")["weight"].sum().rename("bg_weight")
    res = res.merge(bg_weight, on="geoid").merge(bgs[["geoid", "no_vehicle"]], on="geoid", how="left")
    res["hh"] = np.where(res["bg_weight"] > 0, res["no_vehicle"] * res["weight"] / res["bg_weight"], 0)

    res["h3"] = [h3.latlng_to_cell(lat, lon, H3_RESOLUTION) for lat, lon in zip(res["lat"], res["lon"])]
    hexes = (
        res.groupby(["h3", "city"], as_index=False)
        .agg(no_vehicle=("hh", "sum"), buildings=("id", "count"), lat=("lat", "mean"), lon=("lon", "mean"))
        .sort_values("no_vehicle", ascending=False)
    )

    coverage = {
        "buildings_in_cities": int(len(buildings)),
        "residential_buildings": int(buildings["residential"].sum()) if "residential" in buildings.columns else int(len(res)),
        "residential_share": round(float(buildings["residential"].mean()), 3) if len(buildings) else 0,
        "num_floors_nonnull": round(float(pd.to_numeric(buildings["num_floors"], errors="coerce").notna().mean()), 3) if len(buildings) else 0,
        "height_nonnull": round(float(pd.to_numeric(buildings["height"], errors="coerce").notna().mean()), 3) if len(buildings) else 0,
        "block_groups": int(len(bgs)),
        "no_vehicle_households": round(float(bgs["no_vehicle"].sum()), 1),
        "hexes": int(len(hexes)),
        "dasymetric_ok": bool(pd.to_numeric(buildings["num_floors"], errors="coerce").notna().mean() > 0.2 or pd.to_numeric(buildings["height"], errors="coerce").notna().mean() > 0.4),
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
