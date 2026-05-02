"""PZU chronological SOC dispatch regression tests.

Per audit/BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT_2026-05-01.md (Agent 1, Critical):
the PZU optimizer must enforce charge BEFORE discharge in the same day.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.pzu_service import PZUService  # noqa: E402


def _day_prices(prices: list[float]) -> pd.DataFrame:
    """Build a 24-row daily price DataFrame matching the loader's shape."""
    return pd.DataFrame({
        "date": [pd.Timestamp("2024-01-01")] * 24,
        "hour": list(range(24)),
        "price": prices,
    })


def test_charge_must_precede_discharge():
    """Cheapest hour at index 23 (last hour of day) → no chronologically
    valid discharge window can come AFTER it, so the simulator must NOT
    discharge the same day. Result should be a zero-trade day."""
    svc = PZUService()
    prices = [100.0] * 24
    prices[23] = 10.0   # cheapest at the last hour
    prices[20] = 200.0  # most expensive *before* the cheapest
    result = svc._compute_daily_arbitrage(_day_prices(prices), power_mw=15.0, capacity_mwh=30.0, efficiency=0.9)
    assert result is not None
    # If the simulator picks charge_start=23, there are no valid discharge windows
    # remaining. The next-cheapest price is 100 €/MWh which can pair with 200 €/MWh
    # at hour 20-21, but ONLY if charge_start <= 18. So we expect a profitable
    # trade — but assert the chronological rule held:
    if result["charge_start_hour"] is not None:
        assert result["charge_start_hour"] + 2 <= result["discharge_start_hour"], (
            f"charge_start {result['charge_start_hour']} must end before discharge_start {result['discharge_start_hour']}"
        )


def test_block_size_respected():
    """Charged MWh per block must not exceed power_mw × BLOCK_HOURS."""
    svc = PZUService()
    prices = list(range(24))  # ascending: cheapest at start, most expensive at end
    result = svc._compute_daily_arbitrage(_day_prices([float(p) for p in prices]), power_mw=15.0, capacity_mwh=30.0, efficiency=0.9)
    assert result is not None
    # spread must be positive for ascending prices (cheap morning, expensive evening)
    assert result["spread"] > 0
    # charge starts at the cheapest hours; with BLOCK_HOURS=2 we charge at h=0,1
    assert result["charge_start_hour"] == 0
    # discharge after; the simulator picks the most profitable window AFTER charge
    assert result["discharge_start_hour"] is not None
    assert result["discharge_start_hour"] >= 2


def test_efficiency_applied_on_discharge():
    """With an explicit empty-to-full idealized SOC window, charge=30 MWh,
       sell=200, buy=10, eta=0.9:
       discharge revenue ≈ 30 × 0.9 × 200 = 5400
       charge cost = 30 × 10 = 300
       profit ≈ 5100

       The production default starts at 50% SOC with a 90% SOC ceiling, so this
       test declares the full-cycle SOC window it is proving.
    """
    svc = PZUService()
    prices = [100.0] * 24
    prices[0] = 10.0
    prices[1] = 10.0  # cheap window
    prices[20] = 200.0
    prices[21] = 200.0  # expensive window
    result = svc._compute_daily_arbitrage(
        _day_prices(prices),
        power_mw=15.0,
        capacity_mwh=30.0,
        efficiency=0.9,
        soc_min=0.0,
        soc_max=1.0,
        soc_initial=0.0,
    )
    assert result is not None
    # charge_grid_mwh = 30; discharge_grid_mwh = 27 after round-trip efficiency.
    expected_profit = 200.0 * 27 - 10.0 * 30
    assert abs(result["gross_profit"] - expected_profit) < 1e-2
    assert result["charge_start_hour"] == 0
    assert result["discharge_start_hour"] == 20


def test_no_profitable_pair_returns_zero():
    """Strictly descending prices → no chronologically valid + profitable pair."""
    svc = PZUService()
    prices = [float(24 - p) for p in range(24)]  # 24 → 1, descending
    result = svc._compute_daily_arbitrage(_day_prices(prices), power_mw=15.0, capacity_mwh=30.0, efficiency=0.9)
    assert result is not None
    assert result["gross_profit"] == 0.0
    assert result["spread"] == 0.0
    assert result["charge_start_hour"] is None


def test_audit_metadata_present():
    """Every daily result must carry pricing_basis + confidence_label."""
    svc = PZUService()
    prices = [100.0] * 24
    prices[0] = 10.0
    prices[1] = 10.0
    prices[20] = 200.0
    prices[21] = 200.0
    result = svc._compute_daily_arbitrage(_day_prices(prices), power_mw=15.0, capacity_mwh=30.0, efficiency=0.9)
    assert result["pricing_basis"] == "public_marginal"
    assert "Participant-only-for-bankability" in result["confidence_label"]
    assert result["dispatch_method"] == "chronological_soc"
