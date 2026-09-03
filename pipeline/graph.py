"""Pedestrian graph from Overture segments, using connector IDs as topology."""

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
    GRAPH_ROUTES,
    GRAPH_SEEDS,
    REQUIRED_BRIDGES,
    WALKABLE_CLASSES,
    ensure_dirs,
)
from pipeline.db import connect

WALK_DENIED = re.compile(r"walk|foot|pedestrian", re.I)
WALKABLE_TRUNK_NAME = re.compile(r"\b(?:bridge|overpass)\b", re.I)
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


def keep_segment(klass: str, name: str | None) -> bool:
    """Walkable classes, plus trunk segments that are named bridges/overpasses."""
    if klass in WALKABLE_CLASSES:
        return True
    return klass == "trunk" and bool(name and WALKABLE_TRUNK_NAME.search(str(name)))


def parse_connectors(raw) -> list[tuple[str, float]]:
    """Return (connector_id, at) sorted along the segment. Geometry coincidence is ignored."""
    if raw is None:
        return []
    try:
        if pd.isna(raw):
            return []
    except Exception:
        pass
    if isinstance(raw, list):
        data = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                data = json.loads(text.replace("'", '"'))
            except json.JSONDecodeError:
                pairs = re.findall(
                    r"connector_id['\"=\s:]+([0-9a-fA-F-]+)[^0-9]*at['\"=\s:]+([0-9.]+)",
                    text,
                )
                rows = [(cid, float(at)) for cid, at in pairs]
                rows.sort(key=lambda x: x[1])
                return rows
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cid = item.get("connector_id") or item.get("connectorId")
        if not cid:
            continue
        at = item.get("at")
        rows.append((str(cid), float(at) if at is not None else 0.0))
    rows.sort(key=lambda x: x[1])
    return rows


def _cum_m(coords: list[tuple[float, float]]) -> tuple[float, list[float]]:
    cum = [0.0]
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        cum.append(cum[-1] + _haversine_m(lat1, lon1, lat2, lon2))
    return cum[-1], cum


def portion_m(coords: list[tuple[float, float]], at_a: float, at_b: float) -> float:
    """Length of the geometry between two linear-reference positions."""
    if len(coords) < 2:
        return 0.0
    total, _ = _cum_m(coords)
    if total <= 0:
        return 0.0
    a, b = sorted((max(0.0, min(1.0, at_a)), max(0.0, min(1.0, at_b))))
    return (b - a) * total


def point_at(coords: list[tuple[float, float]], at: float) -> tuple[float, float]:
    total, cum = _cum_m(coords)
    if total <= 0:
        return coords[0]
    target = max(0.0, min(1.0, at)) * total
    for i in range(1, len(coords)):
        if cum[i] >= target:
            span = cum[i] - cum[i - 1]
            t = 0.0 if span <= 0 else (target - cum[i - 1]) / span
            lon = coords[i - 1][0] + t * (coords[i][0] - coords[i - 1][0])
            lat = coords[i - 1][1] + t * (coords[i][1] - coords[i - 1][1])
            return lon, lat
    return coords[-1]


def load_segments() -> pd.DataFrame:
    path = DATA_RAW / "segments.parquet"
    con = connect()
    classes = ", ".join(f"'{c}'" for c in sorted(WALKABLE_CLASSES | {"trunk"}))
    df = con.execute(
        f"""
        SELECT id, name, subtype, class, access_json, connectors_json, ST_AsText(geometry) AS wkt
        FROM read_parquet('{path.as_posix()}')
        WHERE subtype = 'road'
          AND class IN ({classes})
        """
    ).df()
    df["access_json"] = df["access_json"].astype("string")
    keep = pd.Series(
        [keep_segment(klass, name) for klass, name in zip(df["class"], df["name"])],
        index=df.index,
    )
    df = df[keep & ~df["access_json"].map(_walk_denied)]
    return df


def load_connector_xy() -> dict[str, tuple[float, float]]:
    path = DATA_RAW / "connectors.parquet"
    if not path.exists():
        return {}
    con = connect()
    df = con.execute(
        f"SELECT id, ST_X(geometry) AS lon, ST_Y(geometry) AS lat FROM read_parquet('{path.as_posix()}')"
    ).df()
    return {str(r.id): (float(r.lon), float(r.lat)) for r in df.itertuples(index=False)}


def build_graph(segments: pd.DataFrame, connector_xy: dict[str, tuple[float, float]] | None = None) -> dict:
    """Nodes are Overture connector IDs. Shared connector_id is the only junction."""
    connector_xy = connector_xy or {}
    node_index: dict[str, int] = {}
    lats: list[float] = []
    lons: list[float] = []
    edge_w: dict[tuple[int, int], float] = {}
    named: dict[str, list[int]] = defaultdict(list)

    def node(cid: str, lon: float, lat: float) -> int:
        idx = node_index.get(cid)
        if idx is None:
            idx = len(node_index)
            node_index[cid] = idx
            lons.append(lon)
            lats.append(lat)
        return idx

    used = 0
    for rec in segments.itertuples(index=False):
        try:
            geom = shapely_wkt.loads(rec.wkt)
        except Exception:
            continue
        if geom.is_empty or not isinstance(geom, LineString):
            continue
        coords = list(geom.coords)
        if len(coords) < 2:
            continue
        connectors = parse_connectors(getattr(rec, "connectors_json", None))
        if len(connectors) < 2:
            continue
        used += 1
        idxs = []
        for cid, at in connectors:
            xy = connector_xy.get(cid)
            if xy is None:
                xy = point_at(coords, at)
            idxs.append(node(cid, xy[0], xy[1]))
        for i in range(1, len(connectors)):
            a, b = idxs[i - 1], idxs[i]
            if a == b:
                continue
            meters = portion_m(coords, connectors[i - 1][1], connectors[i][1])
            if meters <= 0:
                continue
            for u, v in ((a, b), (b, a)):
                prev = edge_w.get((u, v))
                if prev is None or meters < prev:
                    edge_w[(u, v)] = meters
        name = (rec.name or "") if isinstance(rec.name, str) else ""
        if name:
            named[name].append(idxs[-1])

    rows, cols, data = [], [], []
    for (u, v), meters in edge_w.items():
        rows.append(u)
        cols.append(v)
        data.append(meters)
    n = len(node_index)
    graph = csr_matrix((data, (rows, cols)), shape=(n, n))
    coords = np.column_stack([np.array(lats), np.array(lons)]) if lats else np.zeros((0, 2))
    return {
        "graph": graph,
        "coords": coords,
        "named": named,
        "n_edges": len(edge_w) // 2,
        "segments_used": used,
    }


def nearest_node(coords: np.ndarray, lat: float, lon: float) -> tuple[int, float]:
    d2 = (coords[:, 0] - lat) ** 2 + (coords[:, 1] - lon) ** 2
    idx = int(np.argmin(d2))
    meters = _haversine_m(lat, lon, coords[idx, 0], coords[idx, 1])
    return idx, meters


def main_component_mask(graph) -> np.ndarray:
    n_comp, labels = connected_components(graph, directed=False)
    if not len(labels):
        return np.zeros(0, dtype=bool)
    main = int(np.argmax(np.bincount(labels)))
    return labels == main


def route_between(
    graph,
    coords: np.ndarray,
    origin: tuple[float, float],
    dest: tuple[float, float],
) -> dict:
    """Snap both ends the same way access does, then measure the graph path."""
    o_idx, o_snap = nearest_reachable_node(graph, coords, origin[0], origin[1])
    d_idx, d_snap = nearest_reachable_node(graph, coords, dest[0], dest[1])
    dist = dijkstra(graph, directed=False, indices=o_idx, unweighted=False)
    val = float(dist[d_idx])
    return {
        "modeled_m": None if np.isinf(val) else val,
        "geodesic_m": _haversine_m(origin[0], origin[1], dest[0], dest[1]),
        "snap_origin_m": o_snap,
        "snap_dest_m": d_snap,
    }


def nearest_reachable_node(
    graph,
    coords: np.ndarray,
    lat: float,
    lon: float,
    max_m: float = 250,
    candidates: int = 800,
) -> tuple[int, float]:
    """Snap to the nearest graph node in the main walkable component."""
    if coords.size == 0:
        return 0, float("inf")
    mask = main_component_mask(graph)
    d2 = (coords[:, 0] - lat) ** 2 + (coords[:, 1] - lon) ** 2
    best = (int(np.argmin(d2)), float("inf"))
    for idx in np.argsort(d2)[:candidates]:
        idx = int(idx)
        if not mask[idx]:
            continue
        meters = _haversine_m(lat, lon, coords[idx, 0], coords[idx, 1])
        if meters < best[1]:
            best = (idx, meters)
        if meters <= max_m:
            break
    return best


def report(graph_pack: dict, segments: pd.DataFrame) -> dict:
    graph = graph_pack["graph"]
    coords = graph_pack["coords"]
    n_comp, labels = connected_components(graph, directed=False)
    counts = np.bincount(labels)
    largest = int(counts.max()) if len(counts) else 0
    largest_share = largest / graph.shape[0] if graph.shape[0] else 0

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

    measured = {}
    routes = {key: None for key, _, _ in GRAPH_ROUTES}
    if graph.shape[0]:
        for key, origin, dest in GRAPH_ROUTES:
            measured[key] = route_between(graph, coords, GRAPH_SEEDS[origin], GRAPH_SEEDS[dest])
            routes[key] = measured[key]["modeled_m"]
    snapped = (
        {
            name: nearest_reachable_node(graph, coords, lat, lon)
            for name, (lat, lon) in GRAPH_SEEDS.items()
        }
        if graph.shape[0]
        else {}
    )

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
        "segments_used": int(graph_pack.get("segments_used", len(segments))),
        "topology": "overture_connector_id",
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
    pack = build_graph(segments, load_connector_xy())
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
