from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


CONTRACT_REVISION = "file-pair-handoff/v1"
ROLES = ("data", "metadata")


@dataclass(frozen=True)
class FileFact:
    path: Path
    name: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": str(self.path),
            "size": self.size,
            "sha256": self.sha256,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_local_pair(data: str | Path, metadata: str | Path) -> dict[str, FileFact]:
    """Verify the transport pair without interpreting either file."""

    paths = {"data": Path(data), "metadata": Path(metadata)}
    resolved = {role: path.resolve() for role, path in paths.items()}
    if resolved["data"] == resolved["metadata"]:
        raise ValueError("data and metadata must be distinct files")
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("data and metadata must both be regular files")
    parents = {path.resolve().parent for path in paths.values()}
    if len(parents) != 1:
        raise ValueError("data and metadata must share one output directory")
    output_files = {path.resolve() for path in next(iter(parents)).iterdir() if path.is_file()}
    if output_files != set(resolved.values()):
        raise ValueError("output directory must contain exactly two files")

    return {
        role: FileFact(
            path=path,
            name=path.name,
            size=path.stat().st_size,
            sha256=_sha256(path),
        )
        for role, path in paths.items()
    }


def _draft_state(release: Mapping[str, Any]) -> bool:
    if "isDraft" in release:
        value = release["isDraft"]
    elif "draft" in release:
        value = release["draft"]
    else:
        raise ValueError("release draft state is missing")
    if not isinstance(value, bool):
        raise ValueError("release draft state is invalid")
    return value


def _safe_asset_name(value: object) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError("release asset name is invalid")
    if "/" in value or "\\" in value:
        raise ValueError("release asset name must be a basename")
    return value


def _select_release_assets(
    release: Mapping[str, Any], *, expected_draft: bool
) -> dict[str, Mapping[str, Any]]:
    if _draft_state(release) is not expected_draft:
        expected = "draft" if expected_draft else "published"
        raise ValueError(f"release must be {expected}")
    if not expected_draft and release.get("prerelease") is True:
        raise ValueError("release must not be a prerelease")

    assets = release.get("assets")
    if not isinstance(assets, list) or len(assets) != 2:
        raise ValueError("release must contain exactly two assets")

    selected: dict[str, Mapping[str, Any]] = {}
    names: set[str] = set()
    for asset in assets:
        if not isinstance(asset, Mapping):
            raise ValueError("release asset is invalid")
        if asset.get("state") != "uploaded":
            raise ValueError("release contains an asset that is not uploaded")
        role = asset.get("label")
        if role not in ROLES or role in selected:
            raise ValueError("release must label one data and one metadata asset")
        name = _safe_asset_name(asset.get("name"))
        if name in names:
            raise ValueError("release assets must have distinct names")
        size = asset.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("release asset size is invalid")
        names.add(name)
        selected[role] = asset

    if set(selected) != set(ROLES):
        raise ValueError("release must label one data and one metadata asset")
    return selected


def verify_draft_release_assets(
    release: Mapping[str, Any], data: str | Path, metadata: str | Path
) -> dict[str, Mapping[str, Any]]:
    local = verify_local_pair(data, metadata)
    selected = _select_release_assets(release, expected_draft=True)
    for role in ROLES:
        asset = selected[role]
        fact = local[role]
        if asset["name"] != fact.name or asset["size"] != fact.size:
            raise ValueError(f"release {role} asset does not match the local file")
        digest = asset.get("digest")
        if not isinstance(digest, str):
            raise ValueError(f"release {role} asset digest is required")
        if digest != f"sha256:{fact.sha256}":
            raise ValueError(f"release {role} asset digest does not match the local file")
    return selected


def select_published_release_assets(
    release: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Select an opaque published pair by role; never inspect either file."""

    return _select_release_assets(release, expected_draft=False)
