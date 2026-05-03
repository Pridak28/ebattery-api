"""
PZU (Day-Ahead Market) API Routes
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import date

from app.models.pzu import (
    PZUSimulationParams,
    PZUSimulationResponse,
    PZUPriceHistoryResponse,
    PZUTypicalDayResponse,
    PZUMonthlyOptimalResponse,
)
from app.services.pzu_service import PZUService

router = APIRouter()
pzu_service = PZUService()


@router.get("/history", response_model=PZUPriceHistoryResponse)
async def get_price_history(
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    aggregate: str = Query("daily", description="Aggregation: hourly, daily, monthly"),
):
    """Get PZU price history data"""
    try:
        return pzu_service.get_price_history(
            start_date=start_date,
            end_date=end_date,
            aggregate=aggregate,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simulate", response_model=PZUSimulationResponse)
async def run_simulation(params: PZUSimulationParams):
    """Run PZU arbitrage simulation"""
    try:
        return pzu_service.simulate(params)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monthly-summary")
async def get_monthly_summary(
    power_mw: float = Query(10.0, ge=0.1, description="Battery power MW (default 10 MW per user directive)"),
    capacity_mwh: float = Query(20.0, ge=0.1, description="Battery capacity MWh (default 20 MWh per user directive)"),
    efficiency: float = Query(0.97, ge=0.5, le=1.0, description="Round-trip efficiency (0.97 = 3% loss, per user directive)"),
    year: Optional[int] = Query(None, description="Filter by year"),
):
    """Get monthly arbitrage summary"""
    try:
        params = PZUSimulationParams(
            power_mw=power_mw,
            capacity_mwh=capacity_mwh,
            round_trip_efficiency=efficiency,
        )
        result = pzu_service.simulate(params)

        # Filter by year if specified
        monthly = result.monthly_results
        if year:
            monthly = [m for m in monthly if m.month.startswith(str(year))]

        return {
            "monthly_results": monthly,
            "total_profit_eur": sum(m.net_profit_eur for m in monthly),
            "avg_monthly_profit_eur": sum(m.net_profit_eur for m in monthly) / len(monthly) if monthly else 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_market_stats():
    """Get overall PZU market statistics"""
    try:
        return pzu_service.get_market_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/typical-day", response_model=PZUTypicalDayResponse)
async def get_typical_day_pattern(
    start_date: Optional[date] = Query(date(2024, 1, 1), description="Start date for analysis (default: 2024-01-01)"),
    end_date: Optional[date] = Query(date(2025, 12, 31), description="End date for analysis (default: 2025-12-31)"),
    num_charge_hours: int = Query(3, ge=1, le=12, description="Number of charge hours"),
    num_discharge_hours: int = Query(3, ge=1, le=12, description="Number of discharge hours"),
):
    """
    Get typical charge/discharge pattern based on historical hourly price averages.
    Returns which hours are typically best for charging (buying) and discharging (selling).

    Defaults to 2024-2025 data.
    """
    try:
        return pzu_service.get_typical_day_pattern(
            start_date=start_date,
            end_date=end_date,
            num_charge_hours=num_charge_hours,
            num_discharge_hours=num_discharge_hours,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monthly-optimal", response_model=PZUMonthlyOptimalResponse)
async def get_monthly_optimal_schedules(
    start_date: Optional[date] = Query(date(2024, 1, 1), description="Start date for analysis (default: 2024-01-01)"),
    end_date: Optional[date] = Query(date(2025, 12, 31), description="End date for analysis (default: 2025-12-31)"),
    num_charge_hours: int = Query(3, ge=1, le=12, description="Number of charge hours per month"),
    num_discharge_hours: int = Query(3, ge=1, le=12, description="Number of discharge hours per month"),
    power_mw: float = Query(10.0, ge=0.1, description="Battery power in MW (default 10 MW per user directive)"),
    capacity_mwh: float = Query(20.0, ge=0.1, description="Battery capacity in MWh (default 20 MWh per user directive)"),
    efficiency: float = Query(0.97, ge=0.5, le=1.0, description="Round-trip efficiency (0.97 = 3% loss, per user directive)"),
):
    """
    Get optimal charge/discharge schedules calculated separately for each month.
    Each month gets its own best hours based on that month's price patterns.

    Returns month-by-month optimal hours and spreads, showing how the best
    charging/discharging times vary throughout the year.

    Defaults to 2024-2025 data.
    """
    try:
        return pzu_service.get_monthly_optimal_schedules(
            start_date=start_date,
            end_date=end_date,
            num_charge_hours=num_charge_hours,
            num_discharge_hours=num_discharge_hours,
            power_mw=power_mw,
            capacity_mwh=capacity_mwh,
            efficiency=efficiency,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-breakdown/{month}")
async def get_daily_breakdown(
    month: str,
    power_mw: float = Query(10.0, ge=0.1, description="Battery power in MW (default 10 MW per user directive)"),
    capacity_mwh: float = Query(20.0, ge=0.1, description="Battery capacity in MWh (default 20 MWh per user directive)"),
    efficiency: float = Query(0.97, ge=0.5, le=1.0, description="Round-trip efficiency (0.97 = 3% loss, per user directive)"),
):
    """
    Get daily breakdown for a specific month.
    Month format: YYYY-MM (e.g., 2024-01)

    Returns daily profit, optimal buy/sell hours, and price statistics for each day.
    """
    try:
        return pzu_service.get_daily_breakdown(
            month=month,
            power_mw=power_mw,
            capacity_mwh=capacity_mwh,
            efficiency=efficiency,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/available-dates")
async def get_available_dates():
    """
    Get list of all available dates with summary statistics.
    Returns date, min/max/avg price, and spread for each day.
    """
    try:
        return pzu_service.get_available_dates()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hourly-prices/{date_str}")
async def get_hourly_prices(
    date_str: str,
    power_mw: float = Query(10.0, ge=0.1, description="Battery power in MW (default 10 MW per user directive)"),
    capacity_mwh: float = Query(20.0, ge=0.1, description="Battery capacity in MWh (default 20 MWh per user directive)"),
    efficiency: float = Query(0.97, ge=0.5, le=1.0, description="Round-trip efficiency (0.97 = 3% loss, per user directive)"),
):
    """
    Get hourly prices for a specific date with energy costs calculated.
    Date format: YYYY-MM-DD (e.g., 2024-11-15)

    Returns:
    - Hourly prices (24 hours)
    - Recommended action per hour (charge/discharge/idle)
    - Energy cost per hour (positive = cost, negative = revenue)
    - Daily summary (spread, profit, OPCOM link)
    """
    try:
        result = pzu_service.get_hourly_prices(
            date_str=date_str,
            power_mw=power_mw,
            capacity_mwh=capacity_mwh,
            efficiency=efficiency,
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
