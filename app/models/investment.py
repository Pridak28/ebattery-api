"""
Investment & Financial Analysis Pydantic Models
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class InvestmentParams(BaseModel):
    """Investment parameters.

    Defaults anchored on the user's actual quote: €3,500,000 EPC for
    10 MW / 20 MWh = €175/kWh installed.
    """
    total_investment_eur: float = Field(3_500_000, ge=0, description="Total project investment (€3.5M for 10MW/20MWh)")
    equity_percentage: float = Field(30.0, ge=0, le=100, description="Equity percentage")
    loan_interest_rate: float = Field(6.0, ge=0, le=30, description="Annual interest rate %")
    loan_term_years: int = Field(10, ge=1, le=30, description="Loan term in years")

    # Operating costs
    opex_percentage: float = Field(2.0, ge=0, le=20, description="Annual OPEX as % of investment")
    insurance_percentage: float = Field(0.5, ge=0, le=5, description="Annual insurance as % of investment")

    # Battery parameters — canonical 10 MW / 20 MWh.
    power_mw: float = Field(10.0, ge=0.1, description="Battery power MW")
    capacity_mwh: float = Field(20.0, ge=0.1, description="Battery capacity MWh")

    # Lifecycle assumptions (audit Agent 1 High; Agent 5 Medium):
    degradation_rate_pct: float = Field(2.5, ge=0, le=10, description="Annual capacity fade %, applies to revenue")
    opex_inflation_pct: float = Field(3.0, ge=0, le=20, description="Annual OPEX inflation %")

    # Phase D — physical realism (gap audit 2026-05-01).
    rte_ac_ac: float = Field(0.88, ge=0.5, le=1.0, description="AC-to-AC round-trip efficiency (sqrt-symmetric)")
    soc_min: float = Field(0.10, ge=0.0, le=0.5, description="Minimum SOC (warranty floor)")
    soc_max: float = Field(0.90, ge=0.5, le=1.0, description="Maximum SOC (warranty ceiling)")
    # Industry range for HVAC/BMS/fire suppression: 1-3% of rated power.
    # Default 1.5% (= 0.15 MW for 10 MW battery) — mid-range, matches modern
    # Sermatec/Huawei/BYD spec sheets. Earlier 0.3 MW (= 3%) was high-end.
    auxiliary_load_mw: float = Field(0.15, ge=0.0, description="Continuous HVAC/BMS/fire-suppression draw (MW); default 1.5% of rated")
    availability_pct: float = Field(97.5, ge=0.0, le=100.0, description="Annual uptime %")
    efc_budget: int = Field(6000, ge=1, description="Vendor warranty: equivalent full cycles allowed across asset life")
    warranty_years: int = Field(15, ge=1, le=30, description="Vendor warranty length in years")
    augmentation_pct_of_epc: float = Field(10.0, ge=0.0, le=50.0, description="Augmentation cost as % of EPC at year 5 + year 10")
    self_discharge_pct_per_month: float = Field(2.0, ge=0.0, le=20.0, description="Self-discharge %/month at idle")
    cycle_fade_per_efc: float = Field(0.00005, ge=0.0, le=0.001, description="Capacity fade per EFC (additive to calendar fade)")
    annual_efc_assumption: float = Field(365.0, ge=0.0, le=2000.0, description="Assumed annual cycles for warranty + cycle-fade tracking")
    avg_pzu_price_eur_mwh_for_aux: float = Field(80.0, ge=0.0, description="Average PZU price used to value auxiliary-load energy draw")

    # Phase F — risk / financing.
    revenue_currency: Literal["EUR", "RON"] = Field("EUR", description="Currency in which market revenue is denominated")
    fx_hedge_cost_pct: float = Field(2.5, ge=0.0, le=10.0, description="Annual FX hedge cost % of revenue when revenue_currency=RON")

    # Realism fix #4 (2026-05-02): Romanian aFRR capacity prices are 2-4× European
    # norms today and will compress as more BESS enters. UK Dynamic Containment
    # fell 75% in 24 months once 6 GW of BESS came online; Germany SRL had
    # similar compression in 2023-2024.
    #
    # Default: 10%/yr starting Y3, FLOOR at 40% of Y1 (so steady-state revenue
    # is 40% of premium). This matches the German trajectory: prices compressed
    # ~70% in 2 years then stabilized — they didn't drop to zero. The floor is
    # critical for 15-year IRR realism (without it, late-year cashflow goes
    # deeply negative and lifetime IRR becomes ill-defined).
    capacity_price_compression_pct_per_year: float = Field(
        8.0, ge=0.0, le=50.0,
        description="Annual % compression of revenue starting year 3, until floor reached"
    )
    capacity_price_compression_start_year: int = Field(
        3, ge=1, le=15,
        description="Year in which capacity-price compression begins (Y1+Y2 keep premium pricing)"
    )
    capacity_price_compression_floor_pct: float = Field(
        55.0, ge=0.0, le=100.0,
        description=(
            "Floor on revenue as % of Y1 (default 55% = compression saturates at -45% from Y1). "
            "Captures the German pattern where capacity prices crashed but activation revenue "
            "(driven by grid stress, not BESS supply) stayed near its market level."
        )
    )


class FinancingBreakdown(BaseModel):
    """Financing structure breakdown"""
    total_investment_eur: float
    equity_eur: float
    equity_percentage: float
    debt_eur: float
    debt_percentage: float
    annual_debt_service_eur: float
    monthly_debt_service_eur: float
    total_interest_paid_eur: float


class AnnualCashflow(BaseModel):
    """Annual cashflow projection"""
    year: int
    gross_revenue_eur: float
    energy_cost_eur: float
    operating_cost_eur: float
    debt_service_eur: float
    net_profit_eur: float
    cumulative_profit_eur: float

    # Phase D — physical realism. Default 0 / "ok" so historical responses
    # remain valid; populated when investment_service runs the new pipeline.
    auxiliary_cost_eur: float = 0.0
    augmentation_cost_eur: float = 0.0
    cumulative_efc: float = 0.0
    warranty_status: Literal["ok", "exceeded"] = "ok"
    calendar_fade: float = 0.0
    cycle_fade: float = 0.0
    capacity_factor: float = 1.0

    # Phase F — risk + bankability covenants.
    cfads_eur: float = 0.0
    dscr: float = 0.0
    fx_hedge_cost_eur: float = 0.0


class ScenarioResult(BaseModel):
    """Result for a single scenario (FR or PZU)"""
    name: str  # 'FR' or 'PZU'

    # Revenue
    gross_revenue_eur: float
    energy_cost_eur: float
    operating_cost_eur: float

    # After debt
    annual_debt_service_eur: float
    net_profit_after_debt_eur: float

    # Metrics
    roi_percentage: float
    payback_years: float
    profit_margin_percentage: float

    # Provenance (audit Agent 1 High; Agent 5 Critical/High):
    pricing_basis: str = "scenario"           # public_marginal | participant_bid | settlement_export | scenario
    confidence_label: str = "Likely-source / Scenario"
    revenue_source: str = "simulation"        # simulation | fallback_estimate
    warnings: List[str] = []                  # populated when fallbacks fired


class InvestmentComparisonResponse(BaseModel):
    """Investment comparison response"""
    params: InvestmentParams
    financing: FinancingBreakdown

    # Scenario results
    fr_scenario: ScenarioResult
    pzu_scenario: ScenarioResult

    # Comparison
    recommended_scenario: str
    advantage_eur: float
    advantage_percentage: float

    # Projections
    fr_cashflow: List[AnnualCashflow]
    pzu_cashflow: List[AnnualCashflow]

    # Top-level provenance / disclosures (audit Agent 5 High/Medium):
    warnings: List[str] = []
    excluded_from_model: List[str] = Field(
        default_factory=lambda: [
            "Tax / VAT timing",
            "Network connection / extraction tariffs (Tg/Td) until ANRE Order 56/2025 fully applied",
            "Insurance escalation",
            "REMIT / penalty exposure",
            "Forced curtailment",
            "Compliance gates: ANRE / OPCOM / PRE / BRP / BSP / FSE / DAMAS",
        ],
        description="Costs/risks intentionally NOT modelled — investors must add these before bankability.",
    )
    audit_reference: str = "audit/BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT_2026-05-01.md"

    # Phase F — DSCR covenant: years where DSCR < 1.20 (lender covenant typical).
    dscr_violation_years: List[int] = []

    # Realism (2026-05-02): the bankability number is the LIFETIME IRR over the
    # full projection horizon, NOT the Year-1 ROI which can be misleading in
    # markets with strong premium today and predictable compression (Romania
    # 2026 fits this pattern). Surface both so investors / lenders read the
    # right number for their decision.
    #
    # ``*_lifetime_irr_pct = None`` means no positive IRR exists over the
    # projection horizon (project is loss-making in NPV terms). ``0.0``
    # means a real 0% IRR. ``*_lifetime_payback_years = None`` means the
    # project never breaks even within the projection.
    fr_year1_roi_pct: float = 0.0
    pzu_year1_roi_pct: float = 0.0
    fr_lifetime_irr_pct: Optional[float] = None
    pzu_lifetime_irr_pct: Optional[float] = None
    fr_lifetime_payback_years: Optional[float] = None
    pzu_lifetime_payback_years: Optional[float] = None
    projection_horizon_years: int = 0


class InvestmentAnalysisResponse(BaseModel):
    """Simple investment analysis response"""
    params: InvestmentParams
    financing: FinancingBreakdown

    # Scenario results
    fr_scenario: ScenarioResult
    pzu_scenario: ScenarioResult

    # Comparison
    recommended_scenario: str
    advantage_eur: float
    advantage_percentage: float


class ROIMetrics(BaseModel):
    """ROI and financial metrics"""
    roi_on_equity: float
    roi_on_investment: float
    payback_period_years: float
    irr_percentage: Optional[float] = None
    npv_eur: Optional[float] = None
