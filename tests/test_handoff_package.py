from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[1] / "handoff-package"


def load_handoff_module():
    sys.path.insert(0, str(PACKAGE_ROOT))
    try:
        import file_pair_handoff
    except ModuleNotFoundError:
        return None
    return file_pair_handoff


class HandoffPackageTests(unittest.TestCase):
    def make_pair(self) -> tuple[Path, Path, tempfile.TemporaryDirectory]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        data = root / "capture.tar.gz"
        metadata = root / "capture.metadata.bin"
        data.write_bytes(b"opaque data")
        metadata.write_bytes(b"\xff\x00opaque metadata")
        return data, metadata, temporary

    def test_local_pair_accepts_arbitrary_binary_metadata(self):
        handoff = load_handoff_module()
        self.assertIsNotNone(handoff, "the repo-local handoff package is not implemented")
        data, metadata, temporary = self.make_pair()
        self.addCleanup(temporary.cleanup)

        pair = handoff.verify_local_pair(data, metadata)

        self.assertEqual(pair["data"].path, data)
        self.assertEqual(pair["metadata"].path, metadata)
        self.assertEqual(pair["metadata"].sha256, hashlib.sha256(metadata.read_bytes()).hexdigest())

    def test_release_gate_uses_roles_without_decoding_metadata(self):
        handoff = load_handoff_module()
        self.assertIsNotNone(handoff)
        data, metadata, temporary = self.make_pair()
        self.addCleanup(temporary.cleanup)
        release = {
            "isDraft": True,
            "assets": [
                {
                    "name": data.name,
                    "label": "data",
                    "size": data.stat().st_size,
                    "digest": f"sha256:{hashlib.sha256(data.read_bytes()).hexdigest()}",
                    "state": "uploaded",
                },
                {
                    "name": metadata.name,
                    "label": "metadata",
                    "size": metadata.stat().st_size,
                    "digest": f"sha256:{hashlib.sha256(metadata.read_bytes()).hexdigest()}",
                    "state": "uploaded",
                },
            ],
        }

        selected = handoff.verify_draft_release_assets(release, data, metadata)

        self.assertEqual(selected["data"]["name"], data.name)
        self.assertEqual(selected["metadata"]["name"], metadata.name)

    def test_release_gate_rejects_a_third_asset(self):
        handoff = load_handoff_module()
        self.assertIsNotNone(handoff)
        data, metadata, temporary = self.make_pair()
        self.addCleanup(temporary.cleanup)
        release = {
            "isDraft": True,
            "assets": [
                {"name": data.name, "label": "data", "size": data.stat().st_size, "state": "uploaded"},
                {
                    "name": metadata.name,
                    "label": "metadata",
                    "size": metadata.stat().st_size,
                    "state": "uploaded",
                },
                {"name": "stale", "label": "data", "size": 0, "state": "starter"},
            ],
        }

        with self.assertRaisesRegex(ValueError, "exactly two"):
            handoff.verify_draft_release_assets(release, data, metadata)

    def test_release_gate_requires_github_digests_for_both_uploaded_files(self):
        handoff = load_handoff_module()
        self.assertIsNotNone(handoff)
        data, metadata, temporary = self.make_pair()
        self.addCleanup(temporary.cleanup)
        release = {
            "isDraft": True,
            "assets": [
                {
                    "name": data.name,
                    "label": "data",
                    "size": data.stat().st_size,
                    "state": "uploaded",
                },
                {
                    "name": metadata.name,
                    "label": "metadata",
                    "size": metadata.stat().st_size,
                    "state": "uploaded",
                },
            ],
        }

        with self.assertRaisesRegex(ValueError, "digest is required"):
            handoff.verify_draft_release_assets(release, data, metadata)

    def test_cli_verifies_a_local_pair(self):
        data, metadata, temporary = self.make_pair()
        self.addCleanup(temporary.cleanup)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "file_pair_handoff",
                "verify-local",
                "--data",
                str(data),
                "--metadata",
                str(metadata),
            ],
            cwd=Path(__file__).parents[1],
            env={**os.environ, "PYTHONPATH": str(PACKAGE_ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["data"]["name"], data.name)
        self.assertEqual(output["metadata"]["name"], metadata.name)


if __name__ == "__main__":
    unittest.main()
