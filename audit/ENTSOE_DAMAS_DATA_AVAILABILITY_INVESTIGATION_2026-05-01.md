# ENTSO-E / DAMAS Data Availability Investigation

Date: 2026-05-01
Project: Battery Analytics Pro

## Executive Verdict

We can legally build a much better Romanian BESS public-data model from ENTSO-E, Transelectrica/DAMAS public routes, and OPCOM. We cannot make it bankable from those public sources alone.

Bankable settlement still requires one of these evidence types:

- participant DAMAS/FSE export,
- BRP/PRE imbalance and settlement export,
- OPCOM participant settlement export,
- or a signed route-to-market / tolling / revenue-floor contract from a credible counterparty.

The ENTSO-E URL previously provided uses `10Y1001C--00003F`, which ENTSO-E identifies as Ukraine. Romania must use `10YRO-TEL------P`.

## Official Source Anchors

| Topic | Official Source | What It Proves |
|---|---|---|
| ENTSO-E API endpoint | https://transparencyplatform.zendesk.com/hc/en-us/articles/15696677194644-Request-Endpoint | Production API endpoint is `https://web-api.tp.entsoe.eu/api`; HTTPS only. |
| ENTSO-E token | https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token | Security token is required; registration and email request for RESTful API access are needed. |
| ENTSO-E EIC area codes | https://transparencyplatform.zendesk.com/hc/en-us/articles/15885757676308-Area-List-with-Energy-Identification-Code-EIC | `10YRO-TEL------P` is Romania; `10Y1001C--00003F` is Ukraine. |
| ENTSO-E document types | https://transparencyplatform.zendesk.com/hc/en-us/articles/15857043092756-DocumentType | `A82` accepted offers, `A83` activated balancing quantities, `A84` activated balancing prices, `A85` imbalance prices, `A86` imbalance volume, `A87` financial situation, `A89` contracted reserve prices. |
| ENTSO-E balancing API parameters | https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide_prod_backup_06_11_2024.html | Balancing endpoints generally use `ControlArea_Domain` and a time interval; several endpoints have one-year query range limits. |
| Transelectrica transparency | https://www.transelectrica.ro/ro/web/tel/echilibrare-si-sts | Public balancing sections reference ENTSO-E, daily reports, and say some data is available in public DAMAS II from `2024-07-01`. |
| Transelectrica DAMAS access | https://www.transelectrica.ro/ro/web/tel/piata-de-echilibrare | Lists DAMAS guides, Webservice documentation, and access information for the new platform. |
| OPCOM DAM/IDM access and settlement context | https://www.opcom.ro/tranzactii-produse/en/46 | DAM/IDM registration, BRP requirement, settlement platform notes, procedures, and public reports context. |

## Source Matrix

| Source | Data We Can Get | Confirmed / Discoverable Date Range | Access Route | Public or Participant | Bankable? | Use in App |
|---|---|---:|---|---|---|---|
| ENTSO-E `A85` | Imbalance prices | Exact range requires API token discovery; official docs allow time interval query and one-year chunks. | `https://web-api.tp.entsoe.eu/api?documentType=A85&ControlArea_Domain=10YRO-TEL------P&periodStart=YYYYMMDDHHMM&periodEnd=YYYYMMDDHHMM&securityToken=TOKEN` | Public API with free token | No | Reconcile Romanian imbalance prices; public proxy only. |
| ENTSO-E `A86` | Imbalance volumes | Exact range requires token discovery. | Same endpoint with `documentType=A86`. | Public API with free token | No | System imbalance proxy and PRE exposure scenario. |
| ENTSO-E `A83` | Activated balancing quantities | Exact range requires token discovery; official docs list one-year range limit. | Same endpoint with `documentType=A83`; may need `businessType`/`psrType` depending returned series. | Public API with free token | No | aFRR/mFRR volume calibration. |
| ENTSO-E `A84` | Activated balancing prices / aFRR CBMPs | Exact range requires token discovery; official docs list one-year range limit and `processType=A16` if not provided. | Same endpoint with `documentType=A84&processType=A16`. | Public API with free token | No | Public price calibration and DAMAS cross-check. |
| ENTSO-E `A82` | Accepted aggregated offers | Exact range requires token discovery; official docs list one-year range limit. | Same endpoint with `documentType=A82`; may need `businessType`/`psrType`. | Public API with free token | No | Acceptance/merit-order proxy; not project accepted bids. |
| ENTSO-E `A87` | Financial expenses and income for balancing | Exact range requires token discovery; minimum interval can be monthly. | Same endpoint with `documentType=A87`. | Public API with free token | No | Macro balancing-cost context. |
| ENTSO-E `A89` | Contracted reserve prices | Exact range requires token discovery; docs require market-agreement type for reserve-price endpoint. | `documentType=A89&type_MarketAgreement.Type=...&ControlArea_Domain=10YRO-TEL------P`. | Public API with free token | No | Reserve price benchmark if Romania publishes it. |
| Transelectrica public DAMAS II | Public balancing/DAMAS market reports, including public imbalance/price/volume routes where available. | Official public DAMAS II availability starts `2024-07-01` for listed public sections. Local route currently supports public estimated imbalance style data. | Public UI/API, including existing public JSON route in code: `publicReport/estimatedImbalancePrices`. | Public | No | Scenario calibration and current public-market refresh. |
| Transelectrica daily reports / Excel legacy | Daily balancing-market reports and older transparency files. | Official page references pre-DAMAS daily reports and Excel availability for some sections from `2021-02-01`; exact files must be separately catalogued. | Transelectrica public transparency links / archives. | Public | No | Historical backfill only; must be source-labelled. |
| OPCOM public DAM/PZU | Day-ahead market prices and reports. | Local current dataset: `2022-09-16` to `2025-12-03`; mixed 60/15-minute resolution flagged. | OPCOM public report route and website reports. | Public | No | PZU/DAM arbitrage scenario and market context. |
| OPCOM IDM public reports | Intraday market public results where published. | Not currently ingested. Exact range requires separate OPCOM endpoint discovery. | OPCOM public reports. | Public | No | Missing BESS revenue stream; useful for flexibility scenario. |
| Participant DAMAS/FSE | Accepted bids/offers, activation logs, capacity awards, settlement prices, penalties, availability. | Only the participant export period. | DAMAS account/Webservice/manual export. | Participant-only | Yes, if validated | Bankable FR/balancing revenue replay. |
| BRP/PRE settlement | Imbalance settlement, nominations, imbalance charges/credits. | Only settlement export period. | BRP/PRE portal/export/contracted counterparty. | Participant-only | Yes, if validated | Bankable imbalance exposure and avoided-cost model. |
| Route-to-market contract | Fixed/floor revenue, tolling, optimization fees, penalties, availability terms. | Contract tenor. | Signed contract from aggregator/trader/BSP/FSE. | Private contract | Yes, if enforceable | Bankable revenue assumption independent of public data. |

## Current Local Dataset Ranges

These are what Battery Analytics Pro currently has on disk, not proof of what the official sources can always provide.

| Local File | Rows | Date Range | Status |
|---|---:|---:|---|
| `backend/data_catalog/processed/pzu_history_3y.csv` | 32,809 | `2022-09-16` to `2025-12-03` | Public OPCOM PZU, scenario only, stale as of 2026-05-01, mixed 15/60-minute resolution. |
| `backend/data_catalog/processed/damas_clean.csv` | 61,248 | `2024-01-05` to `2025-10-03` | DAMAS-shaped, but `unverified_snapshot`; not settlement proof. |
| `backend/data 2/imbalance_history.csv` | 47,430 | `2024-06-01` to `2025-11-06` | Public/raw-style imbalance data; not participant settlement. |
| `backend/data 2/fr_data_clean.csv` | 47,430 | `2024-06-01` to `2025-11-06` | Derived public-like FR data; must not be treated as settlement. |
| `backend/data 2/system_imbalance_awards.csv` | 42,624 | `2024-06-01` to `2025-09-15` | Scenario/supporting data; source status needs proof. |
| `backend/data 2/fr_daily_history.csv` | 496 | `2024-06-01` to `2025-11-06` | Aggregated derived history. |
| `backend/data 2/fr_daily_predictions.csv` | 365 | `2025-11-07` to `2026-11-06` | Predictions, not observed market data. |
| `backend/data 2/damas_complete_fr_dataset.csv` | 61,276 | `2024-01-05` to `2025-10-03` | Raw source for cleaned DAMAS-shaped file; source URL/export route still unverified. |

## ENTSO-E Checks To Run When Token Exists

No `ENTSOE_API_KEY` was present in the local environment during this investigation, so authenticated ENTSO-E range discovery could not be run. Use Romania EIC `10YRO-TEL------P`; do not use `10Y1001C--00003F` for Romania.

First smoke test for imbalance prices:

```bash
curl "https://web-api.tp.entsoe.eu/api?documentType=A85&ControlArea_Domain=10YRO-TEL------P&periodStart=202601010000&periodEnd=202601080000&securityToken=$ENTSOE_API_KEY"
```

Repeat for:

```text
A82, A83, A84, A85, A86, A87, A89
```

Recommended discovery windows:

```text
2015-01-01 to 2015-12-31
2016-01-01 to 2016-12-31
...
2025-01-01 to 2025-12-31
2026-01-01 to 2026-05-01
```

For each successful response, record:

- first timestamp,
- last timestamp,
- resolution (`PT15M`, `PT30M`, `PT60M`, etc.),
- units,
- `businessType`, `psrType`, `processType`, direction, and market product if present,
- whether the response is XML or ZIP,
- whether additional parameters are required,
- whether empty periods mean no publication or wrong parameterization.

## Data We Still Cannot Get Publicly

Public data does not reveal project-specific settlement. These are still unavailable without participant/contract access:

- accepted bids/offers for the actual BESS,
- actual bid prices submitted by that participant,
- activation logs tied to that asset,
- capacity awards tied to that asset,
- non-performance penalties,
- availability/telemetry failures,
- BRP/PRE settlement notes,
- OPCOM participant settlement exports,
- collateral, fee, tax, and contractual settlement details.

## Required App Labels

Use these labels until real settlement evidence exists:

| Data | Required `source_kind` | Required Bankability |
|---|---|---|
| ENTSO-E public balancing data | `entsoe_public_system` or current equivalent `public_aggregate` | `scenario_public_market_only` |
| Transelectrica public DAMAS II data | `public_estimated` / `public_aggregate` | `scenario_public_market_only` |
| Local DAMAS-shaped unverified files | `unverified_snapshot` | `historical_backtest_only` |
| Participant DAMAS/FSE export | `participant_export` | `bankable_settlement` after validation |
| Settlement export | `settlement_export` | `bankable_settlement` after validation |
| Revenue-floor/tolling contract | `contract_backed` future label | Bankable only if legal/commercial review accepts terms |

## Implementation Recommendation After Report Review

1. Add a real ENTSO-E adapter using `ENTSOE_API_KEY`, chunked yearly/monthly requests, XML/ZIP parsing, and raw response hashing.
2. Add an ENTSO-E discovery command that produces a `data_catalog/audit/entsoe_availability_matrix.json` file.
3. Add processed datasets for `entsoe_imbalance_prices`, `entsoe_imbalance_volumes`, `entsoe_activated_balancing_quantities`, and `entsoe_activated_balancing_prices`.
4. Add a public-proxy estimator that combines ENTSO-E + Transelectrica + OPCOM but always labels results as non-bankable.
5. Keep bankable mode disabled unless `participant_export`, `settlement_export`, or contract-backed evidence is uploaded and validated.

## Bottom Line

We can get strong public system-level data from ENTSO-E, Transelectrica/DAMAS public routes, and OPCOM. We can discover exact ENTSO-E publication ranges as soon as a token is configured. None of those public routes provides bankable participant settlement by itself.
