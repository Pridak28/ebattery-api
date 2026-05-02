"""Edge-case coverage for app.services.sensitivity defensive branches.

Targets the small set of guards/fallbacks not exercised by the main suite:
  - _triangular: lo == hi short-circuit, mode <= lo and mode >= hi clamps.
  - _irr: degenerate input (size < 2), all-positive / all-negative cashflows.
  - _payback_years: never-break-even path returns +inf.
  - monte_carlo: degenerate-case (no finite IRRs) returns NaN report safely.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.investment import AnnualCashflow, InvestmentParams  # noqa: E402
from app.services.sensitivity import (  # noqa: E402
    SensitivityConfig,
    _irr,
    _payback_years,
    _triangular,
    monte_carlo,
)


# ----------------------------- _triangular guards ----------------------------
def test_triangular_lo_eq_hi():
    rng = np.random.default_rng(0)
    # Degenerate distribution — all three identical → returns lo (== hi).
    assert _triangular(rng, 5.0, 5.0, 5.0) == 5.0


def test_triangular_mode_below_lo():
    rng = np.random.default_rng(1)
    # After sort, the args are (3.0, 5.0, 10.0) so mode=5.0 is fine; supply
    # ordering that forces the mode <= lo branch via the post-sort check.
    # Using (5.0, 5.0, 10.0) — sorted gives lo=5, mode=5, hi=10 → mode <= lo.
    val = _triangular(rng, 5.0, 5.0, 10.0)
    assert 5.0 <= val <= 10.0


def test_triangular_mode_above_hi():
    rng = np.random.default_rng(2)
    # Sorted (5.0, 10.0, 10.0) → lo=5, mode=10, hi=10 → mode >= hi clamp.
    val = _triangular(rng, 5.0, 10.0, 10.0)
    assert 5.0 <= val <= 10.0


# ----------------------------- _irr guards -----------------------------------
def test_irr_size_lt_2_returns_nan():
    # arr.size < 2 short-circuit.
    assert math.isnan(_irr([-1000.0]))
    assert math.isnan(_irr([]))


def test_irr_no_sign_change_returns_nan():
    # All-positive cashflows → no IRR exists.
    assert math.isnan(_irr([100.0, 100.0, 100.0]))


def test_irr_all_negative_returns_nan():
    # All-negative cashflows → no IRR exists.
    assert math.isnan(_irr([-100.0, -10.0, -10.0]))


# ----------------------------- _payback_years guard --------------------------
def test_payback_years_never_breaks_even():
    # Cumulative cashflow stays negative → +inf.
    assert _payback_years([-100.0, -10.0, -10.0]) == float("inf")


# ----------------------------- monte_carlo degenerate ------------------------
def test_monte_carlo_degenerate_no_finite_irrs():
    """When create_cashflow yields only-negative annual flows for every run,
    no IRR can be computed and the report falls into the NaN branch."""
    params = InvestmentParams(
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
    cfg = SensitivityConfig(runs=10, seed=123)

    def negative_cashflow(years, gross, energy_cost, opex, debt, *, params, epc_eur):
        # Force an unambiguously negative annual stream — no IRR can exist.
        return [
            AnnualCashflow(
                year=y + 1,
                gross_revenue_eur=0.0,
                energy_cost_eur=0.0,
                operating_cost_eur=0.0,
                debt_service_eur=0.0,
                net_profit_eur=-1000.0,
                cumulative_profit_eur=-1000.0 * (y + 1),
            )
            for y in range(years)
        ]

    report = monte_carlo(
        params=params,
        fr_revenue_y1={"gross_revenue": 0.0, "energy_cost": 0.0},
        pzu_revenue_y1={"gross_revenue": 0.0, "energy_cost": 0.0},
        operating_cost_y1=0.0,
        annual_debt_service=0.0,
        equity_eur=1_750_000.0,
        cfg=cfg,
        create_cashflow=negative_cashflow,
    )
    assert report.runs == 10
    assert math.isnan(report.p10_irr)
    assert math.isnan(report.p50_irr)
    assert math.isnan(report.p90_irr)
    assert math.isnan(report.mean_irr)
    assert report.irr_samples == []
