"""
Frequency Regulation (FR) Pydantic Models
"""
from datetime import date
from typing import Optional, List
from pydantic import BaseModel, Field


class FRProductConfig(BaseModel):
    """Configuration for a single FR product"""
    enabled: bool = True
    power_mw: float = Field(15.0, ge=0, le=1000, description="Allocated power in MW")
    capacity_price_eur_mw_h: float = Field(15.0, ge=0, le=500, description="Capacity price EUR/MW/h")
    activation_rate: float = Field(
        0.10,
        ge=0.01,
        le=0.50,
        description="Market share percentage (1-50%). Based on Romanian merit-order dispatch: 10% = capturing 10% of total market activations. NOT a duty cycle."
    )


class FRSimulationParams(BaseModel):
    """Parameters for FR simulation"""
    capacity_mwh: float = Field(30.0, ge=0.1, le=2000, description="Battery capacity in MWh")
    round_trip_efficiency: float = Field(0.88, ge=0.5, le=1.0, description="Round-trip efficiency")

    # Product configurations - each with own capacity price and activation rate
    afrr_up: FRProductConfig = Field(default_factory=lambda: FRProductConfig(power_mw=15.0))
    afrr_down: FRProductConfig = Field(default_factory=lambda: FRProductConfig(power_mw=15.0))
    mfrr_up: FRProductConfig = Field(default_factory=lambda: FRProductConfig(enabled=False, power_mw=0.0))
    mfrr_down: FRProductConfig = Field(default_factory=lambda: FRProductConfig(enabled=False, power_mw=0.0))

    # Energy cost for recharging
    energy_cost_eur_mwh: float = Field(80.0, ge=0, description="Energy cost for charging")

    # Date range
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class FRMonthlyResult(BaseModel):
    """Monthly FR simulation result"""
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


class FRProductSummary(BaseModel):
    """Summary for a single product across all months"""
    product: str
    total_capacity_revenue_eur: float
    total_activation_revenue_eur: float
    total_revenue_eur: float
    total_energy_cost_eur: float
    total_net_profit_eur: float
    months_count: int


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
