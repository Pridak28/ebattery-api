"""Edge-case coverage tests for fr_service and investment_service.

Targets the specific missed branches identified in coverage report:
- Investment fallback paths (FR + PZU revenue).
- monte_carlo non-finite IRR / payback fallbacks.
- compute_multi_product_revenue regime filter / unknown product.
- _get_activation_price fallback to defaults.
- _avg_activation_price_for_product volume_weighted fallback.
- Financing edge case (zero interest, no debt).
- FR get_monthly_breakdown (lines 805-824).
- FR analyze_bidding_strategy / project_annual_revenue / calculate_optimal_bids
  / calculate_safe_bid_prices empty-data error branches.
- PICASSO compression disabled / zero-pct.
- Compliance gates warning when tariff opted-in without metering.
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data.quality import regulatory_regime_for_date  # noqa: E402
from app.models.fr import FRMultiProductRequest  # noqa: E402
from app.models.investment import ComplianceGates, InvestmentParams  # noqa: E402
from app.services.fr_service import FRService  # noqa: E402
from app.services.investment_service import InvestmentService  # noqa: E402
from app.services.sensitivity import SensitivityConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — synthetic FR DataFrame mirroring DAMAS schema.
# ---------------------------------------------------------------------------
def _make_synthetic_fr_df(
    start: date = date(2025, 1, 1),
    n_days: int = 30,
    seed: int = 7,
    span_regime_change: bool = False,
):
    """Build a 96-slot × N-day DAMAS-shaped DataFrame.

    Set ``span_regime_change=True`` to anchor the window so it spans the
    2024-10-01 ANRE Order 60/2024 boundary (gives both pre/post regimes).
    """
    import numpy as np
    import pandas as pd

    if span_regime_change:
        start = date(2024, 9, 15)  # 30 days starting before 2024-10-01

    rng = np.random.default_rng(seed)
    days = [pd.Timestamp(start) + pd.Timedelta(days=i) for i in range(n_days)]
    rows: List[Dict[str, Any]] = []
    for day in days:
        regime = regulatory_regime_for_date(day.date())
        up_prices = rng.normal(150.0, 40.0, size=96).clip(20.0, 480.0)
        down_prices = rng.normal(-25.0, 30.0, size=96).clip(-200.0, 100.0)
        mfrr_up_prices = rng.normal(180.0, 50.0, size=96).clip(30.0, 480.0)
        mfrr_down_prices = rng.normal(-30.0, 30.0, size=96).clip(-200.0, 100.0)
        up_acts = rng.uniform(0.5, 4.0, size=96)
        down_acts = rng.uniform(0.5, 4.0, size=96)
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                "afrr_up_price_eur": float(up_prices[s]),
                "afrr_down_price_eur": float(down_prices[s]),
                "afrr_up_activated_mwh": float(up_acts[s]),
                "afrr_down_activated_mwh": float(down_acts[s]),
                "mfrr_up_activated_mwh": float(rng.uniform(0.0, 2.0)),
                "mfrr_down_activated_mwh": float(rng.uniform(0.0, 2.0)),
                "mfrr_up_scheduled_price_eur": float(mfrr_up_prices[s]),
                "mfrr_down_scheduled_price_eur": float(mfrr_down_prices[s]),
                "fcr_activated_mwh": 0.0,
                "regulatory_regime": regime,
            })
    df = pd.DataFrame(rows)
    df.attrs["source_kind"] = "synthetic_test"
    df.attrs["settlement_grade"] = False
    return df


def _seed_fr(svc: FRService, df) -> None:
    svc._fr_data = df
    svc._fr_metadata = {
        "source_kind": "synthetic_test",
        "data_date_min": str(df["date"].min().date()),
        "data_date_max": str(df["date"].max().date()),
        "bankability_level": "historical_backtest_only",
        "settlement_grade": False,
        "source_file": None,
    }


def _base_investment_params(**overrides) -> InvestmentParams:
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


# ---------------------------------------------------------------------------
# Investment-service fallback branches.
# ---------------------------------------------------------------------------
def test_get_fr_annual_revenue_fallback_on_missing_data(monkeypatch):
    """FR simulate raises FileNotFoundError → fallback estimate + warning."""
    svc = InvestmentService()
    monkeypatch.setattr(
        svc.fr_service,
        "simulate",
        lambda _params: (_ for _ in ()).throw(FileNotFoundError("fr csv missing")),
    )
    rev = svc._get_fr_annual_revenue(_base_investment_params())
    assert rev["revenue_source"] == "fallback_estimate"
    assert rev["gross_revenue"] > 0
    assert rev["energy_cost"] > 0
    assert any("FR simulation failed" in w for w in rev["warnings"])


def test_get_fr_annual_revenue_fallback_on_zero_months(monkeypatch):
    """FR simulate returns no months → falls through warnings.append + fallback."""
    from app.models.fr import FRSimulationResponse, FRSimulationParams as FP

    empty_response = FRSimulationResponse(
        params=FP(),
        monthly_results=[],
        product_summaries=[],
        total_revenue_eur=0.0,
        total_energy_cost_eur=0.0,
        total_net_profit_eur=0.0,
    )
    svc = InvestmentService()
    monkeypatch.setattr(svc.fr_service, "simulate", lambda _p: empty_response)
    rev = svc._get_fr_annual_revenue(_base_investment_params())
    assert rev["revenue_source"] == "fallback_estimate"
    assert any("returned no months" in w for w in rev["warnings"])


def test_get_pzu_annual_revenue_fallback_on_missing_data(monkeypatch):
    """PZU simulate raises ValueError → fallback estimate + warning (lines 156-157, 159+)."""
    svc = InvestmentService()
    monkeypatch.setattr(
        svc.pzu_service,
        "simulate",
        lambda _p: (_ for _ in ()).throw(ValueError("no pzu data")),
    )
    rev = svc._get_pzu_annual_revenue(_base_investment_params())
    assert rev["revenue_source"] == "fallback_estimate"
    assert rev["gross_revenue"] > 0
    assert rev["energy_cost"] > 0
    assert any("PZU simulation failed" in w for w in rev["warnings"])


def test_get_pzu_annual_revenue_fallback_on_zero_months(monkeypatch):
    """PZU simulate returns no months → fallback line 155."""
    from app.models.pzu import PZUSimulationResponse, PZUSimulationParams as PP

    empty_response = PZUSimulationResponse(
        params=PP(),
        monthly_results=[],
        total_profit_eur=0.0,
        avg_monthly_profit_eur=0.0,
    )
    svc = InvestmentService()
    monkeypatch.setattr(svc.pzu_service, "simulate", lambda _p: empty_response)
    rev = svc._get_pzu_annual_revenue(_base_investment_params())
    assert rev["revenue_source"] == "fallback_estimate"
    assert any("returned no months" in w for w in rev["warnings"])


def test_calculate_financing_zero_interest_loan():
    """Zero interest rate → monthly_payment = debt / num_payments (line 64)."""
    svc = InvestmentService()
    params = _base_investment_params(loan_interest_rate=0.0)
    fin = svc.calculate_financing(params)
    # Debt is 50% × 3.5M = 1.75M; over 10y × 12mo = 120 payments.
    expected_monthly = (params.total_investment_eur * 0.5) / 120
    assert math.isclose(fin.monthly_debt_service_eur, expected_monthly, rel_tol=1e-6)
    assert fin.total_interest_paid_eur == pytest.approx(0.0, abs=1e-3)


def test_calculate_financing_no_debt():
    """Equity percentage = 100 → debt branch falls through to else (lines 69-71)."""
    svc = InvestmentService()
    params = _base_investment_params(equity_percentage=100.0)
    fin = svc.calculate_financing(params)
    assert fin.debt_eur == 0.0
    assert fin.annual_debt_service_eur == 0.0
    assert fin.monthly_debt_service_eur == 0.0
    assert fin.total_interest_paid_eur == 0.0


# ---------------------------------------------------------------------------
# PICASSO compression edge cases.
# ---------------------------------------------------------------------------
def test_picasso_compression_disabled_with_high_year(monkeypatch):
    """``picasso_go_live_year`` past projection horizon → no PICASSO step-down.

    Pydantic caps the field at 15 (matches ``loan_term_years`` etc.); the
    cashflow projection horizon is max(loan_term_years, 10, warranty_years),
    so setting go-live to 15 with a 10y loan/10y horizon means PICASSO never
    fires within the projected window — equivalent to the "disabled" branch.
    """
    svc = InvestmentService()
    monkeypatch.setattr(
        svc.fr_service, "simulate",
        lambda _p: (_ for _ in ()).throw(FileNotFoundError("force fallback")),
    )
    monkeypatch.setattr(
        svc.pzu_service, "simulate",
        lambda _p: (_ for _ in ()).throw(FileNotFoundError("force fallback")),
    )
    # Use loan_term_years=5 + warranty_years=5 so projection horizon = 10,
    # and go-live at 15 → never fires.
    params = _base_investment_params(
        loan_term_years=5,
        warranty_years=5,
        picasso_go_live_year=15,
        capacity_price_compression_pct_per_year=0.0,
        capacity_price_compression_floor_pct=100.0,
    )
    resp = svc.analyze(params)
    cf = resp.fr_cashflow
    # All projected years must be < picasso_go_live_year=15.
    assert all(c.year < 15 for c in cf)
    # With PICASSO never firing in the projected window and zero compression,
    # gross_revenue ratios match capacity_factor ratios exactly.
    for c in cf:
        expected = c.capacity_factor / cf[0].capacity_factor
        actual = c.gross_revenue_eur / cf[0].gross_revenue_eur
        assert math.isclose(actual, expected, rel_tol=1e-6)


def test_picasso_compression_zero_pct(monkeypatch):
    """``picasso_one_time_compression_pct=0`` → factor=1, identical to PICASSO disabled.

    With go-live=2 (within window) but drop=0%, the revenue trajectory must
    match the projection where go-live is past the horizon (15) — both should
    produce identical PICASSO factors of 1.0 every year.
    """
    svc = InvestmentService()
    monkeypatch.setattr(
        svc.fr_service, "simulate",
        lambda _p: (_ for _ in ()).throw(FileNotFoundError("force fallback")),
    )
    monkeypatch.setattr(
        svc.pzu_service, "simulate",
        lambda _p: (_ for _ in ()).throw(FileNotFoundError("force fallback")),
    )
    params_zero = _base_investment_params(
        loan_term_years=5,
        warranty_years=5,
        picasso_go_live_year=2,
        picasso_one_time_compression_pct=0.0,
        capacity_price_compression_pct_per_year=0.0,
        capacity_price_compression_floor_pct=100.0,
    )
    params_none = _base_investment_params(
        loan_term_years=5,
        warranty_years=5,
        picasso_go_live_year=15,
        picasso_one_time_compression_pct=0.0,
        capacity_price_compression_pct_per_year=0.0,
        capacity_price_compression_floor_pct=100.0,
    )
    resp_zero = svc.analyze(params_zero)
    resp_none = svc.analyze(params_none)
    for cf_zero, cf_none in zip(resp_zero.fr_cashflow, resp_none.fr_cashflow):
        assert math.isclose(
            cf_zero.gross_revenue_eur, cf_none.gross_revenue_eur, rel_tol=1e-9
        )


# ---------------------------------------------------------------------------
# Compliance gates / tariff exemption warnings.
# ---------------------------------------------------------------------------
def test_compliance_gates_warning_when_tariff_opted_in_with_unqualified_metering():
    """include_tariff_exemption=True + ComplianceGates() (all not_declared) → warning."""
    svc = InvestmentService()
    params = _base_investment_params(
        include_tariff_exemption=True,
        compliance_gates=ComplianceGates(),
    )
    resp = svc.analyze(params)
    assert any(
        "Tariff exemption included" in w and "metering qualification" in w
        for w in resp.warnings
    )


def test_compliance_gates_blocked_streams_warning():
    """ComplianceGates() (all not_declared) surfaces blocked-streams warning."""
    svc = InvestmentService()
    params = _base_investment_params(compliance_gates=ComplianceGates())
    resp = svc.analyze(params)
    assert resp.compliance_revenue_streams_blocked  # non-empty
    assert any("Compliance gates not satisfied" in w for w in resp.warnings)


# ---------------------------------------------------------------------------
# Sensitivity / monte_carlo.
# ---------------------------------------------------------------------------
def test_run_sensitivity_default_config():
    """run_sensitivity with default SensitivityConfig finishes and returns runs > 0."""
    svc = InvestmentService()
    params = _base_investment_params()
    cfg = SensitivityConfig(runs=20, seed=3)  # tiny — keep test fast
    report = svc.run_sensitivity(params, cfg)
    assert report.runs == 20
    # IRR samples may be empty if all runs degenerate, but normally we get some.
    assert isinstance(report.irr_samples, list)


# ---------------------------------------------------------------------------
# FR _get_activation_price fallback (line 163).
# ---------------------------------------------------------------------------
def test_get_activation_price_fallback_when_column_missing():
    """No matching column → fallback default (175 for UP, -30 for DOWN)."""
    import pandas as pd

    svc = FRService()
    empty_df = pd.DataFrame({"foo": [1, 2, 3]})  # no afrr_*_price_eur columns
    up = svc._get_activation_price(empty_df, "aFRR+")
    down = svc._get_activation_price(empty_df, "aFRR-")
    assert up == 175.0
    assert down == -30.0


def test_get_activation_price_fallback_when_only_outliers():
    """All prices outside (0, 500) abs band → fallback (line 162-163)."""
    import pandas as pd

    svc = FRService()
    # All zeros → filtered out by `prices.abs() > 0`
    df = pd.DataFrame({
        "afrr_up_price_eur": [0.0, 0.0, 0.0],
        "afrr_down_price_eur": [600.0, -700.0, 0.0],  # all outside ±500
    })
    assert svc._get_activation_price(df, "aFRR+") == 175.0
    assert svc._get_activation_price(df, "aFRR-") == -30.0


def test_get_activation_price_uses_mfrr_columns_when_not_afrr():
    """For non-aFRR products, the mfrr_*_scheduled_price_eur columns are read."""
    import pandas as pd

    svc = FRService()
    df = pd.DataFrame({
        "mfrr_up_scheduled_price_eur": [100.0, 200.0, 150.0],
        "mfrr_down_scheduled_price_eur": [-40.0, -20.0, -10.0],
    })
    up = svc._get_activation_price(df, "mFRR+")
    down = svc._get_activation_price(df, "mFRR-")
    assert math.isclose(up, 150.0, rel_tol=1e-6)
    assert math.isclose(down, -23.333, abs_tol=0.01)


# ---------------------------------------------------------------------------
# FR _avg_activation_price_for_product — volume_weighted + edge cases.
# ---------------------------------------------------------------------------
def test_avg_activation_price_volume_weighted_no_activation():
    """volume_weighted with no activation (>0) data → falls back to slot-weighted."""
    import pandas as pd

    svc = FRService()
    df = pd.DataFrame({
        "afrr_up_price_eur": [100.0, 200.0, 300.0],
        "afrr_up_activated_mwh": [0.0, 0.0, 0.0],  # no activation
    })
    # volume_weighted should fall through to slot-weighted mean = 200.0
    avg = svc._avg_activation_price_for_product(df, "aFRR", pricing_mode="volume_weighted")
    assert math.isclose(avg, 200.0, rel_tol=1e-6)


def test_avg_activation_price_volume_weighted_active():
    """volume_weighted with activation > 0 → MWh-weighted mean."""
    import pandas as pd

    svc = FRService()
    df = pd.DataFrame({
        "afrr_up_price_eur": [100.0, 200.0, 300.0],
        "afrr_up_activated_mwh": [10.0, 0.0, 30.0],  # weights: 10, _, 30
    })
    # Expected: (100×10 + 300×30) / (10+30) = 10000/40 = 250.0
    avg = svc._avg_activation_price_for_product(df, "aFRR", pricing_mode="volume_weighted")
    assert math.isclose(avg, 250.0, rel_tol=1e-6)


def test_avg_activation_price_unknown_product_returns_zero():
    """Unknown product key → return 0.0 (line 597 path)."""
    import pandas as pd

    svc = FRService()
    df = pd.DataFrame({"afrr_up_price_eur": [100.0, 200.0]})
    avg = svc._avg_activation_price_for_product(df, "FCR")  # not in col_map
    assert avg == 0.0


def test_avg_activation_price_no_valid_prices():
    """All zero prices → no valid samples → 0.0 (line 602)."""
    import pandas as pd

    svc = FRService()
    df = pd.DataFrame({"afrr_up_price_eur": [0.0, 0.0, 0.0]})
    avg = svc._avg_activation_price_for_product(df, "aFRR")
    assert avg == 0.0


# ---------------------------------------------------------------------------
# compute_multi_product_revenue — regime filter / unknown product.
# ---------------------------------------------------------------------------
def test_compute_multi_product_revenue_with_post_regime_filter():
    """regulatory_regime_filter='post_order60_2024_pay_as_bid' filters to post window."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(span_regime_change=True, n_days=30))
    req = FRMultiProductRequest(
        products=["aFRR"],
        power_mw=10.0,
        capacity_mwh=20.0,
        target_date=date(2025, 1, 1),
        regulatory_regime_filter="post_order60_2024_pay_as_bid",
    )
    response = svc.compute_multi_product_revenue(req)
    assert response.regulatory_regime_used == "post_order60_2024_pay_as_bid"
    # Row counts dict should only contain post regime
    assert "post_order60_2024_pay_as_bid" in response.regime_row_counts


def test_compute_multi_product_revenue_with_pre_regime_filter():
    """regulatory_regime_filter='pre_order60_2024_marginal' filters to pre window."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(span_regime_change=True, n_days=15))
    req = FRMultiProductRequest(
        products=["aFRR"],
        power_mw=10.0,
        capacity_mwh=20.0,
        target_date=date(2025, 1, 1),
        regulatory_regime_filter="pre_order60_2024_marginal",
    )
    response = svc.compute_multi_product_revenue(req)
    assert response.regulatory_regime_used == "pre_order60_2024_marginal"


def test_compute_multi_product_revenue_empty_window_raises():
    """Filter to a window with no rows → ValueError (line 638-641)."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=10))
    req = FRMultiProductRequest(
        products=["aFRR"],
        power_mw=10.0,
        start_date=date(2099, 1, 1),
        end_date=date(2099, 12, 31),
    )
    with pytest.raises(ValueError, match="No FR data in the requested window"):
        svc.compute_multi_product_revenue(req)


def test_compute_multi_product_revenue_multiple_products_split_warning():
    """Two products → physical-power split violation warning (line 676)."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=15))
    req = FRMultiProductRequest(
        products=["aFRR", "mFRR"],
        power_mw=10.0,
        capacity_mwh=20.0,
        target_date=date(2025, 1, 1),
    )
    response = svc.compute_multi_product_revenue(req)
    assert any("physical-power constraint" in v for v in response.min_bid_violations)


def test_compute_multi_product_revenue_zero_activation_warning():
    """Window where one product has zero activation → warning (line 720)."""
    import pandas as pd

    svc = FRService()
    df = _make_synthetic_fr_df(n_days=10)
    # Force mFRR activations to 0 across the window
    df.loc[:, "mfrr_up_activated_mwh"] = 0.0
    df.loc[:, "mfrr_down_activated_mwh"] = 0.0
    _seed_fr(svc, df)
    req = FRMultiProductRequest(
        products=["mFRR"],
        power_mw=10.0,
        capacity_mwh=20.0,
        target_date=date(2025, 1, 1),
    )
    response = svc.compute_multi_product_revenue(req)
    assert any(
        "zero market activation" in v or "FCR: dataset reports zero" in v
        for v in response.min_bid_violations
    )


# ---------------------------------------------------------------------------
# FR get_monthly_breakdown — covers lines 805-824.
# ---------------------------------------------------------------------------
def test_get_monthly_breakdown_default():
    """get_monthly_breakdown returns one row per month for the default product."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=40))  # spans 2 months
    out = svc.get_monthly_breakdown()  # default: aFRR+
    assert isinstance(out, list)
    assert len(out) >= 1
    sample = out[0]
    assert "month" in sample
    assert "slots" in sample
    assert "avg_price" in sample
    assert "pct_negative" in sample


def test_get_monthly_breakdown_down_product():
    """get_monthly_breakdown with a DOWN product reads the down price column."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=40))
    out = svc.get_monthly_breakdown(product="aFRR-")
    assert isinstance(out, list)
    assert len(out) >= 1


# ---------------------------------------------------------------------------
# FR empty-data error branches.
# ---------------------------------------------------------------------------
def test_simulate_raises_on_empty_window(tmp_path):
    """When date filter strips all rows, simulate raises ValueError (lines 305-306)."""
    import pandas as pd
    from app.models.fr import FRSimulationParams

    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=5))
    params = FRSimulationParams(
        start_date=date(2099, 1, 1),
        end_date=date(2099, 12, 31),
    )
    with pytest.raises(ValueError, match="No data available"):
        svc.simulate(params)


def test_simulate_raises_when_no_products_enabled():
    """All product configs disabled → ValueError 'No products enabled' (line 325)."""
    from app.models.fr import FRProductConfig, FRSimulationParams

    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=5))
    params = FRSimulationParams(
        afrr_up=FRProductConfig(enabled=False, power_mw=0.0),
        afrr_down=FRProductConfig(enabled=False, power_mw=0.0),
        mfrr_up=FRProductConfig(enabled=False, power_mw=0.0),
        mfrr_down=FRProductConfig(enabled=False, power_mw=0.0),
    )
    with pytest.raises(ValueError, match="No products enabled"):
        svc.simulate(params)


def test_analyze_bidding_strategy_empty_data_returns_error():
    """Empty df → 'No data available' error (line 985)."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=5))
    out = svc.analyze_bidding_strategy(start_date="2099-01-01", end_date="2099-12-31")
    assert "error" in out


def test_calculate_optimal_bids_empty_window():
    """Date with no surrounding data → error (line 1108)."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=5))
    out = svc.calculate_optimal_bids(date_str="2099-06-15", power_mw=10.0)
    assert "error" in out


def _seed_empty_fr(svc: FRService, columns: List[str]) -> None:
    """Seed with an empty DataFrame, bypassing _seed_fr's date-bounds metadata."""
    import pandas as pd

    svc._fr_data = pd.DataFrame(columns=columns)
    svc._fr_metadata = {
        "source_kind": "synthetic_test",
        "data_date_min": None,
        "data_date_max": None,
        "bankability_level": "historical_backtest_only",
        "settlement_grade": False,
        "source_file": None,
    }


def test_project_annual_revenue_empty_data_returns_error():
    """Empty df → 'No historical data available' (line 1252)."""
    svc = FRService()
    _seed_empty_fr(svc, [
        "date", "slot", "afrr_up_price_eur", "afrr_down_price_eur",
        "afrr_up_activated_mwh", "afrr_down_activated_mwh",
    ])
    out = svc.project_annual_revenue(power_mw=10.0)
    assert "error" in out


def test_calculate_safe_bid_prices_empty_data_returns_error():
    """Empty df → 'No historical data available' (line 1426)."""
    svc = FRService()
    _seed_empty_fr(svc, [
        "date", "slot", "afrr_up_price_eur", "afrr_down_price_eur",
    ])
    out = svc.calculate_safe_bid_prices(power_mw=10.0)
    assert "error" in out


# ---------------------------------------------------------------------------
# FR _compute_monthly_revenue scenario fallback (lines 270-272).
# ---------------------------------------------------------------------------
def test_simulate_uses_scenario_fallback_when_activation_column_missing():
    """When activation MWh column is absent → pricing_basis='scenario'.

    Build a synthetic frame WITHOUT afrr_up_activated_mwh / afrr_down_activated_mwh
    so _compute_monthly_revenue takes the duty-cycle fallback branch.
    """
    import pandas as pd
    import numpy as np
    from app.models.fr import FRSimulationParams, FRProductConfig

    rng = np.random.default_rng(0)
    days = [pd.Timestamp("2025-01-01") + pd.Timedelta(days=i) for i in range(5)]
    rows = []
    for day in days:
        regime = regulatory_regime_for_date(day.date())
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                "afrr_up_price_eur": float(rng.normal(150.0, 30.0)),
                "afrr_down_price_eur": float(rng.normal(-25.0, 20.0)),
                # NO activation columns → scenario branch triggered
                "regulatory_regime": regime,
            })
    df = pd.DataFrame(rows)

    svc = FRService()
    _seed_fr(svc, df)
    params = FRSimulationParams(
        afrr_up=FRProductConfig(power_mw=10.0),
        afrr_down=FRProductConfig(enabled=False, power_mw=0.0),
        mfrr_up=FRProductConfig(enabled=False, power_mw=0.0),
        mfrr_down=FRProductConfig(enabled=False, power_mw=0.0),
    )
    response = svc.simulate(params)
    assert all(m.pricing_basis == "scenario" for m in response.monthly_results)
    assert all(m.activation_method == "duty_cycle_fallback" for m in response.monthly_results)


# ---------------------------------------------------------------------------
# analyze_bidding_strategy — recommendation branches (lines 1049-1054).
# ---------------------------------------------------------------------------
def test_analyze_bidding_strategy_recommendations_cover_branches():
    """Build datasets where the up/down profitability ratio lands in each band.

    The recommendation string depends on
        ratio = avg_up_price / abs(avg_down_price)
    Bands: >2.0, >1.5, >0.8, else. Build three synthetic datasets so each
    branch fires.
    """
    import pandas as pd
    import numpy as np

    def _build_df(up_mean: float, down_mean: float):
        rng = np.random.default_rng(42)
        days = [pd.Timestamp("2025-03-01") + pd.Timedelta(days=i) for i in range(10)]
        rows = []
        for day in days:
            regime = regulatory_regime_for_date(day.date())
            for s in range(96):
                rows.append({
                    "date": day,
                    "slot": s,
                    "afrr_up_price_eur": float(rng.normal(up_mean, 5.0)),
                    "afrr_down_price_eur": float(rng.normal(down_mean, 5.0)),
                    "afrr_up_activated_mwh": float(rng.uniform(0.5, 2.0)),
                    "afrr_down_activated_mwh": float(rng.uniform(0.5, 2.0)),
                    "regulatory_regime": regime,
                })
        return pd.DataFrame(rows)

    # Ratio > 2.0  → first branch
    svc1 = FRService()
    _seed_fr(svc1, _build_df(up_mean=300.0, down_mean=-50.0))  # ratio = 6
    out1 = svc1.analyze_bidding_strategy()
    assert "significantly more profitable" in out1["profitability_comparison"]["recommendation"]

    # Ratio in (1.5, 2.0] → second branch
    svc2 = FRService()
    _seed_fr(svc2, _build_df(up_mean=180.0, down_mean=-100.0))  # ratio ≈ 1.8
    out2 = svc2.analyze_bidding_strategy()
    rec2 = out2["profitability_comparison"]["recommendation"]
    assert "more profitable" in rec2 and "Prefer UP" in rec2

    # Ratio in (0.8, 1.5] → third branch
    svc3 = FRService()
    _seed_fr(svc3, _build_df(up_mean=100.0, down_mean=-100.0))  # ratio = 1.0
    out3 = svc3.analyze_bidding_strategy()
    assert "similarly profitable" in out3["profitability_comparison"]["recommendation"]

    # Ratio ≤ 0.8 → fourth branch (down more profitable)
    svc4 = FRService()
    _seed_fr(svc4, _build_df(up_mean=50.0, down_mean=-200.0))  # ratio = 0.25
    out4 = svc4.analyze_bidding_strategy()
    assert "aFRR-" in out4["profitability_comparison"]["recommendation"]


# ---------------------------------------------------------------------------
# calculate_optimal_bids — fallback when target date has no exact match.
# ---------------------------------------------------------------------------
def test_calculate_optimal_bids_target_date_outside_data_uses_fallback():
    """When target_date is in the lookback window but has no exact-match rows
    in historical_data, the fallback branch (lines 1193-1196) fires.

    To trigger this, we seed data with a 1-day GAP at target_date — surrounding
    window has rows but the exact date does not.
    """
    import pandas as pd
    import numpy as np

    rng = np.random.default_rng(1)
    rows = []
    for offset in [-30, -15, -5, 5, 15, 30]:  # skips offset=0 (the target)
        day = pd.Timestamp("2025-03-15") + pd.Timedelta(days=offset)
        regime = regulatory_regime_for_date(day.date())
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                "afrr_up_price_eur": float(rng.normal(150.0, 30.0)),
                "afrr_down_price_eur": float(rng.normal(-25.0, 20.0)),
                "afrr_up_activated_mwh": float(rng.uniform(0.5, 2.0)),
                "afrr_down_activated_mwh": float(rng.uniform(0.5, 2.0)),
                "regulatory_regime": regime,
            })
    df = pd.DataFrame(rows)
    svc = FRService()
    _seed_fr(svc, df)

    out = svc.calculate_optimal_bids(date_str="2025-03-15", power_mw=10.0)
    assert "error" not in out
    # Falls back to estimated approach (lines 1193-1196)
    assert out["historical_data_points"] == 6 * 96


# ---------------------------------------------------------------------------
# project_annual_revenue — month with no valid prices is skipped (line 1296).
# ---------------------------------------------------------------------------
def test_project_annual_revenue_skips_month_with_no_valid_prices():
    """A month where all prices are 0 / out-of-band should be skipped."""
    import pandas as pd
    import numpy as np

    rng = np.random.default_rng(2)
    rows = []
    # Month 1: all zero prices → skipped
    for day_idx in range(15):
        day = pd.Timestamp("2025-01-01") + pd.Timedelta(days=day_idx)
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                "afrr_up_price_eur": 0.0,
                "afrr_down_price_eur": 0.0,
                "afrr_up_activated_mwh": 1.0,
                "afrr_down_activated_mwh": 1.0,
                "regulatory_regime": regulatory_regime_for_date(day.date()),
            })
    # Month 2: real prices → kept
    for day_idx in range(15):
        day = pd.Timestamp("2025-02-01") + pd.Timedelta(days=day_idx)
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                "afrr_up_price_eur": float(rng.normal(150.0, 20.0)),
                "afrr_down_price_eur": float(rng.normal(-25.0, 10.0)),
                "afrr_up_activated_mwh": 1.0,
                "afrr_down_activated_mwh": 1.0,
                "regulatory_regime": regulatory_regime_for_date(day.date()),
            })
    df = pd.DataFrame(rows)
    svc = FRService()
    _seed_fr(svc, df)
    out = svc.project_annual_revenue(power_mw=10.0, strategy="balanced")
    # Only month 2 produces a projection
    assert out["months_analyzed"] == 1


# ---------------------------------------------------------------------------
# project_annual_revenue — afrr_up > afrr_down branch (lines 1374-1375).
# ---------------------------------------------------------------------------
def test_project_annual_revenue_picks_afrr_up_when_more_profitable():
    """Build a dataset where aFRR+ revenue dominates so 'aFRR+' branch fires."""
    import pandas as pd
    import numpy as np

    rng = np.random.default_rng(3)
    rows = []
    for day_idx in range(20):
        day = pd.Timestamp("2025-04-01") + pd.Timedelta(days=day_idx)
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                # Very high up prices, near-zero down
                "afrr_up_price_eur": float(rng.normal(400.0, 10.0)),
                "afrr_down_price_eur": float(rng.normal(-1.0, 0.1)),
                "afrr_up_activated_mwh": 3.0,
                "afrr_down_activated_mwh": 0.05,
                "regulatory_regime": regulatory_regime_for_date(day.date()),
            })
    df = pd.DataFrame(rows)
    svc = FRService()
    _seed_fr(svc, df)
    out = svc.project_annual_revenue(power_mw=10.0, strategy="balanced")
    assert out["months_analyzed"] >= 1
    # All months should select aFRR+ given the price signal
    assert any(m["selected_service"] == "aFRR+" for m in out["monthly_projections"])


# ---------------------------------------------------------------------------
# calculate_optimal_bids — capacity_mwh override (Branch 1 reduction).
# ---------------------------------------------------------------------------
def test_calculate_optimal_bids_capacity_mwh_override_changes_activation_revenue():
    """Doubling the per-call capacity_mwh must scale the battery-throughput
    cap and therefore the activation-revenue component (capacity-bid component
    is independent of throughput, so it should not move).
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(11)
    rows = []
    target = pd.Timestamp("2025-03-15")
    for offset in range(-30, 31):
        day = target + pd.Timedelta(days=offset)
        regime = regulatory_regime_for_date(day.date())
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                "afrr_up_price_eur": float(rng.normal(150.0, 30.0)),
                "afrr_down_price_eur": float(rng.normal(-25.0, 20.0)),
                "afrr_up_activated_mwh": float(rng.uniform(1.0, 3.0)),
                "afrr_down_activated_mwh": float(rng.uniform(1.0, 3.0)),
                "regulatory_regime": regime,
            })
    df = pd.DataFrame(rows)
    svc = FRService()
    _seed_fr(svc, df)

    out_small = svc.calculate_optimal_bids(
        date_str="2025-03-15", power_mw=10.0, capacity_mwh=10.0,
    )
    out_big = svc.calculate_optimal_bids(
        date_str="2025-03-15", power_mw=10.0, capacity_mwh=40.0,
    )
    assert "error" not in out_small and "error" not in out_big

    # Capacity bids are throughput-independent → identical across calls.
    assert (
        out_small["optimal_bids"]["afrr_up"]["recommended_capacity_bid"]
        == out_big["optimal_bids"]["afrr_up"]["recommended_capacity_bid"]
    )
    # Activation-revenue depends on the throughput cap. With market-share
    # path active and ample market activations, the larger cap should
    # produce strictly larger activation revenue.
    act_small = out_small["optimal_bids"]["afrr_up"]["activation_component"]
    act_big = out_big["optimal_bids"]["afrr_up"]["activation_component"]
    assert act_big > act_small


def test_calculate_optimal_bids_capacity_mwh_default_matches_settings():
    """Omitting capacity_mwh must use settings.DEFAULT_CAPACITY_MWH (the
    same anchor pattern used elsewhere in the file). Passing the same
    explicit value must produce an identical result.
    """
    import numpy as np
    import pandas as pd

    from app.config import settings

    rng = np.random.default_rng(12)
    rows = []
    target = pd.Timestamp("2025-03-15")
    for offset in range(-30, 31):
        day = target + pd.Timedelta(days=offset)
        regime = regulatory_regime_for_date(day.date())
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                "afrr_up_price_eur": float(rng.normal(150.0, 30.0)),
                "afrr_down_price_eur": float(rng.normal(-25.0, 20.0)),
                "afrr_up_activated_mwh": float(rng.uniform(1.0, 3.0)),
                "afrr_down_activated_mwh": float(rng.uniform(1.0, 3.0)),
                "regulatory_regime": regime,
            })
    df = pd.DataFrame(rows)
    svc = FRService()
    _seed_fr(svc, df)

    out_default = svc.calculate_optimal_bids(date_str="2025-03-15", power_mw=10.0)
    out_explicit = svc.calculate_optimal_bids(
        date_str="2025-03-15",
        power_mw=10.0,
        capacity_mwh=float(settings.DEFAULT_CAPACITY_MWH),
    )
    assert out_default == out_explicit


def test_calculate_optimal_bids_capacity_mwh_zero_or_negative_raises():
    """capacity_mwh ≤ 0 must raise ValueError before any work is done."""
    svc = FRService()
    _seed_fr(svc, _make_synthetic_fr_df(n_days=5))

    with pytest.raises(ValueError):
        svc.calculate_optimal_bids(date_str="2025-01-15", power_mw=10.0, capacity_mwh=0)
    with pytest.raises(ValueError):
        svc.calculate_optimal_bids(date_str="2025-01-15", power_mw=10.0, capacity_mwh=-5)
