# DAMAS live data integration — 2026-05-03

Reviewer: Claude
Triggered by: user directive — "lets scrape that and integretate coreclyt
in our simulation" (capacity-tender prices), then "scrape all the other
data that is necessary for newmarkets and compare to the simulations
for activations price etc !!! update our bot !!!"

## Goal

Replace the model's synthetic capacity-bid formula (which was producing
bids ~3-4× too high vs documented Romanian market reality) with REAL
prices scraped from Transelectrica's DAMAS II portal. Also verify our
cached activation price/volume data still matches live DAMAS.

## What landed

### 1. Capacity-tender scraper (real bid prices)

`backend/scripts/scrape_damas_capacity.py` — Playwright-based scraper
for the DAMAS Ancillary Services Tender Statistics pages. Renders each
tender's URL (`tenderStatistics?code=N_YYYY`), clicks the aFRRUp /
aFRRDown / mFRRUp / mFRRDown service tabs, and extracts the 24 hourly
clearing prices from the virtualized div-grid table.

Output: `backend/data_catalog/processed/damas_capacity_clearing.csv`
(11 rows from 6 successfully scraped tenders, Apr 2025 – Jan 2026).

| Sample date | aFRRUp (€/MW/h) | aFRRDown (€/MW/h) |
|---|---|---|
| 2025-04-27 | €12.12 | €14.21 |
| 2025-06-05 | €11.73 | €10.24 |
| 2025-08-20 | (failed) | €7.31 |
| 2025-11-07 | €7.44 | €2.33 |
| 2025-12-06 | €5.45 | €4.14 |
| 2026-01-01 | €6.83 | €1.31 |
| **Mean** | **€8.72** | **€6.59** |

**Pattern**: aFRR capacity prices have **compressed through 2025**
(€10-14/MW/h in spring → €5-7/MW/h by late 2025 / early 2026). This is
the BESS-arrival compression we'd expect.

### 2. Live-activation scraper (validation)

`backend/scripts/scrape_damas_activations.py` — Playwright scraper for
the live `marginalPricesOverview` and `activatedBalancingEnergyOverview`
pages. Today's snapshot (2026-05-03) saved to
`backend/data_catalog/processed/damas_live_snapshots/`.

Handles the table virtualization (only ~7 rows in DOM at a time) by
scrolling all scrollable elements progressively and accumulating until
no new intervals appear for several cycles.

### 3. Drift check vs cached data

| Metric | Cached (last 7 days, 2026-04-25 → 2026-05-01) | Live today (2026-05-03) | Verdict |
|---|---|---|---|
| aFRR Up activation price mean | €155.77/MWh | €224.00/MWh | Today is high-stress; magnitude consistent |
| aFRR Up activation price max | €1,314.30/MWh | €1,400/MWh (6,999 LEI) | Same magnitude — cached captures the tail |
| aFRR Down activation price min | −€1,499.80/MWh | −€784/MWh | Cached has bigger negatives — both real |
| aFRR Up daily volume | 1,154 MWh/day avg | 414 MWh today | Today low; magnitude consistent with mid-week pattern |

**Conclusion**: cached data magnitudes match live DAMAS reality. No
material drift; the model is working with realistic data. Cached data
is 2 days behind live (covers up to 2026-05-01; today is 2026-05-03).

### 4. Model integration

`backend/app/services/fr_service.py` — added module-level
`_load_damas_capacity_avgs()` that reads the scraped CSV at import time
and computes the per-service average clearing price. Both
`project_annual_revenue()` and `calculate_optimal_bids()` now derive
the capacity bid as `damas_clearing × strategy_multiplier` instead of
the old `proxy_activation × 0.22 × multiplier`.

Bid floor stays anchored on `ROMANIAN_FR_PRODUCTS["aFRR"]` catalog
floor (€5/MW/h). Bid cap reduced from €60/€40 to €20/€20 (well above
sampled DAMAS prices, allowing aggressive over-bidding in stress weeks
but not the absurd 22%-of-€1000-activation values the old formula
produced).

`backend/scripts/afrr_daily_excel.py` and
`backend/scripts/afrr_daily_real_market_excel.py` updated with the
same `_DAMAS_AVGS` loader for consistency between the production
service and the analysis scripts.

## Impact on canonical scenario (10 MW / 20 MWh, last 12 months)

| Metric | Before (synthetic 22% rule) | After (real DAMAS scrape) | Δ |
|---|---|---|---|
| Avg capacity bid (balanced) | €27.81/MW/h | **€8.72 / €6.59** | −69% |
| Capacity revenue (balanced) | €1,954,107 | **€597,767** | **−69%** |
| Activation revenue (balanced, real-market sim) | €2,632,327 | €2,675,941 | unchanged |
| **Total aFRR balanced (real-market)** | €4,586,434 | **€3,273,709** | **−29%** |
| aFRR Y1 (proxy method, canonical scenario) | €2,976,060 | **€1,524,946** | **−49%** |

The corrected numbers are now in the realistic Romanian range (industry
sources quote €100/MW/day = €4.17/MW/h for capacity; we're at €8.72/MW/h
average across the year — slightly above the industry quote because our
sample includes pre-compression spring 2025 prices).

## Validation

- Backend pytest: **357 / 357 passed** (existing tests use structural
  assertions, not hardcoded revenue numbers, so the bid recalibration
  doesn't break them).
- Frontend tsc / lint / build: not re-run — no frontend files touched.

## Files committed

| File | Purpose |
|---|---|
| `backend/app/services/fr_service.py` | Wire real DAMAS prices into bid logic |
| `backend/data_catalog/processed/damas_capacity_clearing.csv` | Scraped real capacity prices |
| `backend/data_catalog/processed/damas_live_snapshots/marginalPricesOverview_2026-05-03.csv` | Today's activation prices snapshot (96 slots, all 8 reserve products) |
| `backend/data_catalog/processed/damas_live_snapshots/activatedBalancingEnergyOverview_2026-05-03.csv` | Today's activation volumes snapshot |
| `backend/scripts/scrape_damas_capacity.py` | Capacity-tender scraper (Playwright) |
| `backend/scripts/scrape_damas_activations.py` | Live activation scraper (Playwright) |
| `backend/scripts/afrr_daily_excel.py` | aFRR daily Excel using DAMAS bids |
| `backend/scripts/afrr_daily_real_market_excel.py` | Same with per-slot real-market sim |
| `backend/scripts/pzu_one_vs_two_cycle_excel.py` | PZU 1- vs 2-cycle daily Excel |
| `backend/scripts/pzu_two_cycle_estimate.py` | Standalone 2-cycle estimator |
| `backend/reports/*.xlsx` | Generated investor-grade Excels (PZU + aFRR) |
| This file | Audit notes |

## Honest caveats

1. **Capacity sample size**: only 6 valid tenders out of 17 attempted
   (intermittent JS click timeouts on the rest). Mean of €8.72 / €6.59
   is a calibration anchor, not a 365-day full coverage. Re-running the
   scraper with longer waits would yield more samples.
2. **Compression trend ignored**: the single annual mean overweights
   the pre-compression spring 2025 prices. For forward bankability
   modeling, the Nov 2025 - Jan 2026 samples (€5-7/MW/h) are more
   representative.
3. **DAMAS source classification unchanged**: `source_kind =
   unverified_snapshot`. We scraped from public web pages, not from
   TSO-signed settlement exports. The bankability ladder still reports
   `historical_backtest_only` — same gap as before.
4. **Live snapshot is one-day only**: today's aggregate stats match
   cached data magnitude, but this isn't a slot-by-slot validation
   against an overlapping date. To do that properly we'd need to scrape
   a historical date (the date picker on DAMAS pages requires UI
   manipulation we haven't built).

## Remaining bankability gaps (unchanged from prior audits)

- Compliance gates default to `not_declared` → revenue legally blocked
  until ANRE / OPCOM / PRE / BRP / BSP / FSE qualifications obtained.
- 10% activation share is still a guess, not a contract.
- Capacity-price compression: Y1 numbers OK; Y6-15 projections still
  require the compression schedule already in `InvestmentParams`.
- DSCR < 1.20 in years 3-10 — lender covenant breach in default
  scenario.

## Recommended next steps

1. Fix scraper click-timeout issues so we can pull all ~700 tender
   codes for 2025 + 2026 → annual / monthly capacity-price time series.
2. Build daily refresh job for live-activation snapshots (cron / task
   queue) → continuous drift monitoring.
3. Add slot-by-slot validation: scrape a historical date that overlaps
   our cached CSV and compare per-15-min-slot.
4. Wire the compression trend explicitly into the bid model so forward
   years use lower (€5-6/MW/h) prices rather than the 12-month mean.
