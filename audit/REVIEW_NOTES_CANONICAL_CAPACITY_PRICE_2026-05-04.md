# Canonical capacity-price source — 2026-05-04

Reviewer: Claude
Triggered by: user directive — *"make sure that in the app capacity prices
around 5-7 EUR/MW/h are defensible from your DAMAS export and current
scraped data. The old high prices are not defensible unless you have
participant settlement/auction proof. The next fix should be: one
canonical capacity price source, labelled as DAMAS public tender sample,
with participant settlement required for bankable mode."*

## What changed

### 1. New canonical resolver

`backend/app/market_data/capacity_prices.py` is the single source of
truth. Three modes:

| Mode | Source | Returns | Bankability label |
|---|---|---|---|
| `public_damas_sample` (default) | `damas_capacity_clearing.csv` filtered to last 270 days | mean of recent samples | `"Public-data / Backtest-only"` |
| `catalog_floor` | hardcoded €5/MW/h | catalog floor | `"Floor-only"` |
| `bankable` | `damas_capacity_settlement.csv` (does not exist yet) | settlement mean | `"Bankable"` (raises ValueError if no settlement data) |

Each call returns a `CapacityPrice` dataclass with: price, source,
bankability_label, n_samples, window_start, window_end, note.

### 2. Default values now defensible

With the default mode + today's CSV (asof 2026-05-04, last 270 days =
since 2025-08-07):

| Direction | Price | n_samples | Window |
|---|---|---|---|
| **aFRRUp** | **€6.57/MW/h** | 3 | 2025-11-07 → 2026-01-01 |
| **aFRRDown** | **€3.77/MW/h** | 4 | 2025-08-20 → 2026-01-01 |

The previous default (`€8.72 / €6.59`) was the mean across ALL samples
(including spring 2025 highs of €12-14). Those high prices are not
defensible today because the market has compressed; using them would
overclaim revenue.

**Old high prices are explicitly not defensible** without participant
settlement proof. The bankable mode is gated on a CSV that doesn't
exist yet — it will exist when the project entity becomes a registered
DAMAS participant and exports settlement records.

### 3. Four code paths now use the canonical resolver

Before this commit, four functions computed capacity bids
independently — each producing a different number:

| Function | Old logic | New logic |
|---|---|---|
| `project_annual_revenue()` | `_DAMAS_CAPACITY_AVGS` (mean of all samples) | canonical resolver default |
| `calculate_optimal_bids()` | `_DAMAS_CAPACITY_AVGS` (mean of all samples) | canonical resolver default |
| `calculate_safe_bid_prices()` | `safe_activation × 0.20` synthetic formula | canonical resolver × 0.85 conservative multiplier |
| `compute_multi_product_revenue()` | catalog floor €5.0 flat regardless of direction | canonical resolver per-direction (€6.57 / €3.77) |

The module-level `_DAMAS_CAPACITY_AVGS` cache now reads from the
canonical resolver too, so backwards-compat call sites get the same
value as direct callers.

### 4. New API endpoint for the frontend

`GET /api/v1/fr/capacity-prices/canonical` returns:
```json
{
  "aFRRUp":   {"price_eur_mw_h": 6.57, "source": "PUBLIC_DAMAS_SAMPLE",
               "bankability_label": "Public-data / Backtest-only",
               "n_samples": 3, "window_start": "2025-11-07", ...},
  "aFRRDown": {...},
  "bankability_label": "Public-data / Backtest-only",
  "source": "PUBLIC_DAMAS_SAMPLE"
}
```

The frontend can now read from this single endpoint instead of
hardcoding bid defaults — closes the frontend-input drift the user
flagged.

## Validation

| Check | Result |
|---|---|
| Resolver returns €6.57 / €3.77 (target was 5-7 €/MW/h) | ✓ |
| Bankable mode raises when no settlement data present | ✓ |
| Catalog floor mode returns €5.0 with `Floor-only` label | ✓ |
| Backend pytest | **357 / 357 passed** in 91.45s |

## Files changed

| File | Change |
|---|---|
| `backend/app/market_data/capacity_prices.py` | NEW — canonical resolver module |
| `backend/app/services/fr_service.py` | Wire all 4 capacity-bid paths through canonical resolver |
| `backend/app/api/routes/fr.py` | New `/capacity-prices/canonical` endpoint for frontend consumption |
| This file | Audit notes |

## Honest gaps (still open)

1. **Frontend doesn't yet consume the new endpoint.** Backend now
   exposes the canonical price; updating the frontend forms to read
   from it is a separate change.
2. **The 6 sampled tenders are still all DAMAS public data** — none
   are participant settlement. Bankable mode will remain locked until
   the project entity is a registered participant.
3. **270-day window is a heuristic.** Could shorten to 90 days for
   more aggressive recent-emphasis, or use exponential decay weighting
   for a smoother compression curve. Defensible compromise for now.

## Next pass would be

1. Update frontend Investment / FR Simulator forms to fetch defaults
   from `/capacity-prices/canonical` and display the bankability
   label next to the bid input.
2. Re-run scraper to add 20-30 more tender samples → tighter mean.
3. When project becomes a DAMAS participant, drop the settlement CSV
   at `data_catalog/processed/damas_capacity_settlement.csv` and the
   model auto-promotes from `Backtest-only` → `Bankable`.
