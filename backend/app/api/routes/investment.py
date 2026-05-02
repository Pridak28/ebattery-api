"""
Investment & Financial Analysis API Routes
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.investment import (
    InvestmentParams,
    InvestmentComparisonResponse,
    FinancingBreakdown,
    InvestorSummary,
)
from app.services.investment_service import InvestmentService
from app.services.sensitivity import SensitivityConfig, SensitivityReport
from app.services.tariff_exemption import (
    TariffExemptionRequest,
    TariffExemptionResult,
    compute_tariff_exemption,
)

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


@router.post("/investor-summary", response_model=InvestorSummary)
async def get_investor_summary(params: InvestmentParams):
    """One-page summary for external integrations (PDF/email/lender).

    Consolidates analysis output into the flat structure used by the
    investor Quick-Look page; no need to navigate fr_cashflow / pzu_cashflow
    separately.
    """
    try:
        return investment_service.build_investor_summary(params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tariff-exemption", response_model=TariffExemptionResult)
async def tariff_exemption(req: TariffExemptionRequest):
    """B3: Stored-energy tariff exemption (Law 123 Art. 66³ + ANRE Order 56/2025).

    Returns avoided regulated charges (transmission Tl/Tg, distribution Td,
    system services, green certificate, cogeneration) on the annual round-trip
    throughput. Treat as AVOIDED COST (regulatory benefit), not gross market
    revenue. Eligibility is conditional on the metering qualification gate.
    """
    try:
        return compute_tariff_exemption(req)
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
