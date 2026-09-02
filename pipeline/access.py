"""Nearest and second-nearest walk distances from each H3 cell to pharmacies."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

from pipeline.config import DATA_PROCESSED, DATA_REPORTS, ensure_dirs
from pipeline.graph import load_graph, nearest_reachable_node

SNAP_MAX_M = 250


def _exclude_reason(row, snap_ok: bool) -> str | None:
    if not bool(getattr(row, "walk_in", True)):
        reason = getattr(row, "storefront_reason", None)
        if reason is not None and str(reason).lower() not in {"nan", "none", ""}:
            return str(reason)
        return "Not a public walk-in storefront"
    if snap_ok:
        return None
    snap_m = float(row.snap_m)
    if snap_m <= SNAP_MAX_M * 4:
        return f"More than {SNAP_MAX_M} m from connected walk network ({int(round(snap_m))} m snap)"
    return f"More than {SNAP_MAX_M} m from walkable street network ({int(round(snap_m))} m snap)"


def with_snaps(graph_m, hex_snap, pharm_snap):
    """Demand → graph + graph path + graph → pharmacy."""
    return np.where(np.isfinite(graph_m), graph_m + hex_snap + pharm_snap, np.inf)


def run() -> pd.DataFrame:
    ensure_dirs()
    graph, coords = load_graph()
    hexes = pd.read_csv(DATA_PROCESSED / "hexes.csv")
    pharmacies = pd.read_csv(DATA_PROCESSED / "pharmacies.csv", dtype={"npi": str, "license": str})

    p_snap = [
        nearest_reachable_node(graph, coords, float(r.lat), float(r.lon), SNAP_MAX_M)
        for r in pharmacies.itertuples(index=False)
    ]
    pharmacies = pharmacies.copy()
    if "walk_in" in pharmacies.columns:
        pharmacies["walk_in"] = pharmacies["walk_in"].astype(str).str.lower().isin(["true", "1", "yes"])
    else:
        pharmacies["walk_in"] = True
    pharmacies["node"] = [n[0] for n in p_snap]
    pharmacies["snap_m"] = [n[1] for n in p_snap]
    snap_ok = pharmacies["snap_m"] <= SNAP_MAX_M
    pharmacies["routable"] = pharmacies["walk_in"] & snap_ok
    pharmacies["exclude_reason"] = [
        _exclude_reason(row, snap_ok=ok)
        for row, ok in zip(pharmacies.itertuples(index=False), snap_ok)
    ]
    routable = pharmacies[pharmacies["routable"]].copy()

    h_snap = [
        nearest_reachable_node(graph, coords, float(r.lat), float(r.lon), SNAP_MAX_M)
        for r in hexes.itertuples(index=False)
    ]
    hexes = hexes.copy()
    hexes["node"] = [n[0] for n in h_snap]
    hexes["snap_m"] = [n[1] for n in h_snap]
    hexes["routable"] = hexes["snap_m"] <= SNAP_MAX_M

    n_h, n_p = len(hexes), len(routable)
    if n_p < 2:
        raise RuntimeError("At least two routable pharmacies are required for closure analysis.")
    dist = np.full((n_h, n_p), np.inf)
    demand_idx = hexes["node"].to_numpy()
    pharm_nodes = routable["node"].to_numpy()
    hex_snap = hexes["snap_m"].to_numpy()[:, None]
    pharm_snap = routable["snap_m"].to_numpy()[None, :]
    for j, src in enumerate(pharm_nodes):
        d = dijkstra(graph, directed=False, indices=int(src), unweighted=False)
        graph_m = d[demand_idx]
        dist[:, j] = with_snaps(graph_m, hex_snap[:, 0], pharm_snap[0, j])
        if j % 10 == 0:
            print(f"  pharmacy {j + 1}/{n_p}")
    dist[~hexes["routable"].to_numpy(), :] = np.inf

    nearest_j = np.argmin(dist, axis=1)
    nearest_m = dist[np.arange(n_h), nearest_j]
    dist2 = dist.copy()
    dist2[np.arange(n_h), nearest_j] = np.inf
    second_j = np.argmin(dist2, axis=1)
    second_m = dist2[np.arange(n_h), second_j]

    ids = routable["license"].astype(str).to_numpy()
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
        "hexes_total": int(n_h),
        "hexes_routable": int(hexes["routable"].sum()),
        "pharmacies_routable": int(n_p),
        "pharmacies_total": int(len(pharmacies)),
        "reachable_hex_share": round(float(reachable.mean()), 3),
        "median_nearest_m": round(float(np.nanmedian(nearest_m[reachable])), 1) if reachable.any() else None,
        "p90_nearest_m": round(float(np.nanpercentile(nearest_m[reachable], 90)), 1) if reachable.any() else None,
    }
    (DATA_REPORTS / "access.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return hexes


if __name__ == "__main__":
    run()
