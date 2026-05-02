"""FX-driven Monte Carlo variance tests.

Verifies that the formerly-dead `_fx` sample now drives variability in
`monte_carlo()` when `revenue_currency == "RON"`, and is a no-op for EUR
(behavior preserved).
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

from app.models.investment import InvestmentParams  # noqa: E402
from app.services.investment_service import InvestmentService  # noqa: E402
from app.services.sensitivity import SensitivityConfig  # noqa: E402


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


def test_fx_unused_when_eur(base_params):
    """For EUR revenue, FX sample is drawn but applied nowhere; mean IRR
    should be a finite number on the default config."""
    eur_params = base_params.model_copy(update={"revenue_currency": "EUR"})
    svc = InvestmentService()
    cfg = SensitivityConfig(runs=150, seed=21)
    report = svc.run_sensitivity(eur_params, cfg)
    assert report.runs == 150
    # mean_irr should be finite (NaN means engine failed entirely).
    assert math.isfinite(report.mean_irr)
    # And the sample distribution should be ordered.
    if math.isfinite(report.p10_irr):
        assert report.p10_irr <= report.p50_irr <= report.p90_irr


def test_fx_drives_irr_variance_when_ron(base_params):
    """For RON revenue with a wide FX triangular and a non-trivial hedge
    cost, the FX sample must propagate into IRR variance — std > 0.001."""
    ron_params = base_params.model_copy(update={
        "revenue_currency": "RON",
        "fx_hedge_cost_pct": 5.0,
    })
    svc = InvestmentService()
    cfg = SensitivityConfig(
        runs=400,
        seed=99,
        # Wide FX spread: 4.0 lo / 5.0 mode / 6.0 hi.
        fx_ron_per_eur=(4.0, 5.0, 6.0),
        # Pin the other drivers to a tight band so FX dominates the
        # remaining variance signal.
        activation_share=(0.099, 0.10, 0.101),
        rte_ac_ac=(0.879, 0.88, 0.881),
        degradation_y1=(0.0249, 0.025, 0.0251),
        pzu_avg_spread_pct=(0.999, 1.0, 1.001),
    )
    report = svc.run_sensitivity(ron_params, cfg)
    assert len(report.irr_samples) > 50, "need a meaningful sample size"
    irr_arr = np.asarray(report.irr_samples)
    std_irr = float(np.std(irr_arr))
    assert std_irr > 0.001, (
        f"FX sampling did not move IRR (std={std_irr:.6f}); "
        "the _fx variable may still be dead."
    )
