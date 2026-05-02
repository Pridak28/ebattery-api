# Battery Analytics Pro Market Data Pipeline Implementation Log

Date: 2026-05-01

## What Was Implemented

- Added a backend market-data package under `backend/app/market_data/`:
  - `schemas.py` for source-kind, bankability, and schema constants.
  - `manifest.py` for hashes, row counts, delivery-date bounds, manifest upserts, and audit events.
  - `quality.py` for PZU resolution normalization, DAMAS cleaning, freshness checks, duplicate checks, DST-aware slot-count checks, negative activation-volume checks, price-outlier quarantine, and bankable-source enforcement.
  - `pipeline.py` for the command-line refresh/validation pipeline.
  - `sources/opcom_pzu.py`, `sources/transelectrica_public.py`, and `sources/damas_import.py` for public/seed/manual data adapters and the participant-DAMAS placeholder.
- Added public OPCOM PZU and Transelectrica DAMAS II/public imbalance adapters.
- Added a manual DAMAS import adapter and a participant-DAMAS adapter that refuses to run until a participant or settlement export is supplied.
- Added a deploy-safe catalog under `backend/data_catalog/`:
  - `raw/` for immutable source snapshots.
  - `processed/` for simulator-ready CSVs.
  - `audit/` for validation reports, duplicate files, outlier quarantines, and run logs.
  - `manifest.json` for provenance, hashes, delivery dates, source kinds, confidence labels, and bankability level.
- Generated `DATA_PIPELINE_MANIFEST.md` from the manifest so source status is visible outside JSON.
- Changed backend default `DATA_DIR` resolution to prefer `backend/data_catalog/processed`, then `backend/data 2`, then the old `backend/data` symlink.
- Added `/api/v1/data/status` and `/api/v1/data/manifest`.
- Added source metadata to FR simulation and FR/PZU stats: `source_kind`, `data_date_max`, `bankability_level`, settlement-grade status, and warnings.
- Updated the FR frontend so it shows source kind and bankability level instead of implying the data is simply live/bankable DAMAS data.
- Added a daily GitHub Actions workflow at `.github/workflows/refresh-market-data.yml`.
- Made `DEBUG=release`, `DEBUG=prod`, and `DEBUG=production` parse as production false, because the local environment used `DEBUG=release` and the backend could not even import settings before this fix.
- Fixed `backend/requirements.txt` formatting so `requests` and `tenacity` install correctly in GitHub Actions.
- Aligned the existing PZU efficiency regression test with the current SOC-aware helper defaults by declaring the idealized full-cycle SOC window explicitly.

## Generated Artifacts

- `backend/data_catalog/processed/pzu_history_3y.csv`
- `backend/data_catalog/processed/damas_clean.csv`
- `backend/data_catalog/audit/opcom_pzu_validation.json`
- `backend/data_catalog/audit/damas_clean_validation.json`
- `backend/data_catalog/audit/damas_clean_price_outliers.csv`
- `backend/data_catalog/audit/damas_duplicates.csv`
- `backend/data_catalog/audit/market_data_refresh.jsonl`
- `backend/data_catalog/manifest.json`
- `DATA_PIPELINE_MANIFEST.md`

## Current Dataset Status

- `opcom_pzu`: `source_kind=public_observed_system`, `bankability_level=scenario_public_market_only`, 32,809 rows, max delivery date `2025-12-03`, mixed 15/60-minute resolution flagged.
- `damas_clean`: `source_kind=unverified_snapshot`, `bankability_level=historical_backtest_only`, 61,248 rows, max delivery date `2025-10-03`, 74 high-price outlier rows quarantined.

## Important Safety Behavior

- `fr_data_clean.csv` is classified as `derived_public` even if it has `afrr_*` columns.
- The cleaned DAMAS file from the current repo is classified as `unverified_snapshot`, not settlement-grade.
- Bankable mode requires `participant_export` or `settlement_export`.
- Public Transelectrica/DAMAS data is scenario/calibration data, not project-specific settlement proof.
- Stale public data can remain usable for historical backtests but must not be presented as operational/current without a fresh run.

## Verification Run

Run from `backend/`:

```bash
python3 -m app.market_data.pipeline --sources seed-pzu,seed-damas --skip-network --as-of 2026-05-01
python3 -m pytest
```

Result: pipeline refreshed `backend/data_catalog/manifest.json`; backend tests passed `15 passed, 1 warning`.

Run from `frontend/`:

```bash
npm run build
```

Result: Next.js production build passed. `npm run lint` is not a reliable assertion yet because the repo does not have ESLint configured and Next prompts interactively to create a config.

## Not Implemented Yet

- Live participant DAMAS settlement import.
- ENTSO-E reconciliation with token-backed source mapping.
- Automatic Netlify/Render deployment changes.
- Full frontend display of the new `/api/v1/data/manifest` table.
- A complete bankable mode that blocks every investor output unless settlement/participant data is supplied.
