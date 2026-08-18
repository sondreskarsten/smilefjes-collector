from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("RUN_DATE", "2026-08-18")

import collect


TILSYN = (
    b"tilsynsobjektid;orgnummer;navn;adrlinje1;adrlinje2;postnr;poststed;"
    b"tilsynid;sakref;status;dato;total_karakter;tilsynsbesoektype;tema1_no;"
    b"tema1_nn;karakter1;tema2_no;tema2_nn;karakter2;tema3_no;tema3_nn;"
    b"karakter3;tema4_no;tema4_nn;karakter4\n"
    b"11;999888777;\"Kafe; \"\"A\"\"\";Gate 1;;0101;Oslo;101;2026/1;publisert;18082026;"
    b"0;foerste;Renhold;Reinhald;0;;;;;;;;;\n"
)

VURDERINGER = (
    b"tilsynid;dato;ordningsverdi;kravpunktnavn_no;kravpunktnavn_nn;karakter;"
    b"tekst_no;tekst_nn\n"
    b"101;18082026;1;Renhold;Reinhald;0;;\n"
    b"999;18082026;1;Historisk;Historisk;1;;\n"
)


class FakeClient:
    _request_count = 2

    def fetch(self, dataset: str) -> bytes:
        return {"tilsyn": TILSYN, "vurderinger": VURDERINGER}[dataset]


class CapturePairTests(unittest.TestCase):
    def run_capture(self, *, run_id: str = "12345", client=None) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        output = root / "dist"
        old_cwd = Path.cwd()
        os.chdir(root)
        try:
            with (
                patch.object(collect, "SmilefjesClient", return_value=client or FakeClient()),
                patch.object(collect, "RUN_DATE", "2026-08-18"),
                patch.dict(
                    os.environ,
                    {
                        "OUTPUT_DIR": str(output),
                        "RUN_ID": run_id,
                        "SOURCE_COMMIT": "a" * 40,
                        "RETRIEVED_AT_UTC": "2026-08-18T04:30:00Z",
                    },
                ),
            ):
                collect.main()
        finally:
            os.chdir(old_cwd)
        return output

    def test_run_emits_one_archive_and_one_binding_metadata_file(self):
        output = self.run_capture()
        names = sorted(path.name for path in output.glob("*"))
        self.assertEqual(
            names,
            [
                "smilefjes-2026-08-18-run-12345.metadata.json",
                "smilefjes-2026-08-18-run-12345.tar.gz",
            ],
        )

        archive_path = output / names[1]
        with tarfile.open(archive_path, "r:gz") as archive:
            self.assertEqual(archive.getnames(), ["tilsyn.csv", "vurderinger.csv"])
            self.assertEqual(archive.extractfile("tilsyn.csv").read(), TILSYN)
            self.assertEqual(archive.extractfile("vurderinger.csv").read(), VURDERINGER)

        metadata = json.loads((output / names[0]).read_text(encoding="utf-8"))
        self.assertEqual(metadata["schema_version"], "smilefjes-capture/v1")
        self.assertEqual(metadata["status"], "complete")
        self.assertIn("release_tag", metadata)
        self.assertEqual(metadata["release_tag"], "smilefjes-2026-08-18-run-12345")
        self.assertEqual(metadata["data"]["name"], archive_path.name)
        self.assertEqual(metadata["data"]["bytes"], archive_path.stat().st_size)
        self.assertEqual(
            metadata["data"]["sha256"],
            hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        )

    def test_metadata_records_source_identity_and_smilefjes_validation(self):
        output = self.run_capture()
        metadata_path = next(output.glob("*.metadata.json"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertIn("members", metadata["data"])
        members = {item["name"]: item for item in metadata["data"]["members"]}

        self.assertEqual(
            members["tilsyn.csv"],
            {
                "name": "tilsyn.csv",
                "source_url": "https://matnyttig.mattilsynet.no/smilefjes/tilsyn.csv",
                "bytes": len(TILSYN),
                "sha256": hashlib.sha256(TILSYN).hexdigest(),
                "row_count": 1,
                "header": TILSYN.splitlines()[0].decode("utf-8").split(";"),
            },
        )
        self.assertEqual(members["vurderinger.csv"]["row_count"], 2)
        self.assertEqual(
            metadata["validation"],
            {
                "tilsyn_id_count": 1,
                "vurdering_tilsyn_id_count": 2,
                "orphan_vurdering_tilsyn_id_count": 1,
                "orphan_vurdering_row_count": 1,
            },
        )

    def test_identical_source_snapshots_make_identical_data_archives(self):
        first = next(self.run_capture(run_id="111").glob("*.tar.gz")).read_bytes()
        second = next(self.run_capture(run_id="222").glob("*.tar.gz")).read_bytes()

        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())

    def test_unexpected_source_header_is_rejected_before_publication(self):
        class ChangedSource(FakeClient):
            def fetch(self, dataset: str) -> bytes:
                body = super().fetch(dataset)
                if dataset == "tilsyn":
                    return body.replace(b"tilsynsobjektid", b"changed_field", 1)
                return body

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dist"
            with (
                patch.object(collect, "SmilefjesClient", return_value=ChangedSource()),
                patch.dict(
                    os.environ,
                    {"OUTPUT_DIR": str(output), "RUN_DATE": "2026-08-18", "RUN_ID": "bad"},
                ),
            ):
                with self.assertRaisesRegex(ValueError, "tilsyn.csv header"):
                    collect.main()

            self.assertEqual(list(output.glob("*")), [])

    def test_header_only_source_is_rejected_before_publication(self):
        class HeaderOnlySource(FakeClient):
            def fetch(self, dataset: str) -> bytes:
                body = super().fetch(dataset)
                if dataset == "vurderinger":
                    return body.splitlines()[0] + b"\n"
                return body

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dist"
            with (
                patch.object(collect, "SmilefjesClient", return_value=HeaderOnlySource()),
                patch.dict(
                    os.environ,
                    {"OUTPUT_DIR": str(output), "RUN_DATE": "2026-08-18", "RUN_ID": "empty"},
                ),
            ):
                with self.assertRaisesRegex(ValueError, "at least one data row"):
                    collect.main()

            self.assertEqual(list(output.glob("*")), [])

    def test_truncated_source_row_is_rejected_before_publication(self):
        class TruncatedSource(FakeClient):
            def fetch(self, dataset: str) -> bytes:
                body = super().fetch(dataset)
                if dataset == "vurderinger":
                    return body.splitlines()[0] + b"\n101\n"
                return body

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dist"
            with (
                patch.object(collect, "SmilefjesClient", return_value=TruncatedSource()),
                patch.dict(
                    os.environ,
                    {"OUTPUT_DIR": str(output), "RUN_DATE": "2026-08-18", "RUN_ID": "short"},
                ),
            ):
                with self.assertRaisesRegex(ValueError, "column count"):
                    collect.main()

            self.assertEqual(list(output.glob("*")), [])

    def test_workflow_uses_the_opaque_pair_contract_and_role_labels(self):
        workflow = (
            Path(__file__).parents[1] / ".github" / "workflows" / "collect-smilefjes.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("python -m file_pair_handoff verify-local", workflow)
        self.assertIn('"$data_asset#data"', workflow)
        self.assertIn('"$metadata_asset#metadata"', workflow)
        self.assertIn("python -m file_pair_handoff verify-draft-release", workflow)
        self.assertNotIn("metadata = json.loads", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("github.event.repository.default_branch", workflow)
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", workflow)
        self.assertIn("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", workflow)

    def test_tracked_dockerfile_installs_the_local_package_after_copying_it(self):
        dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")

        package_copy = dockerfile.index("COPY handoff-package/ ./handoff-package/")
        requirements_install = dockerfile.index("RUN pip install --no-cache-dir -r requirements.txt")
        self.assertLess(package_copy, requirements_install)


if __name__ == "__main__":
    unittest.main()
