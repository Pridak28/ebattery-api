"""Investment fail-closed regression tests.

Per audit/BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT_2026-05-01.md (Agent 1 High,
Agent 5 High):
- Silent fallbacks must populate ``warnings`` and tag ``revenue_source``.
- Unexpected exceptions must propagate (no fake ROI).
- Cashflow must degrade revenue and inflate OPEX year over year.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.investment import InvestmentParams  # noqa: E402
from app.services.investment_service import InvestmentService  # noqa: E402


@pytest.fixture
def base_params() -> InvestmentParams:
    return InvestmentParams(
        total_investment_eur=5_250_000,
        equity_percentage=50,
        loan_interest_rate=6.0,
        loan_term_years=10,
        opex_percentage=2.0,
        insurance_percentage=0.5,
        power_mw=15.0,
        capacity_mwh=30.0,
        degradation_rate_pct=2.5,
        opex_inflation_pct=3.0,
    )


def test_warnings_populated_when_pzu_fails(monkeypatch, base_params):
    """When PZU simulate raises a known data error, response must include
    a warning string and tag revenue_source='fallback_estimate'."""
    svc = InvestmentService()
    monkeypatch.setattr(
        svc.pzu_service,
        "simulate",
        lambda _params: (_ for _ in ()).throw(FileNotFoundError("pzu data missing")),
    )
    response = svc.analyze(base_params)
    assert response.pzu_scenario.revenue_source == "fallback_estimate"
    assert any("PZU simulation failed" in w for w in response.pzu_scenario.warnings)
    assert any("PZU simulation failed" in w for w in response.warnings)


def test_unexpected_exception_propagates(monkeypatch, base_params):
    """Bare RuntimeError must NOT be silently swallowed — should surface
    as a 5xx (here, propagate to the caller)."""
    svc = InvestmentService()
    monkeypatch.setattr(
        svc.pzu_service,
        "simulate",
        lambda _params: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )
    with pytest.raises(RuntimeError, match="kaboom"):
        svc.analyze(base_params)


def test_cashflow_degrades(base_params):
    """Year 6 gross revenue should be lower than year 1.

    Phase D6 (gap audit 2026-05-01) replaced the flat ``(1-deg)^(year-1)``
    capacity factor with ``1 − calendar_fade − cycle_fade``:
      year 1: capacity = 0.975
      year 6: capacity ≈ 0.900 (calendar 0.025 + 0.015×5 = 0.10) − cycle_fade
    so the year-6/year-1 ratio is around 0.92 in the default config.
    """
    svc = InvestmentService()
    response = svc.analyze(base_params)
    cashflow = response.fr_cashflow
    assert len(cashflow) >= 6
    assert cashflow[5].gross_revenue_eur < cashflow[0].gross_revenue_eur
    # Capacity factor is monotonically non-increasing.
    factors = [cf.capacity_factor for cf in cashflow]
    assert all(factors[i] >= factors[i + 1] - 1e-9 for i in range(len(factors) - 1))
    # Year-6 capacity factor should be close to 1 - 0.10 - small cycle term.
    assert cashflow[5].capacity_factor < 0.92
    assert cashflow[5].capacity_factor > 0.80


def test_cashflow_opex_inflates(base_params):
    """Year 6 operating cost should be higher than year 1 due to inflation."""
    svc = InvestmentService()
    response = svc.analyze(base_params)
    cashflow = response.fr_cashflow
    assert len(cashflow) >= 6
    assert cashflow[5].operating_cost_eur > cashflow[0].operating_cost_eur
    expected_factor = (1 + base_params.opex_inflation_pct / 100) ** 5
    actual_factor = cashflow[5].operating_cost_eur / cashflow[0].operating_cost_eur
    assert abs(actual_factor - expected_factor) < 0.05


def test_excluded_costs_disclosed(base_params):
    """Top-level response must include `excluded_from_model` so investors
    are warned about what's NOT in the model."""
    svc = InvestmentService()
    response = svc.analyze(base_params)
    assert isinstance(response.excluded_from_model, list)
    assert len(response.excluded_from_model) >= 5
    # Audit reference is present
    assert "audit/" in response.audit_reference
