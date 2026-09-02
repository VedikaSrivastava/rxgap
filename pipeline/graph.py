"""Pedestrian graph from Overture segments, plus continuity / bridge assertions."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from shapely import wkt as shapely_wkt
from shapely.geometry import LineString

from pipeline.config import (
    DATA_PROCESSED,
    DATA_RAW,
    DATA_REPORTS,
    REQUIRED_BRIDGES,
    WALKABLE_CLASSES,
    ensure_dirs,
)
from pipeline.db import connect

WALK_DENIED = re.compile(r"walk|foot|pedestrian", re.I)
EARTH_M = 6371000.0


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlamb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlamb / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(a))


def _walk_denied(access_json) -> bool:
    if access_json is None:
        return False
    try:
        if pd.isna(access_json):
            return False
    except Exception:
        pass
    text = str(access_json).lower()
    if "walk" not in text and "foot" not in text and "pedestrian" not in text:
        return False
    return bool(re.search(r"(denied|no).{0,40}(walk|foot|pedestrian)|(walk|foot|pedestrian).{0,40}(denied|no)", text))


def load_segments() -> pd.DataFrame:
    path = DATA_RAW / "segments.parquet"
    con = connect()
    classes = ", ".join(f"'{c}'" for c in sorted(WALKABLE_CLASSES))
    df = con.execute(
        f"""
        SELECT id, name, subtype, class, access_json, ST_AsText(geometry) AS wkt
        FROM read_parquet('{path.as_posix()}')
        WHERE subtype = 'road'
          AND class IN ({classes})
        """
    ).df()
    df["access_json"] = df["access_json"].astype("string")
    df = df[~df["access_json"].map(_walk_denied)]
    return df


def build_graph(segments: pd.DataFrame) -> dict:
    node_index: dict[tuple[int, int], int] = {}
    lats: list[float] = []
    lons: list[float] = []
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    named: dict[str, list[int]] = defaultdict(list)

    def node(lon: float, lat: float) -> int:
        key = (round(lon * 1e5), round(lat * 1e5))
        idx = node_index.get(key)
        if idx is None:
            idx = len(node_index)
            node_index[key] = idx
            lons.append(lon)
            lats.append(lat)
        return idx

    for rec in segments.itertuples(index=False):
        try:
            geom = shapely_wkt.loads(rec.wkt)
        except Exception:
            continue
        if geom.is_empty:
            continue
        coords = list(geom.coords) if isinstance(geom, LineString) else []
        if len(coords) < 2:
            continue
        prev = None
        for lon, lat in coords:
            cur = node(lon, lat)
            if prev is not None and prev != cur:
                meters = _haversine_m(lats[prev], lons[prev], lat, lon)
                if meters <= 0:
                    continue
                rows.extend((prev, cur))
                cols.extend((cur, prev))
                data.extend((meters, meters))
            prev = cur
        name = (rec.name or "") if isinstance(rec.name, str) else ""
        if name:
            named[name].append(prev if prev is not None else 0)

    n = len(node_index)
    graph = csr_matrix((data, (rows, cols)), shape=(n, n))
    coords = np.column_stack([np.array(lats), np.array(lons)])
    return {"graph": graph, "coords": coords, "named": named, "n_edges": len(data) // 2}


def nearest_node(coords: np.ndarray, lat: float, lon: float) -> tuple[int, float]:
    d2 = (coords[:, 0] - lat) ** 2 + (coords[:, 1] - lon) ** 2
    idx = int(np.argmin(d2))
    meters = _haversine_m(lat, lon, coords[idx, 0], coords[idx, 1])
    return idx, meters


def report(graph_pack: dict, segments: pd.DataFrame) -> dict:
    graph = graph_pack["graph"]
    coords = graph_pack["coords"]
    n_comp, labels = connected_components(graph, directed=False)
    counts = np.bincount(labels)
    largest = int(counts.max()) if len(counts) else 0
    largest_share = largest / graph.shape[0] if graph.shape[0] else 0

    name_blob = " ".join(segments["name"].dropna().astype(str).unique())
    bridge_hits = {}
    for needle in REQUIRED_BRIDGES:
        pattern = re.compile(rf"\b{re.escape(needle)}\b", re.I)
        hits = [n for n in segments["name"].dropna().unique() if pattern.search(str(n))]
        if needle == "BU":
            hits = [
                n
                for n in segments["name"].dropna().unique()
                if re.search(r"\bBU\b|Boston University Bridge|B\.U\. Bridge", str(n), re.I)
            ]
        bridge_hits[needle] = hits[:8]

    seeds = {
        "boston_city_hall": (42.3604, -71.0578),
        "harvard_square": (42.3736, -71.1189),
        "kendall": (42.3626, -71.0843),
        "nubian": (42.3296, -71.0845),
        "longfellow_boston": (42.3615, -71.0678),
        "longfellow_cambridge": (42.3629, -71.0762),
        "harvard_bridge_boston": (42.3540, -71.0875),
        "harvard_bridge_cambridge": (42.3565, -71.0955),
        "bu_boston": (42.3516, -71.1109),
        "bu_cambridge": (42.3534, -71.1175),
        "brookline_border": (42.3420, -71.1210),
        "somerville_border": (42.3870, -71.1000),
        "newton_border": (42.3370, -71.1500),
    }
    snapped = {k: nearest_node(coords, lat, lon) for k, (lat, lon) in seeds.items()}

    def path_m(a: str, b: str) -> float | None:
        src = snapped[a][0]
        dst = snapped[b][0]
        dist = dijkstra(graph, directed=False, indices=src, unweighted=False)
        val = float(dist[dst])
        return None if np.isinf(val) else val

    routes = {
        "boston_to_harvard_square_m": path_m("boston_city_hall", "harvard_square"),
        "longfellow_cross_m": path_m("longfellow_boston", "longfellow_cambridge"),
        "harvard_bridge_cross_m": path_m("harvard_bridge_boston", "harvard_bridge_cambridge"),
        "bu_bridge_cross_m": path_m("bu_boston", "bu_cambridge"),
        "boston_to_brookline_border_m": path_m("boston_city_hall", "brookline_border"),
        "cambridge_to_somerville_border_m": path_m("harvard_square", "somerville_border"),
        "boston_to_newton_border_m": path_m("boston_city_hall", "newton_border"),
    }

    passed = {
        "largest_component_dominant": largest_share >= 0.85,
        "boston_cambridge_connected": routes["boston_to_harvard_square_m"] is not None,
        "longfellow": routes["longfellow_cross_m"] is not None,
        "harvard_bridge": routes["harvard_bridge_cross_m"] is not None,
        "bu_bridge": routes["bu_bridge_cross_m"] is not None,
        "brookline_not_clipped": routes["boston_to_brookline_border_m"] is not None,
        "somerville_not_clipped": routes["cambridge_to_somerville_border_m"] is not None,
        "newton_not_clipped": routes["boston_to_newton_border_m"] is not None,
    }

    return {
        "nodes": int(graph.shape[0]),
        "undirected_edges": int(graph_pack["n_edges"]),
        "segments_used": int(len(segments)),
        "components": int(n_comp),
        "largest_component_nodes": largest,
        "largest_component_share": round(largest_share, 4),
        "bridge_name_hits": bridge_hits,
        "snap_meters": {k: round(v[1], 1) for k, v in snapped.items()},
        "routes_m": {k: (None if v is None else round(v, 1)) for k, v in routes.items()},
        "pass": passed,
        "all_pass": all(passed.values()),
    }


def run() -> dict:
    ensure_dirs()
    segments = load_segments()
    pack = build_graph(segments)
    stats = report(pack, segments)
    np.savez_compressed(
        DATA_PROCESSED / "graph.npz",
        data=pack["graph"].data,
        indices=pack["graph"].indices,
        indptr=pack["graph"].indptr,
        coords=pack["coords"],
    )
    (DATA_REPORTS / "graph.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))
    if not stats["all_pass"]:
        print("GRAPH SPIKE: one or more continuity checks failed.")
    return stats


def load_graph() -> tuple[csr_matrix, np.ndarray]:
    blob = np.load(DATA_PROCESSED / "graph.npz")
    graph = csr_matrix((blob["data"], blob["indices"], blob["indptr"]))
    return graph, blob["coords"]


if __name__ == "__main__":
    run()
