"""PZU spread distribution + capacity-utilization sensitivity.

Two questions:
  1. What is the actual OPCOM PZU intraday spread? (raw market data, no model)
  2. If the install is sized so the FULL 20 MWh is usable per cycle (oversize
     the nominal capacity, or widen the SOC band), what does that do to
     revenue?

Both come from the same `_load_price_data()` source the simulator uses.

Run from `backend/`:
    PYTHONPATH=. arch -arm64 /usr/local/bin/python3 scripts/pzu_spread_and_capacity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.pzu import PZUSimulationParams  # noqa: E402
from app.services.pzu_service import PZUService  # noqa: E402


def hr(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n{title}\n{bar}")


def fmt_eur(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"€{value:,.0f}"


def main() -> None:
    pzu = PZUService()
    df = pzu._load_price_data().copy()

    # Normalise columns: expect (date, hour, price).
    if "hour" not in df.columns:
        # Some loaders use a Period-like index; fall back to hour-of-day.
        df["hour"] = pd.to_datetime(df["date"]).dt.hour
    if "price" not in df.columns:
        df = df.rename(columns={df.columns[1]: "price"})
    df["date_only"] = pd.to_datetime(df["date"]).dt.date

    # ---------------- Raw spread statistics ---------------- #
    hr("OPCOM PZU intraday spread — raw market data, no dispatch model")
    daily = df.groupby("date_only").agg(
        n_hours=("price", "count"),
        min=("price", "min"),
        p10=("price", lambda s: float(np.nanpercentile(s, 10))),
        p25=("price", lambda s: float(np.nanpercentile(s, 25))),
        median=("price", "median"),
        p75=("price", lambda s: float(np.nanpercentile(s, 75))),
        p90=("price", lambda s: float(np.nanpercentile(s, 90))),
        max=("price", "max"),
        mean=("price", "mean"),
    )
    daily["spread_max_min"] = daily["max"] - daily["min"]
    daily["spread_p90_p10"] = daily["p90"] - daily["p10"]
    daily["spread_p75_p25"] = daily["p75"] - daily["p25"]

    full_days = daily[daily["n_hours"] >= 20]
    print(f"  Days with ≥20 hourly prices: {len(full_days)} (of {len(daily)} total)")
    print(f"  Date range: {full_days.index.min()} → {full_days.index.max()}")
    print(f"  Avg daily PZU price (all hours):     "
          f"{full_days['mean'].mean():.2f} €/MWh")
    print()
    print(f"  Spread (max − min):    "
          f"mean {full_days['spread_max_min'].mean():.2f}, "
          f"median {full_days['spread_max_min'].median():.2f}, "
          f"p10/p90 {full_days['spread_max_min'].quantile(0.10):.2f} / "
          f"{full_days['spread_max_min'].quantile(0.90):.2f}")
    print(f"  Spread (p90 − p10):    "
          f"mean {full_days['spread_p90_p10'].mean():.2f}, "
          f"median {full_days['spread_p90_p10'].median():.2f}, "
          f"p10/p90 {full_days['spread_p90_p10'].quantile(0.10):.2f} / "
          f"{full_days['spread_p90_p10'].quantile(0.90):.2f}")
    print(f"  Spread (p75 − p25):    "
          f"mean {full_days['spread_p75_p25'].mean():.2f}, "
          f"median {full_days['spread_p75_p25'].median():.2f}")
    print(f"  Best 2h-block buy / best 2h-block sell (avg over data):")

    # 2h block min and max — what the dispatcher actually targets.
    def _two_h_extremes(group: pd.DataFrame) -> pd.Series:
        prices = np.full(24, np.nan)
        for _, row in group.iterrows():
            h = int(row["hour"])
            if 0 <= h < 24:
                prices[h] = float(row["price"])
        # rolling 2h means
        sums = np.array([prices[h] + prices[h + 1] for h in range(23)])
        valid = ~np.isnan(sums)
        if not valid.any():
            return pd.Series({"buy_2h": np.nan, "sell_2h": np.nan, "spread_2h": np.nan})
        means = sums[valid] / 2.0
        return pd.Series({
            "buy_2h": float(means.min()),
            "sell_2h": float(means.max()),
            "spread_2h": float(means.max() - means.min()),
        })

    blocks = df.groupby("date_only").apply(_two_h_extremes, include_groups=False)
    blocks_full = blocks.dropna()
    print(f"    cheapest 2h block:  mean {blocks_full['buy_2h'].mean():.2f} €/MWh")
    print(f"    priciest 2h block:  mean {blocks_full['sell_2h'].mean():.2f} €/MWh")
    print(f"    2h-block spread:    mean {blocks_full['spread_2h'].mean():.2f} €/MWh, "
          f"median {blocks_full['spread_2h'].median():.2f}")
    print(f"    2h-block spread:    p25/p75 "
          f"{blocks_full['spread_2h'].quantile(0.25):.2f} / "
          f"{blocks_full['spread_2h'].quantile(0.75):.2f}")

    # Last 12 months — recent-market figure for the investor pitch.
    last_12mo_start = pd.to_datetime(df["date"]).max() - pd.Timedelta(days=365)
    blocks_12mo = blocks_full[
        pd.to_datetime(blocks_full.index) >= last_12mo_start
    ]
    print(f"\n  Last 12 months ({len(blocks_12mo)} days):")
    print(f"    cheapest 2h block:  mean {blocks_12mo['buy_2h'].mean():.2f} €/MWh")
    print(f"    priciest 2h block:  mean {blocks_12mo['sell_2h'].mean():.2f} €/MWh")
    print(f"    2h-block spread:    mean {blocks_12mo['spread_2h'].mean():.2f}, "
          f"median {blocks_12mo['spread_2h'].median():.2f} €/MWh")

    # Monthly seasonality — last 12 months.
    blocks_12mo_idx = blocks_12mo.copy()
    blocks_12mo_idx["month"] = pd.to_datetime(blocks_12mo_idx.index).strftime("%Y-%m")
    print("\n  Monthly 2h-block spread (last 12 months):")
    monthly = blocks_12mo_idx.groupby("month")["spread_2h"].agg(
        mean="mean", median="median", n_days="count",
    )
    for m, row in monthly.iterrows():
        bar = "█" * int(row["mean"] / 5)
        print(f"    {m}  mean {row['mean']:>6.2f}  median {row['median']:>6.2f}  "
              f"n {int(row['n_days']):>2d}  {bar}")

    # ---------------- Capacity sensitivity ---------------- #
    hr("Dispatch sensitivity — what changes when the install is sized for full 20 MWh usable")

    # Run 4 scenarios. Each uses the SAME real market data.
    scenarios = [
        # name,                   capacity, soc_min, soc_max, soc_initial,  comment
        ("Current model (8 MWh usable)", 20.0, 0.10, 0.90, 0.50, "stationary 50% start"),
        ("Full warranty band (16 MWh usable)", 20.0, 0.10, 0.90, 0.10, "10→90 band, daily reset to 10%"),
        ("Oversized install (20 MWh usable, 25 MWh nominal)", 25.0, 0.10, 0.90, 0.10, "25 MWh nameplate, 80% DOD"),
        ("Full DOD on 20 MWh nominal (no warranty buffer)", 20.0, 0.0, 1.0, 0.0, "AGGRESSIVE — voids most warranties"),
    ]

    print(f"  {'Scenario':52s}  {'usable/cycle':>13s}  {'12mo net':>12s}  {'12mo gross sell':>16s}  {'12mo buy cost':>14s}")
    for name, cap, smin, smax, sinit, _comment in scenarios:
        params = PZUSimulationParams(
            power_mw=10.0,
            capacity_mwh=cap,
            round_trip_efficiency=0.88,
            soc_min=smin,
            soc_max=smax,
            soc_initial=sinit,
        )
        resp = pzu.simulate(params)
        # 12-month slice from the last 12 months of monthly_results.
        sorted_months = sorted(resp.monthly_results, key=lambda m: m.month)
        last12 = sorted_months[-12:]
        net12 = sum(m.net_profit_eur for m in last12)
        # Gross / cost are only available at top-level (full window). Pro-rate
        # by months covered to estimate the last-12-month gross/cost.
        n_months = max(len(resp.monthly_results), 1)
        gross_12mo = resp.total_gross_revenue_eur * 12 / n_months
        cost_12mo = resp.total_energy_cost_eur * 12 / n_months
        usable = cap * (smax - sinit)
        print(f"  {name:52s}  {usable:>10.1f} MWh  "
              f"{fmt_eur(net12):>12s}  {fmt_eur(gross_12mo):>16s}  {fmt_eur(cost_12mo):>14s}")

    print("\n  All four runs use the same OPCOM data, the same chronological")
    print("  SOC-aware dispatcher, and the same 88% RTE. Only the SOC band /")
    print("  starting SOC / nameplate capacity differs.")

    print("\n" + "=" * 78)
    print("Notes:")
    print("  - 'Current model' is what the canonical-scenario report uses today.")
    print("  - 'Full warranty band' is what the morning fix would land — same")
    print("    20 MWh nameplate but full 10-90% SOC traversal each day.")
    print("  - 'Oversized install' (25 MWh nominal → 20 MWh usable inside the")
    print("    warranty band) matches the user's real-install assumption.")
    print("  - 'Full DOD' is the aggressive ceiling; voids most Li-ion warranties.")
    print("  - All numbers are SIMULATED on real Romanian PZU data — not bankable.")
    print("=" * 78)


if __name__ == "__main__":
    main()
