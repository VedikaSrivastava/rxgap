"""Compare modeled walking distances to a public walking router."""

from __future__ import annotations

import json
import time

import pandas as pd
import requests

from pipeline.config import (
    DATA_PROCESSED,
    DATA_REPORTS,
    GRAPH_ROUTES,
    GRAPH_SEEDS,
    WALK_CHECKS,
    ensure_dirs,
)
from pipeline.graph import _haversine_m, load_graph, route_between

OSRM_FOOT = "https://router.project-osrm.org/route/v1/foot/{lon1},{lat1};{lon2},{lat2}"
MAX_RATIO = 1.5
BRIDGE_GEODESIC_MAX = 1.75
UA = {"User-Agent": "RxGap/1.0 (routing validation)"}


def round_m(value) -> float | None:
    return None if value is None else round(float(value), 1)


def ratio(modeled, reference) -> float | None:
    if modeled is None or reference is None:
        return None
    if reference <= 0:
        return 1.0 if modeled == 0 else None
    return modeled / reference


def within_ratio(modeled, reference, limit: float = MAX_RATIO) -> bool:
    r = ratio(modeled, reference)
    return r is not None and (1 / limit) <= r <= limit


def osrm_plausible(osrm, geodesic, limit: float = 2.0) -> bool:
    """Public OSRM foot sometimes refuses a Charles crossing and detours for kilometres."""
    return osrm is not None and geodesic > 0 and osrm / geodesic <= limit


def pair_ok(modeled, geodesic, osrm, kind: str) -> bool:
    if modeled is None:
        return False
    if geodesic < 200:
        return modeled <= 500
    if kind == "bridge" and not within_ratio(modeled, geodesic, BRIDGE_GEODESIC_MAX):
        return False
    if osrm_plausible(osrm, geodesic):
        return modeled <= osrm * MAX_RATIO
    return geodesic <= 0 or modeled <= geodesic * BRIDGE_GEODESIC_MAX


def osrm_foot_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float | None:
    url = OSRM_FOOT.format(lon1=lon1, lat1=lat1, lon2=lon2, lat2=lat2)
    resp = requests.get(url, params={"overview": "false"}, headers=UA, timeout=30)
    resp.raise_for_status()
    routes = resp.json().get("routes") or []
    if not routes:
        return None
    return float(routes[0]["distance"])


def nearest_named_pharmacy(lat: float, lon: float, pharmacies: pd.DataFrame, hint: str, min_m: float = 200):
    rows = pharmacies
    if hint.lower() != "pharmacy":
        rows = pharmacies[pharmacies["name"].str.contains(hint, case=False, regex=False)]
    if rows.empty:
        return None
    ranked = sorted(
        (
            (_haversine_m(lat, lon, float(r.lat), float(r.lon)), r)
            for r in rows.itertuples(index=False)
        ),
        key=lambda item: item[0],
    )
    for dist, row in ranked:
        if dist >= min_m:
            return row
    return ranked[0][1]


def _pair_row(name: str, origin: str, dest: str, modeled: dict, osrm: float | None, kind: str) -> dict:
    modeled_m = modeled["modeled_m"]
    geodesic = modeled["geodesic_m"]
    osrm_ratio = ratio(modeled_m, osrm)
    geo_ratio = ratio(modeled_m, geodesic)
    return {
        "name": name,
        "kind": kind,
        "origin": origin,
        "dest": dest,
        "geodesic_m": round_m(geodesic),
        "modeled_m": round_m(modeled_m),
        "osrm_m": round_m(osrm),
        "modeled_over_osrm": None if osrm_ratio is None else round(osrm_ratio, 3),
        "modeled_over_geodesic": None if geo_ratio is None else round(geo_ratio, 3),
        "snap_origin_m": round_m(modeled["snap_origin_m"]),
        "snap_dest_m": round_m(modeled["snap_dest_m"]),
        "osrm_plausible": osrm_plausible(osrm, geodesic),
        "ok": pair_ok(modeled_m, geodesic, osrm, kind),
    }


def run() -> dict:
    ensure_dirs()
    graph, coords = load_graph()
    pharmacies = pd.read_csv(DATA_PROCESSED / "pharmacies.csv", dtype={"npi": str, "license": str})
    walk_in = pharmacies
    if "walk_in" in pharmacies.columns:
        walk_in = pharmacies[pharmacies["walk_in"].astype(str).str.lower().isin(["true", "1", "yes"])].copy()

    pairs = []
    osrm_ok = True
    for key, origin, dest in GRAPH_ROUTES:
        o_latlon, d_latlon = GRAPH_SEEDS[origin], GRAPH_SEEDS[dest]
        modeled = route_between(graph, coords, o_latlon, d_latlon)
        osrm = None
        try:
            osrm = osrm_foot_m(o_latlon[0], o_latlon[1], d_latlon[0], d_latlon[1])
            time.sleep(0.4)
        except requests.RequestException:
            osrm_ok = False
        kind = "bridge" if origin.endswith("_boston") and dest.endswith("_cambridge") else "network"
        pairs.append(_pair_row(key, origin, dest, modeled, osrm, kind))

    landmarks = []
    for origin, hint in WALK_CHECKS:
        lat, lon = GRAPH_SEEDS[origin]
        pharmacy = nearest_named_pharmacy(lat, lon, walk_in, hint)
        if pharmacy is None:
            landmarks.append({"origin": origin, "hint": hint, "ok": False, "error": "no matching pharmacy"})
            continue
        dest = (float(pharmacy.lat), float(pharmacy.lon))
        modeled = route_between(graph, coords, (lat, lon), dest)
        osrm = None
        try:
            osrm = osrm_foot_m(lat, lon, dest[0], dest[1])
            time.sleep(0.4)
        except requests.RequestException:
            osrm_ok = False
        row = _pair_row(
            f"{origin} → {pharmacy.name}",
            origin,
            str(pharmacy.license),
            modeled,
            osrm,
            "landmark",
        )
        row["pharmacy"] = pharmacy.name
        row["hint"] = hint
        landmarks.append(row)

    flagged = [row["name"] for row in pairs + landmarks if not row.get("ok")]
    bridge_bad = [
        row["name"]
        for row in pairs
        if row["kind"] == "bridge" and row["modeled_m"] is not None
        and not within_ratio(row["modeled_m"], row["geodesic_m"], BRIDGE_GEODESIC_MAX)
    ]
    summary = {
        "router": "OSRM public foot profile",
        "router_url": "https://router.project-osrm.org",
        "osrm_reachable": osrm_ok,
        "max_ratio": MAX_RATIO,
        "note": (
            "OSRM foot is the comparison router. When it detours more than 2× "
            "straight-line (it often refuses a Charles crossing), geodesic is the gate."
        ),
        "pairs": pairs,
        "landmark_pharmacies": landmarks,
        "flagged": flagged,
        "all_pass": not flagged,
    }
    (DATA_REPORTS / "validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if bridge_bad:
        raise RuntimeError(f"Bridge walks are far from geodesic: {bridge_bad}")
    if flagged:
        print("VALIDATION: one or more walking distances disagree with OSRM/geodesic.")
    return summary


if __name__ == "__main__":
    run()
