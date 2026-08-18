# smilefjes-collector

Daily byte-preserving capture of Mattilsynet's public Smilefjes CSV snapshots.
This repository owns source retrieval, source-specific validation, packaging,
metadata, and publication. It does not parse the data or configure any
downstream platform.

## Source

- `https://matnyttig.mattilsynet.no/smilefjes/tilsyn.csv`
- `https://matnyttig.mattilsynet.no/smilefjes/vurderinger.csv`

The files are cumulative snapshots, published as UTF-8 semicolon-delimited
CSV. The publisher data is licensed under CC BY 4.0. Collection preserves the
response bytes exactly; decoding is used only for validation and metadata.

## Handoff

Every successful run publishes one GitHub Release with exactly two assets:

```text
smilefjes-<date>-run-<run-id>.tar.gz
smilefjes-<date>-run-<run-id>.metadata.json
```

The data archive contains byte-exact `tilsyn.csv` and `vurderinger.csv`.
The separate metadata file binds the archive by filename, byte count, and
SHA-256 and records each source file's URL, size, digest, header, and row
count. It also records Smilefjes-specific orphan-`tilsynid` diagnostics.

The archive is deterministic for identical source bytes. The workflow creates
a draft release, labels the assets `data` and `metadata`, and publishes only
after the transport package has verified the exact two local and uploaded
files. An incomplete run remains a draft.

This two-file pair is the complete boundary. A consumer may verify and copy
the pair as opaque files; parsing, CDC, state, and downstream readiness
contracts are intentionally out of scope.

## Handoff package

`handoff-package/` is the canonical source for `file-pair-handoff` 0.1.0
(`file-pair-handoff/v1`). It owns only transport mechanics: two role-labelled
files, bounded GitHub asset download, optional GitHub digest verification, and
create-only byte-verified S3 storage. It never decodes data or metadata.

For now this repository installs the package from `-e ./handoff-package`. The
Lambda deploy unit carries a manual, byte-identical copy under `local_lib/`.
The current public GitHub runner keeps using the local package. A later move of
the producer to DNB GHE, update of the Lambda's fixed repository coordinates,
and publication to Nexus can let both builds use one pinned package version
without changing imports. Those migration steps are not part of this change.
Source-specific request, archive, and metadata rules remain here.

## Runner

`.github/workflows/collect-smilefjes.yml` is the producer-side workflow. It
runs daily at 04:30 UTC and can be started manually. It uses the
repository-scoped GitHub token only to publish the release; the public source
needs no credential. This workflow is not an IPA Code Job.

## Local verification

```bash
python -m pip install --requirement requirements.txt
python -m unittest discover -s tests -v
OUTPUT_DIR=dist RUN_DATE=2026-08-18 RUN_ID=local SOURCE_COMMIT=local python collect.py
```

The optional environment variables are:

| Variable | Default | Meaning |
|---|---|---|
| `OUTPUT_DIR` | `dist` | Directory for the two deliverables |
| `RUN_DATE` | current UTC date | Capture identity date |
| `RUN_ID` | `local` | Immutable runner identity |
| `SOURCE_COMMIT` | `unknown` | Collector revision recorded in metadata |
| `RETRIEVED_AT_UTC` | current UTC time | Retrieval timestamp override |
