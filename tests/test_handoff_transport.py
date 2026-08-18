from __future__ import annotations

import hashlib
import io
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[1] / "handoff-package"
sys.path.insert(0, str(PACKAGE_ROOT))

from file_pair_handoff import download_asset, store_create_only


class FakeResponse:
    def __init__(self, *, status=200, body=b"", headers=None):
        self.status_code = status
        self.body = body
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        for index in range(0, len(self.body), chunk_size):
            yield self.body[index:index + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FakeS3:
    def __init__(self):
        self.body = None

    def put_object(self, **kwargs):
        self.body = kwargs["Body"].read()
        return {"VersionId": "version-7"}

    def head_object(self, **kwargs):
        return {
            "ContentLength": len(self.body),
            "Metadata": {"sha256": hashlib.sha256(self.body).hexdigest()},
            "VersionId": "version-7",
        }

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.body), "VersionId": "version-7"}


class TransportTests(unittest.TestCase):
    def test_download_follows_only_allowlisted_redirect_and_checks_bytes(self):
        body = b"opaque bytes"
        redirect = FakeResponse(
            status=302,
            headers={"Location": "https://release-assets.githubusercontent.com/signed/object"},
        )
        delivered = FakeResponse(body=body, headers={"Content-Length": str(len(body))})
        session = FakeSession([redirect, delivered])
        asset = {
            "name": "capture.bin",
            "url": "https://api.github.com/repos/example/source/releases/assets/7",
            "size": len(body),
            "digest": f"sha256:{hashlib.sha256(body).hexdigest()}",
        }

        downloaded = download_asset(
            session,
            asset,
            api_host="api.github.com",
            repository="example/source",
            allowed_redirect_hosts={"release-assets.githubusercontent.com"},
            max_bytes=100,
        )
        self.addCleanup(downloaded.close)

        self.assertEqual(downloaded.body.read(), body)
        self.assertEqual(downloaded.size, len(body))
        self.assertEqual(downloaded.sha256, hashlib.sha256(body).hexdigest())
        self.assertTrue(redirect.closed)
        self.assertIsNone(session.calls[1][1]["headers"]["Authorization"])

    def test_download_rejects_a_prefix_confusion_asset_url_before_network(self):
        session = FakeSession([])
        asset = {
            "name": "capture.bin",
            "url": "https://api.github.com/repos/example/source/releases/assets-evil/7",
            "size": 1,
        }

        with self.assertRaisesRegex(ValueError, "asset API URL"):
            download_asset(
                session,
                asset,
                api_host="api.github.com",
                repository="example/source",
                allowed_redirect_hosts={"release-assets.githubusercontent.com"},
                max_bytes=100,
            )

        self.assertEqual(session.calls, [])

    def test_create_only_store_reads_back_bytes_and_returns_version(self):
        body = b"opaque bytes"
        session = FakeSession([FakeResponse(body=body)])
        downloaded = download_asset(
            session,
            {
                "name": "capture.bin",
                "url": "https://api.github.com/repos/example/source/releases/assets/7",
                "size": len(body),
            },
            api_host="api.github.com",
            repository="example/source",
            allowed_redirect_hosts=set(),
            max_bytes=100,
        )
        self.addCleanup(downloaded.close)

        stored = store_create_only(
            FakeS3(), bucket="frozen", key="source/42/data/capture.bin", downloaded=downloaded
        )

        self.assertEqual(stored.key, "source/42/data/capture.bin")
        self.assertEqual(stored.size, len(body))
        self.assertEqual(stored.sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(stored.version_id, "version-7")


if __name__ == "__main__":
    unittest.main()
