"""
Frequency Regulation (FR) Pydantic Models
"""
from datetime import date
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class FRProductConfig(BaseModel):
    """Configuration for a single FR product"""
    enabled: bool = True
    power_mw: float = Field(10.0, ge=0, le=1000, description="Allocated power in MW")
    capacity_price_eur_mw_h: float = Field(15.0, ge=0, le=500, description="Capacity price EUR/MW/h")
    activation_rate: float = Field(
        0.10,
        ge=0.01,
        le=0.50,
        description="Market share percentage (1-50%). Based on Romanian merit-order dispatch: 10% = capturing 10% of total market activations. NOT a duty cycle."
    )


class FRSimulationParams(BaseModel):
    """Parameters for FR simulation"""
    capacity_mwh: float = Field(20.0, ge=0.1, le=2000, description="Battery capacity in MWh")
    round_trip_efficiency: float = Field(0.88, ge=0.5, le=1.0, description="Round-trip efficiency")

    # Product configurations - each with own capacity price and activation rate
    afrr_up: FRProductConfig = Field(default_factory=lambda: FRProductConfig(power_mw=10.0))
    afrr_down: FRProductConfig = Field(default_factory=lambda: FRProductConfig(power_mw=10.0))
    mfrr_up: FRProductConfig = Field(default_factory=lambda: FRProductConfig(enabled=False, power_mw=0.0))
    mfrr_down: FRProductConfig = Field(default_factory=lambda: FRProductConfig(enabled=False, power_mw=0.0))

    # Energy cost for recharging
    energy_cost_eur_mwh: float = Field(80.0, ge=0, description="Energy cost for charging")

    # Phase D5 — availability factor (97-98% typical for new BESS).
    availability_pct: float = Field(97.5, ge=0.0, le=100.0, description="Annual uptime % (capacity + activation revenue scale)")

    # Date range
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class FRMonthlyResult(BaseModel):
    """Monthly FR simulation result.

    Per audit/ROMANIAN_BESS_AUDIT_RISK_INVESTIGATION_2026-05-01.md every result
    must declare its `pricing_basis` and `confidence_label` so investors do not
    confuse public/system-level data with participant settlement.
    """
    month: str
    product: str  # 'aFRR+', 'aFRR-', 'mFRR+', 'mFRR-'

    # Slots and availability
    total_slots: int = 0

    # Revenue breakdown
    capacity_revenue_eur: float = 0.0
    activation_revenue_eur: float = 0.0
    total_revenue_eur: float = 0.0

    # Energy
    activation_energy_mwh: float = 0.0
    energy_cost_eur: float = 0.0

    # Net result
    net_profit_eur: float = 0.0

    # Metrics
    avg_capacity_price_eur_mw: float = 0.0
    avg_activation_price_eur_mwh: float = 0.0

    # Audit metadata — see ROMANIAN_BESS_AUDIT_RISK_INVESTIGATION_2026-05-01.md
    pricing_basis: str = "public_marginal"  # public_marginal | participant_bid | settlement_export | scenario
    confidence_label: str = "Public-data / Participant-only-for-bankability"
    activation_method: str = "DAMAS_market_share"
    bankable: bool = False  # True only when settlement_export evidence is supplied
    source_kind: str = "unverified_snapshot"
    data_date_max: Optional[str] = None
    bankability_level: str = "historical_backtest_only"


class FRProductSummary(BaseModel):
    """Summary for a single product across all months"""
    product: str
    total_capacity_revenue_eur: float
    total_activation_revenue_eur: float
    total_revenue_eur: float
    total_energy_cost_eur: float
    total_net_profit_eur: float
    months_count: int


class FRMultiProductRequest(BaseModel):
    """Phase E — multi-product (aFRR / mFRR / FCR) request."""
    products: List[Literal["aFRR", "mFRR", "FCR"]] = Field(
        default_factory=lambda: ["aFRR"],
        description="FR products to include in revenue calculation",
    )
    power_mw: float = Field(10.0, ge=0.1, le=1000, description="Total bid power MW per product")
    capacity_mwh: float = Field(20.0, ge=0.1, le=2000, description="Battery usable capacity")
    round_trip_efficiency: float = Field(0.88, ge=0.5, le=1.0)
    availability_pct: float = Field(97.5, ge=0.0, le=100.0)
    energy_cost_eur_mwh: float = Field(80.0, ge=0, description="Recharge energy price")
    activation_share: float = Field(0.10, ge=0.0, le=1.0, description="Share of market activation captured (bid stack proxy)")
    target_date: Optional[date] = Field(
        None,
        description="Reference date for MARI rule check; defaults to today.",
    )
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class FRProductResult(BaseModel):
    """Per-product breakdown for the multi-product endpoint."""
    product: Literal["aFRR", "mFRR", "FCR"]
    capacity_revenue_eur: float
    activation_revenue_eur: float
    energy_cost_eur: float
    net_revenue_eur: float
    capacity_eur_mw_h: float
    settlement: Literal["pay_as_bid", "marginal"]
    activated_mwh: float
    avg_activation_price_eur_mwh: float
    min_bid_mw: float
    symmetric: bool = False
    pricing_basis: str
    confidence_label: str


class FRMultiProductResponse(BaseModel):
    """Phase E response — combined revenue across selected FR products."""
    params: FRMultiProductRequest
    products: List[FRProductResult]
    total_capacity_revenue_eur: float
    total_activation_revenue_eur: float
    total_energy_cost_eur: float
    total_net_revenue_eur: float
    min_bid_violations: List[str] = Field(
        default_factory=list,
        description="Products where requested power_mw < min bid for the target_date (pre-/post-MARI).",
    )
    mari_active: bool
    target_date: date


class FRSimulationResponse(BaseModel):
    """Complete FR simulation response"""
    params: FRSimulationParams
    monthly_results: List[FRMonthlyResult]
    product_summaries: List[FRProductSummary]

    # Totals
    total_revenue_eur: float
    total_energy_cost_eur: float
    total_net_profit_eur: float
    total_capacity_revenue_eur: float = 0.0
    total_activation_revenue_eur: float = 0.0
    avg_monthly_net_profit_eur: float = 0.0
    annual_net_profit_eur: float = 0.0
    # Annualized metrics (12-month projection)
    annual_revenue_eur: float = 0.0
    annual_capacity_revenue_eur: float = 0.0
    annual_activation_revenue_eur: float = 0.0
    annual_energy_cost_eur: float = 0.0
    months_count: int = 0
    source_kind: str = "unverified_snapshot"
    data_date_max: Optional[str] = None
    bankability_level: str = "historical_backtest_only"
    data_warnings: List[str] = Field(default_factory=list)
