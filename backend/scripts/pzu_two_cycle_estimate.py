"""Estimate PZU revenue with 2 cycles/day vs 1 cycle/day.

Quick analytical study, NOT a model change. For each day in the OPCOM
data, finds:

  - 1-cycle dispatch: the single best (charge_2h, discharge_2h) pair
    with chronological constraint (charge_end ≤ discharge_start). Same
    logic as the production simulator at single-cycle granularity.
  - 2-cycle dispatch: greedily picks the best cycle, blocks the 4
    hours it used, then finds the best second cycle from the remaining
    hours (still chronological inside each pair). Only counts the
    second cycle if it's strictly profitable.

Per-cycle MWh uses the user-directive defaults:
  - 10 MW power, 20 MWh capacity, RTE = 0.97, SOC band 0-100%
  - Internal energy per cycle = min(power × 2h × √η, capacity) = 19.70 MWh
  - charge_grid_mwh  = 19.70 / √0.97 ≈ 20.00 MWh AC bought
  - discharge_grid_mwh = 19.70 × √0.97 ≈ 19.40 MWh AC sold

Run:
    cd backend
    PYTHONPATH=. arch -arm64 /usr/local/bin/python3 scripts/pzu_two_cycle_estimate.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.pzu_service import PZUService  # noqa: E402

POWER_MW = 10.0
CAPACITY_MWH = 20.0
RTE = 0.97
BLOCK = 2

SQRT_ETA = math.sqrt(RTE)
INTERNAL_PER_CYCLE = min(POWER_MW * BLOCK * SQRT_ETA, CAPACITY_MWH)  # 19.70 MWh
CHARGE_GRID_MWH = INTERNAL_PER_CYCLE / SQRT_ETA                       # 20.00 MWh AC in
DISCHARGE_GRID_MWH = INTERNAL_PER_CYCLE * SQRT_ETA                    # 19.40 MWh AC out


def best_cycle(prices: np.ndarray, blocked: set[int]) -> tuple[float, int, int] | None:
    """Find best chronological (charge_start, discharge_start) pair on the
    24-slot price vector that does not touch any blocked hour. Returns
    (profit, cs, ds) or None if no profitable pair exists.
    """
    best = None
    for cs in range(0, 24 - BLOCK + 1):
        if any(h in blocked for h in range(cs, cs + BLOCK)):
            continue
        cw = prices[cs : cs + BLOCK]
        if np.any(np.isnan(cw)):
            continue
        buy = float(cw.mean())
        for ds in range(cs + BLOCK, 24 - BLOCK + 1):
            if any(h in blocked for h in range(ds, ds + BLOCK)):
                continue
            dw = prices[ds : ds + BLOCK]
            if np.any(np.isnan(dw)):
                continue
            sell = float(dw.mean())
            profit = sell * DISCHARGE_GRID_MWH - buy * CHARGE_GRID_MWH
            if profit > 0 and (best is None or profit > best[0]):
                best = (profit, cs, ds)
    return best


def daily_profits(group: pd.DataFrame) -> pd.Series:
    """Return (one_cycle, two_cycle) net profits in EUR for one day."""
    prices = np.full(24, np.nan, dtype=float)
    for _, row in group.iterrows():
        h = int(row["hour"])
        if 0 <= h < 24:
            prices[h] = float(row["price"])

    c1 = best_cycle(prices, blocked=set())
    one_cycle = c1[0] if c1 else 0.0
    if not c1:
        return pd.Series({"one_cycle": 0.0, "two_cycle": 0.0})

    blocked = set(range(c1[1], c1[1] + BLOCK)) | set(range(c1[2], c1[2] + BLOCK))
    c2 = best_cycle(prices, blocked=blocked)
    two_cycle = one_cycle + (c2[0] if c2 else 0.0)
    return pd.Series({"one_cycle": one_cycle, "two_cycle": two_cycle})


def main() -> None:
    pzu = PZUService()
    df = pzu._load_price_data().copy()
    if "hour" not in df.columns:
        df["hour"] = pd.to_datetime(df["date"]).dt.hour
    if "price" not in df.columns:
        df = df.rename(columns={df.columns[1]: "price"})
    df["date_only"] = pd.to_datetime(df["date"]).dt.date

    print(f"Battery: {POWER_MW} MW / {CAPACITY_MWH} MWh, RTE = {RTE}")
    print(f"Per-cycle: internal {INTERNAL_PER_CYCLE:.2f} MWh, "
          f"buy {CHARGE_GRID_MWH:.2f} MWh AC, sell {DISCHARGE_GRID_MWH:.2f} MWh AC")
    print(f"Days in data: {df['date_only'].nunique()}")

    daily = df.groupby("date_only").apply(daily_profits, include_groups=False)
    daily["uplift"] = daily["two_cycle"] - daily["one_cycle"]
    daily["uplift_pct"] = (daily["uplift"] / daily["one_cycle"].replace(0, np.nan)) * 100

    # --- Aggregate by month ---
    daily_idx = daily.copy()
    daily_idx["month"] = pd.to_datetime(daily_idx.index).strftime("%Y-%m")
    monthly = daily_idx.groupby("month").agg(
        days=("one_cycle", "count"),
        one_cycle=("one_cycle", "sum"),
        two_cycle=("two_cycle", "sum"),
        avg_uplift=("uplift", "mean"),
        avg_uplift_pct=("uplift_pct", "mean"),
    )

    # --- Last-12-month and full-window totals ---
    last_12mo_start = pd.to_datetime(df["date"]).max() - pd.Timedelta(days=365)
    last_12mo_mask = pd.to_datetime(daily.index) >= last_12mo_start
    l12 = daily[last_12mo_mask]

    print(f"\n{'=' * 78}")
    print(f"PZU ROI — 1 cycle vs 2 cycles per day")
    print(f"{'=' * 78}")
    print(f"\n{'Window':>22s}  {'1 cycle':>14s}  {'2 cycles':>14s}  {'Uplift':>14s}  {'Uplift %':>10s}")
    print(f"  Full-window ({len(daily)} days)  "
          f"€{daily['one_cycle'].sum():>12,.0f}  "
          f"€{daily['two_cycle'].sum():>12,.0f}  "
          f"€{(daily['two_cycle'].sum() - daily['one_cycle'].sum()):>12,.0f}  "
          f"{((daily['two_cycle'].sum() / daily['one_cycle'].sum()) - 1) * 100:>9.1f}%")
    print(f"  Last 12 months ({len(l12)} days)  "
          f"€{l12['one_cycle'].sum():>12,.0f}  "
          f"€{l12['two_cycle'].sum():>12,.0f}  "
          f"€{(l12['two_cycle'].sum() - l12['one_cycle'].sum()):>12,.0f}  "
          f"{((l12['two_cycle'].sum() / l12['one_cycle'].sum()) - 1) * 100:>9.1f}%")

    print(f"\nMonthly breakdown (last 24 months):")
    print(f"  {'Month':>9s}  {'days':>5s}  {'1 cycle':>14s}  {'2 cycles':>14s}  {'uplift €':>14s}  {'uplift %':>9s}")
    for m, row in monthly.tail(24).iterrows():
        bar_pct = min(row["avg_uplift_pct"], 200)
        bar = "█" * int(bar_pct / 5)
        print(f"  {m:>9s}  {int(row['days']):>5d}  "
              f"€{row['one_cycle']:>12,.0f}  €{row['two_cycle']:>12,.0f}  "
              f"€{(row['two_cycle'] - row['one_cycle']):>12,.0f}  "
              f"{row['avg_uplift_pct']:>8.1f}%  {bar}")

    print(f"\n{'=' * 78}")
    print(f"Days with NO profitable second cycle: "
          f"{((daily['uplift'] <= 0).sum())} / {len(daily)} "
          f"({(daily['uplift'] <= 0).mean() * 100:.1f}%)")
    print(f"Days with second cycle ≥ 50% of first cycle profit: "
          f"{((daily['uplift'] >= 0.5 * daily['one_cycle']).sum())} / {len(daily)}")

    print(f"\nWarranty implication:")
    print(f"  1 cycle/day → 365 EFC/year × 15 yr = 5,475 EFC (under 6,000 budget ✓)")
    print(f"  2 cycles/day → 730 EFC/year × 15 yr = 10,950 EFC")
    print(f"     → exhausts vendor 6,000 EFC budget in ~8.2 years")
    print(f"     → would require oversized warranty contract OR augmentation re-spec")
    print(f"  Investment model param: efc_budget = 6000, annual_efc_assumption = 365")
    print(f"  Both would need updating before claiming 2-cycle revenue is bankable.")
    print(f"{'=' * 78}")


if __name__ == "__main__":
    main()
