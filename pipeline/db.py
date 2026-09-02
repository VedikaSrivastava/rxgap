"""Shared DuckDB connection for cloud GeoParquet reads."""

from __future__ import annotations

import duckdb

from pipeline.config import OVERTURE_AZURE, OVERTURE_S3


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    return con


def parquet_url(theme: str, type_name: str, *, azure: bool = False) -> str:
    root = OVERTURE_AZURE if azure else OVERTURE_S3
    return f"{root}/theme={theme}/type={type_name}/*"


def try_overture_root(con: duckdb.DuckDBPyConnection) -> str:
    """Prefer S3; fall back to Azure HTTPS if anonymous S3 fails."""
    probe = parquet_url("divisions", "division")
    try:
        con.execute(f"SELECT 1 FROM read_parquet('{probe}', hive_partitioning=1) LIMIT 1")
        return OVERTURE_S3
    except Exception:
        probe = parquet_url("divisions", "division", azure=True)
        con.execute(f"SELECT 1 FROM read_parquet('{probe}', hive_partitioning=1) LIMIT 1")
        return OVERTURE_AZURE
