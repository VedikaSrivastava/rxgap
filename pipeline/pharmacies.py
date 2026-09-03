"""Walk-in pharmacies: MA Board license status, then NPPES type, then Overture."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import time
import zipfile
from typing import Any

import pandas as pd
import requests

from pipeline.config import (
    DATA_PROCESSED,
    DATA_RAW,
    DATA_REPORTS,
    EXCLUDE_TAXONOMIES,
    KNOWN_CLOSED_STOREFRONTS,
    LICENSE_CITY_ALIASES,
    MA_ACTIVE_LICENSE_STATUSES,
    MA_LICENSE_API,
    MA_PHARMACY_BOARD,
    MA_RETAIL_EXPORT_PREFIX,
    RETAIL_TAXONOMY,
    STUDY_AREA_LABEL,
    ensure_dirs,
)
from pipeline.db import connect
from pipeline.geography import analysis_envelope, point_in_envelope

NPPES = "https://npiregistry.cms.hhs.gov/api/"
UA = {"User-Agent": "rxgap/0.1 (pharmacy access research)"}
GEOCODE_CACHE = DATA_PROCESSED / "geocode_cache.json"
MAIL_NAME = re.compile(
    r"\b(?:mail[\s-]?order|long[\s-]?term care|\bltc\b|institutional|nuclear|specialty mail)\b",
    re.I,
)
SPECIALTY_NAME = re.compile(
    r"\b(?:genoa healthcare|omnicare|accredo|home infusion|behavioral care)\b",
    re.I,
)
CHAIN_STOREFRONT = re.compile(
    r"\b(?:cvs|walgreens|walgreen|rite aid|star market|walmart|stop and shop)\b",
    re.I,
)
BACK_OFFICE_ADDR = re.compile(r"\b(?:room|suite|ste|unit|floor|fl)\b", re.I)
COUNTY_SUFFIX = re.compile(
    r",\s*(?:Suffolk|Middlesex|Essex|Norfolk|Worcester|Berkshire|Hampden|Hampshire|Franklin|Bristol|Dukes|Nantucket)\s*$",
    re.I,
)
STREET_RE = re.compile(
    r"(\d+[\w\s\-\.#]*(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Way|Drive|Dr|Place|Pl|Court|Ct|Lane|Ln|Parkway|Pkwy|Square|Sq|Highway|Hwy)(?:\s*(?:Ste|Suite|Unit|Rm|Room|#)\s*[\w\d\-]+)?)",
    re.I,
)
CITIES = tuple(name.upper() for name in LICENSE_CITY_ALIASES)


def taxonomy_codes(value) -> set[str]:
    if value is None:
        return set()
    try:
        if pd.isna(value):
            return set()
    except (TypeError, ValueError):
        pass
    return {
        c.strip()
        for c in str(value).split(",")
        if c.strip() and c.strip().lower() != "nan"
    }


def _row_value(row, key: str, default=None):
    try:
        val = row[key]
    except (KeyError, TypeError):
        val = getattr(row, key, default)
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    return val


def is_walk_in_storefront(row) -> bool:
    """Drop licensed sites that are not public walk-in retail storefronts."""
    if _row_value(row, "duplicate_of", None):
        return False
    name = str(_row_value(row, "name", "") or "")
    address = str(_row_value(row, "address", "") or "")
    if SPECIALTY_NAME.search(name):
        return False
    codes = taxonomy_codes(_row_value(row, "taxonomy_codes", None))
    if codes and RETAIL_TAXONOMY not in codes:
        return False
    if codes & EXCLUDE_TAXONOMIES and RETAIL_TAXONOMY not in codes:
        return False
    non_retail = {"3336L0003X", "3336M0002X", "3336I0012X", "3336N0007X"}
    if codes & non_retail and not CHAIN_STOREFRONT.search(name) and BACK_OFFICE_ADDR.search(address):
        return False
    return True


def storefront_reason(row) -> str | None:
    if is_walk_in_storefront(row):
        return None
    duplicate_of = _row_value(row, "duplicate_of", None)
    if duplicate_of:
        return f"Duplicate license for the same storefront; modeled as {duplicate_of}"
    name = str(_row_value(row, "name", "") or "")
    if SPECIALTY_NAME.search(name):
        return "Non-storefront pharmacy service"
    return "Not a public walk-in storefront"


def clean_address(address: str, address2: str = "") -> str:
    """Strip manager names and county junk from Board license addresses."""
    text = " ".join(x for x in [str(address or ""), str(address2 or "")] if x and str(x).lower() != "nan")
    text = COUNTY_SUFFIX.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)
    m = STREET_RE.search(text)
    if m:
        return m.group(1).strip(" ,")
    # Drop a leading person-name prefix before the street number.
    m = re.match(r"^[A-Za-z][A-Za-z'\-\.]+(?:\s+[A-Za-z][A-Za-z'\-\.]+){1,4}\s+(.+)$", text)
    if m:
        return m.group(1).strip(" ,")
    return text.strip(" ,")


def storefront_name_match(board_name: str, overture_name: str | None) -> bool:
    if not overture_name:
        return False
    a = board_name.lower()
    b = overture_name.lower()
    chains = ("cvs", "walgreen", "star market", "rite aid", "stop and shop", "shaw")
    a_chains = {c for c in chains if c in a}
    b_chains = {c for c in chains if c in b}
    if a_chains or b_chains:
        return bool(a_chains & b_chains)

    stop = {"and", "care", "center", "health", "inc", "llc", "medical", "pharmacy", "the"}
    tokens = lambda value: {
        token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) >= 4 and token not in stop
    }
    return bool(tokens(board_name) & tokens(overture_name))


def refine_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer Overture storefront coordinates when the census geocode is weak."""
    out = df.copy()
    lats, lons, sources = [], [], []
    for row in out.itertuples(index=False):
        lat, lon, source = float(row.lat), float(row.lon), "census"
        ov_lat = getattr(row, "overture_lat", None)
        ov_lon = getattr(row, "overture_lon", None)
        ov_m = getattr(row, "overture_m", None)
        ov_name = getattr(row, "overture_name", None)
        if (
            pd.notna(ov_lat)
            and pd.notna(ov_lon)
            and pd.notna(ov_m)
            and float(ov_m) <= 150
            and storefront_name_match(str(row.name), ov_name)
        ):
            lat, lon, source = float(ov_lat), float(ov_lon), "overture"
        lats.append(lat)
        lons.append(lon)
        sources.append(source)
    out["lat"] = lats
    out["lon"] = lons
    out["loc_source"] = sources
    return out


def load_geocode_cache() -> dict[str, list[float] | None]:
    if GEOCODE_CACHE.exists():
        return json.loads(GEOCODE_CACHE.read_text(encoding="utf-8"))
    return {}


def save_geocode_cache(cache: dict[str, list[float] | None]) -> None:
    GEOCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE.write_text(json.dumps(cache), encoding="utf-8")


def cached_nominatim(row, cache: dict[str, list[float] | None]):
    key = f"{row.address}|{row.city}|{row.zip}"
    if key in cache:
        return cache[key], False
    try:
        hit = nominatim_lookup(str(row.address), str(row.city), str(row.zip))
        cache[key] = [hit[0], hit[1]] if hit else None
    except requests.RequestException:
        cache[key] = None
    time.sleep(1.05)
    return cache[key], True


def nominatim_lookup(address: str, city: str, zip_code: str) -> tuple[float, float] | None:
    query = f"{address}, {city}, MA {str(zip_code or '')[:5]}"
    resp = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
        headers=UA,
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    return float(rows[0]["lat"]), float(rows[0]["lon"])


def nominatim_refine(df: pd.DataFrame, cache: dict[str, list[float] | None] | None = None) -> pd.DataFrame:
    """Prefer OSM storefront pins when Census/Overture landed on the wrong part of the block."""
    out = df.copy()
    cache = load_geocode_cache() if cache is None else cache
    changed = False
    lats, lons, sources = [], [], []
    for row in out.itertuples(index=False):
        lat, lon, source = float(row.lat), float(row.lon), getattr(row, "loc_source", "census")
        coords, added = cached_nominatim(row, cache)
        changed |= added
        if coords:
            candidate = (float(coords[0]), float(coords[1]))
            if in_analysis_envelope(*candidate):
                dist = haversine_m(lat, lon, *candidate)
                ov_m = getattr(row, "overture_m", None)
                weak_overture = pd.notna(ov_m) and float(ov_m) > 45
                if (source != "overture" and dist <= 2000) or dist <= 150 or (weak_overture and dist <= 2000):
                    lat, lon, source = candidate[0], candidate[1], "nominatim"
        lats.append(lat)
        lons.append(lon)
        sources.append(source)
    if changed:
        save_geocode_cache(cache)
    out["lat"] = lats
    out["lon"] = lons
    out["loc_source"] = sources
    return out


def nominatim_backfill(df: pd.DataFrame) -> pd.DataFrame:
    """Geocode local addresses that the Census batch geocoder could not parse."""
    out = df.copy()
    cache = load_geocode_cache()
    changed = False
    for row in out.itertuples():
        coords, added = cached_nominatim(row, cache)
        changed |= added
        if coords and in_analysis_envelope(float(coords[0]), float(coords[1])):
            out.at[row.Index, "lat"] = float(coords[0])
            out.at[row.Index, "lon"] = float(coords[1])
    if changed:
        save_geocode_cache(cache)
    return out


def norm_license(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _loc_addr(result: dict[str, Any]) -> dict[str, str]:
    for addr in result.get("addresses") or []:
        if addr.get("address_purpose") == "LOCATION":
            return addr
    return (result.get("addresses") or [{}])[0]


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
    resp = requests.get(NPPES, params=params, timeout=45, headers=UA)
    resp.raise_for_status()
    return resp.json().get("results") or []


def _row_from_nppes(item: dict[str, Any]) -> dict[str, Any] | None:
    basic = item.get("basic") or {}
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


def fetch_ma_retail_licenses() -> pd.DataFrame:
    """Currently licensed retail locations from the Board public bulk export."""
    dest = DATA_RAW / "ma_retail_pharmacy_licenses.zip"
    files = requests.get(f"{MA_LICENSE_API}/export/all", timeout=60, headers=UA)
    files.raise_for_status()
    meta = next(
        (
            row
            for row in files.json()
            if str(row.get("name") or "").startswith(MA_RETAIL_EXPORT_PREFIX)
            and row.get("boardName") == MA_PHARMACY_BOARD
        ),
        None,
    )
    if not meta or not meta.get("licenseMetaId"):
        raise RuntimeError("MA Board retail pharmacy bulk export was not listed.")
    resp = requests.get(
        f"{MA_LICENSE_API}/export/data/license/{meta['licenseMetaId']}",
        timeout=120,
        headers=UA,
    )
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"Downloaded MA retail licenses ({dest.stat().st_size / 1e3:.0f} KB)", flush=True)
    with zipfile.ZipFile(dest) as zf:
        name = next(n for n in zf.namelist() if "Data" in n and n.endswith(".csv"))
        df = pd.read_csv(zf.open(name), dtype=str)
    required = {
        "License Number",
        "License Status",
        "Organization Name",
        "Address 1",
        "City",
        "State",
        "Zip Code",
    }
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"MA Board export is missing columns: {sorted(missing)}")
    df = df.rename(
        columns={
            "License Number": "license",
            "License Type": "license_type",
            "License Status": "license_status",
            "Organization Name": "name",
            "Address 1": "address",
            "Address 2": "address2",
            "City": "city",
            "State": "state",
            "Zip Code": "zip",
            "Closure Date": "closure_date",
        }
    )
    df["address"] = df["address"].fillna("").str.strip()
    df["city"] = df["city"].fillna("").str.title()
    df["zip"] = df["zip"].fillna("").str.replace(r"\D", "", regex=True).str[:5]
    df["state"] = df["state"].fillna("MA").str.upper()
    return df


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
    return con.execute(
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


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def match_overture(rows: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    if places.empty:
        rows = rows.copy()
        for col in ("overture_id", "overture_name", "overture_m", "overture_lat", "overture_lon"):
            rows[col] = None
        return rows
    matched = []
    for row in rows.itertuples(index=False):
        if pd.isna(row.lat) or pd.isna(row.lon):
            matched.append((None, None, None, None, None))
            continue
        best = (None, None, 1e9, None, None)
        for place in places.itertuples(index=False):
            if not storefront_name_match(str(row.name), getattr(place, "name", None)):
                continue
            d = haversine_m(row.lat, row.lon, place.lat, place.lon)
            if d < best[2]:
                best = (place.id, place.name, d, place.lat, place.lon)
        if best[2] <= 150:
            matched.append(best)
        else:
            matched.append((None, None, None, None, None))
    out = rows.copy()
    out["overture_id"] = [m[0] for m in matched]
    out["overture_name"] = [m[1] for m in matched]
    out["overture_m"] = [m[2] for m in matched]
    out["overture_lat"] = [m[3] for m in matched]
    out["overture_lon"] = [m[4] for m in matched]
    return out


def overture_address_backfill(df: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    """Geocode by compatible name plus exact street number and ZIP."""
    out = df.copy()
    if places.empty:
        return out
    for row in out.itertuples():
        number = re.match(r"\s*(\d+)", str(row.address))
        zip_code = re.sub(r"\D", "", str(row.zip))[:5]
        if not number or not zip_code:
            continue
        candidates = []
        for place in places.itertuples(index=False):
            address = str(getattr(place, "addresses_json", "") or "").lower()
            if (
                storefront_name_match(str(row.name), getattr(place, "name", None))
                and re.search(rf"\b{re.escape(number.group(1))}\b", address)
                and zip_code in address
            ):
                pharmacy = str(getattr(place, "category_primary", "")).lower() == "pharmacy"
                raw_confidence = getattr(place, "confidence", 0)
                confidence = 0.0 if pd.isna(raw_confidence) else float(raw_confidence)
                candidates.append(((pharmacy, confidence), place))
        if candidates:
            place = max(candidates, key=lambda item: item[0])[1]
            out.at[row.Index, "lat"] = float(place.lat)
            out.at[row.Index, "lon"] = float(place.lon)
    return out


def license_keys(value) -> set[str]:
    key = norm_license(value)
    if not key:
        return set()
    digits = re.sub(r"^[A-Z]+", "", key)
    keys = {key}
    if digits:
        keys.add(digits)
        keys.add("DS" + digits)
    return keys


def match_nppes(board: pd.DataFrame, nppes: pd.DataFrame) -> pd.DataFrame:
    board = board.copy()
    if nppes.empty:
        board["npi"] = None
        board["taxonomy_codes"] = None
        board["nppes_lat"] = None
        board["nppes_lon"] = None
        return board
    nppes = nppes.copy()
    nppes["npi"] = nppes["npi"].astype(str)
    rows = []
    for rec in nppes.itertuples(index=False):
        for key in license_keys(getattr(rec, "license", None)):
            rows.append(
                (
                    key,
                    rec.npi,
                    rec.name,
                    getattr(rec, "taxonomy_codes", None),
                    getattr(rec, "lat", None),
                    getattr(rec, "lon", None),
                )
            )
    lookup = pd.DataFrame(
        rows,
        columns=["lic_key", "npi", "nppes_name", "taxonomy_codes", "nppes_lat", "nppes_lon"],
    ).drop_duplicates("lic_key")
    exploded = board.assign(lic_key=board["license"].map(lambda v: list(license_keys(v)))).explode("lic_key")
    out = exploded.merge(lookup, on="lic_key", how="left")
    out = out.sort_values("npi", na_position="last").drop_duplicates("license")
    better = out["nppes_name"].fillna("").str.len() > out["name"].fillna("").str.len()
    out.loc[better, "name"] = out.loc[better, "nppes_name"]
    return out.drop(columns=["lic_key", "nppes_name"], errors="ignore")


def match_nppes_near(board: pd.DataFrame, nppes: pd.DataFrame, max_m: float = 60) -> pd.DataFrame:
    if nppes.empty or "lat" not in nppes.columns:
        return board
    pts = nppes[nppes["lat"].notna() & nppes["lon"].notna()].copy()
    if pts.empty:
        return board
    out = board.copy()
    missing = out["npi"].isna() if "npi" in out.columns else pd.Series(True, index=out.index)
    for idx in out.index[missing]:
        row = out.loc[idx]
        if pd.isna(row.lat) or pd.isna(row.lon):
            continue
        best = (None, None, None, 1e9)
        for rec in pts.itertuples(index=False):
            d = haversine_m(float(row.lat), float(row.lon), float(rec.lat), float(rec.lon))
            if d < best[3]:
                best = (rec.npi, rec.name, getattr(rec, "taxonomy_codes", None), d)
        if best[3] <= max_m:
            out.at[idx, "npi"] = best[0]
            out.at[idx, "taxonomy_codes"] = best[2]
            if best[1] and len(str(best[1])) > len(str(row["name"] or "")):
                out.at[idx, "name"] = best[1]
    return out


def storefront_identity(row) -> str | None:
    npi = re.sub(r"\D", "", str(_row_value(row, "npi", "") or ""))
    if len(npi) != 10:
        return None
    name = " ".join(re.findall(r"[a-z0-9]+", str(_row_value(row, "name", "")).lower()))
    return f"{npi}|{name}" if name else None


def mark_duplicate_licenses(df: pd.DataFrame) -> pd.DataFrame:
    """Keep every license visible, but route through one row per physical storefront."""
    out = df.copy()
    out["duplicate_of"] = None
    identities = out.apply(storefront_identity, axis=1)
    for identity in identities.dropna().unique():
        indices = identities[identities == identity].index
        if len(indices) < 2:
            continue
        issue_dates = pd.to_datetime(out.loc[indices, "Issue Date"], errors="coerce")
        primary = issue_dates.fillna(pd.Timestamp.min).idxmax()
        out.loc[indices.difference([primary]), "duplicate_of"] = str(out.at[primary, "license"])
    return out


def in_analysis_envelope(lat: float, lon: float, envelope=None) -> bool:
    """Retain pharmacy iff the geocoded point lies in the true buffered envelope."""
    return point_in_envelope(lon, lat, envelope)


def storefront_blob(df: pd.DataFrame) -> pd.Series:
    return (df["address"].fillna("") + " " + df["city"].fillna("")).str.lower()


def known_closed_hits(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    blob = storefront_blob(df)
    parts = []
    for row in KNOWN_CLOSED_STOREFRONTS:
        hit = blob.str.contains(row["street"], regex=False)
        if row["city"]:
            hit &= df["city"].fillna("").str.lower().str.contains(row["city"])
        parts.append(hit)
    mask = parts[0]
    for extra in parts[1:]:
        mask = mask | extra
    return df.loc[mask]


def assert_known_closures_absent(df: pd.DataFrame) -> None:
    hits = known_closed_hits(df)
    if len(hits):
        sample = hits[["name", "address", "city"]].astype(str).to_dict("records")
        raise RuntimeError(f"Known-closed storefronts are marked active: {sample}")


def run() -> pd.DataFrame:
    ensure_dirs()
    board = fetch_ma_retail_licenses()
    board = board[board["license_status"].isin(MA_ACTIVE_LICENSE_STATUSES)].copy()
    board = board[board["state"].eq("MA")]
    board = board[~board["name"].fillna("").str.contains(MAIL_NAME)]
    board_active = len(board)
    print(f"MA Board currently licensed retail: {len(board)}", flush=True)

    nppes_path = DATA_PROCESSED / "nppes_ma_retail.csv"
    if nppes_path.exists():
        nppes = pd.read_csv(nppes_path, dtype={"npi": str, "zip": str, "license": str})
    else:
        nppes = fetch_nppes()
        nppes.to_csv(nppes_path, index=False)
    board = match_nppes(board, nppes)
    board["address"] = board.apply(
        lambda r: clean_address(r["address"], r.get("address2", "")),
        axis=1,
    )

    places = load_overture_pharmacies()
    print(f"Geocoding {len(board)} licensed addresses...")
    coded = geocode_batch(board)
    board["lat"] = coded["lat"]
    board["lon"] = coded["lon"]
    still = board["lat"].isna()
    print(f"Census matched {len(board) - int(still.sum())}; {int(still.sum())} unmatched")

    nppes_coords = board["nppes_lat"].notna() & board["nppes_lon"].notna()
    nppes_backfilled = still & nppes_coords
    board.loc[nppes_backfilled, ["lat", "lon"]] = board.loc[
        nppes_backfilled, ["nppes_lat", "nppes_lon"]
    ].to_numpy()

    local_city = board["city"].str.upper().isin(CITIES)
    local_missing = board["lat"].isna() & local_city
    overture_backfilled = 0
    if local_missing.any():
        fallback = overture_address_backfill(board.loc[local_missing], places)
        board.loc[local_missing, ["lat", "lon"]] = fallback[["lat", "lon"]]
        overture_backfilled = int(board.loc[local_missing, "lat"].notna().sum())

    local_missing = board["lat"].isna() & local_city
    backfilled = 0
    if local_missing.any():
        fallback = nominatim_backfill(board.loc[local_missing])
        board.loc[local_missing, ["lat", "lon"]] = fallback[["lat", "lon"]]
        backfilled = int(board.loc[local_missing, "lat"].notna().sum())
        print(f"Nominatim backfilled {backfilled}/{int(local_missing.sum())} local addresses")
    unresolved_local = board[local_missing & board["lat"].isna()]

    board = board[board["lat"].notna() & board["lon"].notna()].copy()
    envelope = analysis_envelope()
    board = board[
        board.apply(lambda r: in_analysis_envelope(float(r.lat), float(r.lon), envelope), axis=1)
    ]
    board = match_nppes_near(board, nppes)
    board = board[~board["name"].fillna("").str.contains(MAIL_NAME)]

    board = match_overture(board, places)
    board = refine_coordinates(board)
    board = nominatim_refine(board)
    board["has_retail_taxonomy"] = board["taxonomy_codes"].fillna("").str.contains(RETAIL_TAXONOMY)
    board["confidence"] = board.apply(
        lambda r: "high" if r.has_retail_taxonomy else ("medium" if pd.notna(r.overture_id) else "board"),
        axis=1,
    )
    board = mark_duplicate_licenses(board)
    board["walk_in"] = board.apply(is_walk_in_storefront, axis=1)
    board["storefront_reason"] = board.apply(storefront_reason, axis=1)
    assert_known_closures_absent(board)

    out = DATA_PROCESSED / "pharmacies.csv"
    board.to_csv(out, index=False)
    summary = {
        "source": "MA Board of Registration in Pharmacy, currently licensed Retail Pharmacy",
        "board_active_ma": int(board_active),
        "census_unmatched": int(still.sum()),
        "nppes_geocode_backfilled": int(nppes_backfilled.sum()),
        "overture_address_backfilled": overture_backfilled,
        "local_nominatim_backfilled": backfilled,
        "local_geocode_unresolved": unresolved_local[
            ["license", "name", "address", "city"]
        ].to_dict("records"),
        "licensed_geocoded_in_envelope": int(len(board)),
        "walk_in_storefronts": int(board["walk_in"].sum()),
        "display_only": int((~board["walk_in"]).sum()),
        "nppes_taxonomy_matched": int(board["has_retail_taxonomy"].sum()),
        "overture_matched": int(board["overture_id"].notna().sum()),
        "nominatim_refined": int((board.get("loc_source") == "nominatim").sum()),
        "known_closed_active": 0,
        "study_area_label": STUDY_AREA_LABEL,
    }
    (DATA_REPORTS / "pharmacies.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return board


if __name__ == "__main__":
    run()
