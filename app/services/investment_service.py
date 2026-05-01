"""
Investment & Financial Analysis Service

Audit fixes (Agent 1 High; Agent 5 Critical/High):
- Fail-closed error handling: silent ``except Exception: pass`` blocks replaced
  with specific exception capture into a ``warnings`` accumulator. Unexpected
  exceptions propagate (5xx) instead of producing fake ROI numbers.
- Cashflow now degrades revenue and inflates OPEX year-over-year.
- Provenance / confidence labels surfaced on every ScenarioResult and the
  comparison response, plus an ``excluded_from_model`` disclosure list.

Phase D (gap audit 2026-05-01) — physical realism in cashflow:
- D3: throughput-warranty + augmentation CAPEX at year 5 + 10.
- D4: HVAC/BMS/fire-suppression auxiliary load consumes parasitic energy.
- D6: capacity_factor = 1 − calendar_fade(year) − cycle_fade(cumulative_efc).
- D7: self-discharge already accounted for via FR-side capacity factor.

Phase F (gap audit 2026-05-01) — risk + bankability:
- F2: per-year DSCR = CFADS / debt_service; flag years where DSCR < 1.20.
- F3: FX hedge cost on RON-denominated revenue.
"""
import math
from typing import Any, Dict, List

from app.models.fr import FRSimulationParams
from app.models.investment import (
    AnnualCashflow,
    FinancingBreakdown,
    InvestmentComparisonResponse,
    InvestmentParams,
    ScenarioResult,
)
from app.models.pzu import PZUSimulationParams
from app.services.fr_service import FRService
from app.services.pzu_service import PZUService
from app.services.sensitivity import SensitivityConfig, SensitivityReport, monte_carlo
from app.services.warranty_tracker import WarrantyConfig, track_throughput


class InvestmentService:
    """Service for investment and financial analysis"""

    def __init__(self):
        self.pzu_service = PZUService()
        self.fr_service = FRService()

    def calculate_financing(self, params: InvestmentParams) -> FinancingBreakdown:
        """Calculate financing structure"""
        equity = params.total_investment_eur * (params.equity_percentage / 100)
        debt = params.total_investment_eur - equity

        if debt > 0 and params.loan_term_years > 0:
            monthly_rate = (params.loan_interest_rate / 100) / 12
            num_payments = params.loan_term_years * 12

            if monthly_rate > 0:
                monthly_payment = debt * (monthly_rate * (1 + monthly_rate)**num_payments) / ((1 + monthly_rate)**num_payments - 1)
            else:
                monthly_payment = debt / num_payments

            annual_debt_service = monthly_payment * 12
            total_interest = (monthly_payment * num_payments) - debt
        else:
            annual_debt_service = 0
            monthly_payment = 0
            total_interest = 0

        return FinancingBreakdown(
            total_investment_eur=params.total_investment_eur,
            equity_eur=equity,
            equity_percentage=params.equity_percentage,
            debt_eur=debt,
            debt_percentage=100 - params.equity_percentage,
            annual_debt_service_eur=annual_debt_service,
            monthly_debt_service_eur=monthly_payment,
            total_interest_paid_eur=total_interest,
        )

    def _get_fr_annual_revenue(self, params: InvestmentParams) -> Dict[str, Any]:
        """Get estimated annual FR revenue.

        Fail-closed: catches only known data/lookup errors and falls back to
        a conservative estimate, while populating ``warnings`` and tagging
        ``revenue_source``. Unexpected exceptions propagate so the API
        returns 5xx instead of fake numbers.
        """
        warnings: List[str] = []
        try:
            fr_params = FRSimulationParams(
                capacity_mwh=params.capacity_mwh,
                afrr_up={"enabled": True, "power_mw": params.power_mw},
                afrr_down={"enabled": True, "power_mw": params.power_mw},
            )
            result = self.fr_service.simulate(fr_params)

            months = len(set(r.month for r in result.monthly_results))
            if months > 0:
                annual_factor = 12 / months
                return {
                    "gross_revenue": result.total_revenue_eur * annual_factor,
                    "energy_cost": result.total_energy_cost_eur * annual_factor,
                    "revenue_source": "simulation",
                    "warnings": warnings,
                }
            warnings.append("FR simulation returned no months; using fallback estimate.")
        except (FileNotFoundError, ValueError, KeyError) as exc:
            warnings.append(f"FR simulation failed ({type(exc).__name__}: {exc}); using fallback estimate.")

        # Conservative fallback (5 EUR/MW/h, 30% activation, 40% energy cost ratio)
        capacity_revenue = params.power_mw * 5 * 8760
        activation_revenue = capacity_revenue * 0.3
        gross_revenue = capacity_revenue + activation_revenue
        energy_cost = activation_revenue * 0.4

        return {
            "gross_revenue": gross_revenue,
            "energy_cost": energy_cost,
            "revenue_source": "fallback_estimate",
            "warnings": warnings,
        }

    def _get_pzu_annual_revenue(self, params: InvestmentParams) -> Dict[str, Any]:
        """Get estimated annual PZU revenue

        PZU arbitrage model:
        - Gross Revenue = sell price × energy discharged
        - Energy Cost = buy price × energy charged
        - Net Profit = Gross Revenue - Energy Cost (what PZU service returns)

        We reconstruct the breakdown from monthly data.
        """
        warnings: List[str] = []
        try:
            pzu_params = PZUSimulationParams(
                power_mw=params.power_mw,
                capacity_mwh=params.capacity_mwh,
            )
            result = self.pzu_service.simulate(pzu_params)

            months = len(result.monthly_results)
            if months > 0:
                annual_factor = 12 / months

                # Calculate energy cost from monthly buy prices
                # PZU uses 2-hour blocks, 1 cycle per day
                block_hours = 2
                efficiency = pzu_params.round_trip_efficiency

                total_energy_cost = 0
                total_gross_revenue = 0

                for m in result.monthly_results:
                    # Energy charged per day = power × block_hours
                    energy_per_day = params.power_mw * block_hours

                    # Monthly charge cost (buy price × energy × days)
                    charge_cost = m.avg_buy_price_eur_mwh * energy_per_day * m.days

                    # Monthly discharge revenue (sell price × energy × efficiency × days)
                    discharge_revenue = m.avg_sell_price_eur_mwh * energy_per_day * efficiency * m.days

                    total_energy_cost += charge_cost
                    total_gross_revenue += discharge_revenue

                return {
                    "gross_revenue": total_gross_revenue * annual_factor,
                    "energy_cost": total_energy_cost * annual_factor,
                    "revenue_source": "simulation",
                    "warnings": warnings,
                }
            warnings.append("PZU simulation returned no months; using fallback estimate.")
        except (FileNotFoundError, ValueError, KeyError) as exc:
            warnings.append(f"PZU simulation failed ({type(exc).__name__}: {exc}); using fallback estimate.")

        # Fallback: estimate based on typical Romanian market
        # Assume avg buy ~60 EUR/MWh, avg sell ~110 EUR/MWh, 88% efficiency
        block_hours = 2
        energy_per_day = params.power_mw * block_hours
        days_per_year = 365

        avg_buy_price = 60  # EUR/MWh
        avg_sell_price = 110  # EUR/MWh
        efficiency = 0.88

        annual_charge_cost = avg_buy_price * energy_per_day * days_per_year
        annual_discharge_revenue = avg_sell_price * energy_per_day * efficiency * days_per_year

        return {
            "gross_revenue": annual_discharge_revenue,
            "energy_cost": annual_charge_cost,
            "revenue_source": "fallback_estimate",
            "warnings": warnings,
        }

    def _create_scenario_result(
        self,
        name: str,
        revenue: Dict[str, Any],
        operating_cost: float,
        annual_debt_service: float,
        equity: float,
    ) -> ScenarioResult:
        """Create scenario result with metrics + provenance fields."""
        gross_revenue = float(revenue["gross_revenue"])
        energy_cost = float(revenue["energy_cost"])
        net_profit = gross_revenue - energy_cost - operating_cost - annual_debt_service
        revenue_source = revenue.get("revenue_source", "simulation")
        warnings = list(revenue.get("warnings", []))

        # Confidence labelling matches the FR service convention.
        if revenue_source == "fallback_estimate":
            pricing_basis = "scenario"
            confidence_label = "Scenario (fallback estimate)"
        else:
            pricing_basis = "public_marginal"
            confidence_label = "Public-data / Participant-only-for-bankability"

        return ScenarioResult(
            name=name,
            gross_revenue_eur=gross_revenue,
            energy_cost_eur=energy_cost,
            operating_cost_eur=operating_cost,
            annual_debt_service_eur=annual_debt_service,
            net_profit_after_debt_eur=net_profit,
            roi_percentage=(net_profit / equity * 100) if equity > 0 else 0,
            payback_years=equity / net_profit if net_profit > 0 else float("inf"),
            profit_margin_percentage=(net_profit / gross_revenue * 100) if gross_revenue > 0 else 0,
            pricing_basis=pricing_basis,
            confidence_label=confidence_label,
            revenue_source=revenue_source,
            warnings=warnings,
        )

    def _create_cashflow(
        self,
        years: int,
        gross_revenue_y1: float,
        energy_cost_y1: float,
        operating_cost_y1: float,
        annual_debt_service: float,
        params: InvestmentParams,
        epc_eur: float = 0.0,
    ) -> List[AnnualCashflow]:
        """Annual cashflow with realistic Phase-D physics + Phase-F covenants.

        Year-over-year drivers:
          - **Capacity factor (D6):** ``1 - calendar_fade - cycle_fade``.
            ``calendar_fade = 0.025 + 0.015 × (year - 1)`` (year 1 = 0.025);
            ``cycle_fade = cycle_fade_per_efc × cumulative_efc``.
          - **OPEX inflation:** geometric ``(1 + infl)^(year-1)`` on Y1 OPEX.
          - **Aux load (D4):** ``aux_mw × 8760 × availability / sqrt(eta) × pzu_price``
            charged as parasitic energy each year.
          - **Warranty (D3):** ``cumulative_efc`` tracked against vendor budget;
            augmentation CAPEX added in configured years.
          - **DSCR (F2):** ``CFADS = ebitda``; ``DSCR = CFADS / debt_service``.
          - **FX hedge (F3):** if ``revenue_currency == 'RON'``, deduct
            ``fx_hedge_cost_pct``% of gross revenue per year.
        """
        cashflow: List[AnnualCashflow] = []
        cumulative = 0.0
        infl = float(params.opex_inflation_pct) / 100.0
        availability = max(0.0, min(float(params.availability_pct) / 100.0, 1.0))
        sqrt_eta = math.sqrt(max(float(params.rte_ac_ac), 1e-9))

        # D4 parasitic auxiliary draw (annual MWh ≈ aux_mw × 8760 × availability).
        aux_energy_mwh_per_year = float(params.auxiliary_load_mw) * 8760.0 * availability
        aux_cost_per_year_y1 = (
            aux_energy_mwh_per_year / sqrt_eta * float(params.avg_pzu_price_eur_mwh_for_aux)
        )

        # D3 warranty config from params.
        warranty_cfg = WarrantyConfig(
            efc_budget=int(params.efc_budget),
            warranty_years=int(params.warranty_years),
            augmentation_cost_pct_of_epc=float(params.augmentation_pct_of_epc),
            augmentation_years=[5, 10],
        )

        # F3 FX hedge.
        fx_hedge_rate = (
            float(params.fx_hedge_cost_pct) / 100.0
            if params.revenue_currency == "RON"
            else 0.0
        )

        cumulative_efc = 0.0
        for year in range(1, years + 1):
            # D6 calendar + cycle fade.
            calendar_fade = 0.025 + 0.015 * (year - 1)
            cycle_fade = float(params.cycle_fade_per_efc) * cumulative_efc
            capacity_factor = max(0.0, 1.0 - calendar_fade - cycle_fade)
            opex_factor = (1.0 + infl) ** (year - 1)

            gross_revenue = gross_revenue_y1 * capacity_factor
            energy_cost = energy_cost_y1 * capacity_factor
            operating_cost = operating_cost_y1 * opex_factor

            # D4 aux cost — also inflates with OPEX (energy prices grow ~ inflation).
            auxiliary_cost = aux_cost_per_year_y1 * opex_factor

            # F3 FX hedge cost (only when revenue is in RON).
            fx_hedge_cost = gross_revenue * fx_hedge_rate

            # D3 warranty step. Annual EFC scales with capacity (cycles drop as
            # the battery fades), so the warranty exhausts more slowly.
            annual_efc = float(params.annual_efc_assumption) * capacity_factor
            warranty_step = track_throughput(
                annual_efc=annual_efc,
                year=year,
                cumulative_efc=cumulative_efc,
                epc_eur=epc_eur,
                cfg=warranty_cfg,
            )
            cumulative_efc = warranty_step["cumulative_efc"]
            augmentation_cost = warranty_step["augmentation_cost_eur"]
            warranty_status = "exceeded" if warranty_step["warranty_exceeded"] else "ok"

            ebitda = (
                gross_revenue
                - energy_cost
                - operating_cost
                - auxiliary_cost
                - fx_hedge_cost
            )
            # Augmentation hits as a one-off CAPEX outflow; not part of EBITDA.
            net = ebitda - annual_debt_service - augmentation_cost
            cumulative += net

            # F2 DSCR — CFADS divided by debt service.
            cfads = ebitda
            dscr = (cfads / annual_debt_service) if annual_debt_service > 0 else 0.0

            cashflow.append(AnnualCashflow(
                year=year,
                gross_revenue_eur=gross_revenue,
                energy_cost_eur=energy_cost,
                operating_cost_eur=operating_cost,
                debt_service_eur=annual_debt_service,
                net_profit_eur=net,
                cumulative_profit_eur=cumulative,
                auxiliary_cost_eur=auxiliary_cost,
                augmentation_cost_eur=augmentation_cost,
                cumulative_efc=cumulative_efc,
                warranty_status=warranty_status,
                calendar_fade=calendar_fade,
                cycle_fade=cycle_fade,
                capacity_factor=capacity_factor,
                cfads_eur=cfads,
                dscr=dscr,
                fx_hedge_cost_eur=fx_hedge_cost,
            ))

        return cashflow

    def analyze(self, params: InvestmentParams) -> InvestmentComparisonResponse:
        """Run complete investment analysis (fail-closed + degraded cashflow)."""
        financing = self.calculate_financing(params)

        operating_cost = params.total_investment_eur * (params.opex_percentage / 100)
        operating_cost += params.total_investment_eur * (params.insurance_percentage / 100)

        fr_revenue = self._get_fr_annual_revenue(params)
        pzu_revenue = self._get_pzu_annual_revenue(params)

        fr_scenario = self._create_scenario_result(
            "FR",
            fr_revenue,
            operating_cost,
            financing.annual_debt_service_eur,
            financing.equity_eur,
        )

        pzu_scenario = self._create_scenario_result(
            "PZU",
            pzu_revenue,
            operating_cost,
            financing.annual_debt_service_eur,
            financing.equity_eur,
        )

        # Create cashflow projections.
        # Phase D3 augmentation lands at year 5 + 10, so always project at
        # least 10 years (or warranty_years, whichever is larger) so the
        # warranty schedule is visible to investors.
        projection_years = max(params.loan_term_years, 10, params.warranty_years)
        # EPC anchor for augmentation cost. We treat ``total_investment_eur``
        # as EPC (battery + PCS + transformer + SCADA) — additional CAPEX
        # lines (grid connection, permitting) live outside the simulator.
        epc_eur = float(params.total_investment_eur)

        fr_cashflow = self._create_cashflow(
            projection_years,
            fr_revenue["gross_revenue"],
            fr_revenue["energy_cost"],
            operating_cost,
            financing.annual_debt_service_eur,
            params=params,
            epc_eur=epc_eur,
        )

        pzu_cashflow = self._create_cashflow(
            projection_years,
            pzu_revenue["gross_revenue"],
            pzu_revenue["energy_cost"],
            operating_cost,
            financing.annual_debt_service_eur,
            params=params,
            epc_eur=epc_eur,
        )

        recommended = "FR" if fr_scenario.net_profit_after_debt_eur > pzu_scenario.net_profit_after_debt_eur else "PZU"
        advantage = abs(fr_scenario.net_profit_after_debt_eur - pzu_scenario.net_profit_after_debt_eur)
        min_profit = min(fr_scenario.net_profit_after_debt_eur, pzu_scenario.net_profit_after_debt_eur)

        # Top-level warnings = union of per-scenario warnings
        top_warnings = list(fr_scenario.warnings) + list(pzu_scenario.warnings)

        # F2 DSCR violation years (DSCR < 1.20 covenant) — union across scenarios.
        DSCR_COVENANT = 1.20
        dscr_violations: List[int] = sorted({
            cf.year
            for cf in (*fr_cashflow, *pzu_cashflow)
            if cf.debt_service_eur > 0 and 0 < cf.dscr < DSCR_COVENANT
        })
        if dscr_violations:
            top_warnings.append(
                f"DSCR < {DSCR_COVENANT:.2f} in years {dscr_violations} — "
                f"lender covenant breached. Consider lower gearing or longer tenor."
            )

        return InvestmentComparisonResponse(
            params=params,
            financing=financing,
            fr_scenario=fr_scenario,
            pzu_scenario=pzu_scenario,
            recommended_scenario=recommended,
            advantage_eur=advantage,
            advantage_percentage=(advantage / min_profit * 100) if min_profit > 0 else 0,
            fr_cashflow=fr_cashflow,
            pzu_cashflow=pzu_cashflow,
            warnings=top_warnings,
            dscr_violation_years=dscr_violations,
        )

    def run_sensitivity(
        self,
        params: InvestmentParams,
        cfg: SensitivityConfig,
    ) -> SensitivityReport:
        """Phase F1 entrypoint — Monte Carlo over the deterministic engine.

        Reuses ``_get_fr_annual_revenue`` / ``_get_pzu_annual_revenue`` for the
        Y1 baseline so the sensitivity is anchored on the same simulator the
        deterministic ROI uses.
        """
        financing = self.calculate_financing(params)
        operating_cost = (
            params.total_investment_eur * (params.opex_percentage / 100.0)
            + params.total_investment_eur * (params.insurance_percentage / 100.0)
        )
        fr_revenue = self._get_fr_annual_revenue(params)
        pzu_revenue = self._get_pzu_annual_revenue(params)

        return monte_carlo(
            params=params,
            fr_revenue_y1=fr_revenue,
            pzu_revenue_y1=pzu_revenue,
            operating_cost_y1=operating_cost,
            annual_debt_service=financing.annual_debt_service_eur,
            equity_eur=financing.equity_eur,
            cfg=cfg,
            create_cashflow=self._create_cashflow,
        )

    def get_defaults(self) -> Dict[str, Any]:
        """Canonical Romanian BESS investment defaults.

        Anchored on the user's actual quote: **€3.5M total install cost for
        10 MW / 20 MWh** = €175/kWh installed = €350,000/MW. Both apps
        (Streamlit + battery-analytics-pro) use this as the canonical sizing.
        Bands €150 / €175 / €250 per kWh reflect realistic 2024-2026 RO
        market prices.
        """
        capacity_mwh = 20.0
        power_mw = 10.0
        canonical_capex_per_kwh = 175.0
        return {
            "power_mw": power_mw,
            "capacity_mwh": capacity_mwh,
            "capex_per_kwh": canonical_capex_per_kwh,
            "capex_per_mw": canonical_capex_per_kwh * (capacity_mwh / power_mw) * 1000.0,
            "capex_per_kwh_band": {"low": 150.0, "mid": 175.0, "high": 250.0},
            "total_investment_eur": canonical_capex_per_kwh * capacity_mwh * 1000.0,  # = €3,500,000
            "equity_percentage": 50,             # 50/50 debt-to-equity (Romanian BESS norm)
            "loan_interest_rate": 6.0,
            "loan_term_years": 10,
            "opex_percentage": 2.0,
            "insurance_percentage": 0.5,
            "vendor_quote_anchor": {
                "vendor": "Sermatec",
                "quote_eur": 3_500_000.0,
                "power_mw": 10.0,
                "capacity_mwh": 20.0,
                "eur_per_kwh": 175.0,
            },
            "confidence_label": "Likely-source / Scenario",
            "audit_reference": "audit/ROMANIAN_BESS_AUDIT_RISK_INVESTIGATION_2026-05-01.md",
        }
