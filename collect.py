"""Collector entrypoint: Mattilsynet CSV → gzipped archive on GCS.

Downloads the two cumulative CSV dumps from matnyttig.mattilsynet.no
and writes them as gzipped files to GCS under a dated path. No
parsing, no state management — raw immutable archive only. The parser
(separate repo) reads these files downstream.

Output paths::

    gs://{GCS_BUCKET}/{GCS_PREFIX}/raw/tilsyn/{YYYY-MM-DD}.csv.gz
    gs://{GCS_BUCKET}/{GCS_PREFIX}/raw/vurderinger/{YYYY-MM-DD}.csv.gz

Each file is the full cumulative dump — tilsyn.csv has one row per
tilsyn (from 2015-03-30 onward), vurderinger.csv has one row per
(tilsyn, kravpunkt).  Mattilsynet publishes updates within 5
business days of gjennomført tilsyn. Daily fetches capture both new
tilsyn and any invalidated tilsyn (which disappear from the dump).

Environment variables
---------------------
GCS_BUCKET : str
    Target GCS bucket. Default ``sondre_brreg_data``. Set to empty
    string for local-only mode (writes to ``./data/raw/``).
GCS_PREFIX : str
    GCS path prefix. Default ``smilefjes``.
RUN_DATE : str or unset
    ISO date ``YYYY-MM-DD`` to use in output path. Default: today in
    Europe/Oslo timezone.
"""

import os
import sys
import gzip
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from client import SmilefjesClient

GCS_BUCKET = os.environ.get("GCS_BUCKET", "sondre_brreg_data")
GCS_PREFIX = os.environ.get("GCS_PREFIX", "smilefjes")
RUN_DATE = os.environ.get("RUN_DATE") or datetime.now(ZoneInfo("Europe/Oslo")).date().isoformat()


def upload_gzipped(body, gcs_path):
    """Compress body to gzip and upload to GCS.

    Parameters
    ----------
    body : bytes
        Raw CSV bytes (BOM-stripped).
    gcs_path : str
        Full GCS object path (excluding bucket name).
    """
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)

    with tempfile.NamedTemporaryFile(suffix=".csv.gz", delete=False) as tmp:
        with gzip.open(tmp, "wb") as f:
            f.write(body)
        tmp_path = tmp.name

    blob = bucket.blob(gcs_path)
    blob.upload_from_filename(tmp_path)
    size = os.path.getsize(tmp_path)
    os.unlink(tmp_path)
    print(f"  Uploaded gs://{GCS_BUCKET}/{gcs_path} ({size:,} bytes, {len(body):,} raw)", flush=True)


def write_gzipped_local(body, path):
    """Write body gzipped to local filesystem.

    Parameters
    ----------
    body : bytes
        Raw CSV bytes.
    path : str
        Local file path.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wb") as f:
        f.write(body)
    print(f"  Wrote {path} ({len(body):,} raw bytes)", flush=True)


def main():
    """Fetch both CSVs and upload to GCS (or local) under today's date."""
    print(f"=== smilefjes-collector run_date={RUN_DATE} bucket={GCS_BUCKET or 'LOCAL'} ===", flush=True)
    client = SmilefjesClient()

    for dataset in ("tilsyn", "vurderinger"):
        print(f"Fetching {dataset}.csv...", flush=True)
        body = client.fetch(dataset)
        print(f"  Got {len(body):,} bytes", flush=True)

        gcs_path = f"{GCS_PREFIX}/raw/{dataset}/{RUN_DATE}.csv.gz"
        if GCS_BUCKET:
            upload_gzipped(body, gcs_path)
        else:
            write_gzipped_local(body, f"./data/raw/{dataset}/{RUN_DATE}.csv.gz")

    print(f"=== done ({client._request_count} HTTP requests) ===", flush=True)


if __name__ == "__main__":
    main()
