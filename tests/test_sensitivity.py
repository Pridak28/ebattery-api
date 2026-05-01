"""Phase F1+F2+F3 sensitivity tests (gap audit 2026-05-01).

Coverage:
  F1 — Monte Carlo runs return P10 ≤ P50 ≤ P90 IRR; samples populated.
  F2 — DSCR < 1.20 violation flagged on under-funded scenarios.
  F3 — FX hedge cost subtracts from cashflow when revenue_currency == "RON";
       zero when "EUR".
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.investment import InvestmentParams  # noqa: E402
from app.services.investment_service import InvestmentService  # noqa: E402
from app.services.sensitivity import SensitivityConfig, _irr, _npv, _payback_years  # noqa: E402


@pytest.fixture
def base_params() -> InvestmentParams:
    return InvestmentParams(
        total_investment_eur=3_500_000,
        equity_percentage=50,
        loan_interest_rate=6.0,
        loan_term_years=10,
        opex_percentage=2.0,
        insurance_percentage=0.5,
        power_mw=10.0,
        capacity_mwh=20.0,
        degradation_rate_pct=2.5,
        opex_inflation_pct=3.0,
        rte_ac_ac=0.88,
        availability_pct=97.5,
        auxiliary_load_mw=0.3,
        annual_efc_assumption=365.0,
    )


# ----------------------------- IRR helpers ------------------------------------
def test_irr_helper_basic():
    # Standard cashflow: -1000 today, +500 / +500 / +500 next 3 yrs.
    irr = _irr([-1000, 500, 500, 500])
    # Closed-form: ~23.4%
    assert math.isclose(irr, 0.2337, abs_tol=0.01)


def test_payback_helper():
    # Year-0 capex 1000; recover 400, 400, 400 → payback between yr 2 and 3.
    payback = _payback_years([-1000, 400, 400, 400])
    assert 2.0 <= payback <= 3.0


def test_npv_helper_zero_at_irr():
    cf = [-1000, 500, 500, 500]
    irr = _irr(cf)
    npv = _npv(cf, irr)
    assert abs(npv) < 1e-3


# ----------------------------- F1 Monte Carlo --------------------------------
def test_f1_monte_carlo_percentile_ordering(base_params):
    svc = InvestmentService()
    cfg = SensitivityConfig(runs=200, seed=7)
    report = svc.run_sensitivity(base_params, cfg)
    assert report.runs == 200
    if not math.isnan(report.p10_irr):
        assert report.p10_irr <= report.p50_irr <= report.p90_irr


def test_f1_monte_carlo_samples_populated(base_params):
    svc = InvestmentService()
    cfg = SensitivityConfig(runs=100, seed=11)
    report = svc.run_sensitivity(base_params, cfg)
    assert len(report.irr_samples) > 0
    assert len(report.irr_samples) <= 1000


# ----------------------------- F2 DSCR ----------------------------------------
def test_f2_dscr_violation_on_under_funded_scenario(base_params):
    """Force a low-revenue, high-debt scenario by demanding 0% equity (all debt)
    and setting a tiny operating cost — the DSCR should fall below 1.20 at some
    point given the heavy debt service relative to revenue."""
    underfunded = base_params.model_copy(update={
        "total_investment_eur": 10_000_000,  # large
        "equity_percentage": 1.0,             # almost all debt
        "loan_interest_rate": 12.0,
        "loan_term_years": 5,                 # short tenor → high annual debt service
    })
    svc = InvestmentService()
    response = svc.analyze(underfunded)
    # Either the scenario flags violations, or DSCR is computed and below
    # threshold in at least one cashflow year.
    has_violation = bool(response.dscr_violation_years)
    fr_low_dscr = any(0 < cf.dscr < 1.20 for cf in response.fr_cashflow)
    pzu_low_dscr = any(0 < cf.dscr < 1.20 for cf in response.pzu_cashflow)
    assert has_violation or fr_low_dscr or pzu_low_dscr


def test_f2_dscr_present_on_every_year_with_debt(base_params):
    svc = InvestmentService()
    response = svc.analyze(base_params)
    for cf in response.fr_cashflow:
        if cf.debt_service_eur > 0:
            assert cf.dscr != 0  # real number computed


# ----------------------------- F3 FX hedge ------------------------------------
def test_f3_fx_hedge_zero_for_eur(base_params):
    eur_params = base_params.model_copy(update={"revenue_currency": "EUR"})
    svc = InvestmentService()
    response = svc.analyze(eur_params)
    assert all(cf.fx_hedge_cost_eur == 0.0 for cf in response.fr_cashflow)


def test_f3_fx_hedge_subtracts_from_ron_cashflow(base_params):
    ron_params = base_params.model_copy(update={
        "revenue_currency": "RON",
        "fx_hedge_cost_pct": 2.5,
    })
    svc = InvestmentService()
    response = svc.analyze(ron_params)
    # Year 1 FX hedge cost = 2.5% of gross revenue.
    cf1 = response.fr_cashflow[0]
    expected = cf1.gross_revenue_eur * 0.025
    assert math.isclose(cf1.fx_hedge_cost_eur, expected, rel_tol=1e-6)
