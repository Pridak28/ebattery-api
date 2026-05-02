"""Coverage tests for legacy / less-covered FRService methods.

Targets: get_market_stats, get_available_dates, get_slot_prices,
analyze_bidding_strategy, calculate_optimal_bids, calculate_safe_bid_prices,
project_annual_revenue.

These tests inject a synthetic DAMAS-shaped DataFrame directly into the
service's ``_fr_data`` cache to bypass the CSV loader. The legacy methods
all consume the cached DataFrame; synthetic data covers those code paths
identically and keeps the suite deterministic + fast.

Schema mirrors what ``_load_fr_data`` produces post-processing:
date, slot, afrr_up_price_eur, afrr_down_price_eur, afrr_up_activated_mwh,
afrr_down_activated_mwh, mfrr_up_activated_mwh, mfrr_down_activated_mwh,
mfrr_up_scheduled_price_eur, fcr_activated_mwh, regulatory_regime.
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data.quality import regulatory_regime_for_date  # noqa: E402
from app.services.fr_service import FRService  # noqa: E402


def _make_synthetic_fr_df(
    start: date = date(2025, 1, 1),
    n_days: int = 50,
    seed: int = 42,
):
    """Build a 96-slot × N-day DAMAS-shaped DataFrame.

    Prices follow a realistic pattern: aFRR+ positive (~150 EUR/MWh mean) with
    spread, aFRR- often negative (~ -25 EUR/MWh). Activations non-zero so
    market-share branches in optimal_bids/project_annual_revenue trigger.

    Imports numpy/pandas locally (per the same pytest-cov reload concern
    described in test_pzu_legacy_methods.py).
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    days = [pd.Timestamp(start) + pd.Timedelta(days=i) for i in range(n_days)]

    rows: list[dict] = []
    for day in days:
        regime = regulatory_regime_for_date(day.date())
        # 96 slots = 24h × 4 (15-min)
        up_prices = rng.normal(150.0, 40.0, size=96).clip(20.0, 480.0)
        down_prices = rng.normal(-25.0, 30.0, size=96).clip(-200.0, 100.0)
        mfrr_up_prices = rng.normal(180.0, 50.0, size=96).clip(30.0, 480.0)
        up_acts = rng.uniform(0.5, 4.0, size=96)
        down_acts = rng.uniform(0.5, 4.0, size=96)
        mfrr_up_acts = rng.uniform(0.0, 2.0, size=96)
        mfrr_down_acts = rng.uniform(0.0, 2.0, size=96)
        fcr_acts = rng.uniform(0.0, 1.0, size=96)
        for s in range(96):
            rows.append({
                "date": day,
                "slot": s,
                "afrr_up_price_eur": float(up_prices[s]),
                "afrr_down_price_eur": float(down_prices[s]),
                "afrr_up_activated_mwh": float(up_acts[s]),
                "afrr_down_activated_mwh": float(down_acts[s]),
                "mfrr_up_activated_mwh": float(mfrr_up_acts[s]),
                "mfrr_down_activated_mwh": float(mfrr_down_acts[s]),
                "mfrr_up_scheduled_price_eur": float(mfrr_up_prices[s]),
                "fcr_activated_mwh": float(fcr_acts[s]),
                "regulatory_regime": regime,
            })

    df = pd.DataFrame(rows)
    df.attrs["source_kind"] = "synthetic_test"
    df.attrs["settlement_grade"] = False
    return df


@pytest.fixture(scope="module")
def svc() -> FRService:
    """FRService with a pre-loaded synthetic DAMAS DataFrame."""
    s = FRService()
    s._fr_data = _make_synthetic_fr_df()
    s._fr_metadata = {
        "source_kind": "synthetic_test",
        "data_date_min": "2025-01-01",
        "data_date_max": "2025-02-19",
        "bankability_level": "historical_backtest_only",
        "settlement_grade": False,
        "source_file": None,
    }
    return s


# Window known to be present in the synthetic dataset (50 days from 2025-01-01).
START_STR = "2025-01-01"
END_STR = "2025-02-19"
KNOWN_DATE = "2025-01-15"


# ---------------------------------------------------------------------------
# get_market_stats
# ---------------------------------------------------------------------------

def test_get_market_stats_fr(svc: FRService) -> None:
    stats = svc.get_market_stats()

    assert isinstance(stats, dict)
    assert stats["total_slots"] > 0
    assert stats["total_slots"] == 50 * 96

    dr = stats["date_range"]
    assert dr["start"] <= dr["end"]

    afrr = stats["afrr_stats"]
    assert "up" in afrr and "down" in afrr
    avg = afrr["up"]["avg_price"]
    assert isinstance(avg, float)
    assert math.isfinite(avg)
    assert afrr["up"]["min_price"] <= avg <= afrr["up"]["max_price"]


# ---------------------------------------------------------------------------
# get_available_dates
# ---------------------------------------------------------------------------

def test_get_available_dates(svc: FRService) -> None:
    out = svc.get_available_dates()

    dates = out["dates"]
    assert isinstance(dates, list)
    assert len(dates) == 50

    sample = dates[0]
    assert "afrr_up_avg" in sample
    assert "afrr_down_avg" in sample
    assert "afrr_up_activations" in sample
    assert "afrr_down_activations" in sample
    assert isinstance(sample["afrr_up_avg"], float)
    assert sample["afrr_up_activations"] >= 0


# ---------------------------------------------------------------------------
# get_slot_prices
# ---------------------------------------------------------------------------

def test_get_slot_prices_basic(svc: FRService) -> None:
    out = svc.get_slot_prices(date_str=KNOWN_DATE, power_mw=10.0)

    # Sanity: not the error branch
    assert "error" not in out
    assert out["date"] == KNOWN_DATE

    slot_prices = out["slot_prices"]
    assert len(slot_prices) == 96

    # Each slot must have selected_service in {aFRR+, aFRR-} and revenue >= 0
    for sp in slot_prices:
        assert sp["selected_service"] in ("aFRR+", "aFRR-")
        assert sp["afrr_up_revenue"] >= 0
        assert sp["afrr_down_revenue"] >= 0
        # Battery does only ONE service per slot — at most one revenue is non-zero
        assert sp["afrr_up_revenue"] == 0 or sp["afrr_down_revenue"] == 0

    assert isinstance(out["total_revenue"], float)
    assert out["total_revenue"] >= 0

    # Day-of-week should be a real weekday name (2025-01-15 is a Wednesday)
    assert out["day_of_week"] == "Wednesday"


def test_get_slot_prices_unknown_date(svc: FRService) -> None:
    out = svc.get_slot_prices(date_str="2099-12-31", power_mw=10.0)
    assert "error" in out


# ---------------------------------------------------------------------------
# analyze_bidding_strategy
# ---------------------------------------------------------------------------

def test_analyze_bidding_strategy(svc: FRService) -> None:
    out = svc.analyze_bidding_strategy(start_date=START_STR, end_date=END_STR)

    assert "error" not in out
    period = out["analysis_period"]
    assert period["start_date"] <= period["end_date"]
    assert period["total_days"] > 0

    # aFRR+ percentiles present
    pct = out["afrr_up"]["percentiles"]
    for key in ("p20", "p50", "p70", "p80", "p90"):
        assert key in pct
        assert isinstance(pct[key], float)
    # Percentiles should be monotonically non-decreasing
    assert pct["p20"] <= pct["p50"] <= pct["p70"] <= pct["p80"] <= pct["p90"]

    # aFRR- percentiles also present
    assert "percentiles" in out["afrr_down"]

    # Recommendation non-empty
    rec = out["profitability_comparison"]["recommendation"]
    assert isinstance(rec, str) and len(rec) > 0

    # Seasonal patterns is a list (might cover only Jan/Feb)
    assert isinstance(out["seasonal_patterns"], list)
    assert len(out["seasonal_patterns"]) >= 1


# ---------------------------------------------------------------------------
# calculate_optimal_bids
# ---------------------------------------------------------------------------

def test_calculate_optimal_bids(svc: FRService) -> None:
    out = svc.calculate_optimal_bids(
        date_str=KNOWN_DATE,
        power_mw=10.0,
        target_acceptance_rate=0.80,
    )

    assert "error" not in out
    assert out["date"] == KNOWN_DATE
    assert out["target_acceptance_rate"] == 0.80
    assert out["historical_data_points"] > 0

    bids = out["optimal_bids"]
    afrr_up = bids["afrr_up"]
    # Floor is 5 (catalog), cap is 60
    assert 5.0 <= afrr_up["recommended_capacity_bid"] <= 60.0
    assert afrr_up["estimated_daily_revenue"] >= 0

    afrr_down = bids["afrr_down"]
    # Floor is 5 (catalog), cap is 40 for down
    assert 5.0 <= afrr_down["recommended_capacity_bid"] <= 40.0

    assert out["recommendation"] in ("aFRR+", "aFRR-")


# ---------------------------------------------------------------------------
# calculate_safe_bid_prices
# ---------------------------------------------------------------------------

def test_calculate_safe_bid_prices(svc: FRService) -> None:
    out = svc.calculate_safe_bid_prices(power_mw=10.0)

    assert "error" not in out
    assert out["target_acceptance_rate"] == 0.90

    safe_up = out["safe_bids"]["afrr_up"]
    assert 5.0 <= safe_up["capacity_bid"] <= 60.0
    assert safe_up["activation_bid"] > 0

    safe_down = out["safe_bids"]["afrr_down"]
    assert 5.0 <= safe_down["capacity_bid"] <= 40.0

    rev = out["expected_revenue"]
    assert rev["annual"] > 0
    assert rev["monthly"] > 0
    # Annual ~= 12 × monthly (within rounding)
    assert rev["annual"] == pytest.approx(rev["monthly"] * 12, rel=1e-3)

    comp = out["comparison"]
    assert comp["safe_strategy"]["acceptance_rate"] == 0.90
    assert comp["aggressive_strategy"]["acceptance_rate"] == 0.60


# ---------------------------------------------------------------------------
# project_annual_revenue
# ---------------------------------------------------------------------------

def test_project_annual_revenue_balanced(svc: FRService) -> None:
    out = svc.project_annual_revenue(power_mw=10.0, strategy="balanced")

    assert "error" not in out
    assert out["strategy"] == "balanced"
    assert out["acceptance_rate"] == 0.80
    assert out["power_mw"] == 10.0

    proj = out["monthly_projections"]
    assert len(proj) >= 1
    for m in proj:
        assert m["monthly_revenue"] > 0
        assert m["selected_service"] in ("aFRR+", "aFRR-")
        assert m["afrr_up_revenue"] >= 0
        assert m["afrr_down_revenue"] >= 0

    assert out["total_projected_annual_revenue"] > 0
    assert out["avg_monthly_revenue"] > 0
    assert out["months_analyzed"] == len(proj)


def test_project_annual_revenue_unknown_strategy_fallback(svc: FRService) -> None:
    """Unknown strategy should silently fall back to 'balanced'."""
    out = svc.project_annual_revenue(power_mw=10.0, strategy="bogus")

    assert "error" not in out
    # Falls back to balanced
    assert out["strategy"] == "balanced"
    assert out["acceptance_rate"] == 0.80
    assert out["total_projected_annual_revenue"] > 0


def test_project_annual_revenue_conservative(svc: FRService) -> None:
    """Conservative strategy exercises the 0.90 acceptance branch."""
    out = svc.project_annual_revenue(power_mw=10.0, strategy="conservative")

    assert out["strategy"] == "conservative"
    assert out["acceptance_rate"] == 0.90
    assert out["total_projected_annual_revenue"] > 0
