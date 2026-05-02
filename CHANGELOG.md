# Changelog

All notable changes to battery-analytics-pro are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — autonomous session 2026-05-02

### Added

- **Tariff exemption module** (`backend/app/services/tariff_exemption.py`)
  modeling Law 123 / ANRE Order 56/2025 transmission and distribution tariff
  savings for storage assets.
- **ComplianceGates** core abstraction (`core/compliance_gates.py`) gating
  settlement-grade vs scenario-only outputs.
- **Regime tagging** (`core/regime.py`) classifying each price observation
  into pay-as-bid vs marginal pricing eras with cutover at 2024-10-01.
- **FX sampling** for EUR/RON variability across scenarios.
- **PICASSO compression cliff** modeling — anticipated aFRR price compression
  on Romanian PICASSO accession.
- **`/investor-summary`** printable A4 page plus
  `POST /api/v1/investment/investor-summary` API endpoint returning the
  structured KPI / revenue-stack / bankability payload.
- **`/methodology`** page documenting models and regulatory citations.
- **`/health-detailed`** endpoint surfacing dataset freshness, row counts,
  bankability labels, and regime cutovers.
- **~22 new frontend components and hooks**:
  - Components: `LiveMarketChart`, `BankabilityBadge`, `RegimeBreakdownCard`,
    `RegulatoryNotesPanel`, `DataFreshnessBadge`, `DscrDetailPanel`,
    `ScenarioComparator`, `ExportCashflowButton`, `ShareScenarioButton`,
    `IrrDistributionHistogram`, `ComplianceGatesWizard`, `RegulatoryTimeline`,
    `HealthDiagnostics`, `OnboardingTour`, `SavedReportsPanel`,
    `ScenarioDiffPanel`, `SnapshotButtons`, `ScenarioJsonButtons`.
  - Hooks: `useScenarioUrl`, `useSavedReports`, `useOnboardingTour`.

### Changed

- **Pydantic v2 migration** — moved all models from `class Config` to
  `model_config = ConfigDict(...)`.
- **Aux load math fix** — auxiliary load is no longer divided by
  `sqrt(efficiency)`; corrected to track raw kWh consumption.
- **Bankability surface in FR response** — `/api/v1/fr/*` responses now carry
  the bankability label and gating metadata in-band.
- **Regime breakdown per scenario** — FR scenario results now report revenue
  and hours split per regime (pay-as-bid vs marginal).

### Fixed

- **2 real bugs**
  - `/typical-day` returned HTTP 500 on certain date ranges.
  - `calculate_financing` raised `ZeroDivisionError` for subnormal interest
    rates near zero.
- **4 D-WARN data fixes**
  - €2000 cap saturation in aFRR price ingestion.
  - `NaN` propagation in frequency series.
  - Stray `hour=24` rows in OPCOM ingestion.
  - Manifest path resolution for snapshot loaders.
- **FR slot prices** — corrected 10x inflation in slot price assembly.
- **FR bid floors** — corrected 3x overshoot vs published floors.

### Tests

- Backend tests: **43 → 340** (+297 net).
- Coverage: **48% → 93%+**.
- New: Hypothesis property tests, FastAPI TestClient API integration tests,
  data source validation tests.

### Accessibility

- **H1** — added `htmlFor` to all form labels.
- **H2** — `<tr>` rows now keyboard-activatable where they trigger actions.
- **M1** — heading order linted (no `h2 → h4` jumps).
- **M2** — range slider inputs given visible and programmatic labels.
- **M3** — confidence badges no longer convey state by icon alone.
- **M4** — text contrast palette tweaked to meet WCAG AA.

### Documentation

- `frontend/A11Y_FINDINGS.md` — accessibility audit notes.
- `CHANGELOG.md` — this file.
- `README.md` — project overview, quick start, architecture, data sources,
  regulatory references, disclaimer.
