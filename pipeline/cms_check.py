"""CMS Part D Retail Pharmacy Access spike (hard-capped).

The Q1 2026 ZIP is a plan-level network-adequacy table, not a walk-in
storefront directory. We keep the check so the README can say we looked,
then fall back to NPPES Community/Retail Pharmacy.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import requests

from pipeline.config import DATA_PROCESSED, DATA_RAW, DATA_REPORTS, ensure_dirs

CMS_URL = "https://www.cms.gov/files/zip/q1-2026-medicare-part-d-retail-pharmacy-access.zip"
MAX_BYTES = 400 * 1024 * 1024


def download() -> Path | None:
    ensure_dirs()
    dest = DATA_RAW / "cms_q1_2026_retail_pharmacy_access.zip"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest

    print("Downloading CMS Q1 2026 Retail Pharmacy Access ZIP...", flush=True)
    with requests.get(
        CMS_URL,
        stream=True,
        timeout=60,
        headers={"User-Agent": "rxgap/0.1 (pharmacy access research)"},
    ) as resp:
        resp.raise_for_status()
        length = int(resp.headers.get("Content-Length") or 0)
        if length > MAX_BYTES:
            print(f"CMS file is {length / 1e6:.0f} MB; skipping as a cross-check.", flush=True)
            return None
        written = 0
        with dest.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_BYTES:
                    dest.unlink(missing_ok=True)
                    print("CMS file exceeded size cap; skipping.", flush=True)
                    return None
                f.write(chunk)
    print(f"Downloaded CMS file ({dest.stat().st_size / 1e6:.1f} MB)", flush=True)
    return dest


def extract_ma() -> Path | None:
    zip_path = download()
    if zip_path is None:
        return None

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        (DATA_REPORTS / "cms_zip_contents.json").write_text(json.dumps(names, indent=2), encoding="utf-8")
        sample_cols: list[str] = []
        row_count = 0
        for name in names:
            low = name.lower()
            if not low.endswith((".csv", ".txt", ".xlsx", ".xls")):
                continue
            with zf.open(name) as fh:
                raw = fh.read()
            if low.endswith((".xlsx", ".xls")):
                frame = pd.read_excel(io.BytesIO(raw), nrows=5)
            else:
                frame = pd.read_csv(io.BytesIO(raw), nrows=5)
            sample_cols = [str(c) for c in frame.columns]
            if low.endswith(".csv"):
                row_count = max(row_count, sum(1 for _ in io.BytesIO(raw)) - 1)

    joined = " ".join(sample_cols).lower()
    has_storefront = any(k in joined for k in ("npi", "pharmacy_name", "address", "latitude"))
    summary = {
        "usable_as_storefront_directory": has_storefront,
        "reason": None
        if has_storefront
        else "File is plan-level Part D retail-access adequacy, not a pharmacy address list.",
        "columns": sample_cols,
        "approx_rows": row_count,
        "zip_files": names,
        "fallback": "NPPES taxonomy 3336C0003X (Community/Retail Pharmacy)",
    }
    (DATA_REPORTS / "cms_check.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    stale = DATA_PROCESSED / "cms_ma_retail.csv"
    if stale.exists() and not has_storefront:
        stale.unlink()
    print(json.dumps(summary, indent=2), flush=True)
    return None


if __name__ == "__main__":
    extract_ma()
