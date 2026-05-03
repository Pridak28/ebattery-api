"""Scrape real Romanian aFRR capacity-tender clearing prices from DAMAS.

Source: Transelectrica DAMAS II "Ancillary Services Tender Statistics".
Public data — Transelectrica is required by EU EBGL Article 12 to publish
balancing reserve procurement results. Single-shot, sequential, with
3-second delays between page loads. Default Playwright user-agent
(transparent automation).

Strategy:
  - Sample ~12 tenders across the project's 12-month analysis window.
  - For each, extract aFRRUp + aFRRDown hourly capacity clearing prices
    and average across the 24 hourly slots.
  - Write to backend/data_catalog/processed/damas_capacity_clearing.csv.

Output schema:
  tender_code, delivery_date, service, demand_mw, satisfied_pct_avg,
  avg_clearing_price_lei_mw_h, avg_clearing_price_eur_mw_h, n_hours

Run from `backend/`:
    PYTHONPATH=. arch -arm64 /usr/local/bin/python3 scripts/scrape_damas_capacity.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_CSV = ROOT / "data_catalog" / "processed" / "damas_capacity_clearing.csv"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

BASE = "https://newmarkets.transelectrica.ro/uu-webkit-maing02/00121011300000000000000000000100/tenderStatistics"

# Sample tender codes spread across our 12-month analysis window
# (2025-05-01 → 2026-05-01). Empirical mapping from the discovery probe:
# 100_2025 = 2025-04-08, 200_2025 = 2025-06-22, 300_2025 = 2025-08-11,
# 400_2025 = 2025-09-28, 1_2026 = 2026-01-01, 100_2026 = 2026-02-19.
# We sample ~one per month covering the window.
SAMPLE_CODES = [
    "120_2025",   # ~ 2025-05 mid
    "163_2025",   # 2025-06-05 (already known good)
    "200_2025",   # 2025-06-22
    "230_2025",   # ~ 2025-07
    "275_2025",   # ~ 2025-07-end / 2025-08
    "320_2025",   # ~ 2025-08-end
    "380_2025",   # ~ 2025-09-end
    "440_2025",   # ~ 2025-10
    "490_2025",   # ~ 2025-11
    "550_2025",   # ~ 2025-12
    "1_2026",     # 2026-01-01
    "30_2026",    # 2026-01-15
    "60_2026",    # ~ 2026-02
    "100_2026",   # 2026-02-19
    "150_2026",   # ~ 2026-03
    "200_2026",   # ~ 2026-04
    "250_2026",   # ~ 2026-05
]

SERVICES = ["aFRRUp", "aFRRDown"]
RON_PER_EUR = 5.0  # FX assumption (range 4.85-5.20; sensitivity = ±5%)


def extract_table(page) -> list[dict]:
    titles = page.evaluate("""
        () => Array.from(document.querySelectorAll('[title]'))
              .map(e => e.getAttribute('title'))
              .filter(t => t && t.length > 0)
    """)
    parsed = []
    i, n = 0, len(titles)
    while i < n:
        t = titles[i]
        if " - " in t and "." in t and any(c.isdigit() for c in t):
            if i + 3 < n:
                try:
                    parsed.append({
                        "time_interval": t,
                        "demand_mw": float(titles[i + 1].replace(",", ".")),
                        "satisfied_pct": float(titles[i + 2].replace(",", ".")),
                        "avg_price_lei": float(titles[i + 3].replace(",", ".")),
                    })
                    i += 4
                    continue
                except ValueError:
                    pass
        i += 1
    return parsed


def get_delivery_date(page) -> str:
    """Read the 'Time interval' / delivery date from the basic-params block."""
    text = page.evaluate("() => document.body.innerText") or ""
    import re
    m = re.search(r"Time interval\s+(\d+\.\s*\d+\.\s*\d+)", text)
    return m.group(1).strip() if m else ""


def scrape_tender(page, code: str) -> list[dict]:
    """Render one tender and extract avg price for both services."""
    url = f"{BASE}?code={code}"
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    try:
        page.wait_for_function(
            """() => Array.from(document.querySelectorAll('[title]'))
                        .some(e => /\\d+\\.\\s*\\d+\\.\\s*\\d{4}/.test(e.getAttribute('title') || ''))""",
            timeout=30_000,
        )
    except Exception:
        return []
    time.sleep(2)

    delivery_date = get_delivery_date(page)
    out = []
    for service in SERVICES:
        try:
            page.get_by_text(service, exact=True).first.click(timeout=10_000)
            time.sleep(2.5)
            rows = extract_table(page)
            if rows:
                avg_lei = sum(r["avg_price_lei"] for r in rows) / len(rows)
                demand = sum(r["demand_mw"] for r in rows) / len(rows)
                satisfied = sum(r["satisfied_pct"] for r in rows) / len(rows)
                out.append({
                    "tender_code": code,
                    "delivery_date": delivery_date,
                    "service": service,
                    "demand_mw_avg": round(demand, 1),
                    "satisfied_pct_avg": round(satisfied, 2),
                    "n_hours": len(rows),
                    "avg_clearing_price_lei_mw_h": round(avg_lei, 4),
                    "avg_clearing_price_eur_mw_h": round(avg_lei / RON_PER_EUR, 4),
                })
        except Exception as exc:
            print(f"    {service} failed: {type(exc).__name__}: {exc}")
    return out


def main() -> None:
    from playwright.sync_api import sync_playwright
    print(f"Scraping {len(SAMPLE_CODES)} tenders × {len(SERVICES)} services from DAMAS")
    print(f"Output: {OUT_CSV}")

    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        for idx, code in enumerate(SAMPLE_CODES, 1):
            print(f"\n[{idx}/{len(SAMPLE_CODES)}] {code}")
            try:
                tender_rows = scrape_tender(page, code)
                if tender_rows:
                    for r in tender_rows:
                        print(f"    {r['service']}  date={r['delivery_date']:14s}  "
                              f"demand={r['demand_mw_avg']:>5.0f}MW  "
                              f"avg={r['avg_clearing_price_lei_mw_h']:>7.2f} LEI/MW/h "
                              f"= €{r['avg_clearing_price_eur_mw_h']:.2f}/MW/h")
                    rows.extend(tender_rows)
                else:
                    print("    (no data — possibly invalid tender code)")
            except Exception as exc:
                print(f"    FAIL {type(exc).__name__}: {exc}")
            time.sleep(1)
        browser.close()

    if not rows:
        print("\nNo data scraped — bailing without writing CSV.")
        return

    # Write CSV
    import csv
    fields = list(rows[0].keys())
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {len(rows)} rows → {OUT_CSV}")

    # Quick aggregates
    by_service = {}
    for r in rows:
        by_service.setdefault(r["service"], []).append(r["avg_clearing_price_eur_mw_h"])
    print("\nAggregates (€/MW/h):")
    for svc, prices in by_service.items():
        if prices:
            mn = min(prices)
            mx = max(prices)
            avg = sum(prices) / len(prices)
            print(f"  {svc:12s}  n={len(prices):>3d}  min={mn:>6.2f}  avg={avg:>6.2f}  max={mx:>6.2f}")


if __name__ == "__main__":
    main()
