"""
Investment & Financial Analysis API Routes
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.investment import (
    InvestmentParams,
    InvestmentComparisonResponse,
    FinancingBreakdown,
)
from app.services.investment_service import InvestmentService
from app.services.sensitivity import SensitivityConfig, SensitivityReport

router = APIRouter()
investment_service = InvestmentService()


class SensitivityRequest(BaseModel):
    """Combined params + Monte Carlo config for /sensitivity."""
    params: InvestmentParams
    config: SensitivityConfig = Field(default_factory=SensitivityConfig)


@router.post("/analyze", response_model=InvestmentComparisonResponse)
async def analyze_investment(params: InvestmentParams):
    """Run investment analysis comparing FR vs PZU scenarios"""
    try:
        return investment_service.analyze(params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/financing", response_model=FinancingBreakdown)
async def calculate_financing(params: InvestmentParams):
    """Calculate financing breakdown"""
    try:
        return investment_service.calculate_financing(params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cashflow")
async def project_cashflow(params: InvestmentParams, scenario: str = "fr"):
    """Project annual cashflow for a scenario"""
    try:
        result = investment_service.analyze(params)
        if scenario.lower() == "fr":
            return {"scenario": "FR", "cashflow": result.fr_cashflow}
        elif scenario.lower() == "pzu":
            return {"scenario": "PZU", "cashflow": result.pzu_cashflow}
        else:
            raise HTTPException(status_code=400, detail="Scenario must be 'fr' or 'pzu'")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sensitivity", response_model=SensitivityReport)
async def run_sensitivity(request: SensitivityRequest):
    """Phase F1: Monte Carlo over activation share / RTE / degradation /
    PZU spread / FX. Returns P10/P50/P90 IRR, NPV, payback + raw IRR samples.
    """
    try:
        return investment_service.run_sensitivity(request.params, request.config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/defaults")
async def get_default_params():
    """Get default investment parameters.

    Delegates to InvestmentService.get_defaults() which carries the canonical
    Romanian vendor anchor (€175/kWh = €3.5M for 10 MW / 20 MWh, Huawei),
    Romanian-vendor and European-typical CAPEX bands, and the audit reference.
    """
    return investment_service.get_defaults()
