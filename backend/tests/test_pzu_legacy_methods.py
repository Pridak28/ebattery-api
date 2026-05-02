"""Coverage tests for legacy / less-covered PZUService methods.

Targets: get_market_stats, get_typical_day_pattern, get_monthly_optimal,
get_monthly_optimal_schedules, get_daily_breakdown, get_available_dates,
get_hourly_prices.

These tests inject a synthetic price DataFrame directly into the service's
``_price_data`` cache to bypass the CSV loader. Why: pytest-cov instrumentation
on this codebase triggers a numpy module reload that causes pandas
``to_datetime``+``take_nd`` to crash on the bundled CSVs (numpy ``_NoValueType``
in ``_amin``). The crash is in numpy/coverage interaction, not app code, and
the legacy methods themselves don't depend on CSV-loading behavior — they
just consume the cached DataFrame. Synthetic data covers those code paths
identically.

Schema mirrors what ``_load_price_data`` produces post-``normalize_pzu_resolution``:
columns ``date`` (datetime64), ``hour`` (int 0–23), ``price`` (float),
``resolution_minutes`` (int), plus a ``source_kind`` attr.
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

from app.services.pzu_service import PZUService  # noqa: E402


def _make_synthetic_price_df(
    start: date = date(2025, 1, 1),
    end: date = date(2025, 6, 1),
    seed: int = 42,
):
    """Build a 24h × N-day price DataFrame mirroring the loader's output.

    Prices follow a realistic diurnal pattern: cheap overnight (hours 0–5,
    13–15), expensive in the morning (7–9) and evening (18–21). This guarantees
    a non-zero spread for screening tests.

    Imports numpy/pandas locally because top-level numpy import in test files
    can collide with pytest-cov's instrumentation order and trigger a numpy
    module reload.
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)

    # Base hourly profile (24-vector) — cheap nights, expensive evenings.
    base = np.array([
        80, 70, 60, 55, 55, 60,    # 0-5 (cheap)
        80, 130, 150, 145, 130, 120,  # 6-11
        100, 90, 95, 110, 130, 160,   # 12-17
        180, 170, 150, 130, 110, 95,  # 18-23 (peak evening)
    ], dtype=float)

    # Build day timestamps without going through pd.to_datetime — that path
    # crashes under pytest-cov instrumentation due to a numpy reload bug.
    n_days = (end - start).days + 1
    days = [pd.Timestamp(start) + pd.Timedelta(days=i) for i in range(n_days)]

    rows: list[dict] = []
    for day in days:
        noise = rng.normal(0, 5, size=24)
        prices = base + noise
        for h in range(24):
            rows.append({
                "date": day,
                "hour": h,
                "price": float(prices[h]),
                "resolution_minutes": 60,
            })
    df = pd.DataFrame(rows)
    df.attrs["source_kind"] = "synthetic_test"
    return df


@pytest.fixture(scope="module")
def svc() -> PZUService:
    """Service with a pre-loaded synthetic price DataFrame.

    Bypasses ``_load_price_data`` to avoid the numpy/coverage CSV reload bug
    while still exercising every line of the methods under test.
    """
    s = PZUService()
    s._price_data = _make_synthetic_price_df()
    s._price_metadata = {
        "source_kind": "synthetic_test",
        "data_date_min": date(2025, 1, 1),
        "data_date_max": date(2025, 6, 1),
        "bankability_level": "screening",
        "settlement_grade": False,
        "source_file": None,
        "resolution_minutes": [60],
    }
    return s


# Window known to be present in the synthetic dataset.
START = date(2025, 1, 1)
END = date(2025, 6, 1)


# ---------------------------------------------------------------------------
# get_market_stats
# ---------------------------------------------------------------------------

def test_get_market_stats_returns_summary(svc: PZUService) -> None:
    stats = svc.get_market_stats()

    assert isinstance(stats, dict)
    assert stats["total_days"] > 0

    price_stats = stats["price_stats"]
    assert isinstance(price_stats["mean"], float)
    assert isinstance(price_stats["min"], float)
    assert isinstance(price_stats["max"], float)
    assert price_stats["min"] <= price_stats["mean"] <= price_stats["max"]
    assert not math.isnan(price_stats["mean"])

    meta = stats["data_metadata"]
    assert isinstance(meta["bankability_level"], str)
    assert meta["bankability_level"]  # non-empty

    dr = stats["date_range"]
    assert dr["start"] <= dr["end"]


# ---------------------------------------------------------------------------
# get_typical_day_pattern
# ---------------------------------------------------------------------------

def test_get_typical_day_pattern_basic(svc: PZUService) -> None:
    resp = svc.get_typical_day_pattern()

    # Screening flags
    assert resp.is_screening_only is True

    # 24 hourly entries, hours 0..23 in order
    assert len(resp.hourly_pattern) == 24
    hours = [p.hour for p in resp.hourly_pattern]
    assert hours == list(range(24))

    # At least one charge hour
    assert len(resp.charge_hours) >= 1
    assert len(resp.discharge_hours) >= 1

    # Spread should be non-negative (sell ≥ buy by construction).
    assert resp.avg_spread_eur_mwh >= 0
    assert resp.total_days_analyzed > 0


def test_get_typical_day_pattern_date_range(svc: PZUService) -> None:
    resp = svc.get_typical_day_pattern(
        start_date=START,
        end_date=END,
        num_charge_hours=3,
        num_discharge_hours=3,
    )

    assert len(resp.charge_hours) == 3
    assert len(resp.discharge_hours) == 3
    assert resp.dispatch_method == "non_chronological_screening"
    assert resp.is_screening_only is True

    # Window should be contained in requested range
    assert resp.analysis_period_start >= START
    assert resp.analysis_period_end <= END
    assert resp.total_days_analyzed > 0


# ---------------------------------------------------------------------------
# get_monthly_optimal (no-arg variant)
# ---------------------------------------------------------------------------

def test_get_monthly_optimal_default(svc: PZUService) -> None:
    resp = svc.get_monthly_optimal()

    assert resp.total_months >= 1
    assert len(resp.monthly_schedules) == resp.total_months

    first = resp.monthly_schedules[0]
    assert first.days_in_month > 0
    assert first.avg_sell_price_eur_mwh >= first.avg_buy_price_eur_mwh
    assert isinstance(first.total_profit_eur, float)


# ---------------------------------------------------------------------------
# get_monthly_optimal_schedules
# ---------------------------------------------------------------------------

def test_get_monthly_optimal_schedules_with_params(svc: PZUService) -> None:
    resp = svc.get_monthly_optimal_schedules(
        start_date=START,
        end_date=END,
        num_charge_hours=2,
        num_discharge_hours=2,
        power_mw=10.0,
        capacity_mwh=20.0,
        efficiency=0.88,
    )

    assert resp.total_months >= 1
    assert len(resp.monthly_schedules) == resp.total_months

    first = resp.monthly_schedules[0]
    assert first.total_profit_eur > 0
    assert len(first.charge_hours) == 2
    assert len(first.discharge_hours) == 2
    assert first.days_in_month > 0
    assert first.avg_sell_price_eur_mwh >= first.avg_buy_price_eur_mwh

    # Total profit equals sum of monthly profits
    assert resp.total_profit_eur == pytest.approx(
        sum(m.total_profit_eur for m in resp.monthly_schedules),
        rel=1e-6,
    )


# ---------------------------------------------------------------------------
# get_daily_breakdown
# ---------------------------------------------------------------------------

def test_get_daily_breakdown_returns_days(svc: PZUService) -> None:
    out = svc.get_daily_breakdown(month="2025-01")

    assert out["month"] == "2025-01"
    daily = out["daily_results"]
    assert 28 <= len(daily) <= 31
    assert isinstance(out["total_profit"], float)

    # Spot-check first day's structure
    sample = daily[0]
    assert isinstance(sample["buy_hours"], list)
    assert isinstance(sample["sell_hours"], list)
    assert len(sample["buy_hours"]) >= 1
    assert len(sample["sell_hours"]) >= 1
    assert sample["max_price"] >= sample["min_price"]
    assert "date" in sample
    assert "spread" in sample


# ---------------------------------------------------------------------------
# get_available_dates
# ---------------------------------------------------------------------------

def test_get_available_dates_returns_dates(svc: PZUService) -> None:
    out = svc.get_available_dates()

    assert out["total_days"] > 0
    dates = out["dates"]
    assert len(dates) == out["total_days"]

    # Sorted ascending by ISO date string (lexicographic == chronological).
    date_strs = [d["date"] for d in dates]
    assert date_strs == sorted(date_strs)

    # min_price <= max_price for each day
    for d in dates:
        assert d["min_price"] <= d["max_price"]
        assert d["hours"] > 0

    # date_range matches ends
    assert out["date_range"]["start"] == dates[0]["date"]
    assert out["date_range"]["end"] == dates[-1]["date"]


# ---------------------------------------------------------------------------
# get_hourly_prices
# ---------------------------------------------------------------------------

def test_get_hourly_prices_for_known_date(svc: PZUService) -> None:
    out = svc.get_hourly_prices(date_str="2025-01-15")

    # Sanity: not the error branch
    assert "error" not in out
    assert out["date"] == "2025-01-15"

    hourly = out["hourly_prices"]
    assert len(hourly) == 24

    charge_hours = set(out["charge_hours"])
    discharge_hours = set(out["discharge_hours"])

    # Disjoint sets
    assert charge_hours.isdisjoint(discharge_hours)

    # Spread non-negative
    assert out["spread"] >= 0
    assert out["max_price"] >= out["min_price"]

    # daily_profit field present and float
    assert "daily_profit" in out
    assert isinstance(out["daily_profit"], float)

    # Hourly entries with charge/discharge actions match the charge/discharge sets
    for entry in hourly:
        if entry["action"] == "charge":
            assert entry["hour"] in charge_hours
        elif entry["action"] == "discharge":
            assert entry["hour"] in discharge_hours
