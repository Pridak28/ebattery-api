# battery-analytics-pro

## What is this

A Romanian Battery Energy Storage System (BESS) analytics platform for evaluating
investment cases against the live Romanian power markets. Models four revenue
and cost streams together:

- **PZU** — Day-ahead arbitrage on the OPCOM spot market.
- **aFRR** — Frequency restoration reserve (Transelectrica DAMAS), pay-as-bid
  since ANRE Order 60/2024 (effective 2024-10-01).
- **Investment** — Project economics (CAPEX, OPEX, debt service, IRR/NPV/DSCR,
  payback, sensitivities).
- **Law 123 tariff exemption** — Storage transmission/distribution tariff
  exemption per ANRE Order 56/2025.

Stack: **FastAPI** (Python 3.11) backend, **Next.js 14 / React** frontend.

## Quick start

```bash
# Clone
git clone <repo-url> battery-analytics-pro
cd battery-analytics-pro

# Backend (port 8000)
cd backend
python -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn app.main:app --reload

# Frontend (port 3000) — in a second terminal
cd frontend
npm install
npm run dev
```

API docs: <http://localhost:8000/docs>
Frontend: <http://localhost:3000>

## Architecture

### Backend (`backend/app/`)

| Module                          | Responsibility                                                       |
| ------------------------------- | -------------------------------------------------------------------- |
| `services/pzu_service.py`       | PZU arbitrage backtests against historical OPCOM prices.             |
| `services/fr_service.py`        | aFRR scenario engine (capacity + activation, regime-aware).          |
| `services/investment_service.py`| Cashflow, IRR/NPV/DSCR, sensitivities, investor summary.             |
| `services/tariff_exemption.py`  | Law 123 / Order 56/2025 transmission tariff savings model.           |
| `services/sensitivity.py`       | Tornado / Monte Carlo sensitivity helpers.                           |
| `services/warranty_tracker.py`  | Cycle / SoH degradation tracker.                                     |
| `core/compliance_gates.py`      | ComplianceGates (settlement-grade vs scenario gating).               |
| `core/regime.py`                | Market regime tagging (pay-as-bid vs marginal pricing eras).         |

### Frontend (`frontend/app/`)

| Route                | Page                                                                 |
| -------------------- | -------------------------------------------------------------------- |
| `/`                  | Landing dashboard with live market snapshot.                          |
| `/pzu`               | PZU backtest configurator + results.                                  |
| `/fr-simulator`      | aFRR scenario builder (capacity, activation, regime breakdown).       |
| `/investment`        | Full project model — CAPEX, financing, IRR, sensitivities.            |
| `/methodology`       | Methodology + regulatory citations.                                   |
| `/investor-summary`  | Printable A4 investor quick-look.                                     |

## Data sources

| Source                       | Coverage                  | Rows  | Bankability label                   |
| ---------------------------- | ------------------------- | ----- | ----------------------------------- |
| OPCOM PZU (day-ahead)        | 2022-09 → 2026-05         | ~31k  | `unverified_snapshot`               |
| Transelectrica DAMAS aFRR    | 2024-01 → 2026-05         | ~81k  | `unverified_snapshot`               |

All datasets are tagged `unverified_snapshot` per the data audit. Downstream
results carry one of:

- `historical_backtest_only` — for any model run on historical snapshots.
- `scenario_public_market_only` — for forward scenarios using public price
  surfaces.

Settlement-grade outputs require `settlement_grade=true` on the underlying
dataset, which today's snapshots do not have.

## Tests + coverage

- **340** backend pytest tests, **93%+** coverage.
- Property-based tests via **Hypothesis** for invariants (charge/discharge
  energy balance, cashflow sign rules, IRR bounds).
- End-to-end API tests using **FastAPI TestClient** for every router.
- Frontend: `tsc --noEmit` and `eslint` clean.

Run:

```bash
cd backend && ./venv/bin/pytest
cd frontend && npm run lint && npx tsc --noEmit
```

## Regulatory references

- **ANRE Order 60/2024** — Pay-as-bid clearing for aFRR, effective 2024-10-01.
- **ANRE Order 56/2025** — Storage transmission/distribution tariff exemption.
- **MARI** — European mFRR platform, Romanian go-live anchored to 2026-04-01.
- **PICASSO** — European aFRR platform; Romanian accession pending; modeled as
  a compression cliff once integrated.

See:

- `audit/BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT_2026-05-01.md`
- `audit/BATTERY_ANALYTICS_PRO_MARKET_DATA_PIPELINE_IMPLEMENTATION_2026-05-01.md`
- `/methodology` route in the running app.

## Investor summary

The `/investor-summary` route renders a print-ready A4 one-pager with the
headline economics for a configured project (IRR, NPV, DSCR, payback, revenue
mix). It is backed by the API endpoint:

```
POST /api/v1/investment/investor-summary
```

which returns a structured payload (KPIs + revenue stack + bankability gates)
suitable for both the printable view and external consumers.

## Disclaimer

This tool is **not** bankable settlement proof unless the underlying datasets
carry `settlement_grade=true`. All historical results are
`historical_backtest_only`; all forward scenarios are
`scenario_public_market_only`.

This tool is **not** legal or investment advice. Regulatory citations
(ANRE Orders, MARI, PICASSO timelines) are pointers — confirm against the
official ANRE / Transelectrica publications before relying on them.
