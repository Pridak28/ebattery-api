# Real-scenario engine in production — 2026-05-04

Reviewer: Claude
Triggered by: user directive — "ok lets fix the app now to have the real
scenario !!" + "bro also update all the app and ebattery-analytics".

## What landed

A new production-grade scenario engine that mirrors the offline Excel
financial model (`scripts/bess_cashflow_scenarios_excel.py`). The same
4 PICASSO / market-share scenarios (A_current / B_picasso / C_mature /
D_bear) are now exposed via the backend API and rendered live on the
frontend Investment page.

### Backend additions

| File | Change |
|---|---|
| `backend/app/services/scenario_engine.py` | NEW — full PF cashflow engine: stacking + drag + tax (16% RO) + 8-yr depreciation + loan amortization + 15-yr horizon + DSCR/LLCR/PLCR/IRR/MIRR/NPV/MOIC/payback |
| `backend/app/api/routes/investment.py` | NEW endpoints: `POST /api/v1/investment/scenarios` (runs all 4 scenarios in BOTH modeled + realistic views) and `GET /api/v1/investment/scenarios/defaults` |

### Frontend additions

| File | Change |
|---|---|
| `frontend/lib/api.ts` | NEW client methods: `investmentApi.scenarios()` and `investmentApi.scenarioDefaults()` |
| `frontend/components/charts/ScenariosOverview.tsx` | NEW component — fetches `/scenarios` on mount, renders 4 cards: Modeled vs Realistic IRR + Y1 + payback + MOIC + DSCR/LLCR/PLCR + DSCR breach warning |
| `frontend/app/investment/page.tsx` | Drops `<ScenariosOverview />` below the existing `ScenarioComparator` section |

### Excel updates

| File | Change |
|---|---|
| `backend/scripts/bess_cashflow_scenarios_excel.py` | Same scenario logic now matches `scenario_engine.py` (was already there; this is the source of truth that the engine ports from) |

## Source of truth

`backend/app/services/scenario_engine.py:SCENARIO_DEFAULTS` is the
canonical scenario table. The Excel script and the API both consume it.
Updating Y1 base values, compression curves, or scenario descriptions
should be done in **one place** — in this file — and both the API and
the Excel will pick up the change.

## Sample API output (default inputs)

```
A_current   Modeled IRR  149.77%  Realistic IRR   33.31%  Y1 €1.07M  Min DSCR 1.11x
B_picasso   Modeled IRR  114.10%  Realistic IRR   22.47%  Y1 €0.89M  Min DSCR 1.06x
C_mature    Modeled IRR   92.08%  Realistic IRR    9.64%  Y1 €0.73M  Min DSCR 1.07x
D_bear      Modeled IRR   38.85%  Realistic IRR    0.00%  Y1 €0.46M  Min DSCR 0.66x
```

D_bear realistic IRR collapses to 0% with min DSCR 0.66x — proper
covenant breach scenario for lender stress testing.

## Validation

| Check | Result |
|---|---|
| Backend pytest | **357 / 357 passed** in 86.77s |
| Frontend `npx tsc --noEmit` | clean |
| Frontend `npm run lint` | ✔ no errors |
| Frontend `npm run build` | ✓ 9 static pages compiled |
| Backend smoke test | All 4 scenarios produce sensible IRR / DSCR / payback values |

## Honest gaps

1. **Frontend uses default inputs only.** The new `<ScenariosOverview />`
   call to `/scenarios` doesn't yet pass user-edited form values — it
   uses the canonical 10 MW / 20 MWh / €3.5M defaults baked into the
   API. If the user changes EPC or financing on the existing
   Investment form, the scenario card doesn't update. Wiring the
   form state into the scenarios POST is a follow-up.
2. **Existing `analyze()` endpoint unchanged.** It still treats FR vs
   PZU as alternatives and recommends one. The new `/scenarios`
   endpoint is additive — both coexist. Eventually the `analyze()`
   endpoint should also use the stacking logic, but that's a bigger
   migration.
3. **Realistic-view drag values are hard-coded.** The defaults
   (`drag_afrr_capacity=0.93`, `drag_afrr_activation=0.25`, `drag_pzu=0.80`)
   come from empirical operator data. The API accepts overrides via
   `ScenariosRequest`, but the frontend card doesn't expose sliders.
4. **Tax rate is hard-coded to 16% (Romanian).** Configurable via
   `ScenariosRequest.tax_rate` but no frontend control.

## Source labels (unchanged from prior audits)

- `bankability_label = "Public-data / Backtest-only"` — the
  scenario_engine output carries this label so the frontend always
  shows it in the amber badge. NOT bankable without participant
  settlement proof.
- DAMAS clearing prices come from the canonical resolver
  (`app/market_data/capacity_prices.py`) — same source of truth as
  the rest of the model.

## Next steps

1. Wire frontend Investment form inputs (power, capacity, EPC,
   financing) into the `/scenarios` POST so card updates with user
   edits.
2. Add a "View full cashflow" expansion that shows the year-by-year
   PF table per scenario (currently only headline KPIs visible).
3. Eventually migrate `investment_service.analyze()` to use the
   scenario engine's stacking + drag logic so the legacy `/analyze`
   endpoint matches the new `/scenarios` endpoint.
