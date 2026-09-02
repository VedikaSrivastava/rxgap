"""Write the static JSON the web app reads."""

from __future__ import annotations

import json
import shutil

import pandas as pd

from pipeline.config import (
    ACCESS_THRESHOLD_MINUTES,
    ACS_YEAR,
    BBOX,
    BUFFER_KM,
    DATA_PROCESSED,
    DATA_REPORTS,
    DEFAULT_PACE,
    H3_RESOLUTION,
    OVERTURE_RELEASE,
    PACES,
    STUDY_CITIES,
    WEB_DATA,
    ensure_dirs,
)


def run() -> None:
    ensure_dirs()
    hexes = pd.read_csv(DATA_PROCESSED / "access.csv", dtype={"nearest_id": str, "second_id": str})
    pharmacies = pd.read_csv(DATA_PROCESSED / "pharmacies_snapped.csv", dtype={"npi": str, "zip": str})
    used = {str(x) for x in hexes["nearest_id"].dropna()} | {str(x) for x in hexes["second_id"].dropna()}
    pharmacies = pharmacies[pharmacies["npi"].astype(str).isin(used)].copy()
    reports = {}
    for name in ("pharmacies", "graph", "buildings_demand", "access", "cms_check", "overture_extract"):
        path = DATA_REPORTS / f"{name}.json"
        if path.exists():
            reports[name] = json.loads(path.read_text(encoding="utf-8"))

    payload = {
        "meta": {
            "title": "RxGap",
            "subtitle": "Pharmacy closure impact explorer",
            "cities": list(STUDY_CITIES),
            "bufferKm": BUFFER_KM,
            "bbox": BBOX,
            "h3Resolution": H3_RESOLUTION,
            "thresholdMinutes": ACCESS_THRESHOLD_MINUTES,
            "defaultPace": DEFAULT_PACE,
            "paces": PACES,
            "overtureRelease": OVERTURE_RELEASE,
            "acsYear": ACS_YEAR,
            "demand": "ACS 5-year no-vehicle households (B25044), allocated onto Overture residential buildings, then aggregated to H3-9.",
            "network": "Overture transportation segments, pedestrian-accessible classes, 3 km buffer beyond city limits.",
            "pharmacies": "NPPES Community/Retail Pharmacy taxonomy 3336C0003X, Census-geocoded and matched to Overture places. CMS Q1 2026 Retail Pharmacy Access is plan-level adequacy, not a storefront directory, so it was not used as identity.",
            "reports": reports,
        },
        "pharmacies": [
            {
                "id": str(r.npi),
                "name": r.name,
                "address": f"{r.address}, {r.city} MA {str(r.zip).split('.')[0].zfill(5)}",
                "city": r.city,
                "lat": float(r.lat),
                "lon": float(r.lon),
                "confidence": getattr(r, "confidence", "medium"),
                "cmsRetail": bool(getattr(r, "cms_retail", False)),
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
    cities = DATA_PROCESSED / "cities.geojson"
    if cities.exists():
        shutil.copyfile(cities, WEB_DATA / "cities.geojson")
    print(f"Wrote {WEB_DATA / 'rxgap.json'} ({len(payload['hexes'])} hexes, {len(payload['pharmacies'])} pharmacies)")


if __name__ == "__main__":
    run()
