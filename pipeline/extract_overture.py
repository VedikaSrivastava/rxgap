"""Buffered-bbox Overture extracts: transportation, places, buildings, addresses, divisions."""

from __future__ import annotations

import json

from pipeline.config import BBOX, DATA_RAW, DATA_REPORTS, OVERTURE_RELEASE, ensure_dirs
from pipeline.db import connect, parquet_url

THEMES = (
    ("places", "place", "places.parquet"),
    ("transportation", "segment", "segments.parquet"),
    ("transportation", "connector", "connectors.parquet"),
    ("buildings", "building", "buildings.parquet"),
    ("addresses", "address", "addresses.parquet"),
    ("divisions", "division_area", "divisions.parquet"),
)

REQUIRED_COLUMNS = {
    "place": {"id", "geometry", "name"},
    "segment": {"id", "geometry", "subtype", "class", "connectors_json", "access_json"},
    "connector": {"id", "geometry"},
    "building": {"id", "geometry", "subtype", "class", "height", "num_floors"},
    "address": {"id", "geometry"},
    "division_area": {"id", "geometry", "name", "subtype"},
}


def _bbox_sql(mode: str = "intersect") -> str:
    b = BBOX
    if mode == "points":
        return (
            f"bbox.xmin BETWEEN {b['xmin']} AND {b['xmax']} "
            f"AND bbox.ymin BETWEEN {b['ymin']} AND {b['ymax']}"
        )
    return (
        f"bbox.xmin <= {b['xmax']} AND bbox.xmax >= {b['xmin']} "
        f"AND bbox.ymin <= {b['ymax']} AND bbox.ymax >= {b['ymin']}"
    )


def _columns(con, url: str) -> set[str]:
    rel = con.execute(f"SELECT * FROM read_parquet('{url}', hive_partitioning=1) LIMIT 0")
    return {d[0] for d in rel.description}


def _expr(cols: set[str], name: str, sql: str, alias: str | None = None) -> str | None:
    if name not in cols:
        return None
    return f"{sql} AS {alias or name}"


def extract_layer(con, theme: str, type_name: str, filename: str, azure: bool) -> dict:
    dest = DATA_RAW / filename
    url = parquet_url(theme, type_name, azure=azure)
    pointish = type_name in {"place", "address", "connector"}
    where = _bbox_sql("points" if pointish else "intersect")
    cols = _columns(con, url)

    select = ["id", "geometry"]
    if type_name == "place":
        select += [
            x
            for x in (
                _expr(cols, "names", "names.primary", "name"),
                _expr(cols, "categories", "categories.primary", "category_primary"),
                _expr(cols, "categories", "CAST(categories.alternate AS VARCHAR)", "category_alternate"),
                _expr(cols, "taxonomy", "taxonomy.primary", "taxonomy_primary"),
                _expr(cols, "taxonomy", "CAST(taxonomy AS VARCHAR)", "taxonomy_json"),
                _expr(cols, "basic_category", "basic_category"),
                _expr(cols, "confidence", "confidence"),
                _expr(cols, "addresses", "CAST(addresses AS VARCHAR)", "addresses_json"),
            )
            if x
        ]
    elif type_name == "segment":
        select += [
            x
            for x in (
                _expr(cols, "names", "names.primary", "name"),
                _expr(cols, "subtype", "subtype"),
                _expr(cols, "class", "class"),
                _expr(cols, "subclass", "subclass"),
                _expr(cols, "connectors", "CAST(connectors AS VARCHAR)", "connectors_json"),
                _expr(cols, "access_restrictions", "CAST(access_restrictions AS VARCHAR)", "access_json"),
            )
            if x
        ]
    elif type_name == "building":
        select += [
            x
            for x in (
                _expr(cols, "names", "names.primary", "name"),
                _expr(cols, "subtype", "subtype"),
                _expr(cols, "class", "class"),
                _expr(cols, "height", "height"),
                _expr(cols, "num_floors", "num_floors"),
            )
            if x
        ]
    elif type_name == "address":
        select += [
            x
            for x in (
                _expr(cols, "number", "number"),
                _expr(cols, "street", "street"),
                _expr(cols, "postal_code", "postal_code"),
                _expr(cols, "country", "country"),
            )
            if x
        ]
    elif type_name == "division_area":
        select += [
            x
            for x in (
                _expr(cols, "names", "names.primary", "name"),
                _expr(cols, "subtype", "subtype"),
                _expr(cols, "class", "class"),
                _expr(cols, "country", "country"),
                _expr(cols, "region", "region"),
                _expr(cols, "division_id", "division_id"),
            )
            if x
        ]
        where += " AND country = 'US' AND region = 'US-MA' AND subtype IN ('locality', 'county')"

    if dest.exists() and dest.stat().st_size > 1000:
        local = con.execute(f"SELECT * FROM read_parquet('{dest.as_posix()}') LIMIT 0")
        local_cols = {d[0] for d in local.description}
        missing = REQUIRED_COLUMNS[type_name] - local_cols
        if missing:
            raise RuntimeError(f"{filename} is missing columns: {sorted(missing)}")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{dest.as_posix()}')").fetchone()[0]
        if not n:
            raise RuntimeError(f"{filename} is empty")
        return {"file": filename, "rows": int(n), "skipped": True}

    sql = f"""
        COPY (
            SELECT {", ".join(select)}
            FROM read_parquet('{url}', hive_partitioning=1)
            WHERE {where}
        ) TO '{dest.as_posix()}' (FORMAT PARQUET)
    """
    con.execute(sql)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{dest.as_posix()}')").fetchone()[0]
    return {"file": filename, "rows": int(n), "skipped": False, "columns": [s.split(" AS ")[-1] for s in select]}


def run() -> dict:
    ensure_dirs()
    con = connect()
    azure = False
    try:
        con.execute(
            f"SELECT 1 FROM read_parquet('{parquet_url('divisions', 'division')}', hive_partitioning=1) LIMIT 1"
        )
    except Exception as exc:
        print("S3 probe failed, using Azure HTTPS:", exc)
        azure = True

    stats = []
    for theme, type_name, filename in THEMES:
        print(f"Extracting {theme}/{type_name}...", flush=True)
        stats.append(extract_layer(con, theme, type_name, filename, azure=azure))
        print(" ", stats[-1], flush=True)

    report = {
        "overture_release": OVERTURE_RELEASE,
        "bbox": BBOX,
        "source": "azure" if azure else "s3",
        "layers": stats,
    }
    (DATA_REPORTS / "overture_extract.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
