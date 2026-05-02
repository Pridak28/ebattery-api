"""Final coverage tests for investment_service.py + pzu_service.py.

Targets the residual missed branches reported by pytest-cov:

* ``investment_service.py`` lines 631, 634-635, 637, 639, 641, 650
  → ``_classify_irr`` (None / TypeError / NaN / high / medium tiers) and
    ``_most_blocking_gate`` "all qualified → None" return.

* ``pzu_service.py`` lines 112-116, 234, 239, 250, 413, 574, 648, 727, 868
  → alternate price-column discovery, hour-less dataframe fallbacks,
    ``BLOCK_HOURS=0`` guard, ``simulate`` empty-results raise, the
    ``"hour" not in df.columns`` branches in ``get_monthly_optimal*``,
    ``get_daily_breakdown`` and ``get_hourly_prices`` (no-data-for-date).

All tests inject synthetic DataFrames into ``svc._price_data`` to bypass the
CSV loader (consistent with ``test_pzu_legacy_methods.py``).
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

from app.models.investment import (  # noqa: E402
    ComplianceGates,
    InvestmentParams,
)
from app.services.investment_service import InvestmentService  # noqa: E402
from app.services.pzu_service import PZUService  # noqa: E402


# ---------------------------------------------------------------------------
# investment_service._classify_irr — tier branches + degenerate inputs
# ---------------------------------------------------------------------------

def test_classify_irr_none_returns_unknown() -> None:
    """Line 631: ``irr_pct is None`` → ``"unknown"``."""
    assert InvestmentService._classify_irr(None) == "unknown"


def test_classify_irr_non_castable_returns_unknown() -> None:
    """Lines 634-635: TypeError/ValueError on float() → ``"unknown"``.

    Use a deliberately uncastable object. ``object()`` raises TypeError
    inside ``float()``; the except clause swallows it.
    """
    assert InvestmentService._classify_irr(object()) == "unknown"  # type: ignore[arg-type]


def test_classify_irr_nan_returns_unknown() -> None:
    """Line 637: NaN guard returns ``"unknown"``."""
    assert InvestmentService._classify_irr(float("nan")) == "unknown"


def test_classify_irr_high_tier() -> None:
    """Line 639: IRR > 12 % → ``"high"``."""
    assert InvestmentService._classify_irr(15.0) == "high"


def test_classify_irr_medium_tier() -> None:
    """Line 641: 6 % ≤ IRR ≤ 12 % → ``"medium"``."""
    assert InvestmentService._classify_irr(8.0) == "medium"
    # Boundary: exactly 6.0 must be medium (>= 6.0, not > 6.0).
    assert InvestmentService._classify_irr(6.0) == "medium"


def test_classify_irr_low_tier() -> None:
    """Sanity: < 6 % returns ``"low"``."""
    assert InvestmentService._classify_irr(2.0) == "low"


# ---------------------------------------------------------------------------
# investment_service._most_blocking_gate — all-qualified → None branch
# ---------------------------------------------------------------------------

def test_most_blocking_gate_all_qualified_returns_none() -> None:
    """Line 650: when every gate is ``qualified``, the cascade returns None."""
    qualified = {
        "anre_license_status": "qualified",
        "opcom_short_term_participant": "qualified",
        "brp_pre_responsibility": "qualified",
        "fse_bsp_convention": "qualified",
        "damas_access": "qualified",
        "capacity_reserve_auction_register": "qualified",
        "rsf_fcr_qualification": "qualified",
        "settlement_account_and_guarantees": "qualified",
        "telemetry_and_metering": "qualified",
        "remit_acknowledgement": "qualified",
        "storage_tariff_exemption_metering": "qualified",
    }
    gates = ComplianceGates(**qualified)
    svc = InvestmentService()
    assert svc._most_blocking_gate(gates) is None


# ---------------------------------------------------------------------------
# pzu_service helpers — synthetic dataframe injection
# ---------------------------------------------------------------------------

def _make_min_df():
    """Minimal hour-keyed price frame; standard ``date``/``hour``/``price``."""
    import numpy as np
    import pandas as pd

    base = np.array([
        80, 70, 60, 55, 55, 60,
        80, 130, 150, 145, 130, 120,
        100, 90, 95, 110, 130, 160,
        180, 170, 150, 130, 110, 95,
    ], dtype=float)
    rows = []
    days = [pd.Timestamp("2025-01-01") + pd.Timedelta(days=i) for i in range(5)]
    for d in days:
        for h in range(24):
            rows.append({"date": d, "hour": h, "price": float(base[h])})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# get_price_history — alternate price column discovery (lines 112-116)
# ---------------------------------------------------------------------------

def test_get_price_history_finds_alternate_price_column() -> None:
    """Lines 112-114: when no ``price`` / ``price_eur_mwh`` column exists,
    the loader falls back to the first column that contains "price".
    """
    import pandas as pd

    svc = PZUService()
    days = [pd.Timestamp("2025-01-01") + pd.Timedelta(days=i) for i in range(3)]
    rows = []
    for d in days:
        for h in range(24):
            rows.append({"date": d, "hour": h, "wholesale_price_ron": 100.0 + h})
    svc._price_data = pd.DataFrame(rows)

    resp = svc.get_price_history(aggregate="daily")
    assert resp.count == 3
    assert resp.avg_price > 0


def test_get_price_history_raises_when_no_price_column() -> None:
    """Lines 115-116: no price-like column → ValueError."""
    import pandas as pd

    svc = PZUService()
    days = [pd.Timestamp("2025-01-01") + pd.Timedelta(days=i) for i in range(2)]
    rows = []
    for d in days:
        for h in range(24):
            rows.append({"date": d, "hour": h, "ron_per_kwh": 0.1})
    svc._price_data = pd.DataFrame(rows)

    with pytest.raises(ValueError, match="No price column found"):
        svc.get_price_history(aggregate="daily")


def test_get_price_history_unknown_aggregate_returns_raw() -> None:
    """``aggregate`` not in {daily, monthly} → returns the unaggregated frame
    (the ``else: agg_df = df`` branch).
    """
    import pandas as pd

    svc = PZUService()
    svc._price_data = _make_min_df()
    resp = svc.get_price_history(aggregate="bogus")
    # Raw daily-hourly frame: 5 days × 24 hours = 120 rows.
    assert resp.count == 120


# ---------------------------------------------------------------------------
# _compute_daily_arbitrage — fallback hour/price discovery + block guard
# ---------------------------------------------------------------------------

def test_compute_daily_arbitrage_no_hour_column_uses_arange() -> None:
    """Line 234: when ``hour`` is absent, ``hours = np.arange(len(df))``.

    Build a 24-row frame without ``hour`` column. The arange fallback maps
    rows 0..23 onto hours 0..23, so the dispatch still finds a valid pair.
    """
    import pandas as pd

    svc = PZUService()
    base = [80, 70, 60, 55, 55, 60, 80, 130, 150, 145, 130, 120,
            100, 90, 95, 110, 130, 160, 180, 170, 150, 130, 110, 95]
    df = pd.DataFrame({"date": [pd.Timestamp("2025-01-01")] * 24,
                       "price": base})
    result = svc._compute_daily_arbitrage(df, power_mw=10, capacity_mwh=20,
                                          efficiency=0.88)
    assert result is not None
    assert result["gross_profit"] > 0


def test_compute_daily_arbitrage_no_price_column_uses_iloc() -> None:
    """Line 239: when ``price`` column is missing, fall back to column index 1.

    Frame has columns [date, alt_price, hour] — without ``price``, the
    function takes ``df.iloc[:, 1]`` (= alt_price) as the price series.
    """
    import pandas as pd

    svc = PZUService()
    base = [80, 70, 60, 55, 55, 60, 80, 130, 150, 145, 130, 120,
            100, 90, 95, 110, 130, 160, 180, 170, 150, 130, 110, 95]
    df = pd.DataFrame({
        "date": [pd.Timestamp("2025-01-01")] * 24,
        "alt_price": base,        # column index 1 — picked by iloc[:, 1]
        "hour": list(range(24)),
    })
    result = svc._compute_daily_arbitrage(df, power_mw=10, capacity_mwh=20,
                                          efficiency=0.88)
    assert result is not None
    # ``alt_price`` matches ``base`` so we should detect a profitable spread.
    assert result["gross_profit"] > 0


def test_compute_daily_arbitrage_block_zero_returns_none(monkeypatch) -> None:
    """Line 250: ``BLOCK_HOURS <= 0`` → return None.

    Monkeypatch the class constant on a service instance; the call still
    has enough rows to clear ``MIN_REQUIRED_HOURS``.
    """
    import pandas as pd

    svc = PZUService()
    # Override the constant on the instance so the guard fires.
    monkeypatch.setattr(PZUService, "BLOCK_HOURS", 0)
    df = pd.DataFrame({
        "date": [pd.Timestamp("2025-01-01")] * 24,
        "hour": list(range(24)),
        "price": [50.0] * 24,
    })
    assert svc._compute_daily_arbitrage(df, power_mw=10, capacity_mwh=20,
                                       efficiency=0.88) is None


# ---------------------------------------------------------------------------
# simulate — "no valid trading days" raises (line 413)
# ---------------------------------------------------------------------------

def test_simulate_raises_when_all_days_have_too_few_hours() -> None:
    """Line 413: every day has < MIN_REQUIRED_HOURS rows → all rejected →
    ``daily_results`` empty → ValueError("No valid trading days found").
    """
    import pandas as pd

    from app.models.pzu import PZUSimulationParams

    svc = PZUService()
    # Each day has only 2 rows — below the 4-hour minimum the dispatcher
    # requires, so every day is data-rejected.
    days = [pd.Timestamp("2025-01-01") + pd.Timedelta(days=i) for i in range(3)]
    rows = []
    for d in days:
        for h in range(2):
            rows.append({"date": d, "hour": h, "price": 50.0,
                         "resolution_minutes": 60})
    svc._price_data = pd.DataFrame(rows)

    params = PZUSimulationParams(power_mw=10, capacity_mwh=20)
    with pytest.raises(ValueError, match="No valid trading days"):
        svc.simulate(params)


# ---------------------------------------------------------------------------
# get_monthly_optimal / schedules / daily_breakdown — "hour not in df" branch
# ---------------------------------------------------------------------------

def _df_no_hour_col_per_hour_timestamp():
    """Per-hour timestamps so ``df["date"].dt.hour`` produces 0..23 each day."""
    import pandas as pd

    rows = []
    for d in range(3):
        day0 = pd.Timestamp("2025-01-01") + pd.Timedelta(days=d)
        for h in range(24):
            rows.append({
                "date": day0 + pd.Timedelta(hours=h),
                "price": 80.0 + 10.0 * h,
            })
    return pd.DataFrame(rows)


def test_get_monthly_optimal_synthesizes_hour_when_missing() -> None:
    """Line 574: ``get_monthly_optimal`` derives ``hour`` from ``date``."""
    svc = PZUService()
    svc._price_data = _df_no_hour_col_per_hour_timestamp()
    resp = svc.get_monthly_optimal()
    assert resp.total_months >= 1


def test_get_monthly_optimal_schedules_synthesizes_hour_when_missing() -> None:
    """Line 648: same fallback in ``get_monthly_optimal_schedules``."""
    svc = PZUService()
    svc._price_data = _df_no_hour_col_per_hour_timestamp()
    resp = svc.get_monthly_optimal_schedules(num_charge_hours=2,
                                            num_discharge_hours=2)
    assert resp.total_months >= 1


def test_get_daily_breakdown_synthesizes_hour_when_missing() -> None:
    """Line 727: same fallback in ``get_daily_breakdown``."""
    svc = PZUService()
    svc._price_data = _df_no_hour_col_per_hour_timestamp()
    out = svc.get_daily_breakdown(month="2025-01")
    assert out["month"] == "2025-01"
    assert out["total_days"] >= 1


# ---------------------------------------------------------------------------
# get_hourly_prices — empty-result branch (line 868)
# ---------------------------------------------------------------------------

def test_get_hourly_prices_missing_hours_yields_no_data_entries() -> None:
    """Line 868-874: hours absent from the day's data emit ``no_data`` rows.

    Frame supplies prices for hours 0-11 only on the target date; hours
    12-23 must come back tagged ``"no_data"``.
    """
    import pandas as pd

    svc = PZUService()
    rows = []
    target = pd.Timestamp("2025-01-01")
    for h in range(12):  # only first half of the day
        rows.append({"date": target, "hour": h, "price": 50.0 + h})
    svc._price_data = pd.DataFrame(rows)

    out = svc.get_hourly_prices("2025-01-01", power_mw=10, capacity_mwh=20)
    no_data = [row for row in out["hourly_prices"] if row["action"] == "no_data"]
    assert len(no_data) == 12  # hours 12-23 missing
    assert all(row["price_eur_mwh"] is None for row in no_data)


# ---------------------------------------------------------------------------
# investment_service.build_investor_summary smoke test — exercises the
# summary-construction path so the new branches in _classify_irr /
# _most_blocking_gate are reachable through public API too.
# ---------------------------------------------------------------------------

def test_build_investor_summary_has_all_required_fields() -> None:
    """``build_investor_summary`` returns a fully-populated InvestorSummary."""
    svc = InvestmentService()
    params = InvestmentParams()  # canonical defaults
    summary = svc.build_investor_summary(params)

    # Spot-check a representative subset of fields rather than every one.
    assert summary.project_sizing == "10 MW / 20 MWh"
    assert summary.capex_eur > 0
    assert summary.irr_tier in {"high", "medium", "low", "unknown"}
    assert summary.compliance_gates_total == 11
    assert isinstance(summary.disclaimer, str) and summary.disclaimer
    # Picasso default = 25.0 % > 0 → modeled flag must be True.
    assert summary.picasso_compression_modeled is True


def test_build_investor_summary_picasso_disabled() -> None:
    """``picasso_one_time_compression_pct=0`` → flag flips to False."""
    svc = InvestmentService()
    params = InvestmentParams(picasso_one_time_compression_pct=0.0)
    summary = svc.build_investor_summary(params)
    assert summary.picasso_compression_modeled is False
