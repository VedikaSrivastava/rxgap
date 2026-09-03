"""Write the static JSON the web app reads."""

from __future__ import annotations

import json
import shutil

import pandas as pd
from shapely.geometry import Point

from pipeline.config import (
    ACCESS_THRESHOLD_MINUTES,
    ACS_YEAR,
    BUFFER_KM,
    CITIES_GEOJSON,
    DATA_PROCESSED,
    DATA_REPORTS,
    DEFAULT_PACE,
    H3_RESOLUTION,
    OVERTURE_RELEASE,
    PACES,
    STUDY_AREA_LABEL,
    STUDY_MUNICIPALITIES,
    WEB_DATA,
    ensure_dirs,
)
from pipeline.geography import analysis_bbox, study_union


def in_study_area(row, union) -> bool:
    """Polygon membership only — city-string aliases never grant study status."""
    if union is None:
        return False
    return bool(union.covers(Point(float(row.lon), float(row.lat))))


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def zip5(value) -> str:
    digits = "".join(c for c in str(value or "") if c.isdigit())[:5]
    return digits.zfill(5) if digits else "00000"


def exclude_reason(row) -> str | None:
    if as_bool(row.in_study_area) and as_bool(row.routable):
        return None
    if pd.notna(getattr(row, "exclude_reason", None)) and str(row.exclude_reason).lower() not in {
        "nan",
        "none",
        "",
    }:
        return str(row.exclude_reason)
    if not as_bool(row.in_study_area):
        return f"Outside {STUDY_AREA_LABEL} study area — shown for context"
    return "Not routable"


def run() -> None:
    ensure_dirs()
    hexes = pd.read_csv(DATA_PROCESSED / "access.csv", dtype={"nearest_id": str, "second_id": str})
    licensed = pd.read_csv(DATA_PROCESSED / "pharmacies.csv", dtype={"npi": str, "zip": str, "license": str})
    snapped = pd.read_csv(
        DATA_PROCESSED / "pharmacies_snapped.csv",
        dtype={"npi": str, "zip": str, "license": str},
    )
    snap_cols = snapped[["license", "snap_m", "routable", "exclude_reason"]].drop_duplicates("license")
    pharmacies = licensed.merge(snap_cols, on="license", how="left")
    pharmacies["id"] = pharmacies["license"].astype(str)
    pharmacies["routable"] = pharmacies["routable"].map(as_bool)
    union = study_union()
    pharmacies["in_study_area"] = pharmacies.apply(lambda r: in_study_area(r, union), axis=1)

    reports = {}
    for name in (
        "geography",
        "pharmacies",
        "graph",
        "buildings_demand",
        "access",
        "validation",
        "cms_check",
        "overture_extract",
    ):
        path = DATA_REPORTS / f"{name}.json"
        if path.exists():
            reports[name] = json.loads(path.read_text(encoding="utf-8"))
    demand = reports.get("buildings_demand") or {}
    bbox = analysis_bbox()

    payload = {
        "meta": {
            "title": "RxGap",
            "subtitle": "Pharmacy closure impact explorer",
            "areaLabel": demand.get("study_area_label") or STUDY_AREA_LABEL,
            "cities": list(STUDY_MUNICIPALITIES),
            "bufferKm": BUFFER_KM,
            "bbox": bbox,
            "h3Resolution": H3_RESOLUTION,
            "thresholdMinutes": ACCESS_THRESHOLD_MINUTES,
            "defaultPace": DEFAULT_PACE,
            "paces": PACES,
            "overtureRelease": OVERTURE_RELEASE,
            "acsYear": ACS_YEAR,
            "noVehicleHouseholds": demand.get("no_vehicle_households"),
            "noVehicleMoe": demand.get("no_vehicle_moe"),
            "demand": (
                "ACS 5-year no-vehicle households (B25044) with margins of error, allocated to "
                "residential-classified Overture buildings with block-group fallbacks, then aggregated "
                "to H3-9. Demand exists only inside the 22-municipality study union — never in the "
                "3 km routing buffer."
            ),
            "network": (
                "Overture transportation segments joined on connector_id, pedestrian-accessible "
                "classes, covering the analysis envelope (study union + 3 km in EPSG:26986). "
                "Distances include origin and destination snap legs."
            ),
            "pharmacies": (
                "Currently licensed MA Board Retail Pharmacies with geocodes inside the analysis "
                "envelope polygon. Closable (simulatable) storefronts must also lie in the study "
                "union; envelope-only pins are shown for routing context."
            ),
            "reports": reports,
        },
        "pharmacies": [
            {
                "id": str(r.id),
                "name": r.name,
                "address": f"{r.address}, {r.city} MA {zip5(r.zip)}",
                "city": r.city,
                "lat": float(r.lat),
                "lon": float(r.lon),
                "confidence": getattr(r, "confidence", "medium"),
                "inStudyArea": bool(r.in_study_area),
                "simulatable": bool(r.in_study_area and r.routable),
                "excludeReason": exclude_reason(r),
            }
            for r in pharmacies.itertuples(index=False)
        ],
        "hexes": [
            {
                "h3": r.h3,
                "city": r.city,
                "households": round(float(r.no_vehicle), 3),
                "lat": float(r.lat),
                "lon": float(r.lon),
                "nearestId": None if pd.isna(r.nearest_id) else str(r.nearest_id),
                "nearestM": None if pd.isna(r.nearest_m) else round(float(r.nearest_m), 1),
                "secondId": None if pd.isna(r.second_id) else str(r.second_id),
                "secondM": None if pd.isna(r.second_m) else round(float(r.second_m), 1),
            }
            for r in hexes.itertuples(index=False)
        ],
    }
    (WEB_DATA / "rxgap.json").write_text(json.dumps(payload), encoding="utf-8")
    if CITIES_GEOJSON.exists():
        shutil.copyfile(CITIES_GEOJSON, WEB_DATA / "cities.geojson")
    study_n = sum(1 for p in payload["pharmacies"] if p["inStudyArea"])
    sim_n = sum(1 for p in payload["pharmacies"] if p["simulatable"])
    print(
        f"Wrote {WEB_DATA / 'rxgap.json'} "
        f"({len(payload['hexes'])} hexes, {len(payload['pharmacies'])} pharmacies, "
        f"{study_n} in study area, {sim_n} simulatable)"
    )


if __name__ == "__main__":
    run()
