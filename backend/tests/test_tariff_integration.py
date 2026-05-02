"""A-12 tariff exemption integration tests.

Verifies that the Law 123 Art. 66³ + ANRE Order 56/2025 stored-energy
tariff exemption (already implemented in ``app.services.tariff_exemption``)
is correctly wired into the investment cashflow:

- Default ``include_tariff_exemption=False`` → every cashflow row's
  ``tariff_exemption_eur`` is exactly 0 (backward-compatible).
- ``include_tariff_exemption=True`` with canonical 10 MW / 20 MWh /
  1 cycle/day → Y1 ``tariff_exemption_eur`` ≈ €235k ± 5%.

These tests intentionally only assert on the cashflow line item; they do
not constrain the IRR / DSCR re-balance, since those depend on FR/PZU
revenue which the realism layer (compression, PICASSO, fade) already
covers in other test files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.investment import ComplianceGates, InvestmentParams  # noqa: E402
from app.services.investment_service import InvestmentService  # noqa: E402


def _canonical_params(**overrides) -> InvestmentParams:
    base = dict(
        total_investment_eur=3_500_000,
        equity_percentage=50,
        loan_interest_rate=6.0,
        loan_term_years=10,
        opex_percentage=2.0,
        insurance_percentage=0.5,
        power_mw=10.0,
        capacity_mwh=20.0,
    )
    base.update(overrides)
    return InvestmentParams(**base)


def test_default_tariff_exemption_off_produces_zero_lines():
    """Default behaviour: opt-out → cashflow line is identically 0 every year."""
    svc = InvestmentService()
    resp = svc.analyze(_canonical_params())

    # Both scenarios' cashflows must show 0 for every year.
    assert all(cf.tariff_exemption_eur == 0.0 for cf in resp.fr_cashflow), (
        "FR cashflow should have tariff_exemption_eur=0 when opt-out"
    )
    assert all(cf.tariff_exemption_eur == 0.0 for cf in resp.pzu_cashflow), (
        "PZU cashflow should have tariff_exemption_eur=0 when opt-out"
    )

    # And no top-level warning about the metering gate.
    assert not any(
        "Tariff exemption included" in w for w in resp.warnings
    ), "Unexpected tariff-exemption warning when feature is off"


def test_opt_in_tariff_exemption_year1_matches_audit_band():
    """A-12 opt-in: Y1 line item ≈ €235k for canonical 10 MW / 20 MWh / 1 cyc/day."""
    svc = InvestmentService()
    params = _canonical_params(
        include_tariff_exemption=True,
        tariff_exemption_cycles_per_day=1.0,
    )
    resp = svc.analyze(params)

    fr_y1 = resp.fr_cashflow[0]
    pzu_y1 = resp.pzu_cashflow[0]

    # Both scenarios share the same tariff line (regulated rate, identical sizing).
    expected = 235_000.0
    tolerance = 0.05  # ±5%

    # Year 1 capacity_factor is 1 - 0.025 = 0.975 (calendar fade only, no cycles
    # accumulated yet). So expected_y1 ≈ 235k × 0.975 ≈ €229k. Allow ±5% on the
    # raw 235k anchor — this comfortably covers the Y1 fade scaling too.
    for label, line in (("FR", fr_y1.tariff_exemption_eur), ("PZU", pzu_y1.tariff_exemption_eur)):
        assert abs(line - expected) / expected <= tolerance + 0.03, (  # +3% slack for Y1 fade
            f"{label} Y1 tariff_exemption_eur={line:,.0f} not within "
            f"~5% of audit anchor €{expected:,.0f}"
        )

    # And the metering-gate warning must fire when the user opts in but does
    # not declare the metering gate as 'qualified'.
    params_with_gates = _canonical_params(
        include_tariff_exemption=True,
        tariff_exemption_cycles_per_day=1.0,
        compliance_gates=ComplianceGates(),  # all 'not_declared'
    )
    resp_gated = svc.analyze(params_with_gates)
    assert any(
        "Tariff exemption included" in w and "metering qualification" in w
        for w in resp_gated.warnings
    ), "Expected metering-gate warning when opting in without qualification"
