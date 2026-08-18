"""Capture the two Smilefjes CSV snapshots as one data file plus metadata."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from client import SmilefjesClient


RUN_DATE = os.environ.get("RUN_DATE") or datetime.now(UTC).date().isoformat()
SOURCE_BASE = "https://matnyttig.mattilsynet.no/smilefjes"
EXPECTED_HEADERS = {
    "tilsyn.csv": (
        "tilsynsobjektid", "orgnummer", "navn", "adrlinje1", "adrlinje2", "postnr",
        "poststed", "tilsynid", "sakref", "status", "dato", "total_karakter",
        "tilsynsbesoektype", "tema1_no", "tema1_nn", "karakter1", "tema2_no",
        "tema2_nn", "karakter2", "tema3_no", "tema3_nn", "karakter3", "tema4_no",
        "tema4_nn", "karakter4",
    ),
    "vurderinger.csv": (
        "tilsynid", "dato", "ordningsverdi", "kravpunktnavn_no", "kravpunktnavn_nn",
        "karakter", "tekst_no", "tekst_nn",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_csv(path: Path) -> tuple[dict, list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter=";", strict=True)
        header = next(reader, None)
        if header is None or tuple(header) != EXPECTED_HEADERS[path.name]:
            raise ValueError(
                f"{path.name} header does not match the Smilefjes source contract"
            )
        tilsyn_id_index = header.index("tilsynid")
        tilsyn_ids = []
        row_count = 0
        for line_number, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise ValueError(
                    f"{path.name} row {line_number} has an invalid column count"
                )
            if not row[tilsyn_id_index].strip():
                raise ValueError(
                    f"{path.name} row {line_number} has an empty tilsynid"
                )
            row_count += 1
            tilsyn_ids.append(row[tilsyn_id_index])
        if row_count == 0:
            raise ValueError(f"{path.name} must contain at least one data row")
    return (
        {
            "name": path.name,
            "source_url": f"{SOURCE_BASE}/{path.name}",
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "row_count": row_count,
            "header": header,
        },
        tilsyn_ids,
    )


def _write_archive(paths: list[Path], destination: Path) -> None:
    with destination.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in paths:
                    info = tarfile.TarInfo(path.name)
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with path.open("rb") as source:
                        archive.addfile(info, source)


def main() -> None:
    run_date = os.environ.get("RUN_DATE", RUN_DATE)
    run_id = os.environ.get("RUN_ID", "local")
    output_dir = Path(os.environ.get("OUTPUT_DIR", "dist"))
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"smilefjes-{run_date}-run-{run_id}"
    archive_path = output_dir / f"{stem}.tar.gz"
    metadata_path = output_dir / f"{stem}.metadata.json"

    client = SmilefjesClient()
    with tempfile.TemporaryDirectory(prefix="smilefjes-") as directory:
        staging = Path(directory)
        members = []
        member_metadata = []
        ids_by_dataset = {}
        for dataset in ("tilsyn", "vurderinger"):
            body = client.fetch(dataset)
            path = staging / f"{dataset}.csv"
            path.write_bytes(body)
            members.append(path)
            details, tilsyn_ids = _inspect_csv(path)
            member_metadata.append(details)
            ids_by_dataset[dataset] = tilsyn_ids

        _write_archive(members, archive_path)

    tilsyn_ids = set(ids_by_dataset["tilsyn"])
    vurdering_ids = set(ids_by_dataset["vurderinger"])
    orphan_ids = vurdering_ids - tilsyn_ids
    metadata = {
        "schema_version": "smilefjes-capture/v1",
        "status": "complete",
        "release_tag": stem,
        "observation_date": run_date,
        "retrieved_at_utc": os.environ.get("RETRIEVED_AT_UTC") or datetime.now(UTC).isoformat(),
        "source_commit": os.environ.get("SOURCE_COMMIT", "unknown"),
        "data": {
            "name": archive_path.name,
            "bytes": archive_path.stat().st_size,
            "sha256": _sha256(archive_path),
            "members": member_metadata,
        },
        "validation": {
            "tilsyn_id_count": len(tilsyn_ids),
            "vurdering_tilsyn_id_count": len(vurdering_ids),
            "orphan_vurdering_tilsyn_id_count": len(orphan_ids),
            "orphan_vurdering_row_count": sum(
                tilsyn_id in orphan_ids for tilsyn_id in ids_by_dataset["vurderinger"]
            ),
        },
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
