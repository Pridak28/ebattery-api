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
from app.services.scenario_engine import (
    ScenarioInputs,
    SCENARIO_DEFAULTS,
    analyze_all_scenarios,
)
from app.services.sensitivity import SensitivityConfig, SensitivityReport
from app.services.tariff_exemption import (
    TariffExemptionRequest,
    TariffExemptionResult,
    compute_tariff_exemption,
)

router = APIRouter()
investment_service = InvestmentService()


# ===================================================================
#  Scenario engine — Romanian aFRR + PZU stacked, with realistic drag
# ===================================================================
class ScenariosRequest(BaseModel):
    """Optional inputs for the scenario engine. All fields default to the
    canonical 10 MW / 20 MWh / €3.5M / 30-70 financing setup."""
    epc_eur: float | None = Field(None, description="EPC investment €")
    power_mw: float | None = Field(None, description="Battery power MW")
    capacity_mwh: float | None = Field(None, description="Battery capacity MWh")
    equity_pct: float | None = Field(None, description="Equity % of EPC")
    loan_pct: float | None = Field(None, description="Debt % of EPC")
    loan_rate: float | None = Field(None, description="Loan interest rate (decimal)")
    loan_term_yr: int | None = Field(None, description="Loan tenor years")
    tax_rate: float | None = Field(None, description="Corporate tax rate (decimal)")
    discount_rate: float | None = Field(None, description="NPV discount rate (decimal)")
    # Stacking — physical hardware constraint
    stack_afrr_capacity: float | None = Field(None, description="aFRR capacity stacking factor (0..1)")
    stack_afrr_activation: float | None = Field(None, description="aFRR activation stacking factor (0..1)")
    stack_pzu: float | None = Field(None, description="PZU stacking factor (0..1)")
    # Operator drag — applied to realistic view only
    drag_afrr_capacity: float | None = Field(None, description="aFRR capacity operator drag (0..1)")
    drag_afrr_activation: float | None = Field(None, description="aFRR activation operator drag (0..1)")
    drag_pzu: float | None = Field(None, description="PZU operator drag (0..1)")
    # Scenario selection (default: all 4)
    scenario_keys: list[str] | None = Field(
        None,
        description="Subset of A_current / B_picasso / C_mature / D_bear. Omit for all 4."
    )

    def to_inputs(self) -> ScenarioInputs:
        defaults = ScenarioInputs()
        kwargs = {}
        for f in (
            "epc_eur", "power_mw", "capacity_mwh", "equity_pct", "loan_pct",
            "loan_rate", "loan_term_yr", "tax_rate", "discount_rate",
            "stack_afrr_capacity", "stack_afrr_activation", "stack_pzu",
            "drag_afrr_capacity", "drag_afrr_activation", "drag_pzu",
        ):
            v = getattr(self, f)
            if v is not None:
                kwargs[f] = v
        return ScenarioInputs(**{**defaults.__dict__, **kwargs})


@router.post("/scenarios")
async def analyze_scenarios(request: ScenariosRequest = ScenariosRequest()):
    """Run the 4 PICASSO / market-share scenarios with full project finance:
    stacking, operator drag, tax (16% RO), 8-yr depreciation, loan
    amortization, DSCR/LLCR/PLCR. Returns BOTH modeled (engineering
    optimum) AND realistic (lender-grade) views per scenario.

    Mirrors `scripts/bess_cashflow_scenarios_excel.py` so the Investment
    page in the frontend shows the same numbers as the offline Excel.
    """
    try:
        inputs = request.to_inputs()
        return analyze_all_scenarios(inputs, request.scenario_keys)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/scenarios/defaults")
async def get_scenario_defaults():
    """Return the 4 scenario definitions (Y1 base values + compression
    curves + descriptions) so the frontend can render the scenario list
    without re-computing."""
    return {
        "scenarios": [
            {"key": k, **{kk: v for kk, v in defs.items()
                          if kk in ("label", "color", "description",
                                    "afrr_capacity_y1", "afrr_activation_y1", "pzu_y1")}}
            for k, defs in SCENARIO_DEFAULTS.items()
        ],
    }


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
