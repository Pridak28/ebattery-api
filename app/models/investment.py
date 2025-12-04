"""
Investment & Financial Analysis Pydantic Models
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class InvestmentParams(BaseModel):
    """Investment parameters"""
    total_investment_eur: float = Field(7_500_000, ge=0, description="Total project investment")
    equity_percentage: float = Field(30.0, ge=0, le=100, description="Equity percentage")
    loan_interest_rate: float = Field(6.0, ge=0, le=30, description="Annual interest rate %")
    loan_term_years: int = Field(10, ge=1, le=30, description="Loan term in years")

    # Operating costs
    opex_percentage: float = Field(2.0, ge=0, le=20, description="Annual OPEX as % of investment")
    insurance_percentage: float = Field(0.5, ge=0, le=5, description="Annual insurance as % of investment")

    # Battery parameters
    power_mw: float = Field(15.0, ge=0.1, description="Battery power MW")
    capacity_mwh: float = Field(30.0, ge=0.1, description="Battery capacity MWh")


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
