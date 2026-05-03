"""
Frequency Regulation (FR) API Routes
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import date

from app.models.fr import (
    FRSimulationParams,
    FRSimulationResponse,
    FRMonthlyResult,
    FRMultiProductRequest,
    FRMultiProductResponse,
)
from app.services.fr_service import FRService, ROMANIAN_FR_PRODUCTS

router = APIRouter()
fr_service = FRService()


@router.get("/products")
async def get_available_products():
    """Get list of available FR products"""
    return {
        "products": [
            {"id": "afrr_up", "name": "aFRR+", "description": "Automatic Frequency Restoration Reserve (Up)"},
            {"id": "afrr_down", "name": "aFRR-", "description": "Automatic Frequency Restoration Reserve (Down)"},
            {"id": "mfrr_up", "name": "mFRR+", "description": "Manual Frequency Restoration Reserve (Up)"},
            {"id": "mfrr_down", "name": "mFRR-", "description": "Manual Frequency Restoration Reserve (Down)"},
        ]
    }


@router.get("/product-catalog")
async def get_product_catalog():
    """Phase E2: Romanian FR product catalogue with capacity prices, settlement
    convention, and min-bid thresholds (pre/post MARI 2026-04-01)."""
    return {"products": ROMANIAN_FR_PRODUCTS}


@router.post("/multi-product", response_model=FRMultiProductResponse)
async def run_multi_product(request: FRMultiProductRequest):
    """Phase E1+E2: capacity vs activation revenue per product (aFRR/mFRR/FCR).

    Honors Romanian min-bid rules and the April-2026 MARI threshold raise
    (1 MW → 5 MW for aFRR / mFRR new entrants).
    """
    try:
        return fr_service.compute_multi_product_revenue(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data")
async def get_fr_data(
    product: Optional[str] = Query(None, description="Filter by product"),
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
):
    """Get FR market data"""
    try:
        return fr_service.get_market_data(
            product=product,
            start_date=start_date,
            end_date=end_date,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simulate", response_model=FRSimulationResponse)
async def run_simulation(params: FRSimulationParams):
    """Run FR revenue simulation"""
    try:
        return fr_service.simulate(params)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/monthly-breakdown")
async def get_monthly_breakdown(
    power_mw: float = Query(15.0, ge=0.1, description="Battery power MW"),
    capacity_mwh: float = Query(30.0, ge=0.1, description="Battery capacity MWh"),
    product: Optional[str] = Query(None, description="Filter by product"),
):
    """Get monthly revenue breakdown"""
    try:
        params = FRSimulationParams(
            capacity_mwh=capacity_mwh,
            afrr_up={"enabled": True, "power_mw": power_mw},
            afrr_down={"enabled": True, "power_mw": power_mw},
        )
        result = fr_service.simulate(params)

        monthly = result.monthly_results
        if product:
            monthly = [m for m in monthly if m.product.lower() == product.lower()]

        return {
            "monthly_results": monthly,
            "total_revenue_eur": sum(m.total_revenue_eur for m in monthly),
            "total_net_profit_eur": sum(m.net_profit_eur for m in monthly),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_fr_stats():
    """Get FR market statistics"""
    try:
        return fr_service.get_market_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/available-dates")
async def get_available_dates():
    """
    Get list of all available dates with summary statistics for aFRR.
    Returns date, avg prices, and activation volumes for each day.
    """
    try:
        return fr_service.get_available_dates()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/slot-prices/{date_str}")
async def get_slot_prices(
    date_str: str,
    power_mw: float = Query(15.0, ge=0.1, description="Battery power in MW"),
):
    """
    Get 15-minute slot prices for a specific date with FR revenue calculated.
    Date format: YYYY-MM-DD (e.g., 2024-12-03)

    Returns:
    - 15-minute slot data (96 slots per day)
    - aFRR+ and aFRR- prices and activations
    - Daily summary (avg prices, total revenue, DAMAS link)
    """
    try:
        result = fr_service.get_slot_prices(
            date_str=date_str,
            power_mw=power_mw,
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bidding-strategy")
async def get_bidding_strategy(
    start_date: Optional[date] = Query(None, description="Start date for analysis"),
    end_date: Optional[date] = Query(None, description="End date for analysis"),
):
    """
    Get historical bidding strategy analysis.

    Analyzes historical aFRR data to recommend optimal bidding strategies.
    Returns:
    - Optimal bid prices at different percentiles (conservative, balanced, aggressive)
    - aFRR+ vs aFRR- profitability comparison
    - Seasonal patterns
    - Strategy recommendations
    """
    try:
        start_str = start_date.isoformat() if start_date else None
        end_str = end_date.isoformat() if end_date else None

        result = fr_service.analyze_bidding_strategy(
            start_date=start_str,
            end_date=end_str,
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/optimal-bids/{date_str}")
async def get_optimal_bids(
    date_str: str,
    power_mw: float = Query(15.0, ge=0.1, description="Battery power in MW"),
    target_acceptance: float = Query(0.80, ge=0.5, le=0.95, description="Target acceptance rate (0.5-0.95)"),
    capacity_mwh: Optional[float] = Query(
        None,
        ge=0.1,
        description="Battery energy capacity MWh. Omit to use catalog default (settings.DEFAULT_CAPACITY_MWH).",
    ),
):
    """
    Get optimal bid prices for a specific date.
    Date format: YYYY-MM-DD (e.g., 2024-12-03)

    Uses surrounding 90 days of historical data to recommend optimal capacity bid prices
    for both aFRR+ and aFRR- based on target acceptance rate.

    Returns:
    - Recommended capacity bid prices
    - Expected acceptance probability
    - Estimated daily revenue for each service
    - Service recommendation
    """
    try:
        result = fr_service.calculate_optimal_bids(
            date_str=date_str,
            power_mw=power_mw,
            target_acceptance_rate=target_acceptance,
            capacity_mwh=capacity_mwh,
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue-projection")
async def get_revenue_projection(
    power_mw: float = Query(15.0, ge=0.1, description="Battery power in MW"),
    strategy: str = Query("balanced", description="Strategy: conservative, balanced, or aggressive"),
):
    """
    Get 12-month revenue projection with optimal bidding strategy.

    Strategies:
    - Conservative: 90% acceptance rate, lower bid prices, safer returns
    - Balanced: 80% acceptance rate, moderate bid prices, optimal risk/reward
    - Aggressive: 60% acceptance rate, higher bid prices, higher potential returns

    Returns month-by-month projections using historical data analysis.
    """
    try:
        # Validate strategy
        if strategy not in ["conservative", "balanced", "aggressive"]:
            raise HTTPException(
                status_code=400,
                detail="Strategy must be one of: conservative, balanced, aggressive"
            )

        result = fr_service.project_annual_revenue(
            power_mw=power_mw,
            strategy=strategy,
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/safe-bid-calculator")
async def get_safe_bid_prices(
    power_mw: float = Query(15.0, ge=0.1, description="Battery power in MW"),
    target_acceptance: float = Query(0.90, ge=0.80, le=0.95, description="Target acceptance rate (0.80-0.95)"),
):
    """
    Calculate safe bid prices that guarantee high acceptance rate.

    Strategy: Bid below market average to maximize activation frequency.
    For batteries with capacity constraints (900 MWh/month), utilization
    matters more than price per MWh.

    Target Acceptance Rates:
    - 0.95 (95%): Ultra-safe, almost guaranteed acceptance
    - 0.90 (90%): Conservative, very high acceptance probability
    - 0.85 (85%): Moderate-safe, good balance
    - 0.80 (80%): Balanced, standard acceptance rate

    Returns:
    - Safe bid prices for capacity and activation
    - Expected annual revenue with safe bidding
    - Comparison vs aggressive bidding strategy
    - Market context (avg prices, percentiles)
    """
    try:
        result = fr_service.calculate_safe_bid_prices(
            power_mw=power_mw,
            target_acceptance_rate=target_acceptance,
        )
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
