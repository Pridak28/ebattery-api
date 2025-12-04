"""
Frequency Regulation (FR) Service
Romanian balancing market calculations
"""
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import date
import pandas as pd
import numpy as np

from app.config import settings
from app.models.fr import (
    FRSimulationParams,
    FRSimulationResponse,
    FRMonthlyResult,
    FRProductSummary,
)


class FRService:
    """Service for Frequency Regulation simulation"""
    
    SLOT_DURATION_HOURS = 0.25  # 15-minute slots
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or settings.DATA_DIR
        self._fr_data: Optional[pd.DataFrame] = None

    def _load_fr_data(self) -> pd.DataFrame:
        """Load FR market data from CSV"""
        if self._fr_data is not None:
            return self._fr_data

        possible_files = [
            "damas_complete_fr_dataset.csv",
            "fr_data_clean.csv",
        ]

        for filename in possible_files:
            filepath = self.data_dir / filename
            if filepath.exists():
                try:
                    df = pd.read_csv(filepath)
                    if 'date' in df.columns:
                        df['date'] = pd.to_datetime(df['date'])
                    self._fr_data = df
                    return df
                except Exception:
                    continue

        raise FileNotFoundError(f"No FR data found in {self.data_dir}")

    def _get_activation_price(self, month_data: pd.DataFrame, product: str) -> float:
        """Get average activation price from market data.

        Romanian aFRR Price Convention (DAMAS/Transelectrica):
        - aFRR UP (positive regulation): Positive prices = you get paid to discharge
        - aFRR DOWN (negative regulation):
          - Negative prices = you GET PAID to absorb (common in Romania ~27% of time)
          - Positive prices = you pay to absorb

        Returns the ACTUAL signed average price, not abs().
        """
        is_up = "+" in product
        is_afrr = "afrr" in product.lower()

        if is_afrr:
            col = "afrr_up_price_eur" if is_up else "afrr_down_price_eur"
        else:
            col = "mfrr_up_scheduled_price_eur" if is_up else "mfrr_down_scheduled_price_eur"

        if col in month_data.columns:
            prices = month_data[col]
            # Filter outliers (absolute value) but preserve sign
            valid_prices = prices[(prices.abs() > 0) & (prices.abs() < 500)]
            if len(valid_prices) > 0:
                return float(valid_prices.mean())

        # Fallback defaults (conservative estimates)
        return 175.0 if is_up else -30.0  # DOWN prices are typically negative in Romania

    def _compute_monthly_revenue(
        self,
        month_data: pd.DataFrame,
        product: str,
        power_mw: float,
        efficiency: float,
        energy_cost_eur_mwh: float,
        capacity_price: float,
        activation_rate: float,
        remaining_energy_budget: float,  # NEW: Shared battery energy budget
    ) -> FRMonthlyResult:
        """Compute revenue for one month with SHARED battery capacity constraints"""
        total_slots = len(month_data)
        total_hours = total_slots * self.SLOT_DURATION_HOURS

        # Capacity revenue (paid for AVAILABILITY - 24h/day regardless of SOC)
        capacity_revenue = power_mw * capacity_price * total_hours

        # Activation price from data
        avg_activation_price = self._get_activation_price(month_data, product)

        # SHARED BATTERY CAPACITY CONSTRAINT:
        # Battery energy budget is SHARED across all FR products (aFRR+, aFRR-, mFRR+, mFRR-)
        # Total monthly throughput: 30 MWh × 1 cycle/day × 30 days = 900 MWh/month
        #
        # This method receives the remaining budget after other products have used their share.
        # For example, if aFRR+ used 600 MWh, then aFRR- only gets 300 MWh remaining.

        # Activation energy calculation (MARKET SHARE APPROACH)
        # Based on Romanian merit-order dispatch legislation (Transelectrica DAMAS)
        # activation_rate = market share percentage (e.g., 10% = capturing 10% of market activations)

        # Determine which market data column to use
        activation_column = 'afrr_up_activated_mwh' if '+' in product else 'afrr_down_activated_mwh'

        # Check if we have market activation data
        if activation_column in month_data.columns and not month_data.empty:
            # Market share approach: our_energy = market_total × our_percentage
            market_activated = month_data[activation_column].sum()
            our_max_capacity = power_mw * total_hours  # Physical maximum we could deliver
            unlimited_activation_energy = min(market_activated * activation_rate, our_max_capacity)
        else:
            # Fallback to duty cycle estimation if market data unavailable
            unlimited_activation_energy = power_mw * total_hours * activation_rate

        # Apply battery energy budget constraint
        activation_energy = min(unlimited_activation_energy, remaining_energy_budget)

        # Real-life Romanian aFRR settlement model:
        is_up = "+" in product

        if is_up:
            # aFRR+ (UP regulation): Battery DISCHARGES to grid
            # Revenue: Get paid activation price for energy delivered
            # Cost: Must recharge later at PZU/DAM price (accounting for efficiency losses)
            activation_revenue = activation_energy * avg_activation_price
            energy_cost = activation_energy * energy_cost_eur_mwh / efficiency
        else:
            # aFRR- (DOWN regulation): Battery CHARGES from grid
            #
            # Romanian market reality (DAMAS data shows ~27% negative prices):
            # - Negative activation_price: You GET PAID to absorb energy
            # - Positive activation_price: You pay to absorb energy
            #
            # Settlement logic:
            # 1. Activation payment = activation_energy × activation_price
            #    - If price < 0: You receive money (revenue)
            #    - If price > 0: You pay money (cost)
            # 2. SoC benefit: Absorbed energy saves future PZU recharge cost
            #
            # Net financial effect:
            # - Revenue = max(0, -activation_payment) when price is negative
            # - Cost = activation_payment + (0 if already charged else recharge_cost)
            #
            # Simplified model: We treat DOWN activation as:
            # - If price negative: activation_revenue = |price| × energy (you get paid!)
            # - Energy cost = price × energy - PZU_saved (could be negative = benefit)

            if avg_activation_price < 0:
                # You GET PAID to absorb energy (common in Romania)
                activation_revenue = abs(avg_activation_price) * activation_energy
                # You also save the PZU recharge cost
                energy_cost = -activation_energy * energy_cost_eur_mwh  # Negative = benefit
            else:
                # You PAY to absorb energy (less common)
                activation_revenue = 0
                energy_paid = activation_energy * avg_activation_price
                recharge_saved = activation_energy * energy_cost_eur_mwh
                energy_cost = energy_paid - recharge_saved  # Could be negative if recharge_saved > energy_paid
        
        total_revenue = capacity_revenue + activation_revenue
        net_profit = total_revenue - energy_cost
        
        month_str = str(month_data["date"].dt.to_period("M").iloc[0]) if "date" in month_data.columns else "Unknown"
        
        return FRMonthlyResult(
            month=month_str,
            product=product,
            total_slots=total_slots,
            capacity_revenue_eur=float(capacity_revenue),
            activation_revenue_eur=float(activation_revenue),
            total_revenue_eur=float(total_revenue),
            activation_energy_mwh=float(activation_energy),
            energy_cost_eur=float(energy_cost),
            net_profit_eur=float(net_profit),
            avg_capacity_price_eur_mw=float(capacity_price),
            avg_activation_price_eur_mwh=float(avg_activation_price),
        )

    def simulate(self, params: FRSimulationParams) -> FRSimulationResponse:
        """Run FR revenue simulation"""
        df = self._load_fr_data()

        if "date" in df.columns:
            if params.start_date:
                df = df[df["date"] >= pd.Timestamp(params.start_date)]
            if params.end_date:
                df = df[df["date"] <= pd.Timestamp(params.end_date)]

        if df.empty:
            raise ValueError("No data available")

        monthly_results: List[FRMonthlyResult] = []
        product_summaries: Dict[str, FRProductSummary] = {}

        products_config = {
            "aFRR+": params.afrr_up,
            "aFRR-": params.afrr_down,
            "mFRR+": params.mfrr_up,
            "mFRR-": params.mfrr_down,
        }

        # Filter enabled products
        enabled_products = {name: config for name, config in products_config.items()
                           if config.enabled and config.power_mw > 0}

        if not enabled_products:
            raise ValueError("No products enabled")

        # SHARED BATTERY CAPACITY CONSTRAINT:
        # Process month-by-month, sharing 900 MWh/month budget across ALL products
        # Battery: 30 MWh × 1 cycle/day × 30 days = 900 MWh/month total throughput

        if "date" in df.columns:
            df["month"] = df["date"].dt.to_period("M")

            # Group by month and process all products together
            for month, month_data in df.groupby("month"):
                # Battery capacity constraint per month (shared across all products)
                battery_capacity_mwh = 30
                realistic_daily_cycles = 1.0
                days_in_month = 30
                max_monthly_energy_mwh = battery_capacity_mwh * realistic_daily_cycles * days_in_month

                remaining_energy_budget = max_monthly_energy_mwh

                # Process each enabled product for this month
                for product_name, config in enabled_products.items():
                    result = self._compute_monthly_revenue(
                        month_data,
                        product_name,
                        config.power_mw,
                        params.round_trip_efficiency,
                        params.energy_cost_eur_mwh,
                        config.capacity_price_eur_mw_h,
                        config.activation_rate,
                        remaining_energy_budget,  # Pass remaining budget
                    )
                    monthly_results.append(result)

                    # Deduct used energy from shared budget
                    remaining_energy_budget -= result.activation_energy_mwh
                    remaining_energy_budget = max(0, remaining_energy_budget)

            # Build product summaries
            for product_name in enabled_products.keys():
                product_results = [r for r in monthly_results if r.product == product_name]
                if product_results:
                    product_summaries[product_name] = FRProductSummary(
                        product=product_name,
                        total_capacity_revenue_eur=sum(r.capacity_revenue_eur for r in product_results),
                        total_activation_revenue_eur=sum(r.activation_revenue_eur for r in product_results),
                        total_revenue_eur=sum(r.total_revenue_eur for r in product_results),
                        total_energy_cost_eur=sum(r.energy_cost_eur for r in product_results),
                        total_net_profit_eur=sum(r.net_profit_eur for r in product_results),
                        months_count=len(product_results),
                    )

        monthly_results.sort(key=lambda x: (x.month, x.product))

        total_capacity_revenue = sum(r.capacity_revenue_eur for r in monthly_results)
        total_activation_revenue = sum(r.activation_revenue_eur for r in monthly_results)
        total_revenue = sum(r.total_revenue_eur for r in monthly_results)
        total_energy_cost = sum(r.energy_cost_eur for r in monthly_results)
        total_net_profit = sum(r.net_profit_eur for r in monthly_results)
        num_months = len(set(r.month for r in monthly_results)) or 1

        # Annualized metrics (12-month projection)
        annual_factor = 12 / num_months
        annual_revenue = total_revenue * annual_factor
        annual_capacity_revenue = total_capacity_revenue * annual_factor
        annual_activation_revenue = total_activation_revenue * annual_factor
        annual_energy_cost = total_energy_cost * annual_factor
        annual_profit = total_net_profit * annual_factor
        avg_monthly_profit = total_net_profit / num_months

        return FRSimulationResponse(
            params=params,
            monthly_results=monthly_results,
            product_summaries=list(product_summaries.values()),
            total_revenue_eur=total_revenue,
            total_energy_cost_eur=total_energy_cost,
            total_net_profit_eur=total_net_profit,
            total_capacity_revenue_eur=total_capacity_revenue,
            total_activation_revenue_eur=total_activation_revenue,
            avg_monthly_net_profit_eur=avg_monthly_profit,
            annual_net_profit_eur=annual_profit,
            annual_revenue_eur=annual_revenue,
            annual_capacity_revenue_eur=annual_capacity_revenue,
            annual_activation_revenue_eur=annual_activation_revenue,
            annual_energy_cost_eur=annual_energy_cost,
            months_count=num_months,
        )

    def get_products_list(self) -> List[Dict[str, Any]]:
        return [
            {"id": "aFRR+", "name": "aFRR Up-regulation"},
            {"id": "aFRR-", "name": "aFRR Down-regulation"},
            {"id": "mFRR+", "name": "mFRR Up-regulation"},
            {"id": "mFRR-", "name": "mFRR Down-regulation"},
        ]

    def get_market_stats(self) -> Dict[str, Any]:
        df = self._load_fr_data()
        stats = {"total_slots": len(df), "date_range": {}, "afrr_stats": {}}

        if "date" in df.columns:
            stats["date_range"] = {
                "start": str(df["date"].min().date()),
                "end": str(df["date"].max().date()),
            }

        for col, name in [("afrr_up_price_eur", "up"), ("afrr_down_price_eur", "down")]:
            if col in df.columns:
                prices = df[col]
                # Filter outliers but preserve sign (DOWN prices are often negative)
                valid_prices = prices[(prices.abs() > 0) & (prices.abs() < 500)]
                if len(valid_prices) > 0:
                    stats["afrr_stats"][name] = {
                        "avg_price": float(valid_prices.mean()),
                        "min_price": float(valid_prices.min()),
                        "max_price": float(valid_prices.max()),
                        "pct_negative": float((valid_prices < 0).mean() * 100),
                    }
                else:
                    stats["afrr_stats"][name] = {"avg_price": 0}

        return stats

    def get_monthly_breakdown(self, product: str = "aFRR+") -> List[Dict[str, Any]]:
        df = self._load_fr_data()
        if "date" not in df.columns:
            return []

        df["month"] = df["date"].dt.to_period("M")
        col = "afrr_up_price_eur" if "+" in product else "afrr_down_price_eur"

        results = []
        for month, mdf in df.groupby("month"):
            if col in mdf.columns:
                prices = mdf[col]
                # Filter outliers but preserve sign
                valid_prices = prices[(prices.abs() > 0) & (prices.abs() < 500)]
                results.append({
                    "month": str(month),
                    "slots": len(mdf),
                    "avg_price": float(valid_prices.mean()) if len(valid_prices) > 0 else 0,
                    "pct_negative": float((valid_prices < 0).mean() * 100) if len(valid_prices) > 0 else 0,
                })
        return results

    def get_available_dates(self) -> Dict[str, Any]:
        """Get list of all available dates with aFRR summary statistics"""
        df = self._load_fr_data()

        # Group by date
        daily_stats = []
        for date_val, day_data in df.groupby('date'):
            # Calculate daily averages
            afrr_up_prices = day_data['afrr_up_price_eur']
            afrr_down_prices = day_data['afrr_down_price_eur']

            # Filter valid prices
            valid_up = afrr_up_prices[(afrr_up_prices.abs() > 0) & (afrr_up_prices.abs() < 500)]
            valid_down = afrr_down_prices[(afrr_down_prices.abs() > 0) & (afrr_down_prices.abs() < 500)]

            daily_stats.append({
                "date": str(date_val)[:10] if isinstance(date_val, pd.Timestamp) else str(date_val),
                "afrr_up_avg": round(float(valid_up.mean()), 2) if len(valid_up) > 0 else 0,
                "afrr_down_avg": round(float(valid_down.mean()), 2) if len(valid_down) > 0 else 0,
                "afrr_up_activations": round(float(day_data['afrr_up_activated_mwh'].sum()), 2),
                "afrr_down_activations": round(float(day_data['afrr_down_activated_mwh'].sum()), 2),
            })

        return {"dates": daily_stats}

    def get_slot_prices(self, date_str: str, power_mw: float) -> Dict[str, Any]:
        """Get 15-minute slot prices and revenue for a specific date"""
        df = self._load_fr_data()

        # Filter for the specific date
        day_data = df[df['date'] == date_str].copy()

        if len(day_data) == 0:
            return {"error": f"No data found for date {date_str}"}

        # Sort by slot
        day_data = day_data.sort_values('slot')

        # Calculate revenue per slot (15 minutes = 0.25 hours)
        slot_duration_hours = 0.25

        # Prepare slot data
        slot_prices = []
        total_afrr_up_revenue = 0
        total_afrr_down_revenue = 0

        for _, row in day_data.iterrows():
            slot = int(row['slot'])

            # Get prices and activations
            afrr_up_price = float(row['afrr_up_price_eur'])
            afrr_up_activation = float(row['afrr_up_activated_mwh'])
            afrr_down_price = float(row['afrr_down_price_eur'])
            afrr_down_activation = float(row['afrr_down_activated_mwh'])

            # Calculate potential revenue for each direction
            # aFRR+ revenue (discharge - get paid for delivery)
            afrr_up_capacity_revenue = power_mw * slot_duration_hours * 50  # Typical capacity price
            if afrr_up_price > 0 and afrr_up_activation > 0:
                afrr_up_activation_revenue = min(afrr_up_activation, power_mw * slot_duration_hours) * afrr_up_price
            else:
                afrr_up_activation_revenue = 0
            afrr_up_potential = afrr_up_capacity_revenue + afrr_up_activation_revenue

            # aFRR- revenue (charge - can get paid if price negative)
            afrr_down_capacity_revenue = power_mw * slot_duration_hours * 30  # Typical capacity price
            if afrr_down_price < 0 and afrr_down_activation > 0:
                # Negative price = you get paid to charge
                afrr_down_activation_revenue = min(afrr_down_activation, power_mw * slot_duration_hours) * abs(afrr_down_price)
            else:
                afrr_down_activation_revenue = 0
            afrr_down_potential = afrr_down_capacity_revenue + afrr_down_activation_revenue

            # CRITICAL FIX: Battery can only provide ONE service at a time
            # Choose the most profitable direction for this slot
            if afrr_up_potential > afrr_down_potential:
                # Provide aFRR+ service this slot
                afrr_up_slot_revenue = afrr_up_potential
                afrr_down_slot_revenue = 0
                selected_service = "aFRR+"
            else:
                # Provide aFRR- service this slot
                afrr_up_slot_revenue = 0
                afrr_down_slot_revenue = afrr_down_potential
                selected_service = "aFRR-"

            total_afrr_up_revenue += afrr_up_slot_revenue
            total_afrr_down_revenue += afrr_down_slot_revenue

            slot_prices.append({
                "slot": slot,
                "hour": f"{slot//4:02d}:{(slot%4)*15:02d}",
                "afrr_up_price": round(afrr_up_price, 2),
                "afrr_down_price": round(afrr_down_price, 2),
                "afrr_up_activation_mwh": round(afrr_up_activation, 3),
                "afrr_down_activation_mwh": round(afrr_down_activation, 3),
                "afrr_up_revenue": round(afrr_up_slot_revenue, 2),
                "afrr_down_revenue": round(afrr_down_slot_revenue, 2),
                "selected_service": selected_service,
            })

        # Calculate daily statistics
        afrr_up_prices = day_data['afrr_up_price_eur']
        afrr_down_prices = day_data['afrr_down_price_eur']

        valid_up = afrr_up_prices[(afrr_up_prices.abs() > 0) & (afrr_up_prices.abs() < 500)]
        valid_down = afrr_down_prices[(afrr_down_prices.abs() > 0) & (afrr_down_prices.abs() < 500)]

        # Get day of week
        from datetime import datetime
        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            day_of_week = date_obj.strftime('%A')
        except:
            day_of_week = "Unknown"

        return {
            "date": date_str,
            "day_of_week": day_of_week,
            "slot_prices": slot_prices,
            "afrr_up_avg_price": round(float(valid_up.mean()), 2) if len(valid_up) > 0 else 0,
            "afrr_down_avg_price": round(float(valid_down.mean()), 2) if len(valid_down) > 0 else 0,
            "afrr_up_min_price": round(float(valid_up.min()), 2) if len(valid_up) > 0 else 0,
            "afrr_up_max_price": round(float(valid_up.max()), 2) if len(valid_up) > 0 else 0,
            "afrr_down_min_price": round(float(valid_down.min()), 2) if len(valid_down) > 0 else 0,
            "afrr_down_max_price": round(float(valid_down.max()), 2) if len(valid_down) > 0 else 0,
            "total_afrr_up_revenue": round(total_afrr_up_revenue, 2),
            "total_afrr_down_revenue": round(total_afrr_down_revenue, 2),
            "total_revenue": round(total_afrr_up_revenue + total_afrr_down_revenue, 2),
            "damas_url": "https://www.transelectrica.ro/en/web/tel/piata-de-echilibrare",
        }

    def analyze_bidding_strategy(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze historical data to recommend bidding strategy.

        Returns:
        - Optimal bid prices at different percentiles
        - aFRR+ vs aFRR- profitability comparison
        - Historical acceptance patterns
        - Strategy recommendations
        """
        df = self._load_fr_data()

        # Filter by date range if provided
        if start_date:
            df = df[df['date'] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df['date'] <= pd.Timestamp(end_date)]

        if df.empty:
            return {"error": "No data available for the specified date range"}

        # Calculate profitability metrics for each service
        afrr_up_prices = df['afrr_up_price_eur']
        afrr_down_prices = df['afrr_down_price_eur']
        afrr_up_activations = df['afrr_up_activated_mwh']
        afrr_down_activations = df['afrr_down_activated_mwh']

        # Filter valid prices (exclude outliers but preserve sign)
        valid_up = afrr_up_prices[(afrr_up_prices.abs() > 0) & (afrr_up_prices.abs() < 500)]
        valid_down = afrr_down_prices[(afrr_down_prices.abs() > 0) & (afrr_down_prices.abs() < 500)]

        # Calculate percentiles for optimal bid prices
        # These represent capacity prices that would be profitable
        afrr_up_percentiles = {
            "p20": round(float(valid_up.quantile(0.20)), 2),  # Conservative (90% acceptance)
            "p50": round(float(valid_up.quantile(0.50)), 2),  # Balanced (80% acceptance)
            "p70": round(float(valid_up.quantile(0.70)), 2),  # Aggressive (60% acceptance)
            "p80": round(float(valid_up.quantile(0.80)), 2),
            "p90": round(float(valid_up.quantile(0.90)), 2),
        }

        # For aFRR-, we need to handle negative prices differently
        afrr_down_percentiles = {
            "p20": round(float(valid_down.quantile(0.20)), 2),
            "p50": round(float(valid_down.quantile(0.50)), 2),
            "p70": round(float(valid_down.quantile(0.70)), 2),
            "p80": round(float(valid_down.quantile(0.80)), 2),
            "p90": round(float(valid_down.quantile(0.90)), 2),
        }

        # Calculate profitability comparison
        # aFRR+ profitability: activation price (revenue)
        afrr_up_avg_profit = float(valid_up.mean())
        afrr_up_total_activations = float(afrr_up_activations.sum())

        # aFRR- profitability: negative prices = revenue
        afrr_down_avg_profit = float(valid_down.mean())
        afrr_down_total_activations = float(afrr_down_activations.sum())
        afrr_down_negative_pct = float((valid_down < 0).mean() * 100)

        # Determine which service is more profitable
        # For UP: higher positive price = better
        # For DOWN: more negative price = better (you get paid to charge)
        profitability_ratio = afrr_up_avg_profit / abs(afrr_down_avg_profit) if afrr_down_avg_profit != 0 else 0

        # Calculate seasonal patterns (monthly averages)
        df['month'] = df['date'].dt.month
        monthly_up = df.groupby('month')['afrr_up_price_eur'].mean()
        monthly_down = df.groupby('month')['afrr_down_price_eur'].mean()

        seasonal_patterns = []
        for month in range(1, 13):
            if month in monthly_up.index:
                seasonal_patterns.append({
                    "month": month,
                    "month_name": pd.Timestamp(2024, month, 1).strftime('%B'),
                    "afrr_up_avg": round(float(monthly_up[month]), 2),
                    "afrr_down_avg": round(float(monthly_down[month]), 2),
                })

        # Strategy recommendation
        if profitability_ratio > 2.0:
            recommendation = "aFRR+ is significantly more profitable. Focus on UP regulation."
        elif profitability_ratio > 1.5:
            recommendation = "aFRR+ is more profitable. Prefer UP regulation but consider DOWN during high activation periods."
        elif profitability_ratio > 0.8:
            recommendation = "Both services are similarly profitable. Diversify between UP and DOWN."
        else:
            recommendation = "aFRR- shows better profitability, especially during negative price periods."

        return {
            "analysis_period": {
                "start_date": str(df['date'].min().date()),
                "end_date": str(df['date'].max().date()),
                "total_days": len(df['date'].unique()),
            },
            "afrr_up": {
                "avg_price": round(afrr_up_avg_profit, 2),
                "percentiles": afrr_up_percentiles,
                "total_activations_mwh": round(afrr_up_total_activations, 2),
            },
            "afrr_down": {
                "avg_price": round(afrr_down_avg_profit, 2),
                "percentiles": afrr_down_percentiles,
                "total_activations_mwh": round(afrr_down_total_activations, 2),
                "negative_price_percentage": round(afrr_down_negative_pct, 1),
            },
            "profitability_comparison": {
                "ratio": round(profitability_ratio, 2),
                "recommendation": recommendation,
            },
            "seasonal_patterns": seasonal_patterns,
        }

    def calculate_optimal_bids(
        self,
        date_str: str,
        power_mw: float,
        target_acceptance_rate: float = 0.80
    ) -> Dict[str, Any]:
        """
        Calculate optimal bid prices for a specific date.

        Uses historical data around that date to recommend:
        - aFRR+ capacity bid price
        - aFRR- capacity bid price
        - Expected acceptance probability
        - Expected revenue
        """
        df = self._load_fr_data()

        # Parse target date
        target_date = pd.Timestamp(date_str)

        # Get surrounding 90 days of historical data for context
        lookback_days = 90
        start_window = target_date - pd.Timedelta(days=lookback_days)
        end_window = target_date + pd.Timedelta(days=lookback_days)

        historical_data = df[(df['date'] >= start_window) & (df['date'] <= end_window)]

        if historical_data.empty:
            return {"error": f"No historical data available around {date_str}"}

        # Calculate optimal bid prices based on target acceptance rate
        # Higher acceptance rate = lower bid price (more conservative)
        # Lower acceptance rate = higher bid price (more aggressive)

        # For aFRR+: bid at percentile corresponding to target acceptance
        # Example: 80% acceptance = bid at 20th percentile (you'll be accepted 80% of time)
        bid_percentile = 1 - target_acceptance_rate

        afrr_up_prices = historical_data['afrr_up_price_eur']
        afrr_down_prices = historical_data['afrr_down_price_eur']

        valid_up = afrr_up_prices[(afrr_up_prices.abs() > 0) & (afrr_up_prices.abs() < 500)]
        valid_down = afrr_down_prices[(afrr_down_prices.abs() > 0) & (afrr_down_prices.abs() < 500)]

        # PAY-AS-BID LOGIC:
        # In merit order dispatch, lower bids are accepted first
        # Target acceptance rate determines how conservative to bid
        #
        # Example: If 80% acceptance target, we bid low enough to be in the cheapest 80% of offers
        # This means bidding at the 20th percentile of what the market would bear
        #
        # We use activation prices as a proxy for market stress levels:
        # - High activation prices → tight market → capacity clearing prices are high
        # - Low activation prices → loose market → capacity clearing prices are low

        # Get activation price at the target percentile (this represents market conditions)
        afrr_up_activation_proxy = float(valid_up.quantile(bid_percentile))
        afrr_down_activation_proxy = float(valid_down.quantile(bid_percentile))

        # Derive capacity bid from activation price using empirical ratio
        # Typical Romanian market: capacity bids are ~20-30% of activation prices
        # For conservative bidding (high acceptance), use lower multiplier
        capacity_ratio = 0.20 + (bid_percentile * 0.10)  # 0.20-0.30 range

        afrr_up_capacity_bid = afrr_up_activation_proxy * capacity_ratio
        afrr_down_capacity_bid = abs(afrr_down_activation_proxy) * capacity_ratio

        # Cap at reasonable maximums based on Romanian market observations
        afrr_up_capacity_bid = min(60, max(15, afrr_up_capacity_bid))
        afrr_down_capacity_bid = min(40, max(10, afrr_down_capacity_bid))

        # Estimate daily revenue with battery capacity constraints
        daily_hours = 24
        estimated_acceptance = target_acceptance_rate

        # CAPACITY REVENUE (paid for availability - 24h/day)
        # Pay-as-bid: You get paid YOUR bid price (not the clearing price)
        afrr_up_capacity_revenue = power_mw * daily_hours * afrr_up_capacity_bid * estimated_acceptance
        afrr_down_capacity_revenue = power_mw * daily_hours * afrr_down_capacity_bid * estimated_acceptance

        # ACTIVATION REVENUE (LIMITED by battery capacity)
        # Battery: 15MW/30MWh = 2-hour duration
        # Can only discharge 30 MWh per day (1 full cycle)
        # Must charge first (from PZU or aFRR-)

        battery_capacity_mwh = 30
        realistic_daily_cycles = 1.0
        max_daily_energy_mwh = battery_capacity_mwh * realistic_daily_cycles

        # MARKET SHARE APPROACH: Use actual market activation data for the target date
        target_date_data = historical_data[historical_data['date'] == target_date]

        if not target_date_data.empty:
            # Get actual market activations for this specific date
            daily_market_up = target_date_data['afrr_up_activated_mwh'].sum()
            daily_market_down = target_date_data['afrr_down_activated_mwh'].sum()

            # Market share: 10% of actual market activations
            activation_rate = 0.10
            our_max_capacity = power_mw * daily_hours

            # Calculate our share of market activations (capped by our capacity)
            unlimited_daily_energy_up = min(daily_market_up * activation_rate, our_max_capacity)
            unlimited_daily_energy_down = min(daily_market_down * activation_rate, our_max_capacity)

            # Further constrained by battery throughput limit
            constrained_daily_energy_up = min(unlimited_daily_energy_up, max_daily_energy_mwh)
            constrained_daily_energy_down = min(unlimited_daily_energy_down, max_daily_energy_mwh)
        else:
            # Fallback to estimated approach if no data for target date
            activation_rate = 0.30
            unlimited_daily_energy = power_mw * daily_hours * activation_rate * estimated_acceptance
            constrained_daily_energy_up = min(unlimited_daily_energy, max_daily_energy_mwh)
            constrained_daily_energy_down = constrained_daily_energy_up

        # Activation revenue (constrained by battery capacity)
        afrr_up_activation_revenue = constrained_daily_energy_up * afrr_up_activation_proxy
        afrr_down_activation_revenue = 0
        if afrr_down_activation_proxy < 0:
            # Negative price = revenue (you get paid to charge)
            afrr_down_activation_revenue = constrained_daily_energy_down * abs(afrr_down_activation_proxy)

        afrr_up_total_revenue = afrr_up_capacity_revenue + afrr_up_activation_revenue
        afrr_down_total_revenue = afrr_down_capacity_revenue + afrr_down_activation_revenue

        return {
            "date": date_str,
            "target_acceptance_rate": target_acceptance_rate,
            "lookback_period_days": lookback_days,
            "historical_data_points": len(historical_data),
            "optimal_bids": {
                "afrr_up": {
                    "recommended_capacity_bid": round(afrr_up_capacity_bid, 2),
                    "based_on_activation_price": round(afrr_up_activation_proxy, 2),
                    "expected_acceptance_rate": target_acceptance_rate,
                    "estimated_daily_revenue": round(afrr_up_total_revenue, 2),
                    "capacity_component": round(afrr_up_capacity_revenue, 2),
                    "activation_component": round(afrr_up_activation_revenue, 2),
                },
                "afrr_down": {
                    "recommended_capacity_bid": round(afrr_down_capacity_bid, 2),
                    "based_on_activation_price": round(afrr_down_activation_proxy, 2),
                    "expected_acceptance_rate": target_acceptance_rate,
                    "estimated_daily_revenue": round(afrr_down_total_revenue, 2),
                    "capacity_component": round(afrr_down_capacity_revenue, 2),
                    "activation_component": round(afrr_down_activation_revenue, 2),
                },
            },
            "recommendation": "aFRR+" if afrr_up_total_revenue > afrr_down_total_revenue else "aFRR-",
        }

    def project_annual_revenue(
        self,
        power_mw: float,
        strategy: str = "balanced"
    ) -> Dict[str, Any]:
        """
        Project 12-month revenue using historical data.

        Strategies:
        - Conservative: 90% acceptance, lower bid prices
        - Balanced: 80% acceptance, moderate bid prices
        - Aggressive: 60% acceptance, higher bid prices

        Returns month-by-month projections.
        """
        df = self._load_fr_data()

        if df.empty:
            return {"error": "No historical data available"}

        # Strategy configurations
        strategies = {
            "conservative": {
                "acceptance_rate": 0.90,
                "capacity_multiplier": 0.85,  # Lower capacity bids
                "activation_rate": 0.25,
            },
            "balanced": {
                "acceptance_rate": 0.80,
                "capacity_multiplier": 1.00,  # Standard capacity bids
                "activation_rate": 0.30,
            },
            "aggressive": {
                "acceptance_rate": 0.60,
                "capacity_multiplier": 1.15,  # Higher capacity bids
                "activation_rate": 0.35,
            },
        }

        if strategy not in strategies:
            strategy = "balanced"

        config = strategies[strategy]
        acceptance_rate = config["acceptance_rate"]
        capacity_mult = config["capacity_multiplier"]
        activation_rate = config["activation_rate"]

        # Group data by month
        df['month'] = df['date'].dt.to_period('M')

        monthly_projections = []
        total_annual_revenue = 0

        for month, month_data in df.groupby('month'):
            # Calculate average activation prices
            afrr_up_prices = month_data['afrr_up_price_eur']
            afrr_down_prices = month_data['afrr_down_price_eur']

            valid_up = afrr_up_prices[(afrr_up_prices.abs() > 0) & (afrr_up_prices.abs() < 500)]
            valid_down = afrr_down_prices[(afrr_down_prices.abs() > 0) & (afrr_down_prices.abs() < 500)]

            if len(valid_up) == 0 or len(valid_down) == 0:
                continue

            avg_up_price = float(valid_up.mean())
            avg_down_price = float(valid_down.mean())

            # PAY-AS-BID LOGIC (matching calculate_optimal_bids)
            # Calculate the bid percentile based on acceptance rate
            # Higher acceptance = lower percentile = lower bid
            bid_percentile = 1 - acceptance_rate

            # Get activation price at target percentile (market stress proxy)
            afrr_up_proxy = float(valid_up.quantile(bid_percentile))
            afrr_down_proxy = float(valid_down.quantile(bid_percentile))

            # Derive capacity bid using empirical ratio (20-30% of activation)
            # Conservative strategy uses lower multiplier, aggressive uses higher
            capacity_ratio = 0.20 + (bid_percentile * 0.10)  # 0.20-0.30 range

            afrr_up_capacity_bid = afrr_up_proxy * capacity_ratio * capacity_mult
            afrr_down_capacity_bid = abs(afrr_down_proxy) * capacity_ratio * capacity_mult

            # Cap at reasonable limits
            afrr_up_capacity_bid = min(60, max(15, afrr_up_capacity_bid))
            afrr_down_capacity_bid = min(40, max(10, afrr_down_capacity_bid))

            # Monthly hours (assuming 30 days)
            days_in_month = 30
            hours_in_month = days_in_month * 24

            # CAPACITY REVENUE (paid for availability - 24h/day)
            # Revenue = power × hours × YOUR_BID × acceptance_rate
            afrr_up_capacity_rev = power_mw * hours_in_month * afrr_up_capacity_bid * acceptance_rate
            afrr_down_capacity_rev = power_mw * hours_in_month * afrr_down_capacity_bid * acceptance_rate

            # ACTIVATION REVENUE (LIMITED by battery capacity)
            # Battery: 15MW/30MWh = 2-hour duration
            # Realistic: 1 cycle/day = 30 MWh × 30 days = 900 MWh/month max
            battery_capacity_mwh = 30
            realistic_daily_cycles = 1.0
            max_monthly_energy_mwh = battery_capacity_mwh * realistic_daily_cycles * days_in_month

            # MARKET SHARE APPROACH: Use actual market activation data
            # Get actual market activations for this month
            month_market_up = month_data['afrr_up_activated_mwh'].sum()
            month_market_down = month_data['afrr_down_activated_mwh'].sum()

            # Market share: 10% of actual market activations (realistic for 15MW new entrant)
            market_share = 0.10
            our_max_capacity = power_mw * hours_in_month

            # Calculate our share of market activations (capped by our capacity and acceptance rate)
            unlimited_monthly_energy_up = min(month_market_up * market_share, our_max_capacity) * acceptance_rate
            unlimited_monthly_energy_down = min(month_market_down * market_share, our_max_capacity) * acceptance_rate

            # Further constrained by battery throughput limit
            constrained_monthly_energy_up = min(unlimited_monthly_energy_up, max_monthly_energy_mwh)
            constrained_monthly_energy_down = min(unlimited_monthly_energy_down, max_monthly_energy_mwh)

            # Activation revenue (constrained by battery capacity)
            afrr_up_activation_rev = constrained_monthly_energy_up * afrr_up_proxy
            afrr_down_activation_rev = 0
            if afrr_down_proxy < 0:
                # Negative price = you get paid to charge
                afrr_down_activation_rev = constrained_monthly_energy_down * abs(afrr_down_proxy)

            afrr_up_total = afrr_up_capacity_rev + afrr_up_activation_rev
            afrr_down_total = afrr_down_capacity_rev + afrr_down_activation_rev

            # Choose best service for each month
            if afrr_up_total > afrr_down_total:
                monthly_revenue = afrr_up_total
                selected_service = "aFRR+"
            else:
                monthly_revenue = afrr_down_total
                selected_service = "aFRR-"

            total_annual_revenue += monthly_revenue

            monthly_projections.append({
                "month": str(month),
                "selected_service": selected_service,
                "afrr_up_revenue": round(afrr_up_total, 2),
                "afrr_down_revenue": round(afrr_down_total, 2),
                "monthly_revenue": round(monthly_revenue, 2),
            })

        # Calculate annual metrics
        avg_monthly_revenue = total_annual_revenue / len(monthly_projections) if monthly_projections else 0

        # Annualize to 12 months
        annualization_factor = 12 / len(monthly_projections) if monthly_projections else 1
        projected_annual_revenue = total_annual_revenue * annualization_factor

        return {
            "strategy": strategy,
            "acceptance_rate": acceptance_rate,
            "power_mw": power_mw,
            "monthly_projections": monthly_projections,
            "total_projected_annual_revenue": round(projected_annual_revenue, 2),
            "avg_monthly_revenue": round(avg_monthly_revenue, 2),
            "months_analyzed": len(monthly_projections),
        }

    def calculate_safe_bid_prices(
        self,
        power_mw: float,
        target_acceptance_rate: float = 0.90
    ) -> Dict[str, Any]:
        """
        Calculate "safe" bid prices that guarantee high acceptance rate.

        Strategy: Bid below market average to maximize activation frequency.
        For batteries with capacity constraints (900 MWh/month), utilization
        matters more than price per MWh.

        Args:
            power_mw: Battery power capacity in MW
            target_acceptance_rate: Target acceptance rate (0.80-0.95)

        Returns:
            Safe bid prices, expected revenue, and comparison vs aggressive bidding
        """
        df = self._load_fr_data()

        if df.empty:
            return {"error": "No historical data available"}

        # Calculate percentile corresponding to acceptance rate
        # 90% acceptance = bid at 10th percentile (below 90% of market)
        bid_percentile = 1 - target_acceptance_rate

        # Get activation price data
        afrr_up_prices = df['afrr_up_price_eur']
        afrr_down_prices = df['afrr_down_price_eur']

        valid_up = afrr_up_prices[(afrr_up_prices > 0) & (afrr_up_prices < 500)]
        valid_down = afrr_down_prices[(afrr_down_prices.abs() > 0) & (afrr_down_prices.abs() < 500)]

        # Calculate safe activation bid prices (at target percentile)
        safe_activation_up = float(valid_up.quantile(bid_percentile))
        safe_activation_down = float(valid_down.quantile(bid_percentile))

        # Derive capacity bids (20-25% of activation prices)
        # Conservative bidding uses lower ratio
        capacity_ratio = 0.20 + (bid_percentile * 0.05)
        safe_capacity_up = safe_activation_up * capacity_ratio
        safe_capacity_down = abs(safe_activation_down) * capacity_ratio

        # Cap at reasonable limits
        safe_capacity_up = min(60, max(15, safe_capacity_up))
        safe_capacity_down = min(40, max(10, safe_capacity_down))

        # Calculate expected annual revenue with safe bidding
        monthly_hours = 720
        battery_capacity_mwh = 30
        max_monthly_energy = battery_capacity_mwh * 30  # 900 MWh/month

        # Safe bidding revenue (high acceptance = high utilization)
        safe_capacity_revenue_monthly = power_mw * monthly_hours * safe_capacity_up * target_acceptance_rate
        safe_activation_energy = max_monthly_energy * 0.95  # Near full utilization
        safe_activation_revenue_monthly = safe_activation_energy * safe_activation_up
        safe_total_monthly = safe_capacity_revenue_monthly + safe_activation_revenue_monthly
        safe_annual_revenue = safe_total_monthly * 12

        # Compare with aggressive bidding (higher price, lower acceptance)
        aggressive_acceptance = 0.60
        aggressive_percentile = 1 - aggressive_acceptance
        aggressive_activation_up = float(valid_up.quantile(aggressive_percentile))
        aggressive_capacity_up = aggressive_activation_up * (0.20 + aggressive_percentile * 0.10)
        aggressive_capacity_up = min(60, max(15, aggressive_capacity_up))

        # Aggressive bidding revenue (low acceptance = low utilization)
        aggressive_capacity_revenue_monthly = power_mw * monthly_hours * aggressive_capacity_up * aggressive_acceptance
        aggressive_activation_energy = max_monthly_energy * 0.65  # Lower utilization
        aggressive_activation_revenue_monthly = aggressive_activation_energy * aggressive_activation_up
        aggressive_total_monthly = aggressive_capacity_revenue_monthly + aggressive_activation_revenue_monthly
        aggressive_annual_revenue = aggressive_total_monthly * 12

        # Calculate advantage of safe bidding
        revenue_advantage = safe_annual_revenue - aggressive_annual_revenue
        revenue_advantage_pct = (revenue_advantage / aggressive_annual_revenue) * 100 if aggressive_annual_revenue > 0 else 0

        # Market statistics
        avg_activation_up = float(valid_up.mean())
        median_activation_up = float(valid_up.median())

        return {
            "target_acceptance_rate": target_acceptance_rate,
            "safe_bids": {
                "afrr_up": {
                    "capacity_bid": round(safe_capacity_up, 2),
                    "activation_bid": round(safe_activation_up, 2),
                    "vs_market_avg": round(((safe_activation_up - avg_activation_up) / avg_activation_up) * 100, 1),
                    "percentile": round(bid_percentile * 100, 0),
                },
                "afrr_down": {
                    "capacity_bid": round(safe_capacity_down, 2),
                    "activation_bid": round(safe_activation_down, 2),
                }
            },
            "expected_revenue": {
                "monthly": round(safe_total_monthly, 2),
                "annual": round(safe_annual_revenue, 2),
                "capacity_component": round(safe_capacity_revenue_monthly * 12, 2),
                "activation_component": round(safe_activation_revenue_monthly * 12, 2),
            },
            "comparison": {
                "safe_strategy": {
                    "acceptance_rate": target_acceptance_rate,
                    "annual_revenue": round(safe_annual_revenue, 2),
                    "utilization": "95%",
                },
                "aggressive_strategy": {
                    "acceptance_rate": aggressive_acceptance,
                    "annual_revenue": round(aggressive_annual_revenue, 2),
                    "utilization": "65%",
                },
                "advantage": {
                    "additional_revenue_eur": round(revenue_advantage, 2),
                    "advantage_percentage": round(revenue_advantage_pct, 1),
                }
            },
            "market_context": {
                "avg_activation_price": round(avg_activation_up, 2),
                "median_activation_price": round(median_activation_up, 2),
                "your_safe_bid": round(safe_activation_up, 2),
                "interpretation": f"Bidding at {round(safe_activation_up, 2)} EUR/MWh (vs market avg {round(avg_activation_up, 2)}) gives {int(target_acceptance_rate*100)}% acceptance probability"
            }
        }
