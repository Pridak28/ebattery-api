"""
Phase F1 — Monte Carlo sensitivity for the investment model.

Replaces the deterministic single-point IRR with P10 / P50 / P90 fan over
the high-leverage drivers a lender or investor will stress-test:

  - activation_share        (0.05, 0.10, 0.20)  triangular
  - rte_ac_ac               (0.85, 0.88, 0.90)  triangular
  - degradation_y1          (0.020, 0.025, 0.035)  triangular
  - fx_ron_per_eur (info)   (4.85, 5.00, 5.20)  triangular  (informational)
  - pzu_avg_spread_pct      (0.85, 1.00, 1.15)  triangular  (multiplier on PZU revenue)

Each Monte Carlo run rebuilds the cashflow via
``InvestmentService._create_cashflow`` so the stochastic outputs are fully
consistent with the deterministic engine.

Returns IRR / NPV / payback percentiles and the raw sample arrays so the
frontend can render a fan chart.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
from pydantic import BaseModel, Field

from app.models.investment import AnnualCashflow, InvestmentParams


def _triangular(rng: np.random.Generator, lo: float, mode: float, hi: float) -> float:
    """np.random Generator triangular sampler with safe ordering."""
    lo, mode, hi = sorted([float(lo), float(mode), float(hi)])
    if lo == hi:
        return float(lo)
    if mode <= lo:
        mode = lo + 1e-9
    if mode >= hi:
        mode = hi - 1e-9
    return float(rng.triangular(lo, mode, hi))


def _irr(cashflows: List[float], guess: float = 0.1, tol: float = 1e-6, max_iter: int = 200) -> float:
    """Newton-Raphson IRR; falls back to bisection if Newton diverges.

    ``cashflows[0]`` is typically the year-0 outflow (negative). Returns
    NaN if no IRR can be found (all positive or all negative flows).
    """
    arr = np.asarray(cashflows, dtype=float)
    if arr.size < 2:
        return float("nan")
    if not (np.any(arr > 0) and np.any(arr < 0)):
        return float("nan")

    # Newton-Raphson on NPV.
    rate = float(guess)
    for _ in range(max_iter):
        denom = (1.0 + rate) ** np.arange(arr.size)
        npv = float(np.sum(arr / denom))
        deriv = float(np.sum(-np.arange(arr.size) * arr / (denom * (1.0 + rate))))
        if abs(deriv) < 1e-12:
            break
        new_rate = rate - npv / deriv
        if not np.isfinite(new_rate):
            break
        if abs(new_rate - rate) < tol:
            return float(new_rate)
        rate = new_rate
        if rate <= -0.99:
            rate = -0.99 + 1e-3

    # Bisection fallback.
    lo, hi = -0.99, 10.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        denom_lo = (1.0 + lo) ** np.arange(arr.size)
        denom_mid = (1.0 + mid) ** np.arange(arr.size)
        npv_lo = float(np.sum(arr / denom_lo))
        npv_mid = float(np.sum(arr / denom_mid))
        if abs(npv_mid) < tol:
            return float(mid)
        if npv_lo * npv_mid < 0:
            hi = mid
        else:
            lo = mid
    return float(mid)


def _npv(cashflows: List[float], discount_rate: float) -> float:
    arr = np.asarray(cashflows, dtype=float)
    denom = (1.0 + discount_rate) ** np.arange(arr.size)
    return float(np.sum(arr / denom))


def _payback_years(cashflows: List[float]) -> float:
    """First year cumulative cashflow turns positive (linear interpolation).

    ``cashflows[0]`` should be the year-0 capex outflow. Returns +inf if the
    project never breaks even within the projection horizon.
    """
    cumulative = 0.0
    prev = 0.0
    for i, cf in enumerate(cashflows):
        cumulative += cf
        if cumulative >= 0 and i > 0:
            return float(i - 1 + (-prev) / cf) if cf > 0 else float(i)
        prev = cumulative
    return float("inf")


class SensitivityConfig(BaseModel):
    """Triangular distributions for the five sampled drivers."""
    runs: int = Field(1000, ge=10, le=20000)
    discount_rate: float = Field(0.08, ge=0.0, le=0.30)
    activation_share: Tuple[float, float, float] = (0.05, 0.10, 0.20)
    rte_ac_ac: Tuple[float, float, float] = (0.85, 0.88, 0.90)
    degradation_y1: Tuple[float, float, float] = (0.020, 0.025, 0.035)
    fx_ron_per_eur: Tuple[float, float, float] = (4.85, 5.00, 5.20)
    pzu_avg_spread_pct: Tuple[float, float, float] = (0.85, 1.00, 1.15)
    seed: int = Field(42, ge=0)


class SensitivityReport(BaseModel):
    """Summary statistics + raw IRR samples for fan-chart rendering."""
    runs: int
    p10_irr: float
    p50_irr: float
    p90_irr: float
    p10_npv: float
    p50_npv: float
    p90_npv: float
    p10_payback_yr: float
    p50_payback_yr: float
    p90_payback_yr: float
    mean_irr: float
    irr_samples: List[float] = Field(default_factory=list, description="Sample IRRs (clipped to first 1000 entries)")


def monte_carlo(
    params: InvestmentParams,
    fr_revenue_y1: Dict[str, float],
    pzu_revenue_y1: Dict[str, float],
    operating_cost_y1: float,
    annual_debt_service: float,
    equity_eur: float,
    cfg: SensitivityConfig,
    create_cashflow,
) -> SensitivityReport:
    """Run ``cfg.runs`` Monte Carlo draws over the 5 sampled drivers.

    ``create_cashflow`` is injected (typically ``InvestmentService._create_cashflow``)
    to keep this module pure and testable.
    """
    rng = np.random.default_rng(cfg.seed)
    irrs: List[float] = []
    npvs: List[float] = []
    paybacks: List[float] = []

    base_pzu_revenue = float(pzu_revenue_y1.get("gross_revenue", 0.0))
    base_pzu_cost = float(pzu_revenue_y1.get("energy_cost", 0.0))
    base_fr_revenue = float(fr_revenue_y1.get("gross_revenue", 0.0))
    base_fr_cost = float(fr_revenue_y1.get("energy_cost", 0.0))

    for _ in range(cfg.runs):
        spread_mult = _triangular(rng, *cfg.pzu_avg_spread_pct)
        act_share = _triangular(rng, *cfg.activation_share)
        rte = _triangular(rng, *cfg.rte_ac_ac)
        deg = _triangular(rng, *cfg.degradation_y1)
        # FX is informational here — we don't switch currency mid-run, but
        # apply the hedge cost as if fx_hedge_cost_pct already captures the
        # spread. Sampling is reserved for future RON-revenue scenarios.
        _fx = _triangular(rng, *cfg.fx_ron_per_eur)

        sampled = params.model_copy(update={
            "rte_ac_ac": rte,
            "degradation_rate_pct": deg * 100.0,
        })

        # Approximate sampled revenue.
        # PZU scales with spread multiplier; activation_share linearly scales
        # FR activation revenue (we conservatively scale total FR gross by
        # activation_share / mid-mode to avoid over-attribution).
        mid_mode = float(cfg.activation_share[1]) or 0.10
        fr_scale = act_share / mid_mode if mid_mode > 0 else 1.0
        sampled_pzu_rev = base_pzu_revenue * spread_mult
        sampled_pzu_cost = base_pzu_cost * spread_mult
        sampled_fr_rev = base_fr_revenue * fr_scale
        sampled_fr_cost = base_fr_cost * fr_scale

        # Combined revenue assumes the operator runs both stacks, capped by
        # battery throughput (already enforced in the underlying simulators).
        gross_revenue_y1 = sampled_pzu_rev + sampled_fr_rev
        energy_cost_y1 = sampled_pzu_cost + sampled_fr_cost

        cashflow: List[AnnualCashflow] = create_cashflow(
            params.warranty_years if params.warranty_years > 0 else 15,
            gross_revenue_y1,
            energy_cost_y1,
            operating_cost_y1,
            annual_debt_service,
            params=sampled,
            epc_eur=float(params.total_investment_eur),
        )

        # Build cashflow vector for IRR/NPV: year 0 = -equity, then net per yr.
        cf_vec = [-float(equity_eur)] + [cf.net_profit_eur for cf in cashflow]
        irr_val = _irr(cf_vec)
        npv_val = _npv(cf_vec, cfg.discount_rate)
        payback_val = _payback_years(cf_vec)

        if np.isfinite(irr_val):
            irrs.append(irr_val)
        if np.isfinite(npv_val):
            npvs.append(npv_val)
        if np.isfinite(payback_val):
            paybacks.append(payback_val)

    if not irrs:
        # Degenerate case — return NaNs so the frontend can render a warning.
        nan = float("nan")
        return SensitivityReport(
            runs=cfg.runs,
            p10_irr=nan, p50_irr=nan, p90_irr=nan,
            p10_npv=nan, p50_npv=nan, p90_npv=nan,
            p10_payback_yr=nan, p50_payback_yr=nan, p90_payback_yr=nan,
            mean_irr=nan,
            irr_samples=[],
        )

    irrs_arr = np.asarray(irrs)
    npvs_arr = np.asarray(npvs) if npvs else np.array([float("nan")])
    paybacks_arr = np.asarray(paybacks) if paybacks else np.array([float("inf")])

    return SensitivityReport(
        runs=cfg.runs,
        p10_irr=float(np.percentile(irrs_arr, 10)),
        p50_irr=float(np.percentile(irrs_arr, 50)),
        p90_irr=float(np.percentile(irrs_arr, 90)),
        p10_npv=float(np.percentile(npvs_arr, 10)),
        p50_npv=float(np.percentile(npvs_arr, 50)),
        p90_npv=float(np.percentile(npvs_arr, 90)),
        p10_payback_yr=float(np.percentile(paybacks_arr, 10)),
        p50_payback_yr=float(np.percentile(paybacks_arr, 50)),
        p90_payback_yr=float(np.percentile(paybacks_arr, 90)),
        mean_irr=float(np.mean(irrs_arr)),
        irr_samples=[float(x) for x in irrs_arr[:1000].tolist()],
    )
