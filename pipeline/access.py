"""Nearest and second-nearest walk distances from each H3 cell to pharmacies."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from pipeline.config import DATA_PROCESSED, DATA_REPORTS, ensure_dirs
from pipeline.graph import load_graph, nearest_node

SNAP_MAX_M = 250


def run() -> pd.DataFrame:
    ensure_dirs()
    graph, coords = load_graph()
    hexes = pd.read_csv(DATA_PROCESSED / "hexes.csv")
    pharmacies = pd.read_csv(DATA_PROCESSED / "pharmacies.csv", dtype={"npi": str})

    p_snap = [nearest_node(coords, float(r.lat), float(r.lon)) for r in pharmacies.itertuples(index=False)]
    pharmacies = pharmacies.copy()
    pharmacies["node"] = [n[0] for n in p_snap]
    pharmacies["snap_m"] = [n[1] for n in p_snap]
    pharmacies = pharmacies[pharmacies["snap_m"] <= SNAP_MAX_M].copy()

    h_snap = [nearest_node(coords, float(r.lat), float(r.lon)) for r in hexes.itertuples(index=False)]
    hexes = hexes.copy()
    hexes["node"] = [n[0] for n in h_snap]
    hexes["snap_m"] = [n[1] for n in h_snap]
    hexes = hexes[hexes["snap_m"] <= SNAP_MAX_M].copy()

    n_h, n_p = len(hexes), len(pharmacies)
    dist = np.full((n_h, n_p), np.inf)
    demand_idx = hexes["node"].to_numpy()
    pharm_nodes = pharmacies["node"].to_numpy()
    for j, src in enumerate(pharm_nodes):
        d = dijkstra(graph, directed=False, indices=int(src), unweighted=False)
        dist[:, j] = d[demand_idx]
        if j % 10 == 0:
            print(f"  pharmacy {j + 1}/{n_p}")

    nearest_j = np.argmin(dist, axis=1)
    nearest_m = dist[np.arange(n_h), nearest_j]
    dist2 = dist.copy()
    dist2[np.arange(n_h), nearest_j] = np.inf
    second_j = np.argmin(dist2, axis=1)
    second_m = dist2[np.arange(n_h), second_j]

    ids = pharmacies["npi"].astype(str).to_numpy()
    hexes["nearest_id"] = ids[nearest_j]
    hexes["nearest_m"] = nearest_m
    hexes["second_id"] = ids[second_j]
    hexes["second_m"] = second_m
    hexes.loc[~np.isfinite(hexes["nearest_m"]), ["nearest_id", "nearest_m", "second_id", "second_m"]] = [
        None,
        None,
        None,
        None,
    ]
    hexes.loc[~np.isfinite(hexes["second_m"]), ["second_id", "second_m"]] = [None, None]

    hexes.to_csv(DATA_PROCESSED / "access.csv", index=False)
    pharmacies.to_csv(DATA_PROCESSED / "pharmacies_snapped.csv", index=False)
    reachable = np.isfinite(nearest_m)
    summary = {
        "hexes": int(n_h),
        "pharmacies": int(n_p),
        "reachable_hex_share": round(float(reachable.mean()), 3),
        "median_nearest_m": round(float(np.nanmedian(nearest_m[reachable])), 1) if reachable.any() else None,
        "p90_nearest_m": round(float(np.nanpercentile(nearest_m[reachable], 90)), 1) if reachable.any() else None,
    }
    (DATA_REPORTS / "access.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return hexes


if __name__ == "__main__":
    run()
