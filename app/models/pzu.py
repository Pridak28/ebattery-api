"""
PZU (Day-Ahead Market) Pydantic Models
"""
from datetime import date
from typing import Optional, List
from pydantic import BaseModel, Field


class PZUSimulationParams(BaseModel):
    """Parameters for PZU arbitrage simulation"""
    power_mw: float = Field(10.0, ge=0.1, le=1000, description="Battery power in MW")
    capacity_mwh: float = Field(20.0, ge=0.1, le=2000, description="Battery capacity in MWh")
    round_trip_efficiency: float = Field(0.88, ge=0.5, le=1.0, description="Round-trip efficiency (0-1)")
    soc_min: float = Field(0.10, ge=0.0, le=0.5, description="Minimum SOC (warranty floor)")
    soc_max: float = Field(0.90, ge=0.5, le=1.0, description="Maximum SOC (warranty ceiling)")
    soc_initial: float = Field(0.50, ge=0.0, le=1.0, description="SOC at start of each day")
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
    """Typical day charge/discharge pattern based on historical averages"""
    hourly_pattern: List[PZUHourlyPattern]
    charge_hours: List[int]
    discharge_hours: List[int]
    avg_buy_price_eur_mwh: float
    avg_sell_price_eur_mwh: float
    avg_spread_eur_mwh: float
    analysis_period_start: date
    analysis_period_end: date
    total_days_analyzed: int


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
    """Monthly optimal schedules response"""
    monthly_schedules: List[PZUMonthlyOptimal]
    analysis_period_start: date
    analysis_period_end: date
    total_months: int
    total_profit_eur: float
