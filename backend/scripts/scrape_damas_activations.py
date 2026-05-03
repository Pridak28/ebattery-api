"""Scrape today's DAMAS activation prices + volumes from Transelectrica.

Pulls the live `marginalPricesOverview` (per-15-min activation clearing
prices) and `activatedBalancingEnergyOverview` (per-15-min activated
volumes) for the current day. Saves as CSV and compares against our
existing damas_clean.csv to flag any drift between the live source and
our cached snapshot.

Run from `backend/`:
    PYTHONPATH=. arch -arm64 /usr/local/bin/python3 scripts/scrape_damas_activations.py
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data_catalog" / "processed" / "damas_live_snapshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHED_CSV = ROOT / "data_catalog" / "processed" / "damas_clean.csv"

BASE = "https://newmarkets.transelectrica.ro/uu-webkit-maing02/00121011300000000000000000000100/"
PAGES = {
    "marginalPricesOverview": [
        "aFRR Up [LEI]", "aFRR Down [LEI]",
        "mFRR Up Scheduled [LEI]", "mFRR Down Scheduled [LEI]",
        "mFRR Up Direct [LEI]", "mFRR Down Direct [LEI]",
        "RR Up [LEI]", "RR Down [LEI]",
    ],
    "activatedBalancingEnergyOverview": [
        "FCR [MWh]", "aFRR Up [MWh]", "aFRR Down [MWh]",
        "mFRR Up [MWh]", "mFRR Down [MWh]", "RR Up [MWh]", "RR Down [MWh]",
    ],
}
RON_PER_EUR = 5.0
INTERVAL_RX = re.compile(r"^\d+\.\s*\d+\.\s*\d{4}\s+\d+:\d+\s*-\s*\d+\.\s*\d+\.\s*\d{4}\s+\d+:\d+$")


def extract_table(page, ncols: int) -> list[list[str]]:
    """Extract rows from a virtualized [title]-grid table.

    Empty cells in DAMAS don't render with a [title] attribute, so per
    row we get a variable count of titles: 1 interval + 0 to (ncols-1)
    numeric values. We collect everything between consecutive intervals
    as that interval's value list, then in the caller we treat positional
    indices 0,1 as aFRR Up / aFRR Down (the only columns we actually
    consume — the rest are mFRR/RR which we ignore).
    """
    seen: dict[str, list[str]] = {}

    def grab() -> int:
        titles = page.evaluate("""
            () => Array.from(document.querySelectorAll('[title]'))
                  .map(e => e.getAttribute('title'))
                  .filter(t => t && t.length > 0)
        """)
        added = 0
        i, n = 0, len(titles)
        while i < n:
            t = titles[i]
            if INTERVAL_RX.match(t.strip()):
                # Collect non-interval titles until the next interval (or end).
                values: list[str] = []
                j = i + 1
                while j < n and not INTERVAL_RX.match(titles[j].strip()):
                    values.append(titles[j])
                    j += 1
                if t not in seen:
                    # Pad to ncols-1 with empty strings for downstream alignment.
                    padded = values[: ncols - 1]
                    while len(padded) < ncols - 1:
                        padded.append("")
                    seen[t] = [t] + padded
                    added += 1
                i = j
                continue
            i += 1
        return added

    grab()
    no_progress = 0
    for _ in range(80):
        page.evaluate("""
            () => {
                document.querySelectorAll('*').forEach(el => {
                    if (el.scrollHeight > el.clientHeight + 20) {
                        el.scrollBy({top: 200, behavior: 'auto'});
                    }
                });
                window.scrollBy(0, 200);
            }
        """)
        time.sleep(0.35)
        added = grab()
        if added == 0:
            no_progress += 1
            if no_progress >= 6:
                break
        else:
            no_progress = 0
    return sorted(seen.values(), key=lambda r: r[0])


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    import csv
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    from playwright.sync_api import sync_playwright
    today = time.strftime("%Y-%m-%d")
    print(f"DAMAS live scrape — {today}")
    snapshots = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        for slug, columns in PAGES.items():
            url = BASE + slug
            print(f"\n[{slug}]")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                # Wait for at least one interval-format [title] to appear.
                try:
                    page.wait_for_function(
                        """() => Array.from(document.querySelectorAll('[title]'))
                                    .some(e => /\\d+\\.\\s*\\d+\\.\\s*\\d{4}\\s+\\d+:\\d+\\s*-/.test(e.getAttribute('title') || ''))""",
                        timeout=30_000,
                    )
                except Exception:
                    print("  (table did not render — proceeding)")
                time.sleep(3)
                ncols = 1 + len(columns)
                rows = extract_table(page, ncols)
                print(f"  Extracted {len(rows)} rows × {ncols} cols (expected ~96 × {ncols})")
                if rows:
                    clean_rows = rows  # extractor already pads / aligns
                    out_path = OUT_DIR / f"{slug}_{today}.csv"
                    write_csv(out_path, ["time_interval"] + columns, clean_rows)
                    print(f"  → {out_path}")
                    snapshots[slug] = (out_path, columns)

                    def _safe_float(s: str) -> float | None:
                        try:
                            return float((s or "").replace(",", "."))
                        except ValueError:
                            return None

                    if slug == "marginalPricesOverview":
                        afrr_up_lei = [v for r in clean_rows
                                       if (v := _safe_float(r[1])) is not None]
                        afrr_down_lei = [v for r in clean_rows
                                         if (v := _safe_float(r[2])) is not None]
                        if afrr_up_lei:
                            print(f"  aFRR Up:   n={len(afrr_up_lei):>2d}  "
                                  f"mean {sum(afrr_up_lei)/len(afrr_up_lei):>8.1f} LEI/MWh "
                                  f"= €{sum(afrr_up_lei)/len(afrr_up_lei)/RON_PER_EUR:>6.2f}/MWh "
                                  f"min {min(afrr_up_lei):>7.1f}  max {max(afrr_up_lei):>7.1f}")
                        if afrr_down_lei:
                            print(f"  aFRR Down: n={len(afrr_down_lei):>2d}  "
                                  f"mean {sum(afrr_down_lei)/len(afrr_down_lei):>8.1f} LEI/MWh "
                                  f"= €{sum(afrr_down_lei)/len(afrr_down_lei)/RON_PER_EUR:>6.2f}/MWh "
                                  f"min {min(afrr_down_lei):>7.1f}  max {max(afrr_down_lei):>7.1f}")
                    elif slug == "activatedBalancingEnergyOverview":
                        afrr_up_mwh = [v for r in clean_rows
                                       if (v := _safe_float(r[2])) is not None]
                        afrr_down_mwh = [v for r in clean_rows
                                         if (v := _safe_float(r[3])) is not None]
                        if afrr_up_mwh:
                            print(f"  aFRR Up activated:   n={len(afrr_up_mwh):>2d}  "
                                  f"total {sum(afrr_up_mwh):>8.2f} MWh  "
                                  f"max slot {max(afrr_up_mwh):.2f} MWh")
                        if afrr_down_mwh:
                            print(f"  aFRR Down activated: n={len(afrr_down_mwh):>2d}  "
                                  f"total {sum(afrr_down_mwh):>8.2f} MWh  "
                                  f"max slot {max(afrr_down_mwh):.2f} MWh")
            except Exception as e:
                print(f"  FAIL: {type(e).__name__}: {e}")
        browser.close()

    # ---- Comparison vs cached damas_clean.csv ----
    print(f"\n=== Drift check vs {CACHED_CSV.name} ===")
    if not CACHED_CSV.exists():
        print("  Cached CSV missing — skipping comparison.")
        return
    import pandas as pd
    df = pd.read_csv(CACHED_CSV)
    df["date"] = pd.to_datetime(df["date"])
    last_7 = df[df["date"] >= df["date"].max() - pd.Timedelta(days=7)]
    print(f"  Cached data window: {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"  Last 7 days in cache: aFRR Up activation price mean = "
          f"{last_7['afrr_up_price_eur'].mean():.2f} €/MWh, "
          f"max = {last_7['afrr_up_price_eur'].max():.2f}")
    print(f"  Last 7 days in cache: aFRR Down activation price mean = "
          f"{last_7['afrr_down_price_eur'].mean():.2f} €/MWh, "
          f"min = {last_7['afrr_down_price_eur'].min():.2f}")
    print(f"  Last 7 days in cache: aFRR Up activation volume total = "
          f"{last_7['afrr_up_activated_mwh'].sum():.0f} MWh "
          f"(daily avg {last_7['afrr_up_activated_mwh'].sum()/7:.1f} MWh)")
    print(f"  Today on DAMAS (single day): see scraped numbers above.")
    print(f"  Cache covers up to {df['date'].max().date()}. Today is {today}.")
    print(f"  Cache is {(pd.Timestamp(today) - df['date'].max()).days} days behind live DAMAS.")


if __name__ == "__main__":
    main()
