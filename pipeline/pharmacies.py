"""Build a walk-in retail pharmacy set from NPPES + Overture, with optional CMS cross-check."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import time
from typing import Any

import pandas as pd
import requests

from pipeline.config import (
    BBOX,
    DATA_PROCESSED,
    DATA_RAW,
    DATA_REPORTS,
    EXCLUDE_TAXONOMIES,
    RETAIL_TAXONOMY,
    STUDY_CITIES,
    ensure_dirs,
)
from pipeline.db import connect

NPPES = "https://npiregistry.cms.hhs.gov/api/"
MAIL_NAME = re.compile(
    r"\b(?:mail[\s-]?order|long[\s-]?term care|\bltc\b|institutional|nuclear|specialty mail)\b",
    re.I,
)


def _loc_addr(result: dict[str, Any]) -> dict[str, str]:
    for addr in result.get("addresses") or []:
        if addr.get("address_purpose") == "LOCATION":
            return addr
    return (result.get("addresses") or [{}])[0]


CITIES = (
    "BOSTON",
    "CAMBRIDGE",
    "BROOKLINE",
    "SOMERVILLE",
    "NEWTON",
    "WATERTOWN",
    "CHELSEA",
    "EVERETT",
    "MEDFORD",
    "ARLINGTON",
    "BELMONT",
    "REVERE",
    "WINTHROP",
    "MALDEN",
    "QUINCY",
    "DORCHESTER",
    "ROXBURY",
    "JAMAICA PLAIN",
    "BRIGHTON",
    "ALLSTON",
    "CHARLESTOWN",
    "HYDE PARK",
    "MATTAPAN",
    "ROSLINDALE",
    "WEST ROXBURY",
    "EAST BOSTON",
    "SOUTH BOSTON",
    "MISSION HILL",
    "CHESTNUT HILL",
    "BOSTON COLLEGE",
    "HARVARD SQUARE",
)


def _nppes_page(city: str, skip: int) -> list[dict[str, Any]]:
    params = {
        "version": "2.1",
        "taxonomy_description": "Community/Retail Pharmacy",
        "enumeration_type": "NPI-2",
        "state": "MA",
        "city": city,
        "limit": 200,
        "skip": skip,
    }
    resp = requests.get(NPPES, params=params, timeout=45, headers={"User-Agent": "rxgap/0.1"})
    resp.raise_for_status()
    return resp.json().get("results") or []


def _row_from_nppes(item: dict[str, Any]) -> dict[str, Any] | None:
    basic = item.get("basic") or {}
    if basic.get("status") != "A":
        return None
    loc = _loc_addr(item)
    if (loc.get("state") or "").upper() != "MA":
        return None
    taxonomies = item.get("taxonomies") or []
    codes = {t.get("code") for t in taxonomies}
    if RETAIL_TAXONOMY not in codes:
        return None
    dba = next(
        (n.get("organization_name") for n in item.get("other_names") or [] if n.get("organization_name")),
        None,
    )
    license_no = next(
        (t.get("license") for t in taxonomies if t.get("state") == "MA" and t.get("license")),
        next((t.get("license") for t in taxonomies if t.get("license")), None),
    )
    return {
        "npi": str(item.get("number")),
        "legal_name": basic.get("organization_name"),
        "name": dba or basic.get("organization_name"),
        "address": " ".join(x for x in [loc.get("address_1"), loc.get("address_2")] if x),
        "city": (loc.get("city") or "").title(),
        "state": loc.get("state"),
        "zip": (loc.get("postal_code") or "")[:5],
        "phone": loc.get("telephone_number"),
        "license": license_no,
        "taxonomy_codes": ",".join(sorted(c for c in codes if c)),
    }


def fetch_nppes() -> pd.DataFrame:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for city in CITIES:
        skip = 0
        while skip <= 800:
            batch = _nppes_page(city, skip)
            if not batch:
                break
            for item in batch:
                parsed = _row_from_nppes(item)
                if not parsed or parsed["npi"] in seen:
                    continue
                seen.add(parsed["npi"])
                rows.append(parsed)
            print(f"NPPES {city} skip={skip} total={len(rows)}", flush=True)
            if len(batch) < 200:
                break
            skip += 200
            time.sleep(0.1)
    return pd.DataFrame(rows)


def geocode_batch(df: pd.DataFrame) -> pd.DataFrame:
    """Census address batch geocoder, 10k records per POST."""
    buf = io.StringIO()
    for i, row in df.iterrows():
        street = str(row["address"]).replace(",", " ")
        buf.write(f"{i},{street},{row['city']},{row['state'] or 'MA'},{row['zip']}\n")
    files = {"addressFile": ("addresses.csv", buf.getvalue().encode("utf-8"), "text/csv")}
    resp = requests.post(
        "https://geocoding.geo.census.gov/geocoder/locations/addressbatch",
        files=files,
        data={"benchmark": "Public_AR_Current"},
        timeout=120,
    )
    resp.raise_for_status()
    lat = {}
    lon = {}
    for line in resp.text.splitlines():
        parts = next(csv.reader([line]))
        if len(parts) < 6:
            continue
        idx, match = parts[0], parts[2] if len(parts) > 2 else ""
        if "Match" not in match:
            continue
        # id, input, match, matchtype, matched_addr, "lon,lat", tigerline, side
        coords = parts[5].strip().strip('"')
        try:
            x, y = coords.split(",")
            lon[int(idx)] = float(x)
            lat[int(idx)] = float(y)
        except (ValueError, IndexError):
            continue
    out = df.copy()
    out["lat"] = [lat.get(i) for i in out.index]
    out["lon"] = [lon.get(i) for i in out.index]
    return out


def load_overture_pharmacies() -> pd.DataFrame:
    path = DATA_RAW / "places.parquet"
    if not path.exists():
        return pd.DataFrame()
    con = connect()
    rel = con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}') LIMIT 0")
    cols = {d[0] for d in rel.description}
    name = "name" if "name" in cols else "NULL"
    cat = "category_primary" if "category_primary" in cols else "NULL"
    alt = "category_alternate" if "category_alternate" in cols else "NULL"
    tax = "taxonomy_primary" if "taxonomy_primary" in cols else "NULL"
    taxj = "taxonomy_json" if "taxonomy_json" in cols else "NULL"
    basic = "basic_category" if "basic_category" in cols else "NULL"
    conf = "confidence" if "confidence" in cols else "NULL"
    addr = "addresses_json" if "addresses_json" in cols else "NULL"
    frame = con.execute(
        f"""
        SELECT id,
               {name} AS name,
               {cat} AS category_primary,
               {alt} AS category_alternate,
               {tax} AS taxonomy_primary,
               {conf} AS confidence,
               ST_X(geometry) AS lon,
               ST_Y(geometry) AS lat,
               {addr} AS addresses_json
        FROM read_parquet('{path.as_posix()}')
        WHERE lower(coalesce(CAST({name} AS VARCHAR), '')) LIKE '%pharmacy%'
           OR lower(coalesce(CAST({name} AS VARCHAR), '')) LIKE '%cvs%'
           OR lower(coalesce(CAST({name} AS VARCHAR), '')) LIKE '%walgreen%'
           OR lower(coalesce(CAST({name} AS VARCHAR), '')) LIKE '%rite aid%'
           OR lower(coalesce(CAST({cat} AS VARCHAR), '')) LIKE '%pharmac%'
           OR lower(coalesce(CAST({cat} AS VARCHAR), '')) LIKE '%drug%'
           OR lower(coalesce(CAST({alt} AS VARCHAR), '')) LIKE '%pharmac%'
           OR lower(coalesce(CAST({tax} AS VARCHAR), '')) LIKE '%pharmac%'
           OR lower(coalesce(CAST({taxj} AS VARCHAR), '')) LIKE '%pharmac%'
           OR lower(coalesce(CAST({basic} AS VARCHAR), '')) LIKE '%pharmac%'
        """
    ).df()
    return frame


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def match_overture(nppes: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    if places.empty:
        nppes["overture_id"] = None
        nppes["overture_name"] = None
        nppes["overture_m"] = None
        return nppes
    matched = []
    for row in nppes.itertuples(index=False):
        if pd.isna(row.lat) or pd.isna(row.lon):
            matched.append((None, None, None))
            continue
        best = (None, None, 1e9)
        for place in places.itertuples(index=False):
            d = haversine_m(row.lat, row.lon, place.lat, place.lon)
            if d < best[2]:
                best = (place.id, place.name, d)
        if best[2] <= 120:
            matched.append(best)
        else:
            matched.append((None, None, best[2]))
    nppes = nppes.copy()
    nppes["overture_id"] = [m[0] for m in matched]
    nppes["overture_name"] = [m[1] for m in matched]
    nppes["overture_m"] = [m[2] if m[2] < 1e9 else None for m in matched]
    return nppes


def dedupe_storefronts(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["lat_r"] = df["lat"].round(4)
    df["lon_r"] = df["lon"].round(4)
    df["key"] = df["lat_r"].astype(str) + "|" + df["lon_r"].astype(str)
    keep = []
    for _, grp in df.groupby("key"):
        if len(grp) == 1:
            keep.append(grp.iloc[0])
            continue
        scored = grp.copy()
        scored["_score"] = scored["name"].fillna("").str.len()
        keep.append(scored.sort_values("_score", ascending=False).iloc[0])
    out = pd.DataFrame(keep).drop(columns=["lat_r", "lon_r", "key", "_score"], errors="ignore")
    return out.reset_index(drop=True)


def in_bbox(lat: float, lon: float) -> bool:
    return BBOX["ymin"] <= lat <= BBOX["ymax"] and BBOX["xmin"] <= lon <= BBOX["xmax"]


def run() -> pd.DataFrame:
    ensure_dirs()
    nppes_path = DATA_PROCESSED / "nppes_ma_retail.csv"
    if nppes_path.exists():
        nppes = pd.read_csv(nppes_path, dtype={"npi": str, "zip": str})
    else:
        nppes = fetch_nppes()
        nppes.to_csv(nppes_path, index=False)

    nppes = nppes[nppes["state"].fillna("").str.upper().eq("MA")].copy()
    nppes = nppes[~nppes["name"].fillna("").str.contains(MAIL_NAME)]

    if "lat" not in nppes.columns:
        nppes["lat"] = None
        nppes["lon"] = None
    missing = nppes["lat"].isna()
    if missing.any():
        print(f"Geocoding {int(missing.sum())} NPPES addresses...")
        coded = geocode_batch(nppes.loc[missing])
        nppes.loc[missing, "lat"] = coded["lat"]
        nppes.loc[missing, "lon"] = coded["lon"]
        still = nppes["lat"].isna()
        print(f"Census matched {int(missing.sum() - still.sum())}; {int(still.sum())} unmatched")
    nppes.to_csv(nppes_path, index=False)

    nppes = nppes[nppes["lat"].notna() & nppes["lon"].notna()].copy()
    nppes = nppes[nppes.apply(lambda r: in_bbox(float(r.lat), float(r.lon)), axis=1)]

    places = load_overture_pharmacies()
    nppes = match_overture(nppes, places)
    nppes["cms_retail"] = False
    cms_path = DATA_PROCESSED / "cms_ma_retail.csv"
    if cms_path.exists():
        cms = pd.read_csv(cms_path, dtype=str)
        cms_npis = set(cms["npi"].dropna().str.replace(r"\D", "", regex=True).str[-10:])
        nppes["cms_retail"] = nppes["npi"].astype(str).str[-10:].isin(cms_npis)

    nppes["confidence"] = nppes.apply(
        lambda r: "high" if r.cms_retail else ("medium" if pd.notna(r.overture_id) else "review"),
        axis=1,
    )
    nppes = nppes[~nppes["name"].fillna("").str.contains(MAIL_NAME)]
    nppes = dedupe_storefronts(nppes)

    out = DATA_PROCESSED / "pharmacies.csv"
    nppes.to_csv(out, index=False)

    summary = {
        "nppes_in_bbox": int(len(nppes)),
        "cms_overlap": int(nppes["cms_retail"].sum()) if "cms_retail" in nppes.columns else 0,
        "overture_matched": int(nppes["overture_id"].notna().sum()),
        "review_needed": int((nppes["confidence"] == "review").sum()),
        "study_cities": list(STUDY_CITIES),
        "pct_cms": round(100 * nppes["cms_retail"].mean(), 1) if len(nppes) else 0,
    }
    (DATA_REPORTS / "pharmacies.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return nppes


if __name__ == "__main__":
    run()
