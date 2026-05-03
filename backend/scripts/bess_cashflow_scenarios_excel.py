"""15-year BESS cashflow Excel with 4 scenarios (Goldman-grade format).

Combines aFRR (real DAMAS-anchored) + PZU (real OPCOM-derived) revenue
into a full project finance view: 15-year cashflow, debt service,
augmentation, equity / project IRR, NPV @ 8%, payback, DSCR per year.

Sheet layout:
  1. Executive_Summary           — headline KPIs across 4 scenarios
  2. Inputs_and_Assumptions      — battery, financing, scenario params
  3. Scenario_A_Current          — 15yr cashflow detail
  4. Scenario_B_PICASSO          — 15yr cashflow detail
  5. Scenario_C_Mature           — 15yr cashflow detail
  6. Scenario_D_Bear             — 15yr cashflow detail
  7. Scenarios_Comparison        — side-by-side annual + KPI comparison

Run from `backend/`:
    PYTHONPATH=. arch -arm64 /usr/local/bin/python3 scripts/bess_cashflow_scenarios_excel.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ===================================================================
#  Project finance inputs (mirror InvestmentParams defaults)
# ===================================================================
EPC_INVESTMENT_EUR = 3_500_000.0          # 10 MW / 20 MWh @ €175/kWh
POWER_MW = 10.0
CAPACITY_MWH = 20.0
EQUITY_PCT = 30.0                          # %
LOAN_PCT = 70.0                            # %
LOAN_RATE = 0.06                           # 6%
LOAN_TERM_YR = 10
OPEX_PCT_OF_EPC = 2.0                      # 2% of EPC = €70k/yr Y1
INSURANCE_PCT_OF_EPC = 0.5                 # 0.5% = €17.5k/yr Y1
OPEX_INFLATION = 0.03                      # 3% annually
DEGRADATION_RATE = 0.025                   # 2.5% capacity fade/yr
AUGMENTATION_PCT_OF_EPC = 10.0             # 10% at Y5 and Y10
AUGMENTATION_YEARS = (5, 10)
PROJECT_LIFE_YR = 15
DISCOUNT_RATE = 0.08                       # 8% for NPV
DSCR_COVENANT = 1.20                       # lender covenant typical

# ===================================================================
#  Scenario base Y1 revenues (from real DAMAS / OPCOM data, balanced strategy)
# ===================================================================
# aFRR Y1 numbers come from afrr_scenarios_excel.py (real-market sim).
# PZU Y1 numbers: scenario A = €835k from production simulate(); other
# scenarios apply progressive compression to that base.
SCENARIOS = [
    {
        "key": "A",
        "label": "A. Current (10% share, pre-PICASSO)",
        "short": "Scenario_A_Current",
        "color": "DDEBF7",
        "afrr_capacity_y1": 597_767,
        "afrr_activation_y1": 2_675_941,
        "pzu_y1": 835_187,
        # Compression schedule for years 2..15
        "compression": {
            "afrr_capacity":   [1.00, 1.00, 0.75, 0.69, 0.63, 0.58, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            "afrr_activation": [1.00, 1.00, 0.75, 0.70, 0.66, 0.62, 0.58, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
            "pzu":             [1.00, 0.97, 0.92, 0.87, 0.82, 0.77, 0.72, 0.68, 0.64, 0.60, 0.57, 0.54, 0.51, 0.48, 0.46],
        },
        "description": (
            "Y1 reflects today's Romanian state: 10% market share, pre-PICASSO. "
            "PICASSO assumed to go live at Y3 → -25% step on capacity + activation. "
            "Standard compression schedule (8%/yr from Y3) bottoms at 55% of Y1 by Y8."
        ),
    },
    {
        "key": "B",
        "label": "B. PICASSO go-live (Y1) (10% share)",
        "short": "Scenario_B_PICASSO",
        "color": "FCE4D6",
        "afrr_capacity_y1": 448_725,       # current × 0.75
        "afrr_activation_y1": 2_006_956,   # current × 0.75
        "pzu_y1": 835_187,                  # PZU largely independent of PICASSO
        "compression": {
            "afrr_capacity":   [1.00, 1.00, 0.95, 0.90, 0.86, 0.82, 0.78, 0.74, 0.71, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70],
            "afrr_activation": [1.00, 1.00, 0.95, 0.90, 0.86, 0.82, 0.78, 0.74, 0.71, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70],
            "pzu":             [1.00, 0.97, 0.92, 0.87, 0.82, 0.77, 0.72, 0.68, 0.64, 0.60, 0.57, 0.54, 0.51, 0.48, 0.46],
        },
        "description": (
            "PICASSO already live at Y1 (alternate timeline if Hungary connects faster). "
            "Y1 base already incorporates -25% from current. Slower compression "
            "(~5%/yr) post-PICASSO since extreme tail already capped. Floor at 70% Y1."
        ),
    },
    {
        "key": "C",
        "label": "C. Mature market (5% share, -40%)",
        "short": "Scenario_C_Mature",
        "color": "FFF2CC",
        "afrr_capacity_y1": 363_911,       # 5% share, -40% prices
        "afrr_activation_y1": 1_836_060,
        "pzu_y1": 626_390,                  # PZU also compressed -25%
        "compression": {
            "afrr_capacity":   [1.00, 0.97, 0.94, 0.91, 0.89, 0.87, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85],
            "afrr_activation": [1.00, 0.97, 0.94, 0.91, 0.89, 0.87, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85],
            "pzu":             [1.00, 0.98, 0.95, 0.92, 0.89, 0.86, 0.83, 0.80, 0.77, 0.74, 0.71, 0.68, 0.65, 0.62, 0.59],
        },
        "description": (
            "Realistic Y3-Y8 lender baseline. Romanian BESS pipeline (1+ GW announced) "
            "materializes 2027-2028. Market share compresses to 5%, capacity prices to "
            "Germany current level (~€5/MW/h). Mild ongoing compression to floor of 85% Y1."
        ),
    },
    {
        "key": "D",
        "label": "D. Bear case (2% share, full saturation)",
        "short": "Scenario_D_Bear",
        "color": "F8CBAD",
        "afrr_capacity_y1": 351_360,       # 2% share, -60% prices
        "afrr_activation_y1": 1_035_773,
        "pzu_y1": 417_594,                  # PZU also compressed -50%
        "compression": {
            "afrr_capacity":   [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00],
            "afrr_activation": [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00],
            "pzu":             [1.00, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82, 0.80, 0.78, 0.76, 0.74, 0.72, 0.70, 0.68, 0.66],
        },
        "description": (
            "Long-term steady state stress case (2030+). 2-3 GW BESS deployed Romania. "
            "Already at floor — no further compression. Used by lenders for late-life "
            "(Y8-Y15) DSCR projection."
        ),
    },
]

# ===================================================================
#  Financial calculations
# ===================================================================
def annuity_payment(principal: float, rate: float, n: int) -> float:
    """Standard amortizing loan annual payment (PMT)."""
    if rate == 0:
        return principal / n
    return principal * rate / (1 - (1 + rate) ** -n)


def npv(cashflows: list[float], rate: float) -> float:
    """NPV with cashflows[0] at Y0, cashflows[1] at Y1, etc."""
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def irr(cashflows: list[float], guess: float = 0.10) -> Optional[float]:
    """IRR via Newton-Raphson; returns None if no solution found."""
    if not cashflows or all(cf >= 0 for cf in cashflows) or all(cf <= 0 for cf in cashflows):
        return None
    rate = guess
    for _ in range(200):
        f = sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))
        df = sum(-t * cf / (1 + rate) ** (t + 1) for t, cf in enumerate(cashflows))
        if abs(df) < 1e-10:
            break
        new = rate - f / df
        if abs(new - rate) < 1e-7:
            return new
        rate = new
    return rate if -0.99 < rate < 10 else None


def payback_year(cumulative_cashflows: list[float]) -> Optional[float]:
    """First year (with linear interpolation) where cumulative CF crosses 0."""
    for i, cf in enumerate(cumulative_cashflows):
        if cf >= 0:
            if i == 0:
                return 0.0
            prev = cumulative_cashflows[i - 1]
            if prev < 0:
                return (i - 1) + (-prev) / (cf - prev)
            return float(i)
    return None


def build_cashflow(scenario: dict) -> pd.DataFrame:
    """Build the 15-year per-year cashflow table for one scenario."""
    equity_eur = EPC_INVESTMENT_EUR * EQUITY_PCT / 100.0
    loan_eur = EPC_INVESTMENT_EUR * LOAN_PCT / 100.0
    debt_service = annuity_payment(loan_eur, LOAN_RATE, LOAN_TERM_YR)

    rows = []
    cum_cf_after_debt = 0.0
    cum_cf_project = 0.0
    cum_equity_cf = -equity_eur  # equity outflow at Y0

    for y in range(1, PROJECT_LIFE_YR + 1):
        i = y - 1
        # Compression × degradation (degradation reduces capacity & energy throughput)
        deg = (1 - DEGRADATION_RATE) ** i
        afrr_cap = scenario["afrr_capacity_y1"] * scenario["compression"]["afrr_capacity"][i] * deg
        afrr_act = scenario["afrr_activation_y1"] * scenario["compression"]["afrr_activation"][i] * deg
        pzu = scenario["pzu_y1"] * scenario["compression"]["pzu"][i] * deg
        revenue = afrr_cap + afrr_act + pzu

        opex = (EPC_INVESTMENT_EUR * OPEX_PCT_OF_EPC / 100.0) * (1 + OPEX_INFLATION) ** i
        insurance = (EPC_INVESTMENT_EUR * INSURANCE_PCT_OF_EPC / 100.0) * (1 + OPEX_INFLATION) ** i
        ebitda = revenue - opex - insurance

        debt = debt_service if y <= LOAN_TERM_YR else 0.0
        augmentation = (EPC_INVESTMENT_EUR * AUGMENTATION_PCT_OF_EPC / 100.0) if y in AUGMENTATION_YEARS else 0.0

        cf_after_debt = ebitda - debt - augmentation
        cf_project = ebitda - augmentation  # project-level (no debt)
        cum_cf_after_debt += cf_after_debt
        cum_cf_project += cf_project
        cum_equity_cf += cf_after_debt

        dscr = (ebitda / debt) if debt > 0 else None
        roi_y_pct = (cf_after_debt / equity_eur) * 100.0
        cum_roi_pct = ((cum_cf_after_debt) / equity_eur) * 100.0

        rows.append({
            "Year": y,
            "aFRR capacity (€)": afrr_cap,
            "aFRR activation (€)": afrr_act,
            "PZU arbitrage (€)": pzu,
            "Total revenue (€)": revenue,
            "OPEX (€)": -opex,
            "Insurance (€)": -insurance,
            "EBITDA (€)": ebitda,
            "Debt service (€)": -debt if debt > 0 else 0.0,
            "Augmentation (€)": -augmentation if augmentation > 0 else 0.0,
            "Cashflow after debt (€)": cf_after_debt,
            "Cumulative cashflow (€)": cum_cf_after_debt,
            "DSCR": dscr,
            "Annual equity ROI (%)": roi_y_pct,
            "Cumulative equity ROI (%)": cum_roi_pct,
        })

    df = pd.DataFrame(rows)
    return df


def compute_kpis(scenario: dict, df: pd.DataFrame) -> dict:
    equity_eur = EPC_INVESTMENT_EUR * EQUITY_PCT / 100.0
    loan_eur = EPC_INVESTMENT_EUR * LOAN_PCT / 100.0

    # Equity-perspective cashflows (Y0..Y15)
    equity_cf = [-equity_eur] + df["Cashflow after debt (€)"].tolist()
    # Project-perspective cashflows (treats EPC as initial outflow, EBITDA-aug as inflows)
    project_cf = [-EPC_INVESTMENT_EUR] + (df["EBITDA (€)"] + df["Augmentation (€)"]).tolist()

    cum_equity = []
    s = -equity_eur
    for cf in df["Cashflow after debt (€)"]:
        s += cf
        cum_equity.append(s)
    cum_project = []
    s = -EPC_INVESTMENT_EUR
    for cf in df["EBITDA (€)"] + df["Augmentation (€)"]:
        s += cf
        cum_project.append(s)

    eq_irr = irr(equity_cf)
    pj_irr = irr(project_cf)
    eq_npv = npv(equity_cf, DISCOUNT_RATE)
    pj_npv = npv(project_cf, DISCOUNT_RATE)
    eq_payback = payback_year([-equity_eur] + cum_equity)
    pj_payback = payback_year([-EPC_INVESTMENT_EUR] + cum_project)

    dscr_breach_years = [y for y, dscr in zip(df["Year"], df["DSCR"])
                         if dscr is not None and dscr < DSCR_COVENANT]
    return {
        "equity_irr_pct": (eq_irr * 100.0) if eq_irr is not None else None,
        "project_irr_pct": (pj_irr * 100.0) if pj_irr is not None else None,
        "equity_npv_eur": eq_npv,
        "project_npv_eur": pj_npv,
        "equity_payback_years": eq_payback,
        "project_payback_years": pj_payback,
        "lifetime_revenue_eur": df["Total revenue (€)"].sum(),
        "lifetime_ebitda_eur": df["EBITDA (€)"].sum(),
        "lifetime_cf_after_debt_eur": df["Cashflow after debt (€)"].sum(),
        "y1_revenue_eur": float(df.iloc[0]["Total revenue (€)"]),
        "y1_ebitda_eur": float(df.iloc[0]["EBITDA (€)"]),
        "y1_cf_after_debt_eur": float(df.iloc[0]["Cashflow after debt (€)"]),
        "dscr_breach_years": dscr_breach_years,
        "min_dscr": min((d for d in df["DSCR"] if d is not None), default=None),
    }


# ===================================================================
#  Excel formatting
# ===================================================================
EUR_FMT = '"€"#,##0;[Red]"-€"#,##0'
EUR_K_FMT = '"€"#,##0,"k";[Red]"-€"#,##0,"k"'
PCT_FMT = '0.00%'
PCT_FMT_INT = '0.0%'
DSCR_FMT = '0.00"x"'
INT_FMT = '0'
YR_FMT = '0.0" yr"'


def _styles():
    from openpyxl.styles import Border, Font, PatternFill, Side
    border = Side(border_style="thin", color="BFBFBF")
    thick = Side(border_style="medium", color="2E75B6")
    return {
        "bold": Font(bold=True, size=11),
        "bold_white": Font(bold=True, color="FFFFFF", size=11),
        "bold_big": Font(bold=True, size=15, color="FFFFFF"),
        "bold_huge": Font(bold=True, size=18, color="FFFFFF"),
        "italic": Font(italic=True, size=10, color="595959"),
        "header": PatternFill("solid", fgColor="1F4E78"),
        "title": PatternFill("solid", fgColor="2E75B6"),
        "subtotal": PatternFill("solid", fgColor="BDD7EE"),
        "total": PatternFill("solid", fgColor="FFEB99"),
        "rev": PatternFill("solid", fgColor="E2EFDA"),
        "cost": PatternFill("solid", fgColor="FCE4D6"),
        "kpi_good": PatternFill("solid", fgColor="C6EFCE"),
        "kpi_bad": PatternFill("solid", fgColor="FFC7CE"),
        "kpi_mid": PatternFill("solid", fgColor="FFEB9C"),
        "box": Border(left=border, right=border, top=border, bottom=border),
        "thick_top": Border(top=thick, left=border, right=border, bottom=border),
    }


def _detail_format(col: str) -> Optional[str]:
    if col == "Year":
        return INT_FMT
    if col == "DSCR":
        return DSCR_FMT
    if "ROI" in col or "(%)" in col:
        return PCT_FMT
    if "(€)" in col:
        return EUR_FMT
    return None


def write_scenario_sheet(ws, scenario: dict, df: pd.DataFrame, kpis: dict, styles):
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter

    # Title at top
    ws.merge_cells("A1:P1")
    cell = ws["A1"]
    cell.value = scenario["label"]
    cell.font = styles["bold_big"]
    cell.fill = styles["title"]
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # KPI summary (top, before the table)
    kpi_row = 2
    kpi_labels = [
        ("Y1 revenue", _fmt_eur_short(kpis["y1_revenue_eur"])),
        ("Y1 cashflow after debt", _fmt_eur_short(kpis["y1_cf_after_debt_eur"])),
        ("Equity IRR", _fmt_pct(kpis["equity_irr_pct"])),
        ("Project IRR", _fmt_pct(kpis["project_irr_pct"])),
        ("Equity payback", _fmt_yr(kpis["equity_payback_years"])),
        ("NPV @ 8% (equity)", _fmt_eur_short(kpis["equity_npv_eur"])),
        ("Lifetime revenue", _fmt_eur_short(kpis["lifetime_revenue_eur"])),
        ("Min DSCR", f"{kpis['min_dscr']:.2f}x" if kpis["min_dscr"] is not None else "n/a"),
    ]
    for i, (label, val) in enumerate(kpi_labels):
        c_label = get_column_letter(1 + 2 * i)
        c_val = get_column_letter(2 + 2 * i)
        ws[f"{c_label}{kpi_row}"] = label
        ws[f"{c_label}{kpi_row}"].font = styles["bold"]
        ws[f"{c_label}{kpi_row}"].fill = styles["subtotal"]
        ws[f"{c_label}{kpi_row}"].alignment = Alignment(horizontal="right")
        ws[f"{c_val}{kpi_row}"] = val
        ws[f"{c_val}{kpi_row}"].font = styles["bold"]
        ws[f"{c_val}{kpi_row}"].fill = styles["total"]
        ws[f"{c_val}{kpi_row}"].alignment = Alignment(horizontal="left")
        ws[f"{c_label}{kpi_row}"].border = styles["box"]
        ws[f"{c_val}{kpi_row}"].border = styles["box"]

    # Cashflow table starts at row 4
    table_start = 4
    cols = list(df.columns)
    for col_idx, name in enumerate(cols, start=1):
        cell = ws.cell(row=table_start, column=col_idx, value=name)
        cell.font = styles["bold_white"]
        cell.fill = styles["header"]
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = styles["box"]
    ws.row_dimensions[table_start].height = 36

    rev_cols = {"aFRR capacity (€)", "aFRR activation (€)", "PZU arbitrage (€)", "Total revenue (€)"}
    cost_cols = {"OPEX (€)", "Insurance (€)", "Debt service (€)", "Augmentation (€)"}
    kpi_cols = {"Cashflow after debt (€)", "Cumulative cashflow (€)",
                "Annual equity ROI (%)", "Cumulative equity ROI (%)"}

    for i, row in df.iterrows():
        excel_row = table_start + 1 + i
        for col_idx, name in enumerate(cols, start=1):
            val = row[name]
            cell = ws.cell(row=excel_row, column=col_idx, value=val)
            nf = _detail_format(name)
            if nf:
                cell.number_format = nf
            cell.alignment = Alignment(horizontal="center")
            cell.border = styles["box"]
            if name == "Total revenue (€)":
                cell.font = styles["bold"]
                cell.fill = styles["rev"]
            elif name in rev_cols:
                cell.fill = styles["rev"]
            elif name in cost_cols:
                cell.fill = styles["cost"]
            elif name == "EBITDA (€)":
                cell.font = styles["bold"]
                cell.fill = styles["subtotal"]
            elif name in {"Cashflow after debt (€)", "Cumulative cashflow (€)"}:
                cell.font = styles["bold"]
                cell.fill = styles["total"]
            elif name == "DSCR":
                if val is not None and val < DSCR_COVENANT:
                    cell.fill = styles["kpi_bad"]
                else:
                    cell.fill = styles["kpi_good"]

    ws.freeze_panes = f"B{table_start + 1}"
    # Column widths
    widths = [7, 14, 14, 14, 16, 12, 12, 14, 14, 14, 18, 18, 9, 13, 16]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Description below the table
    desc_row = table_start + len(df) + 2
    ws.merge_cells(start_row=desc_row, start_column=1, end_row=desc_row, end_column=15)
    ws[f"A{desc_row}"] = "Scenario description"
    ws[f"A{desc_row}"].font = styles["bold_white"]
    ws[f"A{desc_row}"].fill = styles["header"]
    ws[f"A{desc_row}"].alignment = Alignment(horizontal="center")
    desc_row += 1
    ws.merge_cells(start_row=desc_row, start_column=1, end_row=desc_row, end_column=15)
    ws[f"A{desc_row}"] = scenario["description"]
    ws[f"A{desc_row}"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[desc_row].height = 60


def _fmt_eur_short(v: float) -> str:
    if v is None:
        return "n/a"
    if abs(v) >= 1_000_000:
        return f"€{v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"€{v/1_000:.0f}k"
    return f"€{v:.0f}"


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.2f}%" if v is not None else "n/a"


def _fmt_yr(v: Optional[float]) -> str:
    return f"{v:.1f} yr" if v is not None else "never"


def write_executive_summary(ws, all_kpis: list[dict], styles):
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter

    ws.merge_cells("A1:F1")
    cell = ws["A1"]
    cell.value = "Executive Summary — 10 MW / 20 MWh BESS, 15-year project finance"
    cell.font = styles["bold_huge"]
    cell.fill = styles["title"]
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    sub = "Romanian aFRR + PZU arbitrage • Real DAMAS-anchored bids • 4 scenarios across PICASSO + market-share dynamics"
    ws.merge_cells("A2:F2")
    ws["A2"] = sub
    ws["A2"].alignment = Alignment(horizontal="center")
    ws["A2"].font = styles["italic"]

    # Quick project facts
    facts_row = 4
    ws[f"A{facts_row}"] = "Project facts"
    ws[f"A{facts_row}"].font = styles["bold_white"]
    ws[f"A{facts_row}"].fill = styles["header"]
    ws.merge_cells(start_row=facts_row, start_column=1, end_row=facts_row, end_column=6)
    ws[f"A{facts_row}"].alignment = Alignment(horizontal="center")
    facts = [
        ("EPC investment", _fmt_eur_short(EPC_INVESTMENT_EUR), "€175/kWh installed"),
        ("Equity / Loan split", f"{EQUITY_PCT:.0f}% / {LOAN_PCT:.0f}%",
         f"Equity = {_fmt_eur_short(EPC_INVESTMENT_EUR * EQUITY_PCT/100)}, "
         f"Loan = {_fmt_eur_short(EPC_INVESTMENT_EUR * LOAN_PCT/100)}"),
        ("Loan terms", f"{LOAN_RATE*100:.1f}% over {LOAN_TERM_YR} years",
         f"Annuity = {_fmt_eur_short(annuity_payment(EPC_INVESTMENT_EUR*LOAN_PCT/100, LOAN_RATE, LOAN_TERM_YR))}/yr"),
        ("OPEX + Insurance", f"{OPEX_PCT_OF_EPC + INSURANCE_PCT_OF_EPC:.1f}% of EPC",
         f"€{(EPC_INVESTMENT_EUR * (OPEX_PCT_OF_EPC + INSURANCE_PCT_OF_EPC)/100)/1000:.0f}k/yr Y1, +3%/yr inflation"),
        ("Augmentation", f"{AUGMENTATION_PCT_OF_EPC:.0f}% of EPC at Y5 + Y10",
         f"€{EPC_INVESTMENT_EUR * AUGMENTATION_PCT_OF_EPC/100/1000:.0f}k each event"),
        ("Project life / Discount rate", f"{PROJECT_LIFE_YR} years / {DISCOUNT_RATE*100:.0f}%",
         f"DSCR covenant {DSCR_COVENANT:.2f}x (lender standard)"),
        ("Battery", f"{POWER_MW:.0f} MW / {CAPACITY_MWH:.0f} MWh",
         "RTE 0.97, full 0-100% SOC, 1 cycle/day"),
        ("Degradation", f"{DEGRADATION_RATE*100:.1f}%/yr",
         "Capacity fade applied to all revenue legs"),
    ]
    for i, (lbl, val, note) in enumerate(facts, start=1):
        r = facts_row + i
        ws[f"A{r}"] = lbl
        ws[f"B{r}"] = val
        ws[f"C{r}"] = note
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=6)
        ws[f"A{r}"].font = styles["bold"]
        for col in "ABCDEF":
            ws[f"{col}{r}"].border = styles["box"]
            ws[f"{col}{r}"].alignment = Alignment(horizontal="left", vertical="center")

    # KPI table — one row per scenario
    kpi_row = facts_row + len(facts) + 2
    ws[f"A{kpi_row}"] = "Headline KPIs by scenario"
    ws[f"A{kpi_row}"].font = styles["bold_white"]
    ws[f"A{kpi_row}"].fill = styles["header"]
    ws.merge_cells(start_row=kpi_row, start_column=1, end_row=kpi_row, end_column=6)
    ws[f"A{kpi_row}"].alignment = Alignment(horizontal="center")

    hdr = kpi_row + 1
    headers = ["Scenario", "Y1 revenue", "Equity IRR", "Project IRR",
               "Equity payback", "NPV @ 8% (equity)"]
    for col_letter, label in zip("ABCDEF", headers):
        c = ws[f"{col_letter}{hdr}"]
        c.value = label
        c.font = styles["bold_white"]
        c.fill = styles["title"]
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        c.border = styles["box"]

    for i, (scen, kpis) in enumerate(zip(SCENARIOS, all_kpis), start=1):
        r = hdr + i
        from openpyxl.styles import PatternFill
        scen_fill = PatternFill("solid", fgColor=scen["color"])
        ws[f"A{r}"] = scen["label"]
        ws[f"B{r}"] = _fmt_eur_short(kpis["y1_revenue_eur"])
        ws[f"C{r}"] = _fmt_pct(kpis["equity_irr_pct"])
        ws[f"D{r}"] = _fmt_pct(kpis["project_irr_pct"])
        ws[f"E{r}"] = _fmt_yr(kpis["equity_payback_years"])
        ws[f"F{r}"] = _fmt_eur_short(kpis["equity_npv_eur"])
        for col in "ABCDEF":
            ws[f"{col}{r}"].font = styles["bold"]
            ws[f"{col}{r}"].fill = scen_fill
            ws[f"{col}{r}"].border = styles["box"]
            ws[f"{col}{r}"].alignment = Alignment(horizontal="center")
        ws[f"A{r}"].alignment = Alignment(horizontal="left")

    # Decision-quality section
    dec_row = hdr + len(SCENARIOS) + 2
    ws[f"A{dec_row}"] = "How to read these numbers (lender perspective)"
    ws[f"A{dec_row}"].font = styles["bold_white"]
    ws[f"A{dec_row}"].fill = styles["header"]
    ws.merge_cells(start_row=dec_row, start_column=1, end_row=dec_row, end_column=6)
    ws[f"A{dec_row}"].alignment = Alignment(horizontal="center")
    rules = [
        "• Pitch deck Y1 number → Scenario A (current state).",
        "• 5-year average projection → blend of A + B (assumes PICASSO mid-period).",
        "• Lender-grade Y3-Y8 bankability case → Scenario C (mature market).",
        "• Lender stress test Y8-Y15 → Scenario D (bear case).",
        "• If DSCR < 1.20 in any year → lender covenant breach. Either lower gearing (more equity), longer tenor, or equity injection.",
        "• Numbers are SIMULATED on real Romanian DAMAS + OPCOM data. Compliance gates (ANRE/OPCOM/PRE/BRP/BSP/FSE) NOT applied — assumed obtained. Without them, all revenue = €0.",
        "• Realistic operator drag (forecast error, market share guess, Tg/Td tariffs) typically reduces revenue another 30-50% vs the engineering optimum shown here.",
    ]
    for i, txt in enumerate(rules):
        r = dec_row + 1 + i
        ws[f"A{r}"] = txt
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        ws[f"A{r}"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 26

    # Column widths
    widths = [38, 16, 14, 14, 16, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_inputs_sheet(ws, styles):
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter

    ws.merge_cells("A1:F1")
    cell = ws["A1"]
    cell.value = "Inputs & Assumptions"
    cell.font = styles["bold_huge"]
    cell.fill = styles["title"]
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # Battery + financing block
    sections = [
        ("Battery technical", [
            ("Power", f"{POWER_MW:.0f} MW", "Inverter rating"),
            ("Energy capacity", f"{CAPACITY_MWH:.0f} MWh", "Daily throughput cap"),
            ("RTE", "0.97", "User directive — 3% loss per round-trip"),
            ("SOC band", "0% – 100%", "User directive — full DOD"),
            ("Cycles/day", "1", "Single round-trip per day"),
            ("Degradation", f"{DEGRADATION_RATE*100:.1f}%/yr",
             "Capacity fade applied to all revenue legs"),
        ]),
        ("Financing", [
            ("EPC investment", _fmt_eur_short(EPC_INVESTMENT_EUR), "€175/kWh installed"),
            ("Equity %", f"{EQUITY_PCT:.0f}%", _fmt_eur_short(EPC_INVESTMENT_EUR * EQUITY_PCT/100)),
            ("Loan %", f"{LOAN_PCT:.0f}%", _fmt_eur_short(EPC_INVESTMENT_EUR * LOAN_PCT/100)),
            ("Loan rate", f"{LOAN_RATE*100:.1f}%", "Fixed-rate annuity"),
            ("Loan term", f"{LOAN_TERM_YR} years", "Annuity payment ≈ "
             + _fmt_eur_short(annuity_payment(EPC_INVESTMENT_EUR*LOAN_PCT/100, LOAN_RATE, LOAN_TERM_YR))),
            ("Discount rate (NPV)", f"{DISCOUNT_RATE*100:.0f}%", "Standard EU project finance"),
            ("DSCR covenant", f"{DSCR_COVENANT:.2f}x", "Lender standard"),
        ]),
        ("Operating costs", [
            ("OPEX", f"{OPEX_PCT_OF_EPC:.1f}% of EPC = "
             + _fmt_eur_short(EPC_INVESTMENT_EUR * OPEX_PCT_OF_EPC/100), "Year 1, +3%/yr inflation"),
            ("Insurance", f"{INSURANCE_PCT_OF_EPC:.1f}% of EPC = "
             + _fmt_eur_short(EPC_INVESTMENT_EUR * INSURANCE_PCT_OF_EPC/100), "Year 1, +3%/yr inflation"),
            ("Augmentation", f"{AUGMENTATION_PCT_OF_EPC:.0f}% of EPC at Y5 + Y10",
             f"= {_fmt_eur_short(EPC_INVESTMENT_EUR * AUGMENTATION_PCT_OF_EPC/100)} per event"),
        ]),
        ("Revenue scenarios — Y1 base values", [
            ("Scenario A — aFRR capacity Y1", _fmt_eur_short(SCENARIOS[0]["afrr_capacity_y1"]),
             "10% market share, real DAMAS clearing"),
            ("Scenario A — aFRR activation Y1", _fmt_eur_short(SCENARIOS[0]["afrr_activation_y1"]),
             "Real per-slot DAMAS settlement"),
            ("Scenario A — PZU Y1", _fmt_eur_short(SCENARIOS[0]["pzu_y1"]),
             "Real OPCOM dispatch"),
            ("Scenario B — base Y1 multiplier", "0.75",
             "PICASSO live → -25% on aFRR; PZU unchanged"),
            ("Scenario C — base Y1 multipliers", "share 0.50, prices 0.60",
             "Mature market: 5% share, capacity at €5/MW/h"),
            ("Scenario D — base Y1 multipliers", "share 0.20, prices 0.40",
             "Bear case: 2% share, prices at German current level"),
        ]),
    ]

    r = 3
    for section_label, items in sections:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
        ws[f"A{r}"] = section_label
        ws[f"A{r}"].font = styles["bold_white"]
        ws[f"A{r}"].fill = styles["header"]
        ws[f"A{r}"].alignment = Alignment(horizontal="center")
        ws.row_dimensions[r].height = 22
        r += 1
        for label, value, note in items:
            ws[f"A{r}"] = label
            ws[f"B{r}"] = value
            ws[f"C{r}"] = note
            ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=6)
            ws[f"A{r}"].font = styles["bold"]
            for col in "ABCDEF":
                ws[f"{col}{r}"].border = styles["box"]
                ws[f"{col}{r}"].alignment = Alignment(horizontal="left", vertical="center")
            r += 1
        r += 1  # spacing

    widths = [34, 22, 22, 22, 22, 22]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_comparison_sheet(ws, dfs: dict[str, pd.DataFrame], all_kpis: list[dict], styles):
    from openpyxl.styles import Alignment, PatternFill
    from openpyxl.utils import get_column_letter

    ws.merge_cells("A1:F1")
    cell = ws["A1"]
    cell.value = "Scenarios Comparison — annual cashflow + KPI summary"
    cell.font = styles["bold_huge"]
    cell.fill = styles["title"]
    cell.alignment = Alignment(horizontal="center")
    ws.row_dimensions[1].height = 32

    # KPI comparison table (top)
    r = 3
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    ws[f"A{r}"] = "Scenario KPIs"
    ws[f"A{r}"].font = styles["bold_white"]
    ws[f"A{r}"].fill = styles["header"]
    ws[f"A{r}"].alignment = Alignment(horizontal="center")
    r += 1
    headers = ["KPI"] + [s["label"][:30] for s in SCENARIOS]
    for col_letter, label in zip("ABCDE"[: len(headers)], headers):
        c = ws[f"{col_letter}{r}"]
        c.value = label
        c.font = styles["bold_white"]
        c.fill = styles["title"]
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        c.border = styles["box"]
    ws.row_dimensions[r].height = 36

    kpi_rows = [
        ("Y1 total revenue (€)", lambda k: k["y1_revenue_eur"], _fmt_eur_short),
        ("Y1 EBITDA (€)", lambda k: k["y1_ebitda_eur"], _fmt_eur_short),
        ("Y1 cashflow after debt (€)", lambda k: k["y1_cf_after_debt_eur"], _fmt_eur_short),
        ("Lifetime revenue (€)", lambda k: k["lifetime_revenue_eur"], _fmt_eur_short),
        ("Lifetime EBITDA (€)", lambda k: k["lifetime_ebitda_eur"], _fmt_eur_short),
        ("Lifetime cashflow after debt (€)", lambda k: k["lifetime_cf_after_debt_eur"], _fmt_eur_short),
        ("Equity IRR", lambda k: k["equity_irr_pct"], _fmt_pct),
        ("Project IRR", lambda k: k["project_irr_pct"], _fmt_pct),
        ("Equity NPV @ 8%", lambda k: k["equity_npv_eur"], _fmt_eur_short),
        ("Project NPV @ 8%", lambda k: k["project_npv_eur"], _fmt_eur_short),
        ("Equity payback", lambda k: k["equity_payback_years"], _fmt_yr),
        ("Project payback", lambda k: k["project_payback_years"], _fmt_yr),
        ("Min DSCR", lambda k: k["min_dscr"], lambda v: f"{v:.2f}x" if v is not None else "n/a"),
        ("DSCR breach years", lambda k: k["dscr_breach_years"],
         lambda v: ", ".join(str(y) for y in v) if v else "—"),
    ]
    for kpi_label, kpi_get, fmt in kpi_rows:
        r += 1
        ws[f"A{r}"] = kpi_label
        ws[f"A{r}"].font = styles["bold"]
        ws[f"A{r}"].fill = styles["subtotal"]
        ws[f"A{r}"].border = styles["box"]
        ws[f"A{r}"].alignment = Alignment(horizontal="left")
        for i, (scen, kpis) in enumerate(zip(SCENARIOS, all_kpis), start=2):
            col_letter = get_column_letter(i)
            try:
                val = kpi_get(kpis)
                ws[f"{col_letter}{r}"] = fmt(val)
            except Exception:
                ws[f"{col_letter}{r}"] = "n/a"
            ws[f"{col_letter}{r}"].fill = PatternFill("solid", fgColor=scen["color"])
            ws[f"{col_letter}{r}"].border = styles["box"]
            ws[f"{col_letter}{r}"].alignment = Alignment(horizontal="center")

    # Annual cashflow comparison — total revenue per scenario per year
    r += 3
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
    ws[f"A{r}"] = "Annual cashflow after debt by scenario (€)"
    ws[f"A{r}"].font = styles["bold_white"]
    ws[f"A{r}"].fill = styles["header"]
    ws[f"A{r}"].alignment = Alignment(horizontal="center")
    r += 1
    headers = ["Year"] + [s["label"][:30] for s in SCENARIOS]
    for col_letter, label in zip("ABCDE", headers):
        c = ws[f"{col_letter}{r}"]
        c.value = label
        c.font = styles["bold_white"]
        c.fill = styles["title"]
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        c.border = styles["box"]
    ws.row_dimensions[r].height = 36

    year_start_row = r + 1
    for y_idx in range(PROJECT_LIFE_YR):
        rr = year_start_row + y_idx
        ws[f"A{rr}"] = y_idx + 1
        ws[f"A{rr}"].font = styles["bold"]
        ws[f"A{rr}"].alignment = Alignment(horizontal="center")
        ws[f"A{rr}"].border = styles["box"]
        for i, scen in enumerate(SCENARIOS, start=2):
            df = dfs[scen["key"]]
            cf = float(df.iloc[y_idx]["Cashflow after debt (€)"])
            col_letter = get_column_letter(i)
            ws[f"{col_letter}{rr}"] = cf
            ws[f"{col_letter}{rr}"].number_format = EUR_FMT
            ws[f"{col_letter}{rr}"].fill = PatternFill("solid", fgColor=scen["color"])
            ws[f"{col_letter}{rr}"].border = styles["box"]
            ws[f"{col_letter}{rr}"].alignment = Alignment(horizontal="right")

    # TOTAL row
    rr = year_start_row + PROJECT_LIFE_YR
    ws[f"A{rr}"] = "TOTAL"
    ws[f"A{rr}"].font = styles["bold"]
    ws[f"A{rr}"].fill = styles["total"]
    ws[f"A{rr}"].alignment = Alignment(horizontal="center")
    ws[f"A{rr}"].border = styles["box"]
    for i, scen in enumerate(SCENARIOS, start=2):
        df = dfs[scen["key"]]
        total = float(df["Cashflow after debt (€)"].sum())
        col_letter = get_column_letter(i)
        ws[f"{col_letter}{rr}"] = total
        ws[f"{col_letter}{rr}"].number_format = EUR_FMT
        ws[f"{col_letter}{rr}"].fill = styles["total"]
        ws[f"{col_letter}{rr}"].font = styles["bold"]
        ws[f"{col_letter}{rr}"].border = styles["box"]
        ws[f"{col_letter}{rr}"].alignment = Alignment(horizontal="right")

    widths = [34, 22, 22, 22, 22]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ===================================================================
#  Main
# ===================================================================
def main() -> None:
    print("Building 15-year cashflow scenarios…")
    dfs = {}
    all_kpis = []
    for scen in SCENARIOS:
        df = build_cashflow(scen)
        dfs[scen["key"]] = df
        kpis = compute_kpis(scen, df)
        all_kpis.append(kpis)
        print(f"  {scen['label']:42s}  Y1 €{kpis['y1_revenue_eur']/1e6:.2f}M  "
              f"Equity IRR {kpis['equity_irr_pct'] or 0:.2f}%  "
              f"Payback {kpis['equity_payback_years'] or float('nan'):.1f}y  "
              f"NPV @8% €{kpis['equity_npv_eur']/1e6:+.2f}M")

    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    today = "2026-05-04"
    out_path = out_dir / f"BESS_15yr_cashflow_scenarios_GoldmanGrade_{today}.xlsx"

    # Write empty placeholder workbook then format from scratch
    with pd.ExcelWriter(out_path, engine="openpyxl") as xl:
        pd.DataFrame().to_excel(xl, sheet_name="Executive_Summary", index=False)
        pd.DataFrame().to_excel(xl, sheet_name="Inputs_and_Assumptions", index=False)
        for scen in SCENARIOS:
            dfs[scen["key"]].to_excel(xl, sheet_name=scen["short"], index=False)
        pd.DataFrame().to_excel(xl, sheet_name="Scenarios_Comparison", index=False)

    from openpyxl import load_workbook
    wb = load_workbook(out_path)
    styles = _styles()

    # Executive Summary
    write_executive_summary(wb["Executive_Summary"], all_kpis, styles)
    # Inputs
    write_inputs_sheet(wb["Inputs_and_Assumptions"], styles)
    # Per-scenario detail sheets — overwrite with formatted version
    for scen, kpis in zip(SCENARIOS, all_kpis):
        ws = wb[scen["short"]]
        # Clear any pandas-written cell values so write_scenario_sheet
        # rebuilds the layout with title at row 1, KPI strip row 2,
        # cashflow table from row 4. Don't touch fills (openpyxl's
        # default StyleArray is required at save time).
        for row in ws.iter_rows():
            for cell in row:
                cell.value = None
        write_scenario_sheet(ws, scen, dfs[scen["key"]], kpis, styles)
    # Comparison
    write_comparison_sheet(wb["Scenarios_Comparison"], dfs, all_kpis, styles)

    wb.active = wb.sheetnames.index("Executive_Summary")
    wb.save(out_path)

    print(f"\nWrote: {out_path}")
    print("\nSheet structure:")
    print("  1. Executive_Summary       — facts + KPI table + lender notes")
    print("  2. Inputs_and_Assumptions  — battery + financing + scenario base values")
    print("  3-6. Scenario_*             — 15-year cashflow per scenario + KPI strip + description")
    print("  7. Scenarios_Comparison    — KPI table + annual CF side-by-side + 15yr total")


if __name__ == "__main__":
    main()
