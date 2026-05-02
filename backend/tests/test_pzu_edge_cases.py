"""Edge-case coverage tests for PZUService.

Targets the previously-uncovered error branches and rare paths in
``app/services/pzu_service.py`` (89% → ≥95%):

- ``simulate()`` empty date range → ValueError
- ``simulate()`` flat-price day → zero-profit result with days_no_profitable_pair counted
- ``simulate()`` narrow SOC bounds preserved on response params
- ``get_typical_day_pattern()`` outside data range → ValueError
- ``get_typical_day()`` thin wrapper exercises legacy alias
- ``get_market_stats`` after synthetic injection (sanity for date_range/std)
- ``get_hourly_prices`` for unknown date → error response
- ``get_daily_breakdown`` for empty month → empty result
- ``get_daily_breakdown`` skips days with <24 rows
- ``_compute_daily_arbitrage`` rejects <MIN_REQUIRED_HOURS frames

Pattern matches ``tests/test_pzu_legacy_methods.py``: synthetic 24h × N-day
DataFrame is injected into ``svc._price_data`` to bypass the CSV loader.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.pzu import PZUSimulationParams  # noqa: E402
from app.services.pzu_service import PZUService  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic data builder (mirrors test_pzu_legacy_methods)
# ---------------------------------------------------------------------------

def _make_synthetic_price_df(
    start: date = date(2025, 1, 1),
    end: date = date(2025, 3, 1),
    seed: int = 7,
):
    """24h × N-day DataFrame with a realistic diurnal price profile."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    base = np.array([
        80, 70, 60, 55, 55, 60,
        80, 130, 150, 145, 130, 120,
        100, 90, 95, 110, 130, 160,
        180, 170, 150, 130, 110, 95,
    ], dtype=float)

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


def _make_flat_price_df(
    start: date = date(2025, 1, 1),
    end: date = date(2025, 1, 5),
    flat_price: float = 100.0,
):
    """Flat-price DataFrame: every hour the same → zero arbitrage opportunity."""
    import pandas as pd

    n_days = (end - start).days + 1
    days = [pd.Timestamp(start) + pd.Timedelta(days=i) for i in range(n_days)]

    rows: list[dict] = []
    for day in days:
        for h in range(24):
            rows.append({
                "date": day,
                "hour": h,
                "price": flat_price,
                "resolution_minutes": 60,
            })
    df = pd.DataFrame(rows)
    df.attrs["source_kind"] = "synthetic_flat"
    return df


def _attach_metadata(svc: PZUService, start: date, end: date) -> None:
    svc._price_metadata = {
        "source_kind": "synthetic_test",
        "data_date_min": start,
        "data_date_max": end,
        "bankability_level": "screening",
        "settlement_grade": False,
        "source_file": None,
        "resolution_minutes": [60],
    }


@pytest.fixture()
def svc() -> PZUService:
    s = PZUService()
    s._price_data = _make_synthetic_price_df()
    _attach_metadata(s, date(2025, 1, 1), date(2025, 3, 1))
    return s


@pytest.fixture()
def svc_flat() -> PZUService:
    s = PZUService()
    s._price_data = _make_flat_price_df()
    _attach_metadata(s, date(2025, 1, 1), date(2025, 1, 5))
    return s


# ---------------------------------------------------------------------------
# simulate() error / zero-profit branches
# ---------------------------------------------------------------------------

def test_simulate_empty_date_range_raises(svc: PZUService) -> None:
    """Range outside the synthetic dataset → no rows → ValueError (line 384)."""
    params = PZUSimulationParams(
        power_mw=10.0,
        capacity_mwh=20.0,
        round_trip_efficiency=0.88,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 5),
    )
    with pytest.raises(ValueError, match="No data available"):
        svc.simulate(params)


def test_simulate_flat_price_day_zero_profit(svc_flat: PZUService) -> None:
    """Flat prices → no profitable pair → zero-trade results (lines 320–343, 410)."""
    params = PZUSimulationParams(
        power_mw=10.0,
        capacity_mwh=20.0,
        round_trip_efficiency=0.88,
    )
    resp = svc_flat.simulate(params)

    assert resp.total_profit_eur == 0.0
    assert resp.total_gross_revenue_eur == 0.0
    assert resp.total_energy_cost_eur == 0.0
    # Every day was simulated but none produced a profitable pair.
    assert resp.days_simulated_count > 0
    assert resp.days_no_profitable_pair == resp.days_simulated_count
    assert resp.days_rejected_data_quality == 0


def test_simulate_narrow_soc_bounds_preserved(svc: PZUService) -> None:
    """Narrow SOC bounds round-trip into the response params (no silent default)."""
    params = PZUSimulationParams(
        power_mw=10.0,
        capacity_mwh=20.0,
        round_trip_efficiency=0.88,
        soc_min=0.20,
        soc_max=0.80,
        soc_initial=0.50,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
    )
    resp = svc.simulate(params)

    assert resp.params.soc_min == pytest.approx(0.20)
    assert resp.params.soc_max == pytest.approx(0.80)
    assert resp.params.soc_initial == pytest.approx(0.50)
    # Sanity: simulation produced monthly results for the window.
    assert len(resp.monthly_results) >= 1
    assert resp.days_simulated_count > 0


# ---------------------------------------------------------------------------
# get_typical_day / get_typical_day_pattern branches
# ---------------------------------------------------------------------------

def test_typical_day_pattern_outside_range_raises(svc: PZUService) -> None:
    """Range that excludes all rows → ValueError (line 524)."""
    with pytest.raises(ValueError, match="No PZU data"):
        svc.get_typical_day_pattern(
            start_date=date(2030, 6, 1),
            end_date=date(2030, 7, 1),
        )


def test_get_typical_day_alias(svc: PZUService) -> None:
    """``get_typical_day`` is a thin alias for ``get_typical_day_pattern`` (line 503)."""
    resp = svc.get_typical_day()
    assert len(resp.hourly_pattern) == 24
    assert resp.is_screening_only is True


# ---------------------------------------------------------------------------
# get_market_stats sanity after synthetic injection
# ---------------------------------------------------------------------------

def test_get_market_stats_after_synthetic_injection(svc: PZUService) -> None:
    stats = svc.get_market_stats()
    ps = stats["price_stats"]
    # Synthetic data has clear day/night spread → std must be positive.
    assert ps["std"] > 0
    assert ps["min"] < ps["max"]
    # date_range strings are ISO-formatted and ordered.
    assert stats["date_range"]["start"] <= stats["date_range"]["end"]


# ---------------------------------------------------------------------------
# get_hourly_prices error branch
# ---------------------------------------------------------------------------

def test_get_hourly_prices_unknown_date_returns_error(svc: PZUService) -> None:
    """Unknown date → error response, not exception (line 821)."""
    out = svc.get_hourly_prices(date_str="2030-12-31")
    assert "error" in out
    assert "2030-12-31" in out["error"]
    assert out["hourly_prices"] == []


# ---------------------------------------------------------------------------
# get_daily_breakdown empty / partial-day branches
# ---------------------------------------------------------------------------

def test_get_daily_breakdown_empty_month(svc: PZUService) -> None:
    """Month with no rows → empty result, no exception (line 723)."""
    out = svc.get_daily_breakdown(month="2030-06")
    assert out["month"] == "2030-06"
    assert out["daily_results"] == []


def test_get_daily_breakdown_skips_partial_days(svc_flat: PZUService) -> None:
    """Days with <24 rows are skipped (line 735).

    Drop hours 20–23 from Jan 3 so only that one day has 20 rows; the rest
    of January still has 24 rows × 4 days = 4 full days.
    """
    df = svc_flat._price_data
    mask_drop = (
        (df["date"] == df["date"].min() + (df["date"].max() - df["date"].min()) * 0)  # placeholder
    )
    # Clean approach: drop rows for Jan 3, hours 20..23
    import pandas as pd

    target = pd.Timestamp(date(2025, 1, 3))
    mask_drop = (df["date"] == target) & (df["hour"] >= 20)
    svc_flat._price_data = df[~mask_drop].reset_index(drop=True)

    out = svc_flat.get_daily_breakdown(month="2025-01")
    dates_in = {d["date"] for d in out["daily_results"]}
    assert "2025-01-03" not in dates_in
    # Other days (Jan 1, 2, 4, 5) still present.
    assert "2025-01-01" in dates_in
    assert "2025-01-04" in dates_in
    assert len(out["daily_results"]) == 4


# ---------------------------------------------------------------------------
# _compute_daily_arbitrage low-level branches
# ---------------------------------------------------------------------------

def test_compute_daily_arbitrage_too_few_hours_returns_none(svc: PZUService) -> None:
    """<MIN_REQUIRED_HOURS rows → None (line 224)."""
    import pandas as pd

    tiny = pd.DataFrame({
        "date": [pd.Timestamp(date(2025, 1, 1))] * 3,
        "hour": [0, 1, 2],
        "price": [50.0, 60.0, 70.0],
    })
    result = svc._compute_daily_arbitrage(
        tiny,
        power_mw=10.0,
        capacity_mwh=20.0,
        efficiency=0.88,
    )
    assert result is None


def test_load_price_data_missing_csv_raises(tmp_path: Path) -> None:
    """No PZU CSV in data_dir → FileNotFoundError (line 75)."""
    s = PZUService(data_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="No PZU price data"):
        s._load_price_data()


def test_get_price_history_filters_and_aggregates(svc: PZUService) -> None:
    """Exercises start/end filters + ``aggregate='monthly'`` path (lines 104, 106, 121-127)."""
    resp = svc.get_price_history(
        start_date=date(2025, 1, 5),
        end_date=date(2025, 2, 10),
        aggregate="monthly",
    )
    # Two calendar months in the window.
    assert resp.count == 2
    assert resp.start_date >= date(2025, 1, 1)
    assert resp.end_date <= date(2025, 2, 28)
    assert resp.min_price <= resp.avg_price <= resp.max_price


def test_get_price_history_raw_fallback_price_col(svc: PZUService) -> None:
    """Rename ``price`` → ``price_eur_mwh`` to exercise alt-column branch (lines 109/112-116)."""
    df = svc._price_data.rename(columns={"price": "price_eur_mwh"})
    svc._price_data = df

    resp = svc.get_price_history(aggregate="raw")
    assert resp.count > 0
    assert resp.min_price <= resp.max_price


def test_typical_day_pattern_no_hour_column(svc: PZUService) -> None:
    """Drop ``hour`` column → method derives hour from ``date`` (line 530)."""
    import pandas as pd

    df = svc._price_data.copy()
    # Replace timestamps with hour-stamped versions and drop hour col.
    df["date"] = df["date"] + pd.to_timedelta(df["hour"], unit="h")
    df = df.drop(columns=["hour"])
    svc._price_data = df

    resp = svc.get_typical_day_pattern()
    assert len(resp.hourly_pattern) == 24
    assert resp.total_days_analyzed > 0


def test_get_hourly_prices_missing_hour_column(svc: PZUService) -> None:
    """Drop ``hour`` column → method derives hour from ``date`` (lines 827-828)."""
    import pandas as pd

    df = svc._price_data.copy()
    df["date"] = df["date"] + pd.to_timedelta(df["hour"], unit="h")
    df = df.drop(columns=["hour"])
    svc._price_data = df

    out = svc.get_hourly_prices(date_str="2025-01-15")
    assert "error" not in out
    assert len(out["hourly_prices"]) == 24


def test_simulate_mixed_partial_and_full_days(svc: PZUService) -> None:
    """One <MIN_REQUIRED_HOURS day + full days → counts both branches (lines 405-406)."""
    import pandas as pd

    df = svc._price_data
    # Drop most rows for Jan 1 → only 2 hourly rows survive (< MIN_REQUIRED_HOURS=4).
    target = pd.Timestamp(date(2025, 1, 1))
    keep_mask = ~((df["date"] == target) & (df["hour"] >= 2))
    svc._price_data = df[keep_mask].reset_index(drop=True)

    params = PZUSimulationParams(
        power_mw=10.0,
        capacity_mwh=20.0,
        round_trip_efficiency=0.88,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 10),
    )
    resp = svc.simulate(params)
    # The truncated Jan-1 day was rejected for data quality.
    assert resp.days_rejected_data_quality >= 1
    assert resp.days_simulated_count >= 1


def test_static_helpers_zero_efficiency(svc: PZUService) -> None:
    """Zero/negative efficiency exercises the eta<=0 guards (lines 153, 164)."""
    import math as _math

    inf = PZUService._charge_grid_input_mwh(10.0, 0.0)
    assert _math.isinf(inf)
    assert PZUService._discharge_grid_output_mwh(10.0, 0.0) == 0.0


def test_simulate_soc_trajectory_zero_capacity() -> None:
    """capacity_mwh<=0 short-circuits to flat trajectory (line 186)."""
    traj = PZUService._simulate_soc_trajectory(
        cs=0, ds=10, block=2,
        capacity_mwh=0.0,
        internal_charge_mwh=10.0,
        internal_discharge_mwh=10.0,
        soc_initial=0.5,
    )
    assert len(traj) == 25
    assert all(s == 0.5 for s in traj)


def test_compute_daily_arbitrage_soc_violation_counter(svc: PZUService) -> None:
    """Tight SOC bounds force violations to be counted (lines 303–304).

    Set ``soc_initial`` outside ``[soc_min, soc_max]`` so every candidate
    trajectory starts in violation — the bound check rejects every (cs, ds)
    pair and increments ``soc_violations``. This bypasses the
    ``PZUSimulationParams`` model validation since we call the internal
    method directly.
    """
    import pandas as pd

    # 24-row day with strong spread
    rows = [
        {"date": pd.Timestamp(date(2025, 1, 1)), "hour": h,
         "price": 50.0 if h < 12 else 200.0}
        for h in range(24)
    ]
    df = pd.DataFrame(rows)

    result = svc._compute_daily_arbitrage(
        df,
        power_mw=10.0,
        capacity_mwh=20.0,
        efficiency=0.88,
        soc_min=0.10,
        soc_max=0.40,       # ceiling
        soc_initial=0.95,   # already above soc_max → every traj violates
    )
    assert result is not None
    # Every candidate trajectory begins out-of-bounds → all rejected.
    assert result["soc_violations"] > 0
    # Zero-trade fallback structure.
    assert result["charge_start_hour"] is None
    assert result["net_profit"] == 0.0
