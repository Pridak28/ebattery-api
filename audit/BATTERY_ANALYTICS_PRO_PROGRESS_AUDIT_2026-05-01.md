# Battery Analytics Pro Progress Audit

Date: 2026-05-01  
Target app: `/Users/seversilaghi/Documents/battery-analytics-pro`  
Audit type: documentation-only implementation/progress audit  
Scope: frontend, backend, data, deployment, market/ROI assumptions, and documentation quality  

This is not legal, tax, accounting, investment, or grid-connection advice. It is an engineering and business-model audit of what the app currently appears to implement and what could be wrong before it is used for investor, bankability, or production decisions.

## Executive Verdict

Battery Analytics Pro is a working BESS analytics demo with useful PZU, FR, and investment-analysis surfaces. It has a coherent split between a Next.js frontend and a FastAPI backend, and it already contains Romanian-market concepts such as PZU arbitrage, aFRR/mFRR simulation, investment scenarios, and deployment config for Netlify/Render.

It is not ready to be treated as a bankable revenue model or production-grade trading/settlement tool. The main risks are hardcoded financial assumptions, incomplete API contracts, a deploy-unsafe data path, public-market data being used like participant settlement evidence, overconfident UI wording, and missing automated tests.

Recommended status:

| Area | Current status | Reason |
| --- | --- | --- |
| Investor demo | Conditional | Useful interface, but must show risk labels and data provenance. |
| Internal research tool | Partially usable | Good starting structure, but core calculations need validation. |
| Bankability model | Not ready | Missing degradation, taxes, penalties, tariffs, participant settlement exports, and compliance gates. |
| Production API | Not ready | Data path, error handling, fallbacks, and endpoint drift need fixing. |
| Live market/trading system | Not implemented | No confirmed OPCOM/DAMAS participant integration or settlement parser. |

## System Map

| Layer | What exists | Evidence | Risk |
| --- | --- | --- | --- |
| Frontend | Next.js app with dashboard, PZU, FR simulator, investment pages | `frontend/app/page.tsx`, `frontend/app/pzu/page.tsx`, `frontend/app/fr-simulator/page.tsx`, `frontend/app/investment/page.tsx` | Several values are hardcoded or fallback-driven while displayed as live/projection outputs. |
| Frontend deploy | Netlify static export | `frontend/netlify.toml`, `frontend/next.config.js` | Netlify setup is consistent with `output: 'export'`, but stale `out 2` and `out 3` folders should not be treated as source evidence. |
| Backend | FastAPI app mounted under `/api/v1` | `backend/app/main.py` | Health endpoint reports data availability but not real external market connectivity. |
| Backend deploy | Render service `ebattery-api` | `backend/render.yaml` | Env config is minimal and does not pin deploy-safe data settings. |
| Data | CSV corpus for PZU, FR, imbalance, forecasts | `backend/data`, `backend/data 2` | `backend/data` is a symlink to another repo; `backend/data 2` contains files the app does not read by default. |
| Local compose | Backend and frontend compose services | `docker-compose.yml` | Mounts data from `../BOT BATTERY/data`, so it is not portable. |

## Six-Agent Findings

### Agent 1: Backend Model Correctness

What is good:

- The backend has separate services and routes for PZU, FR, and investment analysis.
- PZU simulation uses block averages instead of pure min/max prices, which is better than a naive spread model.
- FR logic attempts to share a monthly battery energy budget across enabled FR products.

What could be wrong:

| Severity | Finding | Evidence | Why it matters | Recommended change |
| --- | --- | --- | --- | --- |
| Critical | FR simulation ignores requested capacity and hardcodes a 30 MWh, 30-day monthly energy budget. | `backend/app/services/fr_service.py:230` | Non-30 MWh projects can show false revenue scaling. | Use `params.capacity_mwh`, real month day count, SOC limits, throughput limits, and degradation assumptions. |
| Critical | PZU arbitrage sorts daily prices and picks cheapest/highest blocks without chronological SOC constraints. | `backend/app/services/pzu_service.py:130` | It can imply discharging before charging and overstate realizable arbitrage. | Replace with chronological SOC-aware dispatch. |
| High | Investment service silently swallows PZU/FR errors and falls back to hardcoded estimates. | `backend/app/services/investment_service.py:75`, `backend/app/services/investment_service.py:132` | Broken data can still produce confident ROI outputs. | Return explicit warnings or fail closed when market-data simulations fail. |
| High | FR product allocation consumes the shared energy budget in dictionary order. | `backend/app/services/fr_service.py:239` | Revenue depends on arbitrary product order, not economic optimization or operational feasibility. | Add explicit stacking strategy and product-priority rules. |
| High | Investment cashflows are flat nominal values. | `backend/app/services/investment_service.py:177` | Missing degradation, augmentation, taxes, inflation, tariff/fee changes, penalties, curtailment, and downside scenarios. | Add assumption register and scenario-based cashflow engine. |
| Medium | PZU loader prefers `pzu_history.csv` before `pzu_history_3y.csv`. | `backend/app/services/pzu_service.py:43` | Newer or richer data may be ignored. | Make data source selection explicit and expose coverage dates. |
| Medium | FR loader prefers `damas_complete_fr_dataset.csv` with no schema/provenance validation. | `backend/app/services/fr_service.py:34` | Synthetic/estimated/public aggregate data can be treated as authoritative. | Add data manifest, validation, and source confidence labels. |
| Medium | FR outlier filtering drops absolute prices >= 500 EUR/MWh silently. | `backend/app/services/fr_service.py:74` | Scarcity prices may be valid and financially material. | Make filtering configurable and auditable. |

### Agent 2: Frontend/API Integration

What is good:

- The app exposes clear user-facing modules: dashboard, PZU, FR simulator, and investment analysis.
- There is a central API client in `frontend/lib/api.ts`.
- Static export is configured in `frontend/next.config.js`, matching Netlify's `publish = "out"`.

What could be wrong:

| Severity | Finding | Evidence | Why it matters | Recommended change |
| --- | --- | --- | --- | --- |
| Critical | FR page calls `/api/v1/fr/market-stats`, but backend exposes `/api/v1/fr/stats`. | `frontend/app/fr-simulator/page.tsx:86`, `backend/app/api/routes/fr.py:92` | Production request will 404 and fallback UI can hide it. | Rename frontend call to `/fr/stats` or add backend alias. |
| High | Typed API client is incomplete relative to page usage. | `frontend/lib/api.ts:12` | Direct page fetches bypass contract checking and allow endpoint drift. | Centralize all page API calls in `lib/api.ts`. |
| High | FR client request type omits fields the page sends. | `frontend/lib/api.ts:42`, `frontend/app/fr-simulator/page.tsx` | Future refactors can silently drop important economics inputs. | Align TypeScript request types with backend Pydantic models. |
| Medium | Dashboard labels hardcoded data as `LIVE`. | `frontend/app/page.tsx:20`, `frontend/app/page.tsx:81` | Users may believe static values are live market data. | Add visible `historical`, `simulated`, `fallback`, or `live API` labels. |
| Medium | Revenue cards show hardcoded annual projections. | `frontend/app/page.tsx:100`, `frontend/app/page.tsx:108` | Projections lack scenario, source, and confidence context. | Attach model version, source period, and risk label to every number. |
| Medium | Sidebar shows static `Live Data` and market status labels. | `frontend/components/layouts/Sidebar.tsx` | UI implies live connectivity that is not proven. | Bind status to API health and data freshness or remove live wording. |
| Low | Several API failures only log to console. | `frontend/app/pzu/page.tsx`, `frontend/app/fr-simulator/page.tsx` | Users can see empty/fallback visuals without knowing data failed. | Add visible error and fallback states. |

### Agent 3: Data Quality and Lineage

What is good:

- There is a substantial local CSV corpus covering PZU, FR/DAMAS-style data, imbalance data, and forecasts.
- The app is designed around historical Romanian market datasets instead of only toy inputs.

What could be wrong:

| Severity | Finding | Evidence | Why it matters | Recommended change |
| --- | --- | --- | --- | --- |
| Critical | Backend reads `backend/data`, which is a symlink to `/Users/seversilaghi/Documents/BOT BATTERY/data`. | `backend/app/config.py:24`, `backend/data` | Render or another machine will not have that local symlink target. | Replace symlink dependency with committed/deployed data package or explicit ingest pipeline. |
| High | `backend/data 2` contains many market CSVs, but the app does not read it by default. | `backend/data 2` | The audited corpus may differ from the runtime corpus. | Pick one canonical data directory and document it. |
| High | Data corpus mixes actual, estimated, filtered, backup, and predicted files without a manifest. | `backend/data 2/*.csv` | Users cannot tell observed data from generated assumptions. | Add `data_manifest.md` or CSV metadata with source, period, granularity, and confidence. |
| High | `bm_forecast.csv` is empty. | `backend/data 2/bm_forecast.csv` | Forecast capability may be implied but absent. | Mark balancing forecast as missing or implement it with sourced data. |
| High | Public FR/DAMAS totals are used through a participant-share assumption. | `backend/app/services/fr_service.py:110` | Public aggregate market data is not proof of project-specific settlement. | Require participant settlement exports or label as market-share scenario. |
| Medium | Outlier removal and fallback defaults are not shown in the UI. | `backend/app/services/fr_service.py:74`, `backend/app/services/fr_service.py:79` | Financial output can change materially without user visibility. | Expose filters/fallbacks in API responses and UI. |

### Agent 4: Deployment and Runtime

What is good:

- Backend has a Render config and the service name maps to `https://ebattery-api.onrender.com`.
- Frontend is configured for static export and Netlify `out` publishing.
- Backend exposes health endpoints.

What could be wrong:

| Severity | Finding | Evidence | Why it matters | Recommended change |
| --- | --- | --- | --- | --- |
| Critical | Render deploy will not have the local symlinked data target. | `backend/data`, `backend/render.yaml` | API can fail, fallback, or return stale/missing data in production. | Add deploy-safe data source and env configuration. |
| High | Frontend Dockerfile expects `.next/standalone`, but Next config uses static export. | `frontend/Dockerfile:34`, `frontend/next.config.js:4` | Docker production image will not match the static-export build mode. | Either use static serving for `out` or remove Docker standalone assumptions. |
| Medium | `render.yaml` only sets Python version. | `backend/render.yaml:7` | Production `DEBUG`, CORS, and data path depend on defaults. | Add explicit env vars for production settings. |
| Medium | CORS production origin is hardcoded. | `backend/app/config.py:17` | Netlify previews, custom domains, or renamed sites can be blocked. | Drive CORS origins from env. |
| Low | Docker compose mounts data from sibling `BOT BATTERY`. | `docker-compose.yml:12` | Local setup is not portable. | Use repo-local data or documented env var. |
| Low | Generated folders `frontend/out 2` and `frontend/out 3` exist. | `frontend/out 2`, `frontend/out 3` | Audits/builds may review stale generated HTML. | Exclude or remove generated build artifacts in a separate cleanup. |

### Agent 5: Legal, Market, and ROI Assumptions

What is good:

- The app distinguishes PZU arbitrage, FR revenue, and investment analysis as separate business-model surfaces.
- It includes Romanian-market language that is relevant for BESS revenue analysis.

What could be wrong:

| Severity | Finding | Evidence | Why it matters | Recommended change |
| --- | --- | --- | --- | --- |
| Critical | FR settlement text is too confident for an unverified simplified model. | `backend/app/services/fr_service.py:130`, `frontend/app/fr-simulator/page.tsx` | It can be read as confirmed Romanian settlement logic. | Label as simplified scenario until verified against rules and settlement exports. |
| Critical | aFRR down-regulation logic may double-count benefit when prices are negative. | `backend/app/services/fr_service.py:160` | Revenue can be materially overstated. | Validate against Transelectrica/BRP settlement exports and counsel. |
| High | UI uses language like guaranteed capacity payments and fully utilized bidding. | `frontend/app/page.tsx`, `frontend/app/fr-simulator/page.tsx` | Market acceptance, prequalification, availability, penalties, and price risk are not guaranteed. | Replace guarantee language with conditional/risk-qualified language. |
| High | Investment recommendations are based on modeled profit without compliance gates. | `frontend/app/investment/page.tsx` | A project may be financially impossible without ANRE, OPCOM, PRE/BRP, BSP/FSE, telemetry, grid, and settlement setup. | Add compliance checklist before strategy recommendation. |
| Medium | Typical FR revenue/payback claims need source/date/confidence labels. | `frontend/app/investment/page.tsx` | Investor users may treat illustrative estimates as market facts. | Add evidence status and source links or mark as illustrative. |
| Medium | Tariff, tax, certificate, imbalance, and warranty assumptions are not fully modeled. | Investment service and UI | ROI can be overstated. | Add explicit exclusions and future model tasks. |

### Agent 6: Documentation Quality

What is good:

- Existing mobile/browser verification docs show effort to validate UI behavior.
- There is a shell script for FR API smoke checks.

What could be wrong:

| Severity | Finding | Evidence | Why it matters | Recommended change |
| --- | --- | --- | --- | --- |
| High | Some docs imply verification completeness while checklists still contain manual unchecked items. | `MOBILE_VERIFICATION_CHECKLIST.md`, `BROWSER_VERIFICATION_CHECKLIST.md` | Stakeholders can overestimate testing maturity. | Separate `manual pending`, `manual verified`, and `automated verified`. |
| High | FR shell checks are mostly curl/json generation, not real assertions. | `test_fr_api_data_correctness.sh` | Passing the script does not prove model correctness. | Convert to pytest or assertion-based integration tests. |
| Medium | No single progress report existed before this file. | Project root docs | Findings are scattered and hard to act on. | Use this report as the central audit backlog. |
| Medium | Model assumptions are embedded in code and UI text. | FR, PZU, investment pages/services | Business rules are hard to review or approve. | Add an assumptions register. |

## Top Things That Could Be Wrong

1. FR revenue may be overstated because capacity, days, activation share, and settlement logic are simplified or hardcoded.
2. PZU arbitrage may be overstated because the optimizer does not enforce chronological SOC feasibility.
3. Investment ROI may be overstated because fallbacks hide simulation failures and cashflows omit major costs/risks.
4. Production data may fail because backend data is a symlink to another local repo.
5. The app may show fallback or hardcoded values while labeling them as live.
6. Frontend and backend API contracts have already drifted on FR stats.
7. Public DAMAS/PZU data is not the same as participant-specific settlement revenue.
8. aFRR down-regulation settlement may be sign-confused or double-counted.
9. Netlify static export works by config, but Docker production image assumptions conflict with static export.
10. The repo contains generated folders and local environments that can confuse audits and deployments.
11. Legal/compliance prerequisites are not built into the investment recommendation flow.
12. Data provenance is not sufficient for bankability review.
13. Smoke checks do not prove financial correctness.
14. PZU data-source priority may ignore longer/newer history.
15. CORS and environment config are not robust for previews, custom domains, or production changes.

## Verification Matrix

| Capability | Implementation status | Verification status | Confidence | Notes |
| --- | --- | --- | --- | --- |
| PZU price history API | Implemented | Manual/static checked | Medium | Data source priority needs explicit policy. |
| PZU arbitrage simulation | Partially implemented | Manual/static checked | Low for bankability | Needs chronological SOC model. |
| FR simulation | Partially implemented | Manual/static checked | Low for bankability | Hardcoded 30 MWh/30 days and public-market-share assumptions. |
| FR stats endpoint | Implemented backend | Frontend mismatch found | Medium | Frontend calls `/market-stats`; backend exposes `/stats`. |
| Investment analysis | Partially implemented | Manual/static checked | Low | Silent fallbacks and flat cashflows. |
| Netlify static export | Implemented | Static checked | Medium-high | `output: 'export'` and `publish = "out"` match. |
| Frontend Docker production image | Implemented incorrectly | Static checked | Low | Uses `.next/standalone` with static export config. |
| Render backend deploy | Partially implemented | Static checked | Low-medium | Data path/env vars need deploy-safe setup. |
| Data provenance | Missing | Static checked | Low | Needs manifest and source confidence. |
| Legal/market compliance gates | Missing | Static checked | Low | Needs ANRE/OPCOM/Transelectrica/PRE/BRP/BSP checklist. |
| Automated financial tests | Missing/insufficient | Static checked | Low | Shell smoke script is not enough. |
| UI risk labels | Missing/insufficient | Static checked | Low | Live/projection/fallback labels needed. |

## Missing Compliance and Bankability Gates

Before this app is used for bankability or investor decisions, it needs explicit gates for:

- ANRE licensing/authorization status for storage and electricity market participation.
- OPCOM registration and guarantees for PZU/DAM and intraday participation.
- PRE/BRP responsibility, imbalance exposure, and settlement exports.
- BSP/FSE qualification for aFRR/mFRR/FCR where applicable.
- Transelectrica/DAMAS access, telemetry, metering, prequalification, availability, and penalty rules.
- Network operator connection agreement, tariffs, exemptions for stored energy re-injected, and grid constraints.
- REMIT and market-conduct controls if any live trading or bidding workflow is later added.
- Tax, VAT, corporate tax, depreciation, land, insurance, O&M, augmentation, warranty throughput, and financing covenants.

## Recommended Future Fix Plan

### Backend

- Fix `DATA_DIR` so local, Docker, Render, and audit environments use the same canonical data source.
- Replace silent investment fallbacks with explicit warnings, error states, or scenario labels.
- Replace hardcoded FR monthly energy budget with `capacity_mwh`, actual calendar days, SOC, throughput, and degradation.
- Replace PZU sorted-price arbitrage with chronological charge/discharge dispatch.
- Add schema, freshness, duplicate, timezone, and source validation for every CSV.
- Add response fields that disclose when defaults, filters, or fallback estimates were used.

### Frontend

- Fix `/fr/market-stats` vs `/fr/stats`.
- Move all endpoint calls into `frontend/lib/api.ts` and align TypeScript request/response types with backend models.
- Add visible labels for `live API`, `historical`, `simulated`, `fallback`, and `not verified`.
- Add source/date/model-version labels to revenue cards and investment outputs.
- Replace guarantee language with conditional market-access language.
- Show user-visible errors when auxiliary data loads fail.

### Data

- Create a data manifest with file name, source URL/export, date range, granularity, timezone, observed/estimated/predicted status, and confidence.
- Decide whether `backend/data` or `backend/data 2` is canonical and remove ambiguity.
- Keep public aggregate market data separate from participant settlement/export data.
- Mark empty or placeholder files such as `bm_forecast.csv` as missing capability until implemented.

### Deployment

- Add production env vars in Render for `DEBUG=false`, `DATA_DIR`, and CORS origins.
- Document Netlify `NEXT_PUBLIC_API_URL` instead of relying on source fallback.
- Make Docker either serve static `out` output or switch Next config to standalone mode; do not mix both.
- Remove or ignore generated folders such as `out 2` and `out 3` in a separate cleanup.

### Tests

- Convert shell smoke checks into assertion-based backend tests.
- Add tests for PZU chronological dispatch once implemented.
- Add tests for FR capacity scaling, product stacking, signed activation prices, and fallback warnings.
- Add investment tests for no-silent-fallback behavior, degradation assumptions, and financing scenarios.
- Add frontend tests for API endpoint contracts, failure states, and risk labels.

## Next Evidence Needed

| Evidence | Needed from | Why |
| --- | --- | --- |
| Participant settlement exports for aFRR/mFRR/PZU/imbalance | Operator, PRE/BRP, Transelectrica/settlement systems | Confirm project-specific revenue mechanics. |
| Official legal/compliance memo | Romanian counsel | Confirm market access, licensing, tariff, and certificate treatment. |
| OPCOM registration/guarantee requirements | OPCOM or participant documents | Confirm PZU/IDM access assumptions. |
| Transelectrica prequalification and DAMAS access requirements | Transelectrica | Confirm FR participation and settlement prerequisites. |
| Network tariff/exemption treatment | DSO/TSO/ANRE documents | Separate avoided costs from gross revenue. |
| Data source exports and generation scripts | Project owner | Prove CSV provenance and observed vs estimated periods. |
| Vendor offers and capex source docs | EPC/vendor/project owner | Validate investment inputs and dates. |

## Acceptance Criteria for the Next Review

- Every revenue number visible in the UI has source, date range, model version, and confidence label.
- Every fallback/default estimate is visible in API response and UI.
- Frontend page calls match backend routes and shared TypeScript API definitions.
- Runtime data source is deploy-safe and documented.
- PZU and FR simulations expose limitations clearly until improved.
- Investment outputs include degradation, major costs, taxes/fees, penalties, and downside scenarios or clearly state they are excluded.
- Legal/compliance prerequisites are separated from financial optimization.
- Automated tests assert critical model behavior instead of only producing JSON files.

## Bottom Line

The app is useful as a Romanian BESS analytics prototype. The biggest immediate fixes are not visual. They are data lineage, endpoint consistency, deploy-safe data access, financial model transparency, and risk wording. Until those are fixed, the app should be presented as an illustrative research/demo tool, not as a bankable BESS revenue model.
