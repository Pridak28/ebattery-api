"""Phase D physical-realism tests (gap audit 2026-05-01).

Coverage:
  D1 — symmetric AC-side RTE via sqrt(eta) helpers
  D2 — SOC bounds rejection in PZU daily arbitrage
  D3 — throughput warranty + augmentation schedule
  D4 — auxiliary load parasitic OPEX in cashflow
  D5 — availability factor on FR capacity revenue
  D6 — calendar + cycle aging coupling in cashflow
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.fr import FRSimulationParams  # noqa: E402
from app.models.investment import InvestmentParams  # noqa: E402
from app.services.fr_service import FRService  # noqa: E402
from app.services.investment_service import InvestmentService  # noqa: E402
from app.services.pzu_service import PZUService  # noqa: E402
from app.services.warranty_tracker import WarrantyConfig, project_warranty, track_throughput  # noqa: E402


def _day_prices(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": [pd.Timestamp("2024-01-01")] * 24,
        "hour": list(range(24)),
        "price": prices,
    })


# ----------------------------- D1 --------------------------------------------
def test_d1_charge_grid_input_uses_sqrt_eta():
    eta = 0.88
    grid_in = PZUService._charge_grid_input_mwh(100.0, eta)
    assert math.isclose(grid_in, 100.0 / math.sqrt(eta), rel_tol=1e-9)


def test_d1_discharge_grid_output_uses_sqrt_eta():
    eta = 0.88
    grid_out = PZUService._discharge_grid_output_mwh(100.0, eta)
    assert math.isclose(grid_out, 100.0 * math.sqrt(eta), rel_tol=1e-9)


def test_d1_round_trip_preserves_total_eta():
    """A round trip stores ``internal_mwh`` then delivers it: grid_out / grid_in
    must equal ``eta``."""
    eta = 0.88
    grid_in = PZUService._charge_grid_input_mwh(100.0, eta)
    grid_out = PZUService._discharge_grid_output_mwh(100.0, eta)
    assert math.isclose(grid_out / grid_in, eta, rel_tol=1e-9)


# ----------------------------- D2 --------------------------------------------
def test_d2_soc_bounds_reject_overcharge():
    """If usable headroom is zero (soc_initial == soc_max), no candidate
    SOC trajectory should be feasible — result should be a zero-trade day."""
    svc = PZUService()
    prices = [10.0] * 24
    prices[0] = 10.0
    prices[1] = 10.0
    prices[20] = 200.0
    prices[21] = 200.0
    result = svc._compute_daily_arbitrage(
        _day_prices(prices),
        power_mw=15.0,
        capacity_mwh=30.0,
        efficiency=0.9,
        soc_initial=0.90,  # already at max
        soc_max=0.90,
        soc_min=0.10,
    )
    assert result is not None
    assert result["gross_profit"] == 0.0
    assert result["soc_violations"] >= 0


def test_d2_soc_trajectory_within_bounds():
    """The chosen (cs, ds) trajectory must stay within [soc_min, soc_max]."""
    svc = PZUService()
    prices = [100.0] * 24
    prices[0] = 10.0
    prices[1] = 10.0
    prices[20] = 200.0
    prices[21] = 200.0
    result = svc._compute_daily_arbitrage(
        _day_prices(prices),
        power_mw=15.0,
        capacity_mwh=30.0,
        efficiency=0.9,
        soc_min=0.10,
        soc_max=0.90,
        soc_initial=0.50,
    )
    assert result is not None
    if result["soc_trajectory"] is not None:
        traj = result["soc_trajectory"]
        tol = 1e-6
        assert all(s >= 0.10 - tol for s in traj)
        assert all(s <= 0.90 + tol for s in traj)


# ----------------------------- D3 --------------------------------------------
def test_d3_warranty_exceeded_when_efc_overshoots_budget():
    """Cycling 500 EFC/yr × 15yr = 7500 EFC > 6000 budget → exceeded by year 13."""
    cfg = WarrantyConfig(efc_budget=6000, warranty_years=15)
    schedule = project_warranty(annual_efc=500.0, epc_eur=3_500_000.0, cfg=cfg)
    statuses = [r.warranty_status for r in schedule]
    assert "exceeded" in statuses
    # First exceedance: year ceil(6000 / 500) + 1 = year 13
    first_exceed = next(r.year for r in schedule if r.warranty_status == "exceeded")
    assert first_exceed == 13


def test_d3_augmentation_lands_in_year_5_and_10():
    cfg = WarrantyConfig(
        efc_budget=6000,
        warranty_years=15,
        augmentation_cost_pct_of_epc=10.0,
        augmentation_years=[5, 10],
    )
    schedule = project_warranty(annual_efc=200.0, epc_eur=3_500_000.0, cfg=cfg)
    augs = {r.year: r.augmentation_cost_eur for r in schedule if r.augmentation_cost_eur > 0}
    assert set(augs.keys()) == {5, 10}
    # Each augmentation = 10% of €3.5M = €350k.
    assert all(math.isclose(v, 350_000.0, rel_tol=1e-9) for v in augs.values())


def test_d3_track_throughput_pure_function():
    cfg = WarrantyConfig(efc_budget=100, warranty_years=2, augmentation_years=[2])
    step1 = track_throughput(annual_efc=60, year=1, cumulative_efc=0.0, epc_eur=1_000_000, cfg=cfg)
    assert step1["cumulative_efc"] == 60
    assert step1["warranty_exceeded"] is False
    assert step1["augmentation_cost_eur"] == 0.0

    step2 = track_throughput(annual_efc=60, year=2, cumulative_efc=60, epc_eur=1_000_000, cfg=cfg)
    assert step2["cumulative_efc"] == 120  # > budget
    assert step2["warranty_exceeded"] is True
    assert math.isclose(step2["augmentation_cost_eur"], 100_000.0, rel_tol=1e-9)


# ----------------------------- D4 + D6 ----------------------------------------
@pytest.fixture
def base_investment_params() -> InvestmentParams:
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
        avg_pzu_price_eur_mwh_for_aux=80.0,
        annual_efc_assumption=365.0,
    )


def test_d4_aux_cost_present_in_cashflow(base_investment_params):
    svc = InvestmentService()
    response = svc.analyze(base_investment_params)
    cashflow = response.fr_cashflow
    assert len(cashflow) >= 5
    # Aux cost = aux_mw × 8760h × availability × pzu_price.
    # Mastermind R-1 fix (2026-05-02): aux is GRID-DIRECT (HVAC/BMS/fire
    # suppression), NOT routed through the battery's AC↔DC conversion. The
    # earlier ``/ sqrt(eta)`` factor was a charge-side gross-up that overstated
    # aux cost by ~6%. Test now uses the corrected formula.
    aux_mw = base_investment_params.auxiliary_load_mw
    avail = base_investment_params.availability_pct / 100.0
    pzu_price = base_investment_params.avg_pzu_price_eur_mwh_for_aux
    expected_y1 = aux_mw * 8760.0 * avail * pzu_price
    actual_y1 = cashflow[0].auxiliary_cost_eur
    assert abs(actual_y1 - expected_y1) / expected_y1 < 0.01


def test_d6_capacity_factor_decreases_with_calendar_and_cycle_fade(base_investment_params):
    svc = InvestmentService()
    response = svc.analyze(base_investment_params)
    cashflow = response.fr_cashflow
    # Year 1 capacity_factor: 1 - 0.025 - 0 = 0.975
    assert math.isclose(cashflow[0].capacity_factor, 0.975, abs_tol=0.01)
    # Year 5 calendar fade: 0.025 + 0.015×4 = 0.085 → cap factor ≤ 0.915
    assert cashflow[4].capacity_factor < 0.915 + 1e-6
    # Capacity factor must be monotonically non-increasing.
    factors = [cf.capacity_factor for cf in cashflow]
    assert all(factors[i] >= factors[i + 1] - 1e-9 for i in range(len(factors) - 1))


# ----------------------------- D5 --------------------------------------------
def test_d5_availability_scales_capacity_revenue(monkeypatch):
    """Availability of 50% should halve capacity revenue vs 100%."""
    svc = FRService()

    # Inject a tiny synthetic month-data DataFrame.
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=4, freq="15min"),
        "afrr_up_price_eur": [200.0] * 4,
        "afrr_down_price_eur": [-30.0] * 4,
        "afrr_up_activated_mwh": [0.0] * 4,
        "afrr_down_activated_mwh": [0.0] * 4,
    })

    metadata = {
        "source_kind": "unverified_snapshot",
        "settlement_grade": False,
        "bankability_level": "historical_backtest_only",
        "data_date_max": "2024-01-01",
    }

    full = svc._compute_monthly_revenue(
        df, "aFRR+", power_mw=10.0,
        efficiency=0.88, energy_cost_eur_mwh=80.0,
        capacity_price=5.0, activation_rate=0.10,
        remaining_energy_budget=1_000_000.0,
        data_metadata=metadata,
        availability=1.0,
    )
    half = svc._compute_monthly_revenue(
        df, "aFRR+", power_mw=10.0,
        efficiency=0.88, energy_cost_eur_mwh=80.0,
        capacity_price=5.0, activation_rate=0.10,
        remaining_energy_budget=1_000_000.0,
        data_metadata=metadata,
        availability=0.5,
    )
    assert math.isclose(half.capacity_revenue_eur, full.capacity_revenue_eur * 0.5, rel_tol=1e-6)
