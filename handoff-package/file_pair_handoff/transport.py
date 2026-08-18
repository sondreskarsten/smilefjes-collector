from __future__ import annotations

import hashlib
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Any, BinaryIO, Collection, Mapping
from urllib.parse import urlparse


CHUNK_SIZE = 1024 * 1024
SPOOL_MEMORY_BYTES = 8 * 1024 * 1024


@dataclass
class DownloadedFile:
    name: str
    size: int
    sha256: str
    body: BinaryIO

    def close(self) -> None:
        self.body.close()


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str
    version_id: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "bytes": self.size,
            "sha256": self.sha256,
            "version_id": self.version_id,
        }


def _asset_api_url(url: object, *, api_host: str, repository: str) -> str:
    if not isinstance(url, str):
        raise ValueError("GitHub asset API URL is missing")
    if repository.count("/") != 1:
        raise ValueError("repository must be owner/name")
    parsed = urlparse(url)
    expected = rf"/repos/{re.escape(repository)}/releases/assets/[1-9][0-9]*"
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != api_host.lower()
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or re.fullmatch(expected, parsed.path) is None
    ):
        raise ValueError("unsafe GitHub asset API URL")
    return url


def _positive_size(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("GitHub asset size is invalid")
    return value


def download_asset(
    session,
    asset: Mapping[str, Any],
    *,
    api_host: str,
    repository: str,
    allowed_redirect_hosts: Collection[str],
    max_bytes: int,
) -> DownloadedFile:
    """Download one opaque asset with bounded, allow-listed transport."""

    if max_bytes < 0:
        raise ValueError("maximum byte count is invalid")
    name = asset.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("GitHub asset name is invalid")
    advertised_size = _positive_size(asset.get("size"))
    if advertised_size > max_bytes:
        raise RuntimeError("release asset exceeds maximum byte count")
    url = _asset_api_url(asset.get("url"), api_host=api_host, repository=repository)

    response = session.get(
        url,
        timeout=(10, 60),
        stream=True,
        allow_redirects=False,
        headers={"Accept": "application/octet-stream"},
    )
    if response.status_code in {301, 302, 303, 307, 308}:
        location = response.headers.get("Location", "")
        target = urlparse(location)
        allowed = {host.lower() for host in allowed_redirect_hosts}
        if (
            target.scheme != "https"
            or target.hostname is None
            or target.hostname.lower() not in allowed
            or target.username is not None
            or target.password is not None
        ):
            response.close()
            raise RuntimeError("unsafe GitHub asset redirect")
        response.close()
        response = session.get(
            location,
            timeout=(10, 60),
            stream=True,
            allow_redirects=False,
            headers={"Accept": "application/octet-stream", "Authorization": None},
        )

    if response.status_code != 200:
        status = response.status_code
        response.close()
        raise RuntimeError(f"GitHub asset download failed: HTTP {status}")
    length_header = response.headers.get("Content-Length")
    if length_header:
        try:
            content_length = int(length_header)
        except ValueError as exc:
            response.close()
            raise RuntimeError("GitHub asset Content-Length is invalid") from exc
        if content_length < 0 or content_length > max_bytes:
            response.close()
            raise RuntimeError("release asset exceeds maximum byte count")

    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b")
    digest = hashlib.sha256()
    byte_count = 0
    try:
        for chunk in response.iter_content(CHUNK_SIZE):
            if not chunk:
                continue
            byte_count += len(chunk)
            if byte_count > max_bytes:
                raise RuntimeError("release asset exceeds maximum byte count")
            digest.update(chunk)
            spool.write(chunk)
    except Exception:
        spool.close()
        raise
    finally:
        response.close()

    actual_digest = digest.hexdigest()
    if byte_count != advertised_size:
        spool.close()
        raise RuntimeError("GitHub asset byte count mismatch")
    advertised_digest = asset.get("digest")
    if advertised_digest is not None and advertised_digest != f"sha256:{actual_digest}":
        spool.close()
        raise RuntimeError("GitHub asset digest mismatch")
    spool.seek(0)
    return DownloadedFile(name=name, size=byte_count, sha256=actual_digest, body=spool)


def _error_code(exc: Exception) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))


def _safe_key(key: str) -> None:
    parts = key.split("/")
    if not key or key.startswith("/") or "" in parts or any(part in {".", ".."} for part in parts):
        raise ValueError("S3 key is invalid")


def store_create_only(
    s3,
    *,
    bucket: str,
    key: str,
    downloaded: DownloadedFile,
) -> StoredObject:
    """Create an S3 object once, then read back and verify the exact bytes."""

    if not bucket:
        raise ValueError("S3 bucket is missing")
    _safe_key(key)
    metadata = {"sha256": downloaded.sha256}
    put_result: Mapping[str, Any] = {}
    conflict_attempts = 0
    while True:
        downloaded.body.seek(0)
        try:
            put_result = s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=downloaded.body,
                Metadata=metadata,
                IfNoneMatch="*",
            ) or {}
            break
        except Exception as exc:
            code = _error_code(exc)
            if code in {"ConditionalRequestConflict", "409"} and conflict_attempts < 3:
                time.sleep(0.05 * (2**conflict_attempts))
                conflict_attempts += 1
                continue
            if code in {"PreconditionFailed", "412"}:
                break
            raise

    head = s3.head_object(Bucket=bucket, Key=key)
    if (
        head.get("ContentLength") != downloaded.size
        or head.get("Metadata", {}).get("sha256") != downloaded.sha256
    ):
        raise RuntimeError("S3 read-back verification failed")

    result = s3.get_object(Bucket=bucket, Key=key)
    existing = result["Body"]
    digest = hashlib.sha256()
    try:
        while chunk := existing.read(CHUNK_SIZE):
            digest.update(chunk)
    finally:
        close = getattr(existing, "close", None)
        if close is not None:
            close()
    if digest.hexdigest() != downloaded.sha256:
        raise RuntimeError("S3 read-back verification failed")

    version_id = head.get("VersionId") or put_result.get("VersionId") or result.get("VersionId")
    if version_id is not None:
        version_id = str(version_id)
    return StoredObject(
        key=key,
        size=downloaded.size,
        sha256=downloaded.sha256,
        version_id=version_id,
    )
