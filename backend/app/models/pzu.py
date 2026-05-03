"""
PZU (Day-Ahead Market) Pydantic Models
"""
from datetime import date
from typing import Optional, List
from pydantic import BaseModel, Field


class PZUSimulationParams(BaseModel):
    """Parameters for PZU arbitrage simulation.

    User directive (2026-05-03): the install is sized so the FULL 20 MWh
    is the usable per-cycle throughput. Defaults set the SOC band to
    0-100% with soc_initial=0 so each day cycles 20 MWh end-to-end. RTE
    default is 0.97 (3% round-trip loss) per the user's vendor target.
    Equivalent physical realism: oversize the nameplate so the warranty
    band still covers the full 20 MWh.
    """
    power_mw: float = Field(10.0, ge=0.1, le=1000, description="Battery power in MW")
    capacity_mwh: float = Field(20.0, ge=0.1, le=2000, description="Battery capacity in MWh")
    round_trip_efficiency: float = Field(0.97, ge=0.5, le=1.0, description="Round-trip efficiency (0-1) — user directive: 0.97 (3% loss)")
    soc_min: float = Field(0.0, ge=0.0, le=0.5, description="Minimum SOC — user directive: full DOD (0%)")
    soc_max: float = Field(1.0, ge=0.5, le=1.0, description="Maximum SOC — user directive: full DOD (100%)")
    soc_initial: float = Field(0.0, ge=0.0, le=1.0, description="SOC at start of each day — user directive: empty (0%) so each day cycles full 20 MWh")
    start_date: Optional[date] = Field(None, description="Start date for simulation")
    end_date: Optional[date] = Field(None, description="End date for simulation")


class PZUDailyResult(BaseModel):
    """Daily arbitrage result"""
    date: date
    min_price_eur_mwh: float
    max_price_eur_mwh: float
    spread_eur_mwh: float
    cycles: float
    gross_profit_eur: float
    net_profit_eur: float


class PZUMonthlyResult(BaseModel):
    """Monthly aggregated result"""
    month: str
    days: int
    avg_buy_price_eur_mwh: float
    avg_sell_price_eur_mwh: float
    avg_spread_eur_mwh: float
    total_cycles: float
    gross_profit_eur: float
    net_profit_eur: float
    avg_daily_profit_eur: float


class PZUYearlyResult(BaseModel):
    """Yearly summary"""
    year: int
    total_days: int
    total_cycles: float
    gross_profit_eur: float
    net_profit_eur: float
    avg_daily_profit_eur: float
    best_month: str
    worst_month: str


class PZUSimulationResponse(BaseModel):
    """Complete simulation response"""
    params: PZUSimulationParams
    monthly_results: List[PZUMonthlyResult]
    yearly_summary: Optional[PZUYearlyResult] = None
    total_profit_eur: float
    avg_monthly_profit_eur: float
    # Bankability decomposition: investment_service uses these directly so it
    # no longer has to reconstruct revenue from monthly avg prices × hardcoded
    # cycle assumptions (which over-counted days where simulate() found no
    # profitable chronological window).
    total_gross_revenue_eur: float = Field(
        0.0,
        description="Sum of discharge_grid_mwh × avg_sell_price across all simulated days. Equals 0 only when no profitable day was found.",
    )
    total_energy_cost_eur: float = Field(
        0.0,
        description="Sum of charge_grid_mwh × avg_buy_price across all simulated days. Equals total_gross_revenue_eur − total_profit_eur.",
    )
    # Mastermind R-4: surface silent data loss instead of letting rejected days
    # vanish into the aggregate.
    days_input_count: int = Field(
        0,
        description="Number of calendar days in the requested window.",
    )
    days_simulated_count: int = Field(
        0,
        description="Days that produced a result (profitable or zero-trade).",
    )
    days_no_profitable_pair: int = Field(
        0,
        description="Days where simulate() ran but found no profitable chronological (charge,discharge) pair (zero-trade days).",
    )
    days_rejected_data_quality: int = Field(
        0,
        description="Days dropped before dispatch — too few hours, NaN windows, or data-quality issues.",
    )


class PZUPriceHistory(BaseModel):
    """Price history data point"""
    date: date
    price_eur_mwh: float
    hour: Optional[int] = None


class PZUPriceHistoryResponse(BaseModel):
    """Price history response"""
    data: List[PZUPriceHistory]
    start_date: date
    end_date: date
    count: int
    avg_price: float
    min_price: float
    max_price: float


class PZUHourlyPattern(BaseModel):
    """Hourly charge/discharge pattern"""
    hour: int
    avg_price_eur_mwh: float
    action: str  # 'charge', 'discharge', or 'idle'


class PZUTypicalDayResponse(BaseModel):
    """Typical day charge/discharge pattern based on historical averages.

    Screening helper: picks cheapest-N + priciest-N hours regardless of
    chronological order. NOT a bankable revenue projection — use
    ``/pzu/simulate`` for chronological + SOC-aware dispatch.
    """
    hourly_pattern: List[PZUHourlyPattern]
    charge_hours: List[int]
    discharge_hours: List[int]
    avg_buy_price_eur_mwh: float
    avg_sell_price_eur_mwh: float
    avg_spread_eur_mwh: float
    analysis_period_start: date
    analysis_period_end: date
    total_days_analyzed: int
    is_screening_only: bool = Field(
        True,
        description="True = non-chronological screening; cheapest/priciest hours may be in any order. Use /pzu/simulate for bankable numbers.",
    )
    dispatch_method: str = Field(
        "non_chronological_screening",
        description="screening method label",
    )


class PZUMonthlyOptimal(BaseModel):
    """Optimal charge/discharge schedule for a specific month"""
    month: str
    charge_hours: List[int]
    discharge_hours: List[int]
    avg_buy_price_eur_mwh: float
    avg_sell_price_eur_mwh: float
    avg_spread_eur_mwh: float
    total_profit_eur: float
    days_in_month: int


class PZUMonthlyOptimalResponse(BaseModel):
    """Monthly optimal schedules response.

    Screening helper: picks cheapest-N + priciest-N hours per month regardless
    of chronological order. Profit estimates use symmetric sqrt(η) AC-side
    losses. NOT bankable — use ``/pzu/simulate`` for SOC-aware chronological
    dispatch.
    """
    monthly_schedules: List[PZUMonthlyOptimal]
    analysis_period_start: date
    analysis_period_end: date
    total_months: int
    total_profit_eur: float
    is_screening_only: bool = Field(
        True,
        description="True = non-chronological screening; profit upper-bounds reality.",
    )
    dispatch_method: str = Field(
        "non_chronological_screening",
        description="screening method label",
    )
