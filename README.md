# smilefjes-collector

Daily fetch of Mattilsynet smilefjestilsyn CSV dumps to GCS.

## Source

- `https://matnyttig.mattilsynet.no/smilefjes/tilsyn.csv` — one row per
  tilsyn (inspection), cumulative from 2015-03-30.
- `https://matnyttig.mattilsynet.no/smilefjes/vurderinger.csv` — one
  row per `(tilsyn, kravpunkt)`, cumulative. Contains ~2% ghost
  tilsynids (invalidated tilsyn removed from `tilsyn.csv` but left in
  `vurderinger.csv`). The parser treats `tilsyn.csv` as authoritative.

No authentication. CC BY 4.0. UTF-8 with BOM, semicolon-delimited,
dates in `ddmmyyyy` format.

## Output

```
gs://sondre_brreg_data/smilefjes/raw/tilsyn/{YYYY-MM-DD}.csv.gz
gs://sondre_brreg_data/smilefjes/raw/vurderinger/{YYYY-MM-DD}.csv.gz
```

Every fetch is the full cumulative dump. The parser performs CDC
against prior state to detect `new`, `modified`, and `disappeared`
(invalidated) tilsyn.

## Deployment

- Cloud Run Job: `smilefjes-collector`, `europe-north1`.
- Schedule: `30 5 * * *` Europe/Oslo (before BRREG downloads at 06:30).
- Image: `europe-north1-docker.pkg.dev/sondreskarsten-d7d14/brreg-pipelines/smilefjes-collector:latest`.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `GCS_BUCKET` | `sondre_brreg_data` | Target bucket. Empty = local. |
| `GCS_PREFIX` | `smilefjes` | Path prefix. |
| `RUN_DATE` | today Europe/Oslo | Override output date. |

## Local run

```bash
GCS_BUCKET="" python collect.py
```
