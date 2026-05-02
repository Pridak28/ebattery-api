# Battery Analytics Pro Data Pipeline Manifest

Generated from `backend/data_catalog/manifest.json`.

This catalog separates public/system data from participant settlement exports. Bankable simulations require `source_kind=participant_export` or `source_kind=settlement_export`.

| Dataset | Source kind | Bankability | Rows | Max delivery date | Artifact | Confidence |
|---|---|---|---:|---|---|---|
| damas_clean | unverified_snapshot | historical_backtest_only | 81408 | 2026-05-01 | `backend/data_catalog/processed/damas_clean.csv` | unverified_snapshot_not_settlement_proof |
| opcom_pzu | public_observed_system | scenario_public_market_only | 31772 | 2026-05-01 | `backend/data_catalog/processed/pzu_history_3y.csv` | public_market_report |

## Source-Kind Rules

- `public_estimated`, `public_observed_system`, `public_aggregate`, and `derived_public`: scenario/calibration only.
- `unverified_snapshot`: historical backtest only until source/export proof is attached.
- `participant_export` and `settlement_export`: eligible for bankable mode after validation.
- `fr_data_clean.csv` is treated as `derived_public` even when it has aFRR-like columns.
