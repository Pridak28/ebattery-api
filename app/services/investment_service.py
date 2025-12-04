"""
Investment & Financial Analysis Service
"""
from typing import Dict, Any, List

from app.models.investment import (
    InvestmentParams,
    InvestmentComparisonResponse,
    FinancingBreakdown,
    ScenarioResult,
    AnnualCashflow,
)
from app.services.pzu_service import PZUService
from app.services.fr_service import FRService
from app.models.pzu import PZUSimulationParams
from app.models.fr import FRSimulationParams


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

    def _get_fr_annual_revenue(self, params: InvestmentParams) -> Dict[str, float]:
        """Get estimated annual FR revenue"""
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
                }
        except Exception:
            pass

        # Default estimates based on Romanian market
        capacity_revenue = params.power_mw * 15 * 8760
        activation_revenue = capacity_revenue * 0.3
        gross_revenue = capacity_revenue + activation_revenue
        energy_cost = activation_revenue * 0.4

        return {"gross_revenue": gross_revenue, "energy_cost": energy_cost}

    def _get_pzu_annual_revenue(self, params: InvestmentParams) -> Dict[str, float]:
        """Get estimated annual PZU revenue

        PZU arbitrage model:
        - Gross Revenue = sell price × energy discharged
        - Energy Cost = buy price × energy charged
        - Net Profit = Gross Revenue - Energy Cost (what PZU service returns)

        We reconstruct the breakdown from monthly data.
        """
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
                }
        except Exception:
            pass

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
        }

    def _create_scenario_result(
        self,
        name: str,
        gross_revenue: float,
        energy_cost: float,
        operating_cost: float,
        annual_debt_service: float,
        equity: float,
    ) -> ScenarioResult:
        """Create scenario result with metrics"""
        net_profit = gross_revenue - energy_cost - operating_cost - annual_debt_service

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
        )

    def _create_cashflow(
        self, 
        years: int,
        gross_revenue: float,
        energy_cost: float,
        operating_cost: float,
        annual_debt_service: float,
    ) -> List[AnnualCashflow]:
        """Create annual cashflow projections"""
        cashflow = []
        cumulative = 0
        
        for year in range(1, years + 1):
            net = gross_revenue - energy_cost - operating_cost - annual_debt_service
            cumulative += net
            
            cashflow.append(AnnualCashflow(
                year=year,
                gross_revenue_eur=gross_revenue,
                energy_cost_eur=energy_cost,
                operating_cost_eur=operating_cost,
                debt_service_eur=annual_debt_service,
                net_profit_eur=net,
                cumulative_profit_eur=cumulative,
            ))
        
        return cashflow

    def analyze(self, params: InvestmentParams) -> InvestmentComparisonResponse:
        """Run complete investment analysis"""
        financing = self.calculate_financing(params)
        
        operating_cost = params.total_investment_eur * (params.opex_percentage / 100)
        operating_cost += params.total_investment_eur * (params.insurance_percentage / 100)

        fr_revenue = self._get_fr_annual_revenue(params)
        pzu_revenue = self._get_pzu_annual_revenue(params)

        fr_scenario = self._create_scenario_result(
            "FR",
            fr_revenue["gross_revenue"],
            fr_revenue["energy_cost"],
            operating_cost,
            financing.annual_debt_service_eur,
            financing.equity_eur,
        )

        pzu_scenario = self._create_scenario_result(
            "PZU",
            pzu_revenue["gross_revenue"],
            pzu_revenue["energy_cost"],
            operating_cost,
            financing.annual_debt_service_eur,
            financing.equity_eur,
        )

        # Create cashflow projections (10 years default)
        projection_years = params.loan_term_years
        
        fr_cashflow = self._create_cashflow(
            projection_years,
            fr_revenue["gross_revenue"],
            fr_revenue["energy_cost"],
            operating_cost,
            financing.annual_debt_service_eur,
        )
        
        pzu_cashflow = self._create_cashflow(
            projection_years,
            pzu_revenue["gross_revenue"],
            pzu_revenue["energy_cost"],
            operating_cost,
            financing.annual_debt_service_eur,
        )

        recommended = "FR" if fr_scenario.net_profit_after_debt_eur > pzu_scenario.net_profit_after_debt_eur else "PZU"
        advantage = abs(fr_scenario.net_profit_after_debt_eur - pzu_scenario.net_profit_after_debt_eur)
        min_profit = min(fr_scenario.net_profit_after_debt_eur, pzu_scenario.net_profit_after_debt_eur)

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
        )

    def get_defaults(self) -> Dict[str, Any]:
        """Get default investment parameters"""
        return {
            "total_investment_eur": 5000000,
            "equity_percentage": 30,
            "loan_interest_rate": 6.0,
            "loan_term_years": 10,
            "opex_percentage": 2.0,
            "insurance_percentage": 0.5,
            "power_mw": 15,
            "capacity_mwh": 30,
        }
