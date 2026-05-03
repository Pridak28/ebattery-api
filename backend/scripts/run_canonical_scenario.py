"""Run PZU arbitrage + aFRR + investment ROI on canonical 10 MW / 20 MWh BESS.

One-shot driver script: loads each service with its real Romanian market
data, runs the canonical investor-grade scenario (€3.5M EPC, 30% equity,
6% loan, 10y term, 88% RTE), and prints the headline numbers.

Field names match the actual Pydantic response models — see
backend/app/models/{pzu,investment}.py and the FRService method docstrings.

Run from `backend/`:
    PYTHONPATH=. arch -arm64 /usr/local/bin/python3 scripts/run_canonical_scenario.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models.investment import InvestmentParams  # noqa: E402
from app.models.pzu import PZUSimulationParams  # noqa: E402
from app.services.fr_service import FRService  # noqa: E402
from app.services.investment_service import InvestmentService  # noqa: E402
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
    fr = FRService()
    inv = InvestmentService()

    # =================== PZU 12-month arbitrage =================== #
    hr("PZU arbitrage — canonical 10 MW / 20 MWh, 88% RTE, full data window")
    pzu_params = PZUSimulationParams(
        power_mw=10.0,
        capacity_mwh=20.0,
        round_trip_efficiency=0.88,
    )
    pzu_resp = pzu.simulate(pzu_params)
    yearly = pzu_resp.yearly_summary

    print(f"  Days input / simulated / no-pair / rejected: "
          f"{pzu_resp.days_input_count} / "
          f"{pzu_resp.days_simulated_count} / "
          f"{pzu_resp.days_no_profitable_pair} / "
          f"{pzu_resp.days_rejected_data_quality}")
    print(f"  Total NET PROFIT (window):    {fmt_eur(pzu_resp.total_profit_eur)}")
    print(f"  Gross revenue (sells):        {fmt_eur(pzu_resp.total_gross_revenue_eur)}")
    print(f"  Charging cost (buys):         {fmt_eur(pzu_resp.total_energy_cost_eur)}")
    print(f"  Avg monthly profit:           {fmt_eur(pzu_resp.avg_monthly_profit_eur)}")
    print(f"  Months in result:             {len(pzu_resp.monthly_results)}")
    if yearly:
        print(f"  Yearly summary (year {yearly.year}):")
        print(f"    Total cycles:               {yearly.total_cycles:,.1f}")
        print(f"    Gross profit:               {fmt_eur(yearly.gross_profit_eur)}")
        print(f"    Net profit:                 {fmt_eur(yearly.net_profit_eur)}")
        print(f"    Avg daily profit:           {fmt_eur(yearly.avg_daily_profit_eur)}")
        print(f"    Best / worst month:         {yearly.best_month} / {yearly.worst_month}")

    if pzu_resp.monthly_results:
        # 12-month windowed view: take the most recent 12 months by date string.
        sorted_months = sorted(pzu_resp.monthly_results, key=lambda m: m.month)
        last12 = sorted_months[-12:]
        last12_profit = sum(m.net_profit_eur for m in last12)
        print(f"\n  Last-12-months net profit:    {fmt_eur(last12_profit)}")
        print(f"  (months {last12[0].month} → {last12[-1].month})")
        print("\n  Last 12 monthly profits:")
        for m in last12:
            print(f"    {m.month}: net {fmt_eur(m.net_profit_eur):>12s}  "
                  f"gross {fmt_eur(m.gross_profit_eur):>12s}  "
                  f"days {m.days:>2d}")

    # =================== aFRR 12-month projection =================== #
    hr("aFRR (DAMAS) — annualized revenue projection, balanced strategy, 10 MW")
    fr_balanced = fr.project_annual_revenue(power_mw=10.0, strategy="balanced")
    months = fr_balanced.get("monthly_projections", [])
    annual = fr_balanced.get("total_projected_annual_revenue", 0.0)
    n = fr_balanced.get("months_analyzed", len(months))
    print(f"  Months analyzed:              {n}")
    print(f"  Annualized revenue (Y1):      {fmt_eur(annual)}")
    print(f"  Avg monthly revenue:          {fmt_eur(fr_balanced.get('avg_monthly_revenue', 0.0))}")
    print(f"  Acceptance rate assumed:      {fr_balanced.get('acceptance_rate', 0):.0%}")

    # Strategy comparison.
    print("\n  Strategy comparison (annualized Y1 revenue, 10 MW):")
    for strat in ("conservative", "balanced", "aggressive"):
        out = fr.project_annual_revenue(power_mw=10.0, strategy=strat)
        total = out.get("total_projected_annual_revenue", 0.0)
        print(f"    {strat:13s}: {fmt_eur(total)}  ({out.get('months_analyzed', 0)} months)")

    # Show recent monthly breakdown.
    if months:
        print("\n  Last 6 monthly aFRR projections (balanced):")
        for m in months[-6:]:
            print(f"    {m['month']}: {m['selected_service']:6s}  "
                  f"monthly rev {fmt_eur(m['monthly_revenue']):>14s}  "
                  f"(aFRR+ {fmt_eur(m['afrr_up_revenue'])}, "
                  f"aFRR- {fmt_eur(m['afrr_down_revenue'])})")

    # =================== Single-day optimal bid (Branch 1 reduction in action) =================== #
    hr("aFRR optimal bids — single recent day, with new capacity_mwh override")
    bid_date = "2025-12-15"  # within the DAMAS window
    out_default = fr.calculate_optimal_bids(date_str=bid_date, power_mw=10.0)
    out_override = fr.calculate_optimal_bids(
        date_str=bid_date, power_mw=10.0, capacity_mwh=40.0,
    )
    print(f"  Target date: {bid_date}")
    if "error" not in out_default:
        rec = out_default["optimal_bids"]
        print(f"  Default capacity (settings.DEFAULT_CAPACITY_MWH = 20):")
        print(f"    aFRR+ bid {rec['afrr_up']['recommended_capacity_bid']:.2f} EUR/MW/h, "
              f"daily est. revenue {fmt_eur(rec['afrr_up']['estimated_daily_revenue'])}")
        print(f"    aFRR- bid {rec['afrr_down']['recommended_capacity_bid']:.2f} EUR/MW/h, "
              f"daily est. revenue {fmt_eur(rec['afrr_down']['estimated_daily_revenue'])}")
        print(f"    Recommendation: {out_default['recommendation']}")
    else:
        print(f"  Default: ERROR → {out_default['error']}")
    if "error" not in out_override and "error" not in out_default:
        a_o = out_override["optimal_bids"]["afrr_up"]["activation_component"]
        a_d = out_default["optimal_bids"]["afrr_up"]["activation_component"]
        print(f"  Override capacity_mwh=40.0 (Branch 1 reduction in action):")
        print(f"    aFRR+ activation revenue: {fmt_eur(a_o)} (vs default {fmt_eur(a_d)})")

    # =================== Investment / ROI =================== #
    hr("Investment ROI — canonical scenario (FR vs PZU stacked, 15-yr life)")
    inv_params = InvestmentParams()  # canonical defaults
    inv_resp = inv.analyze(inv_params)

    print(f"  EPC investment:               {fmt_eur(inv_params.total_investment_eur)}  "
          f"({inv_params.total_investment_eur / (inv_params.power_mw * 1000):.0f} EUR/kW)")
    print(f"  Battery:                      {inv_params.power_mw} MW / {inv_params.capacity_mwh} MWh")
    print(f"  Equity / loan:                {inv_params.equity_percentage}% / "
          f"{inv_params.loan_interest_rate}% over {inv_params.loan_term_years}y")
    print(f"  RTE / SOC band / aux load:    {inv_params.rte_ac_ac:.2f} / "
          f"{inv_params.soc_min:.0%}-{inv_params.soc_max:.0%} / "
          f"{inv_params.auxiliary_load_mw} MW")
    print(f"  Recommended scenario:         {inv_resp.recommended_scenario}")
    print(f"  Advantage:                    {fmt_eur(inv_resp.advantage_eur)} "
          f"({inv_resp.advantage_percentage:+.1f}%)")
    print(f"  Projection horizon:           {inv_resp.projection_horizon_years} years")

    # Per-scenario summary (FR vs PZU).
    print("\n  Per-scenario (Y1 single-product, BEFORE compression / degradation):")
    print(f"    {'Scenario':10s}  {'gross rev':>14s}  {'energy cost':>14s}  "
          f"{'opex':>14s}  {'debt service':>14s}  {'net after debt':>14s}  "
          f"{'ROI%':>8s}  {'PB (yrs)':>10s}")
    for s in (inv_resp.fr_scenario, inv_resp.pzu_scenario):
        print(f"    {s.name:10s}  "
              f"{fmt_eur(s.gross_revenue_eur):>14s}  "
              f"{fmt_eur(s.energy_cost_eur):>14s}  "
              f"{fmt_eur(s.operating_cost_eur):>14s}  "
              f"{fmt_eur(s.annual_debt_service_eur):>14s}  "
              f"{fmt_eur(s.net_profit_after_debt_eur):>14s}  "
              f"{s.roi_percentage:>7.2f}%  "
              f"{s.payback_years:>8.2f}y")

    # Lifetime metrics — the bankability number.
    print("\n  Lifetime (over projection horizon):")
    print(f"    FR  Y1 ROI  : {inv_resp.fr_year1_roi_pct:>6.2f}%   "
          f"lifetime IRR: {inv_resp.fr_lifetime_irr_pct if inv_resp.fr_lifetime_irr_pct is not None else 'n/a':>6}   "
          f"lifetime payback: "
          f"{inv_resp.fr_lifetime_payback_years if inv_resp.fr_lifetime_payback_years is not None else 'n/a'}")
    print(f"    PZU Y1 ROI  : {inv_resp.pzu_year1_roi_pct:>6.2f}%   "
          f"lifetime IRR: {inv_resp.pzu_lifetime_irr_pct if inv_resp.pzu_lifetime_irr_pct is not None else 'n/a':>6}   "
          f"lifetime payback: "
          f"{inv_resp.pzu_lifetime_payback_years if inv_resp.pzu_lifetime_payback_years is not None else 'n/a'}")

    # FR cashflow — first 5 years.
    if inv_resp.fr_cashflow:
        print("\n  FR cashflow — first 5 years (after compression & degradation):")
        print(f"    {'year':>4s}  {'revenue':>14s}  {'opex':>14s}  "
              f"{'debt':>14s}  {'cashflow':>14s}  {'cum cashflow':>14s}")
        for cf in inv_resp.fr_cashflow[:5]:
            cf_d = cf.model_dump() if hasattr(cf, "model_dump") else cf.dict()
            print(f"    {cf_d.get('year', '?'):>4}  "
                  f"{fmt_eur(cf_d.get('gross_revenue_eur', 0)):>14s}  "
                  f"{fmt_eur(cf_d.get('operating_cost_eur', 0)):>14s}  "
                  f"{fmt_eur(cf_d.get('debt_service_eur', 0)):>14s}  "
                  f"{fmt_eur(cf_d.get('net_profit_eur', 0)):>14s}  "
                  f"{fmt_eur(cf_d.get('cumulative_profit_eur', 0)):>14s}")

    # PZU cashflow — first 5 years.
    if inv_resp.pzu_cashflow:
        print("\n  PZU cashflow — first 5 years:")
        print(f"    {'year':>4s}  {'revenue':>14s}  {'opex':>14s}  "
              f"{'debt':>14s}  {'cashflow':>14s}  {'cum cashflow':>14s}")
        for cf in inv_resp.pzu_cashflow[:5]:
            cf_d = cf.model_dump() if hasattr(cf, "model_dump") else cf.dict()
            print(f"    {cf_d.get('year', '?'):>4}  "
                  f"{fmt_eur(cf_d.get('gross_revenue_eur', 0)):>14s}  "
                  f"{fmt_eur(cf_d.get('operating_cost_eur', 0)):>14s}  "
                  f"{fmt_eur(cf_d.get('debt_service_eur', 0)):>14s}  "
                  f"{fmt_eur(cf_d.get('net_profit_eur', 0)):>14s}  "
                  f"{fmt_eur(cf_d.get('cumulative_profit_eur', 0)):>14s}")

    # Compliance gates + DSCR violations.
    if inv_resp.dscr_violation_years:
        print(f"\n  ⚠ DSCR < 1.20 in years: {inv_resp.dscr_violation_years}")
    if inv_resp.compliance_revenue_streams_blocked:
        print(f"  ⚠ Revenue streams blocked by compliance: "
              f"{inv_resp.compliance_revenue_streams_blocked}")
    if inv_resp.warnings:
        print("\n  Top-level warnings:")
        for w in inv_resp.warnings:
            print(f"    - {w}")

    # =================== Footer =================== #
    print("\n" + "=" * 78)
    print("All figures are SIMULATED on real Romanian PZU + DAMAS aFRR data.")
    print("Manifest: backend/data/manifest.json — see /api/v1/data/manifest live.")
    print("These numbers are NOT bankable. See:")
    print("  audit/REVIEW_NOTES_LOCAL_AGENT_2026-05-03.md")
    print("  audit/BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT_2026-05-01.md (excluded costs).")
    print("=" * 78)


if __name__ == "__main__":
    main()
