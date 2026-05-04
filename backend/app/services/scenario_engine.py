"""Real-scenario engine — production-grade port of the Excel cashflow logic.

Mirrors `scripts/bess_cashflow_scenarios_excel.py` so the frontend's
"Investment ROI" view can show the same 4 scenarios (A_current / B_picasso /
C_mature / D_bear) the offline Excel models, with the same:

  - Physical stacking constraint (aFRR cap × act × PZU vs full sum)
  - Realistic operator drag (market-share guess, forecast error, REMIT)
  - Tax (16% Romanian corporate)
  - 8-year straight-line depreciation
  - Loan amortization split (interest + principal per year)
  - Compression curves per scenario (PICASSO step + ongoing compression)
  - Augmentation lumps at Y5 + Y10
  - DSCR / LLCR / PLCR / IRR / MIRR / NPV / payback / MOIC / ROE / ROIC

This complements the existing investment_service.analyze() (which treats
FR + PZU as alternatives). The scenario engine STACKS them with proper
constraints so the headline number reflects what an operator would
actually earn.

Source of truth: this module's SCENARIO_DEFAULTS table mirrors the Excel
script. Update both together when assumptions change.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


# ===================================================================
#  Project finance defaults (mirror bess_cashflow_scenarios_excel.py)
# ===================================================================
DEFAULT_EPC_INVESTMENT_EUR = 3_500_000.0
DEFAULT_POWER_MW = 10.0
DEFAULT_CAPACITY_MWH = 20.0
DEFAULT_EQUITY_PCT = 30.0
DEFAULT_LOAN_PCT = 70.0
DEFAULT_LOAN_RATE = 0.06
DEFAULT_LOAN_TERM_YR = 10
DEFAULT_OPEX_PCT_OF_EPC = 2.0
DEFAULT_INSURANCE_PCT_OF_EPC = 0.5
DEFAULT_OPEX_INFLATION = 0.03
DEFAULT_DEGRADATION_RATE = 0.025
DEFAULT_AUGMENTATION_PCT_OF_EPC = 10.0
DEFAULT_AUGMENTATION_YEARS = (5, 10)
DEFAULT_PROJECT_LIFE_YR = 15
DEFAULT_DISCOUNT_RATE = 0.08
DEFAULT_DSCR_COVENANT = 1.20
DEFAULT_TAX_RATE = 0.16
DEFAULT_DEPRECIATION_LIFE_YR = 8

DEFAULT_STACK_AFRR_CAPACITY = 1.00
DEFAULT_STACK_AFRR_ACTIVATION = 0.60
DEFAULT_STACK_PZU = 0.50

# Realistic operator drag (applied alongside stacking for the realistic view)
DEFAULT_DRAG_AFRR_CAPACITY = 0.93
DEFAULT_DRAG_AFRR_ACTIVATION = 0.25
DEFAULT_DRAG_PZU = 0.80

# Scenario base Y1 revenues (10 MW / 20 MWh canonical, real DAMAS / OPCOM data)
SCENARIO_DEFAULTS = {
    "A_current": {
        "label": "A. Current (10% share, pre-PICASSO)",
        "color": "DDEBF7",
        "afrr_capacity_y1": 363_000.0,    # canonical resolver, recent-window mean
        "afrr_activation_y1": 2_675_941.0,
        "pzu_y1": 835_187.0,
        "compression_afrr_capacity":   [1.00, 1.00, 0.75, 0.69, 0.63, 0.58, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        "compression_afrr_activation": [1.00, 1.00, 0.75, 0.70, 0.66, 0.62, 0.58, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55, 0.55],
        "compression_pzu":             [1.00, 0.97, 0.92, 0.87, 0.82, 0.77, 0.72, 0.68, 0.64, 0.60, 0.57, 0.54, 0.51, 0.48, 0.46],
        "description": (
            "Y1 reflects today's Romanian state: 10% market share, pre-PICASSO. "
            "PICASSO assumed to go live at Y3 → -25% step on capacity + activation. "
            "Standard compression schedule (8%/yr from Y3) bottoms at 55% of Y1 by Y8."
        ),
    },
    "B_picasso": {
        "label": "B. PICASSO go-live (Y1) (10% share)",
        "color": "FCE4D6",
        "afrr_capacity_y1": 272_250.0,    # 363k × 0.75
        "afrr_activation_y1": 2_006_956.0,
        "pzu_y1": 835_187.0,
        "compression_afrr_capacity":   [1.00, 1.00, 0.95, 0.90, 0.86, 0.82, 0.78, 0.74, 0.71, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70],
        "compression_afrr_activation": [1.00, 1.00, 0.95, 0.90, 0.86, 0.82, 0.78, 0.74, 0.71, 0.70, 0.70, 0.70, 0.70, 0.70, 0.70],
        "compression_pzu":             [1.00, 0.97, 0.92, 0.87, 0.82, 0.77, 0.72, 0.68, 0.64, 0.60, 0.57, 0.54, 0.51, 0.48, 0.46],
        "description": (
            "PICASSO already live at Y1 (alternate timeline if Hungary connects faster). "
            "Y1 base already incorporates -25% from current. Slower compression (~5%/yr) "
            "post-PICASSO since extreme tail already capped. Floor at 70% Y1."
        ),
    },
    "C_mature": {
        "label": "C. Mature market (5% share, -40%)",
        "color": "FFF2CC",
        "afrr_capacity_y1": 217_800.0,    # 363k × 0.60
        "afrr_activation_y1": 1_836_060.0,
        "pzu_y1": 626_390.0,              # 835k × 0.75
        "compression_afrr_capacity":   [1.00, 0.97, 0.94, 0.91, 0.89, 0.87, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85],
        "compression_afrr_activation": [1.00, 0.97, 0.94, 0.91, 0.89, 0.87, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 0.85],
        "compression_pzu":             [1.00, 0.98, 0.95, 0.92, 0.89, 0.86, 0.83, 0.80, 0.77, 0.74, 0.71, 0.68, 0.65, 0.62, 0.59],
        "description": (
            "Realistic Y3-Y8 lender baseline. Romanian BESS pipeline (1+ GW announced) "
            "materializes 2027-2028. Market share compresses to 5%, capacity prices to "
            "Germany current level (~€5/MW/h). Mild ongoing compression to floor of 85% Y1."
        ),
    },
    "D_bear": {
        "label": "D. Bear case (2% share, full saturation)",
        "color": "F8CBAD",
        "afrr_capacity_y1": 145_200.0,    # 363k × 0.40
        "afrr_activation_y1": 1_035_773.0,
        "pzu_y1": 417_594.0,              # 835k × 0.50
        "compression_afrr_capacity":   [1.00] * 15,
        "compression_afrr_activation": [1.00] * 15,
        "compression_pzu":             [1.00, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82, 0.80, 0.78, 0.76, 0.74, 0.72, 0.70, 0.68, 0.66],
        "description": (
            "Long-term steady state stress case (2030+). 2-3 GW BESS deployed Romania. "
            "Already at floor — no further compression. Used by lenders for late-life "
            "(Y8-Y15) DSCR projection."
        ),
    },
}


# ===================================================================
#  Inputs
# ===================================================================
@dataclass
class ScenarioInputs:
    """All knobs the engine consumes. Every field defaults to the
    canonical 10 MW / 20 MWh / €3.5M / 30-70 financing / Romania tax
    setup so callers can construct with no args."""
    epc_eur: float = DEFAULT_EPC_INVESTMENT_EUR
    power_mw: float = DEFAULT_POWER_MW
    capacity_mwh: float = DEFAULT_CAPACITY_MWH
    equity_pct: float = DEFAULT_EQUITY_PCT
    loan_pct: float = DEFAULT_LOAN_PCT
    loan_rate: float = DEFAULT_LOAN_RATE
    loan_term_yr: int = DEFAULT_LOAN_TERM_YR
    opex_pct_of_epc: float = DEFAULT_OPEX_PCT_OF_EPC
    insurance_pct_of_epc: float = DEFAULT_INSURANCE_PCT_OF_EPC
    opex_inflation: float = DEFAULT_OPEX_INFLATION
    degradation_rate: float = DEFAULT_DEGRADATION_RATE
    augmentation_pct_of_epc: float = DEFAULT_AUGMENTATION_PCT_OF_EPC
    project_life_yr: int = DEFAULT_PROJECT_LIFE_YR
    discount_rate: float = DEFAULT_DISCOUNT_RATE
    dscr_covenant: float = DEFAULT_DSCR_COVENANT
    tax_rate: float = DEFAULT_TAX_RATE
    depreciation_life_yr: int = DEFAULT_DEPRECIATION_LIFE_YR
    # Stacking — physical hardware constraint
    stack_afrr_capacity: float = DEFAULT_STACK_AFRR_CAPACITY
    stack_afrr_activation: float = DEFAULT_STACK_AFRR_ACTIVATION
    stack_pzu: float = DEFAULT_STACK_PZU
    # Operator drag — applied only when apply_drag=True (realistic view)
    drag_afrr_capacity: float = DEFAULT_DRAG_AFRR_CAPACITY
    drag_afrr_activation: float = DEFAULT_DRAG_AFRR_ACTIVATION
    drag_pzu: float = DEFAULT_DRAG_PZU
    augmentation_years: tuple = DEFAULT_AUGMENTATION_YEARS


# ===================================================================
#  Helpers
# ===================================================================
def annuity_payment(principal: float, rate: float, n: int) -> float:
    if rate == 0:
        return principal / n
    return principal * rate / (1 - (1 + rate) ** -n)


def amortization_schedule(principal: float, rate: float, n: int) -> List[dict]:
    pmt = annuity_payment(principal, rate, n)
    balance = principal
    out = []
    for _ in range(n):
        interest = balance * rate
        principal_paid = pmt - interest
        balance = max(0.0, balance - principal_paid)
        out.append({
            "interest": interest,
            "principal": principal_paid,
            "payment_total": pmt,
            "balance_end": balance,
        })
    return out


def npv(cashflows: List[float], rate: float) -> float:
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


def irr(cashflows: List[float], guess: float = 0.10) -> Optional[float]:
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


def mirr(cashflows: List[float], finance_rate: float, reinvest_rate: float) -> Optional[float]:
    n = len(cashflows) - 1
    if n <= 0:
        return None
    pv_neg = sum(cf / (1 + finance_rate) ** t for t, cf in enumerate(cashflows) if cf < 0)
    fv_pos = sum(cf * (1 + reinvest_rate) ** (n - t) for t, cf in enumerate(cashflows) if cf > 0)
    if pv_neg == 0 or fv_pos <= 0:
        return None
    return (fv_pos / -pv_neg) ** (1 / n) - 1


def payback_year(cumulative: List[float]) -> Optional[float]:
    for i, cf in enumerate(cumulative):
        if cf >= 0:
            if i == 0:
                return 0.0
            prev = cumulative[i - 1]
            if prev < 0:
                return (i - 1) + (-prev) / (cf - prev)
            return float(i)
    return None


def discounted_payback(cashflows: List[float], rate: float) -> Optional[float]:
    cum = 0.0
    series = []
    for t, cf in enumerate(cashflows):
        cum += cf / (1 + rate) ** t
        series.append(cum)
    return payback_year(series)


# ===================================================================
#  Cashflow + KPI engine
# ===================================================================
def build_scenario_cashflow(
    scenario_key: str,
    inputs: Optional[ScenarioInputs] = None,
    apply_drag: bool = False,
    scenario_overrides: Optional[dict] = None,
) -> List[dict]:
    """15-year project finance cashflow for one scenario.

    Returns a list of {year, ...} dicts with all standard PF lines:
    revenue/EBITDA/EBIT/Net Income/Project FCF/Equity FCF/DSCR/ROE/ROIC.

    `apply_drag` toggles operator-side haircuts (capacity 0.93, activation
    0.25, PZU 0.80). False = engineering optimum; True = lender-grade.

    `scenario_overrides` lets the caller swap any base-Y1 or compression
    field — used by the API to apply user-supplied scenario customizations.
    """
    if scenario_key not in SCENARIO_DEFAULTS:
        raise ValueError(f"Unknown scenario: {scenario_key!r}")
    if inputs is None:
        inputs = ScenarioInputs()

    scen = dict(SCENARIO_DEFAULTS[scenario_key])
    if scenario_overrides:
        scen.update(scenario_overrides)

    equity_eur = inputs.epc_eur * inputs.equity_pct / 100.0
    loan_eur = inputs.epc_eur * inputs.loan_pct / 100.0
    debt_schedule = amortization_schedule(loan_eur, inputs.loan_rate, inputs.loan_term_yr)
    annual_depreciation = inputs.epc_eur / inputs.depreciation_life_yr

    cap_drag = inputs.drag_afrr_capacity if apply_drag else 1.0
    act_drag = inputs.drag_afrr_activation if apply_drag else 1.0
    pzu_drag = inputs.drag_pzu if apply_drag else 1.0

    rows = []
    cum_equity_fcf = 0.0
    debt_outstanding = loan_eur

    for y in range(1, inputs.project_life_yr + 1):
        i = y - 1
        deg = (1 - inputs.degradation_rate) ** i
        # Compression × degradation × stacking × drag
        afrr_cap = (
            scen["afrr_capacity_y1"]
            * scen["compression_afrr_capacity"][i]
            * deg
            * inputs.stack_afrr_capacity
            * cap_drag
        )
        afrr_act = (
            scen["afrr_activation_y1"]
            * scen["compression_afrr_activation"][i]
            * deg
            * inputs.stack_afrr_activation
            * act_drag
        )
        pzu = (
            scen["pzu_y1"]
            * scen["compression_pzu"][i]
            * deg
            * inputs.stack_pzu
            * pzu_drag
        )
        revenue = afrr_cap + afrr_act + pzu

        opex = (inputs.epc_eur * inputs.opex_pct_of_epc / 100.0) * (1 + inputs.opex_inflation) ** i
        insurance = (inputs.epc_eur * inputs.insurance_pct_of_epc / 100.0) * (1 + inputs.opex_inflation) ** i
        augmentation = (
            inputs.epc_eur * inputs.augmentation_pct_of_epc / 100.0
            if y in inputs.augmentation_years else 0.0
        )

        ebitda = revenue - opex - insurance
        ebitda_margin = (ebitda / revenue * 100.0) if revenue > 0 else 0.0

        depreciation = annual_depreciation if y <= inputs.depreciation_life_yr else 0.0
        ebit = ebitda - depreciation

        if y <= inputs.loan_term_yr:
            interest_exp = debt_schedule[i]["interest"]
            principal_payment = debt_schedule[i]["principal"]
            debt_service = debt_schedule[i]["payment_total"]
            debt_outstanding = debt_schedule[i]["balance_end"]
        else:
            interest_exp = 0.0
            principal_payment = 0.0
            debt_service = 0.0
            debt_outstanding = 0.0

        ebt = ebit - interest_exp
        tax = max(0.0, ebt * inputs.tax_rate)
        net_income = ebt - tax

        # Cashflow
        project_fcf = ebitda - tax - augmentation
        equity_fcf = project_fcf - debt_service
        cum_equity_fcf += equity_fcf

        # Returns
        nopat = ebit * (1 - inputs.tax_rate)
        roe_pct = (net_income / equity_eur * 100.0) if equity_eur > 0 else 0.0
        roic_pct = (nopat / inputs.epc_eur * 100.0) if inputs.epc_eur > 0 else 0.0
        coc_yield = (equity_fcf / equity_eur * 100.0) if equity_eur > 0 else 0.0
        dscr = (ebitda / debt_service) if debt_service > 0 else None

        rows.append({
            "year": y,
            "afrr_capacity_eur": afrr_cap,
            "afrr_activation_eur": afrr_act,
            "pzu_arbitrage_eur": pzu,
            "total_revenue_eur": revenue,
            "opex_eur": opex,
            "insurance_eur": insurance,
            "ebitda_eur": ebitda,
            "ebitda_margin_pct": ebitda_margin,
            "depreciation_eur": depreciation,
            "ebit_eur": ebit,
            "interest_expense_eur": interest_exp,
            "ebt_eur": ebt,
            "tax_eur": tax,
            "net_income_eur": net_income,
            "principal_payment_eur": principal_payment,
            "debt_service_eur": debt_service,
            "debt_outstanding_ye_eur": debt_outstanding,
            "dscr": dscr,
            "augmentation_eur": augmentation,
            "project_fcf_eur": project_fcf,
            "equity_fcf_eur": equity_fcf,
            "cumulative_equity_fcf_eur": cum_equity_fcf,
            "roe_pct": roe_pct,
            "roic_pct": roic_pct,
            "cash_on_cash_yield_pct": coc_yield,
        })
    return rows


def compute_scenario_kpis(
    cashflow: List[dict],
    inputs: ScenarioInputs,
) -> dict:
    """Full PF KPI suite for one scenario cashflow."""
    equity_eur = inputs.epc_eur * inputs.equity_pct / 100.0
    loan_eur = inputs.epc_eur * inputs.loan_pct / 100.0

    equity_cf = [-equity_eur] + [r["equity_fcf_eur"] for r in cashflow]
    project_cf = [-inputs.epc_eur] + [r["project_fcf_eur"] for r in cashflow]

    eq_irr = irr(equity_cf)
    pj_irr = irr(project_cf)
    eq_mirr = mirr(equity_cf, inputs.loan_rate, inputs.discount_rate)
    pj_mirr = mirr(project_cf, inputs.loan_rate, inputs.discount_rate)

    eq_npv_8 = npv(equity_cf, 0.08)
    eq_npv_10 = npv(equity_cf, 0.10)
    eq_npv_12 = npv(equity_cf, 0.12)
    pj_npv_8 = npv(project_cf, 0.08)
    pj_npv_10 = npv(project_cf, 0.10)

    cum_eq = []
    s = -equity_eur
    for r in cashflow:
        s += r["equity_fcf_eur"]
        cum_eq.append(s)
    cum_pj = []
    s = -inputs.epc_eur
    for r in cashflow:
        s += r["project_fcf_eur"]
        cum_pj.append(s)
    eq_payback = payback_year([-equity_eur] + cum_eq)
    pj_payback = payback_year([-inputs.epc_eur] + cum_pj)
    eq_disc_payback = discounted_payback(equity_cf, inputs.discount_rate)
    pj_disc_payback = discounted_payback(project_cf, inputs.discount_rate)

    total_eq_inflow = sum(cf for cf in equity_cf if cf > 0)
    moic = total_eq_inflow / equity_eur if equity_eur > 0 else None

    dscrs = [r["dscr"] for r in cashflow if r["dscr"] is not None]
    avg_dscr = sum(dscrs) / len(dscrs) if dscrs else None
    min_dscr = min(dscrs) if dscrs else None
    breach_years = [r["year"] for r in cashflow
                    if r["dscr"] is not None and r["dscr"] < inputs.dscr_covenant]

    cfads = [r["ebitda_eur"] - r["tax_eur"] - r["augmentation_eur"] for r in cashflow]
    cfads_during_debt = cfads[: inputs.loan_term_yr]
    llcr = (sum(cf / (1 + inputs.loan_rate) ** (t + 1) for t, cf in enumerate(cfads_during_debt))
            / loan_eur) if loan_eur > 0 else None
    plcr = (sum(cf / (1 + inputs.loan_rate) ** (t + 1) for t, cf in enumerate(cfads))
            / loan_eur) if loan_eur > 0 else None

    avg_roe = sum(r["roe_pct"] for r in cashflow) / len(cashflow)
    avg_roic = sum(r["roic_pct"] for r in cashflow) / len(cashflow)
    avg_ebitda_margin = sum(r["ebitda_margin_pct"] for r in cashflow) / len(cashflow)

    return {
        "y1_revenue_eur": cashflow[0]["total_revenue_eur"],
        "y1_ebitda_eur": cashflow[0]["ebitda_eur"],
        "y1_ebitda_margin_pct": cashflow[0]["ebitda_margin_pct"],
        "y1_ebit_eur": cashflow[0]["ebit_eur"],
        "y1_net_income_eur": cashflow[0]["net_income_eur"],
        "y1_equity_fcf_eur": cashflow[0]["equity_fcf_eur"],
        "y1_dscr": cashflow[0]["dscr"],
        "lifetime_revenue_eur": sum(r["total_revenue_eur"] for r in cashflow),
        "lifetime_ebitda_eur": sum(r["ebitda_eur"] for r in cashflow),
        "lifetime_net_income_eur": sum(r["net_income_eur"] for r in cashflow),
        "lifetime_equity_fcf_eur": sum(r["equity_fcf_eur"] for r in cashflow),
        "lifetime_project_fcf_eur": sum(r["project_fcf_eur"] for r in cashflow),
        "avg_ebitda_margin_pct": avg_ebitda_margin,
        "equity_irr_pct": (eq_irr * 100.0) if eq_irr is not None else None,
        "project_irr_pct": (pj_irr * 100.0) if pj_irr is not None else None,
        "equity_mirr_pct": (eq_mirr * 100.0) if eq_mirr is not None else None,
        "project_mirr_pct": (pj_mirr * 100.0) if pj_mirr is not None else None,
        "equity_npv_8_eur": eq_npv_8,
        "equity_npv_10_eur": eq_npv_10,
        "equity_npv_12_eur": eq_npv_12,
        "project_npv_8_eur": pj_npv_8,
        "project_npv_10_eur": pj_npv_10,
        "moic": moic,
        "avg_roe_pct": avg_roe,
        "avg_roic_pct": avg_roic,
        "equity_payback_years": eq_payback,
        "project_payback_years": pj_payback,
        "equity_discounted_payback_years": eq_disc_payback,
        "project_discounted_payback_years": pj_disc_payback,
        "min_dscr": min_dscr,
        "avg_dscr": avg_dscr,
        "llcr": llcr,
        "plcr": plcr,
        "dscr_breach_years": breach_years,
    }


def analyze_all_scenarios(
    inputs: Optional[ScenarioInputs] = None,
    scenario_keys: Optional[List[str]] = None,
) -> dict:
    """Run all 4 (or selected) scenarios in BOTH modeled + realistic views.

    Returns a structured response with every scenario's full cashflow +
    KPI suite — what the API surfaces and what the frontend renders.
    """
    if inputs is None:
        inputs = ScenarioInputs()
    keys = scenario_keys or list(SCENARIO_DEFAULTS.keys())

    results = []
    for key in keys:
        scen_meta = SCENARIO_DEFAULTS[key]
        modeled_cf = build_scenario_cashflow(key, inputs, apply_drag=False)
        realistic_cf = build_scenario_cashflow(key, inputs, apply_drag=True)
        results.append({
            "scenario_key": key,
            "label": scen_meta["label"],
            "color": scen_meta["color"],
            "description": scen_meta["description"],
            "modeled": {
                "cashflow": modeled_cf,
                "kpis": compute_scenario_kpis(modeled_cf, inputs),
            },
            "realistic": {
                "cashflow": realistic_cf,
                "kpis": compute_scenario_kpis(realistic_cf, inputs),
            },
        })

    return {
        "inputs": {
            "epc_eur": inputs.epc_eur,
            "power_mw": inputs.power_mw,
            "capacity_mwh": inputs.capacity_mwh,
            "equity_pct": inputs.equity_pct,
            "loan_pct": inputs.loan_pct,
            "loan_rate": inputs.loan_rate,
            "loan_term_yr": inputs.loan_term_yr,
            "tax_rate": inputs.tax_rate,
            "depreciation_life_yr": inputs.depreciation_life_yr,
            "project_life_yr": inputs.project_life_yr,
            "discount_rate": inputs.discount_rate,
            "dscr_covenant": inputs.dscr_covenant,
            "stack_afrr_capacity": inputs.stack_afrr_capacity,
            "stack_afrr_activation": inputs.stack_afrr_activation,
            "stack_pzu": inputs.stack_pzu,
            "drag_afrr_capacity": inputs.drag_afrr_capacity,
            "drag_afrr_activation": inputs.drag_afrr_activation,
            "drag_pzu": inputs.drag_pzu,
        },
        "scenarios": results,
        "bankability_label": "Public-data / Backtest-only",
        "source_note": (
            "Engineering optimum: stacking constraint applied (physical hardware), "
            "no operator drag. Realistic: + operator drag (market-share guess, "
            "forecast error, REMIT/Tg/Td) + tax + 8-yr depreciation. "
            "Romanian aFRR capacity bid uses canonical DAMAS-derived clearing prices."
        ),
    }
