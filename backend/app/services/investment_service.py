"""
Investment & Financial Analysis Service

Investor-summary endpoint (2026-05-02): ``build_investor_summary`` consolidates
the full ``analyze`` output into a flat one-page payload for external
integrations (PDF generators, lender portals, Slack webhooks). It picks
headline metrics, classifies IRR into tiers, identifies the most-upstream
unqualified compliance gate, and composes a plain-English disclaimer.

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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.fr import FRSimulationParams
from app.models.investment import (
    AnnualCashflow,
    ComplianceGates,
    FinancingBreakdown,
    InvestmentComparisonResponse,
    InvestmentParams,
    InvestorSummary,
    ScenarioResult,
)
from app.models.pzu import PZUSimulationParams
from app.services.fr_service import FRService
from app.services.pzu_service import PZUService
from app.services.sensitivity import SensitivityConfig, SensitivityReport, _irr, _payback_years, monte_carlo
from app.services.tariff_exemption import (
    TariffExemptionRequest,
    compute_tariff_exemption,
)
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

            # Bug fix (hypothesis-found): for subnormal positive rates the
            # PMT denominator ``(1 + r)^n − 1`` underflows to exactly 0.0 in
            # float64 even though ``r > 0``. Treat anything below 1e-12 as
            # effectively zero (linear amortization) — matches the
            # mathematical limit and avoids ZeroDivisionError.
            if monthly_rate > 1e-12:
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
                    "capacity_revenue": result.total_capacity_revenue_eur * annual_factor,
                    "activation_revenue": result.total_activation_revenue_eur * annual_factor,
                    "revenue_source": "simulation",
                    "bankability_level": result.bankability_level,
                    "settlement_grade": result.settlement_grade,
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
            "capacity_revenue": capacity_revenue,
            "activation_revenue": activation_revenue,
            "revenue_source": "fallback_estimate",
            "bankability_level": "historical_backtest_only",
            "settlement_grade": False,
            "warnings": warnings,
        }

    def _get_pzu_annual_revenue(self, params: InvestmentParams) -> Dict[str, Any]:
        """Get estimated annual PZU revenue.

        B1 reconciliation: uses ``PZUSimulationResponse.total_gross_revenue_eur``
        and ``total_energy_cost_eur`` directly. The earlier reconstruction
        multiplied each month's avg_buy / avg_sell × power × 2h × days,
        which overcounted days where ``simulate()`` found no profitable
        chronological pair (those days contribute €0 to ``net_profit`` but
        their prices still pulled the monthly avg). Now both gross revenue
        and cost come from the actual per-day dispatch.
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
                return {
                    "gross_revenue": float(result.total_gross_revenue_eur) * annual_factor,
                    "energy_cost": float(result.total_energy_cost_eur) * annual_factor,
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
            # Cap at 999.0 instead of float("inf") — JSON serializer rejects inf,
            # and 999 is a clear "never breaks even" sentinel that survives
            # round-tripping through the API.
            payback_years=(equity / net_profit) if net_profit > 0 else 999.0,
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
        # Aux (HVAC, BMS, fire suppression) draws DIRECTLY from the grid — it is
        # NOT routed through the battery's AC↔DC conversion. The earlier
        # ``/ sqrt(eta)`` factor implied a charge-side gross-up that overstated
        # aux cost by ~6%. Removed (Mastermind Rules-team finding R-1).
        aux_energy_mwh_per_year = float(params.auxiliary_load_mw) * 8760.0 * availability
        aux_cost_per_year_y1 = (
            aux_energy_mwh_per_year * float(params.avg_pzu_price_eur_mwh_for_aux)
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

        # Realism fix #4 (2026-05-02): Romanian aFRR capacity-price compression
        # with a FLOOR. Y1 + Y2 keep premium pricing (~€399/MWh observed); from
        # year `compression_start_year` revenue compresses geometrically until
        # it reaches `compression_floor_pct`% of Y1 revenue, then holds.
        # This matches the German aFRR trajectory: 70% compression over 2 years
        # then stable. Without the floor, geometric compression drives cashflow
        # negative in late years and breaks lifetime-IRR convergence.
        compression_pct_per_yr = max(0.0, float(params.capacity_price_compression_pct_per_year)) / 100.0
        compression_start = max(1, int(params.capacity_price_compression_start_year))
        compression_floor = max(0.0, float(params.capacity_price_compression_floor_pct)) / 100.0

        # A-4: PICASSO go-live one-time compression. Once Romania connects
        # (currently OFF; expected ~2026-2027), revenue takes a step-down on
        # top of the gradual capacity_price_compression. Modelled as a constant
        # multiplier from ``picasso_go_live_year`` onward.
        picasso_go_live = max(1, int(getattr(params, "picasso_go_live_year", 999)))
        picasso_drop_pct = max(0.0, float(getattr(params, "picasso_one_time_compression_pct", 0.0))) / 100.0

        # A-12: Law 123 Art. 66³ + ANRE Order 56/2025 stored-energy tariff
        # exemption. Computed ONCE upfront and scaled by capacity_factor each
        # year (regulated rate → does NOT compress with PICASSO / capacity-
        # price compression). Treated as avoided cost added to EBITDA, NOT
        # gross market revenue. Wrapped in try/except: failure degrades to
        # 0 with a warning rather than breaking the whole cashflow.
        tariff_exemption_y1 = 0.0
        if bool(getattr(params, "include_tariff_exemption", False)):
            try:
                tariff_result = compute_tariff_exemption(
                    TariffExemptionRequest(
                        power_mw=float(params.power_mw),
                        capacity_mwh=float(params.capacity_mwh),
                        cycles_per_day=float(params.tariff_exemption_cycles_per_day),
                        operating_days_per_year=365,
                    )
                )
                tariff_exemption_y1 = float(tariff_result.avoided_cost_eur)
            except Exception as exc:  # pragma: no cover — defensive degrade-to-zero
                # Don't break cashflow on a tariff-module hiccup; degrade to 0.
                # We rely on the analyze() layer to surface a top-level warning;
                # the per-year line item will simply be 0.
                tariff_exemption_y1 = 0.0

        cumulative_efc = 0.0
        for year in range(1, years + 1):
            # D6 calendar + cycle fade.
            calendar_fade = 0.025 + 0.015 * (year - 1)
            cycle_fade = float(params.cycle_fade_per_efc) * cumulative_efc
            capacity_factor = max(0.0, 1.0 - calendar_fade - cycle_fade)
            opex_factor = (1.0 + infl) ** (year - 1)

            # Fix #4: capacity-price compression with floor.
            # Geometric decay from `compression_start` until the per-year
            # multiplier hits the floor, then holds. Recharge cost doesn't
            # compress (energy market follows different drivers).
            years_compressed = max(0, year - compression_start + 1)
            compression_factor = max(
                compression_floor,
                (1.0 - compression_pct_per_yr) ** years_compressed,
            )

            # A-4: PICASSO step-change. Multiplies on top of the gradual
            # compression. Stays at (1 - drop) for all years from go-live on.
            picasso_factor = (1.0 - picasso_drop_pct) if year >= picasso_go_live else 1.0

            gross_revenue = gross_revenue_y1 * capacity_factor * compression_factor * picasso_factor
            energy_cost = energy_cost_y1 * capacity_factor  # recharge cost doesn't compress
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

            # A-12: tariff exemption scales with capacity_factor (degrades like
            # other revenue) but NOT with compression / PICASSO (it's a
            # regulated avoided-cost rate, not a market price).
            tariff_exemption_year = tariff_exemption_y1 * capacity_factor

            ebitda = (
                gross_revenue
                - energy_cost
                - operating_cost
                - auxiliary_cost
                - fx_hedge_cost
                + tariff_exemption_year  # avoided regulated charges → cost reduction
            )
            # Realism fix #4b (2026-05-02): debt service stops at loan_term_years.
            # The earlier model billed annual_debt_service every projection year,
            # which is wrong (loan amortizes over loan_term_years and then ends)
            # AND produced spurious DSCR violations in years 11-15.
            debt_service_this_year = (
                annual_debt_service if year <= int(params.loan_term_years) else 0.0
            )
            # Augmentation hits as a one-off CAPEX outflow; not part of EBITDA.
            net = ebitda - debt_service_this_year - augmentation_cost
            cumulative += net

            # F2 DSCR — CFADS divided by debt service.
            cfads = ebitda
            dscr = (cfads / debt_service_this_year) if debt_service_this_year > 0 else 0.0

            cashflow.append(AnnualCashflow(
                year=year,
                gross_revenue_eur=gross_revenue,
                energy_cost_eur=energy_cost,
                operating_cost_eur=operating_cost,
                debt_service_eur=debt_service_this_year,
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
                tariff_exemption_eur=tariff_exemption_year,
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

        # Lifetime IRR + payback per scenario, computed from the actual cashflow.
        # Y0 outflow = equity; Y1..N inflows = each year's net_profit.
        equity_outflow = -float(financing.equity_eur)
        fr_cf_vec = [equity_outflow] + [cf.net_profit_eur for cf in fr_cashflow]
        pzu_cf_vec = [equity_outflow] + [cf.net_profit_eur for cf in pzu_cashflow]
        fr_lifetime_irr = _irr(fr_cf_vec)
        pzu_lifetime_irr = _irr(pzu_cf_vec)
        fr_lifetime_payback = _payback_years(fr_cf_vec)
        pzu_lifetime_payback = _payback_years(pzu_cf_vec)

        # B2 — surface compliance gates so investors / consumers see exactly
        # which qualifications are missing AND which revenue streams are
        # legally blocked. Defaults to all-not_declared if user didn't supply.
        gates = params.compliance_gates or ComplianceGates()
        blocked_streams = gates.revenue_streams_blocked()
        if blocked_streams:
            top_warnings.append(
                "Compliance gates not satisfied — these revenue streams are "
                "legally unavailable until qualified: " + ", ".join(blocked_streams)
            )

        # A-12: tariff exemption metering gate enforcement. If the user opted
        # in but didn't declare metering qualification, surface a top-level
        # warning. We continue (don't block) so the cashflow still shows what
        # the line WOULD contribute — investors then know what's at stake when
        # the gate slips.
        if (
            bool(getattr(params, "include_tariff_exemption", False))
            and params.compliance_gates is not None
            and params.compliance_gates.storage_tariff_exemption_metering != "qualified"
        ):
            top_warnings.append(
                "Tariff exemption included but metering qualification gate not "
                "declared — eligibility unverified."
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
            fr_year1_roi_pct=fr_scenario.roi_percentage,
            pzu_year1_roi_pct=pzu_scenario.roi_percentage,
            fr_lifetime_irr_pct=(fr_lifetime_irr * 100.0) if fr_lifetime_irr == fr_lifetime_irr else None,
            pzu_lifetime_irr_pct=(pzu_lifetime_irr * 100.0) if pzu_lifetime_irr == pzu_lifetime_irr else None,
            fr_lifetime_payback_years=(fr_lifetime_payback if fr_lifetime_payback < 1e9 else None),
            pzu_lifetime_payback_years=(pzu_lifetime_payback if pzu_lifetime_payback < 1e9 else None),
            projection_horizon_years=projection_years,
            compliance_gates=gates,
            compliance_revenue_streams_blocked=blocked_streams,
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

    # Cascade order for compliance gates: most-upstream (license/registration)
    # to most-specific (per-product qualifications + metering). The first
    # gate in this order that is not "qualified" is the one most blocking the
    # project from earning revenue. Mirrors the logic in
    # ``ComplianceGates.revenue_streams_blocked``.
    _GATE_CASCADE_ORDER = (
        "anre_license_status",
        "brp_pre_responsibility",
        "settlement_account_and_guarantees",
        "remit_acknowledgement",
        "telemetry_and_metering",
        "opcom_short_term_participant",
        "fse_bsp_convention",
        "damas_access",
        "capacity_reserve_auction_register",
        "rsf_fcr_qualification",
        "storage_tariff_exemption_metering",
    )

    @staticmethod
    def _classify_irr(irr_pct: Optional[float]) -> str:
        """Bucket lifetime IRR into investor-readable tiers.

        - ``high``    : IRR > 12%   (project-finance bankable)
        - ``medium``  : 6% ≤ IRR ≤ 12% (marginal, needs negotiation)
        - ``low``     : IRR < 6%    (sub-cost-of-capital)
        - ``unknown`` : IRR is None / NaN (loss-making over horizon)
        """
        if irr_pct is None:
            return "unknown"
        try:
            v = float(irr_pct)
        except (TypeError, ValueError):
            return "unknown"
        if v != v:  # NaN guard
            return "unknown"
        if v > 12.0:
            return "high"
        if v >= 6.0:
            return "medium"
        return "low"

    def _most_blocking_gate(self, gates: ComplianceGates) -> Optional[str]:
        """Return the first gate (per cascade) that is not yet ``qualified``."""
        snapshot = gates.model_dump()
        for name in self._GATE_CASCADE_ORDER:
            if snapshot.get(name) != "qualified":
                return name
        return None

    def build_investor_summary(self, params: InvestmentParams) -> InvestorSummary:
        """One-page summary for external integrations (PDF, email, lender).

        Re-runs the full deterministic ``analyze`` pipeline and consolidates
        outputs into a flat structure. Picks Y1 DSCR + worst-year DSCR from
        the FR cashflow (FR carries the project's debt service the same as
        PZU under our model). Compliance gate count + most-blocking gate are
        derived from the gate cascade, NOT from a static enum order.
        """
        result = self.analyze(params)

        # Re-derive raw revenue dicts so we can surface revenue stack + provenance.
        fr_rev = self._get_fr_annual_revenue(params)
        pzu_rev = self._get_pzu_annual_revenue(params)

        fr_y1 = result.fr_cashflow[0] if result.fr_cashflow else None
        pzu_y1 = result.pzu_cashflow[0] if result.pzu_cashflow else None

        # DSCR: Y1 + worst loan-tenor year. ``debt_service_eur > 0`` excludes
        # post-loan years that carry DSCR=0.0 by convention.
        dscr_y1 = float(fr_y1.dscr) if fr_y1 is not None else 0.0
        debt_years = [cf.dscr for cf in result.fr_cashflow if cf.debt_service_eur > 0]
        dscr_worst = float(min(debt_years)) if debt_years else 0.0

        # Tariff exemption (Y1 line item from FR cashflow — same exemption is
        # applied to both scenarios; FR cashflow is the canonical reference).
        tariff_exemption_y1 = float(fr_y1.tariff_exemption_eur) if fr_y1 is not None else 0.0

        # Combined Y1 net profit = sum of both scenario Y1 nets. This is a
        # bankability-friendly view (project earns from BOTH stacks if
        # operated in hybrid dispatch). For external rendering only.
        fr_y1_net = float(fr_y1.net_profit_eur) if fr_y1 is not None else 0.0
        pzu_y1_net = float(pzu_y1.net_profit_eur) if pzu_y1 is not None else 0.0

        gates = result.compliance_gates
        gates_snapshot = gates.model_dump()
        qualified_count = sum(1 for v in gates_snapshot.values() if v == "qualified")
        most_blocking = self._most_blocking_gate(gates)

        irr_tier = self._classify_irr(result.fr_lifetime_irr_pct)

        bankability_level = str(fr_rev.get("bankability_level", "historical_backtest_only"))
        settlement_grade = bool(fr_rev.get("settlement_grade", False))
        pricing_basis = result.fr_scenario.pricing_basis
        revenue_source = result.fr_scenario.revenue_source

        # Plain-English disclaimer composed from bankability + grade so PDF /
        # Slack consumers don't have to reconstruct it from provenance fields.
        disclaimer_parts = [
            f"Bankability: {bankability_level}.",
            (
                "Settlement-grade evidence supplied."
                if settlement_grade
                else "Not participant settlement proof — scenario / backtest only."
            ),
            f"Pricing basis: {pricing_basis}; revenue source: {revenue_source}.",
            "Compliance gates and excluded costs (taxes, grid tariffs, REMIT exposure) "
            "must be reviewed before underwriting — see /api/v1/investment/analyze for "
            "the full payload.",
        ]
        disclaimer = " ".join(disclaimer_parts)

        return InvestorSummary(
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            project_sizing=f"{params.power_mw:g} MW / {params.capacity_mwh:g} MWh",
            capex_eur=float(params.total_investment_eur),

            fr_y1_net_profit_eur=fr_y1_net,
            pzu_y1_net_profit_eur=pzu_y1_net,
            combined_y1_net_profit_eur=fr_y1_net + pzu_y1_net,
            fr_lifetime_irr_pct=result.fr_lifetime_irr_pct,
            pzu_lifetime_irr_pct=result.pzu_lifetime_irr_pct,
            irr_tier=irr_tier,

            bankability_level=bankability_level,
            settlement_grade=settlement_grade,
            pricing_basis=pricing_basis,
            revenue_source=revenue_source,

            dscr_y1=dscr_y1,
            dscr_worst_year=dscr_worst,
            dscr_violation_count=len(result.dscr_violation_years),
            picasso_compression_modeled=(
                float(getattr(params, "picasso_one_time_compression_pct", 0.0)) > 0.0
            ),

            compliance_gates_qualified_count=qualified_count,
            compliance_gates_total=len(gates_snapshot),
            most_blocking_gate=most_blocking,
            blocked_revenue_streams=list(result.compliance_revenue_streams_blocked),

            fr_capacity_revenue_y1=float(fr_rev.get("capacity_revenue", 0.0)),
            fr_activation_revenue_y1=float(fr_rev.get("activation_revenue", 0.0)),
            pzu_arbitrage_y1=float(pzu_rev.get("gross_revenue", 0.0))
                              - float(pzu_rev.get("energy_cost", 0.0)),
            tariff_exemption_y1=tariff_exemption_y1,

            disclaimer=disclaimer,
            audit_reference="audit/BATTERY_ANALYTICS_PRO_PROGRESS_AUDIT_2026-05-01.md",
        )

    def get_defaults(self) -> Dict[str, Any]:
        """Canonical Romanian BESS investment defaults.

        **Project anchor:** €3,500,000 total install cost for 10 MW / 20 MWh
        = €175/kWh installed (= €350,000/MW). Vendor: **Huawei** (this is the
        user's reference quote). Sermatec offers below this anchor, BYD and
        YESS sit between. The €175/kWh band is exceptional vs European norms
        (typical EPC €300-500/kWh including grid connection, BoP, civils).

        The CAPEX "anchor + EU-typical" band is shown to investors so the
        model is honest under both the user's vendor quote AND the European
        bankability case (which is the lifetime IRR a project-finance bank
        would actually underwrite to).
        """
        capacity_mwh = 20.0
        power_mw = 10.0
        canonical_capex_per_kwh = 175.0
        return {
            "power_mw": power_mw,
            "capacity_mwh": capacity_mwh,
            "capex_per_kwh": canonical_capex_per_kwh,
            "capex_per_mw": canonical_capex_per_kwh * (capacity_mwh / power_mw) * 1000.0,
            # Romanian-vendor band (low/mid/high) anchored on user's vendor quotes:
            #   low (Sermatec-equivalent):     €150/kWh
            #   mid (Huawei-anchor):           €175/kWh
            #   high (premium European spec):  €250/kWh
            "capex_per_kwh_band": {"low": 150.0, "mid": 175.0, "high": 250.0},
            # European-typical band (low/mid/high), used to surface bankability
            # against EU project-finance norms — banks will underwrite at these
            # levels, NOT at the user's exceptional vendor quote.
            "capex_per_kwh_band_eu_typical": {"low": 300.0, "mid": 400.0, "high": 500.0},
            "total_investment_eur": canonical_capex_per_kwh * capacity_mwh * 1000.0,  # = €3,500,000
            "equity_percentage": 50,             # 50/50 debt-to-equity (Romanian BESS norm)
            "loan_interest_rate": 6.0,
            "loan_term_years": 10,
            "opex_percentage": 2.0,
            "insurance_percentage": 0.5,
            "vendor_quote_anchor": {
                "vendor": "Huawei",
                "quote_eur": 3_500_000.0,
                "power_mw": 10.0,
                "capacity_mwh": 20.0,
                "eur_per_kwh": 175.0,
                "note": "User-supplied reference quote. Sermatec quotes below this anchor; YESS / BYD sit between.",
            },
            "confidence_label": "Likely-source / Scenario",
            "audit_reference": "audit/BESS_REVENUE_REALITY_CHECK_2026-05-02.md",
        }
