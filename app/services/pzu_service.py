"""
PZU (Day-Ahead Market) Service
FIXED VERSION - Correct spread calculation using realistic buy/sell block prices
"""
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import date
import pandas as pd
import numpy as np

from app.config import settings
from app.models.pzu import (
    PZUSimulationParams,
    PZUSimulationResponse,
    PZUMonthlyResult,
    PZUYearlyResult,
    PZUPriceHistory,
    PZUPriceHistoryResponse,
    PZUHourlyPattern,
    PZUTypicalDayResponse,
    PZUMonthlyOptimal,
    PZUMonthlyOptimalResponse,
)


class PZUService:
    """Service for PZU market analysis and simulation"""

    # Constants
    BLOCK_HOURS = 2  # Hours per charge/discharge block
    MIN_REQUIRED_HOURS = 4  # Minimum hours needed per day
    DEFAULT_FX_RON_EUR = 5.0

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or settings.DATA_DIR
        self._price_data: Optional[pd.DataFrame] = None

    def _load_price_data(self) -> pd.DataFrame:
        """Load PZU price history from CSV"""
        if self._price_data is not None:
            return self._price_data

        # Try different file names
        possible_files = [
            "pzu_history.csv",
            "pzu_history_3y.csv",
            "pzu_history_2y.csv",
            "pzu_history_1y.csv",
        ]

        for filename in possible_files:
            filepath = self.data_dir / filename
            if filepath.exists():
                df = pd.read_csv(filepath, parse_dates=["date"])
                self._price_data = df
                return df

        raise FileNotFoundError(f"No PZU price data found in {self.data_dir}")

    def get_price_history(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        aggregate: str = "daily",
    ) -> PZUPriceHistoryResponse:
        """Get price history with optional filtering"""
        df = self._load_price_data()

        # Filter by date range
        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]

        # Get price column (handle different column names)
        price_col = "price" if "price" in df.columns else "price_eur_mwh"
        if price_col not in df.columns:
            # Try to find any price-related column
            price_cols = [c for c in df.columns if "price" in c.lower()]
            if price_cols:
                price_col = price_cols[0]
            else:
                raise ValueError("No price column found in data")

        # Aggregate if needed
        if aggregate == "daily":
            agg_df = df.groupby("date").agg({price_col: "mean"}).reset_index()
        elif aggregate == "monthly":
            df["month"] = df["date"].dt.to_period("M")
            agg_df = df.groupby("month").agg({price_col: "mean"}).reset_index()
            agg_df["date"] = agg_df["month"].apply(lambda x: x.to_timestamp())
            agg_df = agg_df.drop(columns=["month"])
        else:
            agg_df = df

        # Build response
        data = [
            PZUPriceHistory(date=row["date"].date(), price_eur_mwh=row[price_col])
            for _, row in agg_df.iterrows()
        ]

        return PZUPriceHistoryResponse(
            data=data,
            start_date=agg_df["date"].min().date(),
            end_date=agg_df["date"].max().date(),
            count=len(data),
            avg_price=float(agg_df[price_col].mean()),
            min_price=float(agg_df[price_col].min()),
            max_price=float(agg_df[price_col].max()),
        )

    def _compute_daily_arbitrage(
        self,
        daily_prices: pd.DataFrame,
        power_mw: float,
        capacity_mwh: float,
        efficiency: float,
    ) -> Dict[str, Any]:
        """
        Compute arbitrage profit for a single day.
        
        FIXED: Now calculates realistic spread using average of best buy/sell hours
        instead of absolute min/max prices.
        """
        if len(daily_prices) < self.MIN_REQUIRED_HOURS:
            return None

        prices = daily_prices["price"].values if "price" in daily_prices.columns else daily_prices.iloc[:, 1].values

        # Sort prices to find best buy and sell blocks
        sorted_prices = np.sort(prices)
        
        # Best buy hours = lowest N hours (where N = BLOCK_HOURS)
        # Best sell hours = highest N hours
        # This is more realistic than using absolute min/max
        avg_buy_price = float(np.mean(sorted_prices[:self.BLOCK_HOURS]))
        avg_sell_price = float(np.mean(sorted_prices[-self.BLOCK_HOURS:]))
        
        # CORRECT SPREAD = difference between avg sell and avg buy prices
        spread = avg_sell_price - avg_buy_price
        
        # Keep min/max for reference
        min_price = float(np.min(prices))
        max_price = float(np.max(prices))

        # Calculate cycles possible (limited by capacity and power)
        max_cycles = capacity_mwh / (power_mw * self.BLOCK_HOURS)
        cycles = min(max_cycles, 1.0)  # Simplified: max 1 full cycle per day

        # Calculate profit using realistic block prices
        energy_per_cycle = power_mw * self.BLOCK_HOURS
        charge_cost = energy_per_cycle * avg_buy_price
        discharge_revenue = energy_per_cycle * efficiency * avg_sell_price
        gross_profit = (discharge_revenue - charge_cost) * cycles
        net_profit = gross_profit  # Energy cost already factored in

        return {
            "avg_buy_price": avg_buy_price,
            "avg_sell_price": avg_sell_price,
            "min_price": min_price,
            "max_price": max_price,
            "spread": spread,  # Now this is the realistic achievable spread
            "cycles": cycles,
            "gross_profit": gross_profit,
            "net_profit": net_profit,
        }

    def simulate(self, params: PZUSimulationParams) -> PZUSimulationResponse:
        """Run PZU arbitrage simulation"""
        df = self._load_price_data()

        # Filter by date range
        if params.start_date:
            df = df[df["date"] >= pd.Timestamp(params.start_date)]
        if params.end_date:
            df = df[df["date"] <= pd.Timestamp(params.end_date)]

        if df.empty:
            raise ValueError("No data available for the specified date range")

        # Group by day and compute arbitrage
        daily_results = []
        for date_val, day_data in df.groupby(df["date"].dt.date):
            result = self._compute_daily_arbitrage(
                day_data,
                params.power_mw,
                params.capacity_mwh,
                params.round_trip_efficiency,
            )
            if result:
                result["date"] = date_val
                daily_results.append(result)

        if not daily_results:
            raise ValueError("No valid trading days found")

        # Convert to DataFrame for aggregation
        results_df = pd.DataFrame(daily_results)
        results_df["date"] = pd.to_datetime(results_df["date"])
        results_df["month"] = results_df["date"].dt.to_period("M")

        # Aggregate by month - INCLUDE avg_buy_price and avg_sell_price
        monthly_agg = results_df.groupby("month").agg({
            "spread": "mean",
            "avg_buy_price": "mean",
            "avg_sell_price": "mean",
            "cycles": "sum",
            "gross_profit": "sum",
            "net_profit": "sum",
            "date": "count",
        }).reset_index()

        monthly_results = [
            PZUMonthlyResult(
                month=str(row["month"]),
                days=int(row["date"]),
                avg_buy_price_eur_mwh=float(row["avg_buy_price"]),
                avg_sell_price_eur_mwh=float(row["avg_sell_price"]),
                avg_spread_eur_mwh=float(row["spread"]),
                total_cycles=float(row["cycles"]),
                gross_profit_eur=float(row["gross_profit"]),
                net_profit_eur=float(row["net_profit"]),
                avg_daily_profit_eur=float(row["net_profit"] / row["date"]) if row["date"] > 0 else 0,
            )
            for _, row in monthly_agg.iterrows()
        ]

        total_profit = sum(m.net_profit_eur for m in monthly_results)
        avg_monthly = total_profit / len(monthly_results) if monthly_results else 0

        return PZUSimulationResponse(
            params=params,
            monthly_results=monthly_results,
            total_profit_eur=total_profit,
            avg_monthly_profit_eur=avg_monthly,
        )

    def get_market_stats(self) -> Dict[str, Any]:
        """Get overall market statistics"""
        df = self._load_price_data()
        price_col = "price" if "price" in df.columns else df.columns[1]

        return {
            "total_days": len(df["date"].unique()),
            "date_range": {
                "start": str(df["date"].min().date()),
                "end": str(df["date"].max().date()),
            },
            "price_stats": {
                "mean": float(df[price_col].mean()),
                "min": float(df[price_col].min()),
                "max": float(df[price_col].max()),
                "std": float(df[price_col].std()),
            },
        }

    def get_typical_day(self) -> PZUTypicalDayResponse:
        """Get typical daily charge/discharge pattern"""
        df = self._load_price_data()
        
        # Ensure we have hour column
        if "hour" not in df.columns:
            df["hour"] = df["date"].dt.hour
            
        price_col = "price" if "price" in df.columns else df.columns[1]
        
        # Calculate hourly averages
        hourly_avg = df.groupby("hour")[price_col].mean()
        
        # Sort hours by price to find charge/discharge times
        sorted_hours = hourly_avg.sort_values()
        charge_hours = list(sorted_hours.head(self.BLOCK_HOURS).index)
        discharge_hours = list(sorted_hours.tail(self.BLOCK_HOURS).index)
        
        # Build hourly pattern
        hourly_pattern = []
        for hour in range(24):
            if hour in charge_hours:
                action = "charge"
            elif hour in discharge_hours:
                action = "discharge"
            else:
                action = "idle"
            hourly_pattern.append(PZUHourlyPattern(
                hour=hour,
                avg_price_eur_mwh=float(hourly_avg[hour]) if hour in hourly_avg else 0,
                action=action,
            ))
        
        avg_buy = float(hourly_avg[charge_hours].mean())
        avg_sell = float(hourly_avg[discharge_hours].mean())
        
        return PZUTypicalDayResponse(
            hourly_pattern=hourly_pattern,
            charge_hours=charge_hours,
            discharge_hours=discharge_hours,
            avg_buy_price_eur_mwh=avg_buy,
            avg_sell_price_eur_mwh=avg_sell,
            avg_spread_eur_mwh=avg_sell - avg_buy,
            analysis_period_start=df["date"].min().date(),
            analysis_period_end=df["date"].max().date(),
            total_days_analyzed=len(df["date"].dt.date.unique()),
        )

    def get_monthly_optimal(self) -> PZUMonthlyOptimalResponse:
        """Get monthly optimal schedules"""
        df = self._load_price_data()
        
        # Ensure we have hour column
        if "hour" not in df.columns:
            df["hour"] = df["date"].dt.hour
            
        price_col = "price" if "price" in df.columns else df.columns[1]
        df["month"] = df["date"].dt.to_period("M")
        
        monthly_schedules = []
        total_profit = 0
        
        for month, month_df in df.groupby("month"):
            # Get hourly averages for this month
            hourly_avg = month_df.groupby("hour")[price_col].mean()
            
            # Sort to find optimal hours
            sorted_hours = hourly_avg.sort_values()
            charge_hours = list(sorted_hours.head(self.BLOCK_HOURS).index)
            discharge_hours = list(sorted_hours.tail(self.BLOCK_HOURS).index)
            
            avg_buy = float(hourly_avg[charge_hours].mean())
            avg_sell = float(hourly_avg[discharge_hours].mean())
            spread = avg_sell - avg_buy
            
            # Estimate profit for this month (simplified)
            days_in_month = len(month_df["date"].dt.date.unique())
            # Assume 15 MW, 30 MWh battery, 88% efficiency
            energy_per_cycle = 15 * self.BLOCK_HOURS  # 30 MWh
            daily_profit = (avg_sell * 0.88 - avg_buy) * energy_per_cycle
            monthly_profit = daily_profit * days_in_month
            
            monthly_schedules.append(PZUMonthlyOptimal(
                month=str(month),
                charge_hours=charge_hours,
                discharge_hours=discharge_hours,
                avg_buy_price_eur_mwh=avg_buy,
                avg_sell_price_eur_mwh=avg_sell,
                avg_spread_eur_mwh=spread,
                total_profit_eur=monthly_profit,
                days_in_month=days_in_month,
            ))
            total_profit += monthly_profit
        
        return PZUMonthlyOptimalResponse(
            monthly_schedules=monthly_schedules,
            analysis_period_start=df["date"].min().date(),
            analysis_period_end=df["date"].max().date(),
            total_months=len(monthly_schedules),
            total_profit_eur=total_profit,
        )

    def get_monthly_optimal_schedules(
        self,
        start_date: date = None,
        end_date: date = None,
        num_charge_hours: int = 3,
        num_discharge_hours: int = 3,
        power_mw: float = 15.0,
        capacity_mwh: float = 30.0,
        efficiency: float = 0.88,
    ) -> PZUMonthlyOptimalResponse:
        """Get monthly optimal schedules with custom parameters"""
        df = self._load_price_data()
        
        # Filter by date range if provided
        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]
        
        # Ensure we have hour column
        if "hour" not in df.columns:
            df["hour"] = df["date"].dt.hour
            
        price_col = "price" if "price" in df.columns else df.columns[1]
        df["month"] = df["date"].dt.to_period("M")
        
        monthly_schedules = []
        total_profit = 0
        
        for month, month_df in df.groupby("month"):
            # Get hourly averages for this month
            hourly_avg = month_df.groupby("hour")[price_col].mean()
            
            # Sort to find optimal hours
            sorted_hours = hourly_avg.sort_values()
            charge_hours = list(sorted_hours.head(num_charge_hours).index)
            discharge_hours = list(sorted_hours.tail(num_discharge_hours).index)
            
            # Convert numpy int64 to Python int
            charge_hours = [int(h) for h in charge_hours]
            discharge_hours = [int(h) for h in discharge_hours]
            
            avg_buy = float(hourly_avg[charge_hours].mean())
            avg_sell = float(hourly_avg[discharge_hours].mean())
            spread = avg_sell - avg_buy
            
            # Estimate profit for this month
            days_in_month = len(month_df["date"].dt.date.unique())
            energy_per_cycle = power_mw * num_charge_hours
            daily_profit = (avg_sell * efficiency - avg_buy) * energy_per_cycle
            monthly_profit = daily_profit * days_in_month
            
            monthly_schedules.append(PZUMonthlyOptimal(
                month=str(month),
                charge_hours=charge_hours,
                discharge_hours=discharge_hours,
                avg_buy_price_eur_mwh=avg_buy,
                avg_sell_price_eur_mwh=avg_sell,
                avg_spread_eur_mwh=spread,
                total_profit_eur=monthly_profit,
                days_in_month=days_in_month,
            ))
            total_profit += monthly_profit
        
        return PZUMonthlyOptimalResponse(
            monthly_schedules=monthly_schedules,
            analysis_period_start=df["date"].min().date(),
            analysis_period_end=df["date"].max().date(),
            total_months=len(monthly_schedules),
            total_profit_eur=total_profit,
        )

    def get_daily_breakdown(
        self,
        month: str,  # Format: "2024-01"
        power_mw: float = 15.0,
        capacity_mwh: float = 30.0,
        efficiency: float = 0.90,
    ) -> dict:
        """Get daily breakdown for a specific month"""
        df = self._load_price_data()
        
        # Parse month and filter
        year, month_num = map(int, month.split('-'))
        df = df[
            (df["date"].dt.year == year) & 
            (df["date"].dt.month == month_num)
        ]
        
        if df.empty:
            return {"daily_results": [], "month": month}
        
        # Ensure we have hour column
        if "hour" not in df.columns:
            df["hour"] = df["date"].dt.hour
            
        price_col = "price" if "price" in df.columns else df.columns[1]
        
        daily_results = []
        
        for day, day_df in df.groupby(df["date"].dt.date):
            if len(day_df) < 24:
                continue
                
            # Get hourly prices for this day
            hourly = day_df.groupby("hour")[price_col].mean()
            sorted_hours = hourly.sort_values()
            
            # Get best buy (lowest) and sell (highest) hours
            buy_hours = list(sorted_hours.head(self.BLOCK_HOURS).index)
            sell_hours = list(sorted_hours.tail(self.BLOCK_HOURS).index)
            
            buy_hours = [int(h) for h in buy_hours]
            sell_hours = [int(h) for h in sell_hours]
            
            avg_buy = float(hourly[buy_hours].mean())
            avg_sell = float(hourly[sell_hours].mean())
            spread = avg_sell - avg_buy
            
            # Calculate profit for this day
            energy = capacity_mwh
            profit = (avg_sell * efficiency - avg_buy) * energy
            
            daily_results.append({
                "date": str(day),
                "day_of_week": day.strftime("%a"),
                "buy_hours": buy_hours,
                "sell_hours": sell_hours,
                "avg_buy_price": round(avg_buy, 2),
                "avg_sell_price": round(avg_sell, 2),
                "spread": round(spread, 2),
                "profit": round(profit, 2),
                "min_price": round(float(hourly.min()), 2),
                "max_price": round(float(hourly.max()), 2),
            })
        
        return {
            "month": month,
            "daily_results": daily_results,
            "total_days": len(daily_results),
            "total_profit": round(sum(d["profit"] for d in daily_results), 2),
            "avg_daily_profit": round(sum(d["profit"] for d in daily_results) / len(daily_results), 2) if daily_results else 0,
        }

    def get_available_dates(self) -> dict:
        """Get list of available dates with summary stats"""
        df = self._load_price_data()

        price_col = "price" if "price" in df.columns else df.columns[1]

        # Group by date and get stats
        daily_stats = df.groupby(df["date"].dt.date).agg({
            price_col: ["min", "max", "mean", "count"]
        }).reset_index()

        daily_stats.columns = ["date", "min_price", "max_price", "avg_price", "hours"]

        dates = []
        for _, row in daily_stats.iterrows():
            dates.append({
                "date": str(row["date"]),
                "min_price": round(float(row["min_price"]), 2),
                "max_price": round(float(row["max_price"]), 2),
                "avg_price": round(float(row["avg_price"]), 2),
                "spread": round(float(row["max_price"] - row["min_price"]), 2),
                "hours": int(row["hours"]),
            })

        return {
            "dates": dates,
            "total_days": len(dates),
            "date_range": {
                "start": dates[0]["date"] if dates else None,
                "end": dates[-1]["date"] if dates else None,
            }
        }

    def get_hourly_prices(self, date_str: str, power_mw: float = 15.0, capacity_mwh: float = 30.0, efficiency: float = 0.88) -> dict:
        """Get hourly prices for a specific date with energy costs calculated"""
        df = self._load_price_data()

        # Parse date
        target_date = pd.to_datetime(date_str).date()

        # Filter for specific date
        day_df = df[df["date"].dt.date == target_date]

        if day_df.empty:
            return {"error": f"No data for date {date_str}", "hourly_prices": []}

        price_col = "price" if "price" in day_df.columns else day_df.columns[1]

        # Ensure we have hour column
        if "hour" not in day_df.columns:
            day_df = day_df.copy()
            day_df["hour"] = day_df["date"].dt.hour

        # Sort by hour and get hourly prices
        hourly = day_df.groupby("hour")[price_col].mean().sort_index()

        # Find optimal charge/discharge hours
        sorted_hours = hourly.sort_values()
        charge_hours = list(sorted_hours.head(self.BLOCK_HOURS).index)
        discharge_hours = list(sorted_hours.tail(self.BLOCK_HOURS).index)

        # Calculate energy costs for each hour
        hourly_data = []
        for hour in range(24):
            if hour in hourly.index:
                price = float(hourly[hour])

                # Determine action and calculate energy cost
                if hour in charge_hours:
                    action = "charge"
                    # Energy cost = price × power × 1 hour
                    energy_cost = price * power_mw
                    energy_mwh = power_mw
                elif hour in discharge_hours:
                    action = "discharge"
                    # Revenue = price × power × efficiency × 1 hour
                    energy_cost = -price * power_mw * efficiency  # Negative = revenue
                    energy_mwh = power_mw * efficiency
                else:
                    action = "idle"
                    energy_cost = 0
                    energy_mwh = 0

                hourly_data.append({
                    "hour": hour,
                    "price_eur_mwh": round(price, 2),
                    "action": action,
                    "energy_cost_eur": round(energy_cost, 2),
                    "energy_mwh": round(energy_mwh, 2),
                })
            else:
                hourly_data.append({
                    "hour": hour,
                    "price_eur_mwh": None,
                    "action": "no_data",
                    "energy_cost_eur": 0,
                    "energy_mwh": 0,
                })

        # Calculate summary
        avg_buy = float(hourly[charge_hours].mean()) if charge_hours else 0
        avg_sell = float(hourly[discharge_hours].mean()) if discharge_hours else 0
        spread = avg_sell - avg_buy

        # Daily profit calculation
        energy_per_cycle = power_mw * self.BLOCK_HOURS
        daily_profit = (avg_sell * efficiency - avg_buy) * energy_per_cycle

        # Calculate total energy cost (for charging)
        total_charge_cost = sum(h["energy_cost_eur"] for h in hourly_data if h["action"] == "charge")
        total_discharge_revenue = abs(sum(h["energy_cost_eur"] for h in hourly_data if h["action"] == "discharge"))

        return {
            "date": date_str,
            "day_of_week": target_date.strftime("%A"),
            "hourly_prices": hourly_data,
            "charge_hours": [int(h) for h in sorted(charge_hours)],
            "discharge_hours": [int(h) for h in sorted(discharge_hours)],
            "avg_buy_price": round(avg_buy, 2),
            "avg_sell_price": round(avg_sell, 2),
            "spread": round(spread, 2),
            "min_price": round(float(hourly.min()), 2),
            "max_price": round(float(hourly.max()), 2),
            "avg_price": round(float(hourly.mean()), 2),
            "daily_profit": round(daily_profit, 2),
            "total_charge_cost": round(total_charge_cost, 2),
            "total_discharge_revenue": round(total_discharge_revenue, 2),
            "opcom_url": "https://www.opcom.ro/grafice-ip-raportPIP-si-volumTranzactionat/en",
        }
