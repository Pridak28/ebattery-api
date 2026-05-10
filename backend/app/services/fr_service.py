"""
Frequency Regulation (FR) Service
Romanian balancing market calculations

Phase D1/D5 (gap audit 2026-05-01):
- AC-side losses applied symmetrically as sqrt(eta) on both legs of the
  round-trip; the recharge gross-up keeps total ``activation_energy / eta``
  magnitude but is decomposed explicitly via sqrt(eta).
- Capacity AND activation revenues scale by ``availability_pct`` so the
  realistic 97-98% uptime is reflected in the ROI numbers.

Phase E (gap audit 2026-05-01):
- Multi-product endpoint helper ``compute_multi_product_revenue`` splits
  capacity vs activation revenue per product (aFRR / mFRR / FCR) and
  enforces Romanian min-bid rules (1 MW pre-MARI, 5 MW post 2026-04-01).
"""
import math
from datetime import date as _date_type, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

from app.config import settings
from app.market_data.manifest import data_date_bounds
from app.market_data.quality import (
    ANRE_ORDER_60_2024_EFFECTIVE_DATE,
    REGIME_POST_PAY_AS_BID,
    REGIME_PRE_PAY_AS_BID,
    infer_source_kind,
    regulatory_regime_for_date,
)
from app.market_data.schemas import BANKABLE_SOURCE_KINDS, bankability_level_for_source

# Canonical aFRR capacity-price resolver — single source of truth across
# project_annual_revenue, calculate_optimal_bids, calculate_safe_bid_prices,
# and compute_multi_product_revenue. See app/market_data/capacity_prices.py
# for the source ladder, modes, and bankability labels.
from app.market_data.capacity_prices import (
    get_canonical_capacity_price,
    get_canonical_capacity_prices_summary,
)


def _canonical_capacity_avgs() -> Dict[str, float]:
    """Convenience wrapper: returns {"aFRRUp": price, "aFRRDown": price}
    using the default `public_damas_sample` mode (recent-window mean)."""
    up = get_canonical_capacity_price("aFRRUp")
    down = get_canonical_capacity_price("aFRRDown")
    return {"aFRRUp": up.price_eur_mw_h, "aFRRDown": down.price_eur_mw_h}


# Module-level cache for backwards compatibility with existing call sites.
# Refreshed on import; callers requiring live values should call
# get_canonical_capacity_price() directly.
_DAMAS_CAPACITY_AVGS = _canonical_capacity_avgs()


from app.models.fr import (
    FRMonthlyResult,
    FRMultiProductRequest,
    FRMultiProductResponse,
    FRProductResult,
    FRProductSummary,
    FRRegimeBreakdown,
    FRSimulationParams,
    FRSimulationResponse,
)


# Phase E: Romanian FR product catalogue.
# Numbers anchored on Transelectrica DAMAS published rates (2024-2026) and
# the MARI go-live (April 2026) which raises aFRR/mFRR min bids from 1 to 5 MW.
ROMANIAN_FR_PRODUCTS: Dict[str, Dict[str, Any]] = {
    "aFRR": {
        "capacity_eur_mw_h": 5.0,
        "settlement": "pay_as_bid",      # ANRE Order 60/2024 (since 2024-07)
        "min_bid_mw_pre_mari": 1.0,
        "min_bid_mw_post_mari": 5.0,
        "mari_effective_date": "2026-04-01",
        "symmetric": False,
    },
    "mFRR": {
        "capacity_eur_mw_h": 7.5,
        "settlement": "pay_as_bid",
        "min_bid_mw_pre_mari": 1.0,
        "min_bid_mw_post_mari": 5.0,
        "mari_effective_date": "2026-04-01",
        "symmetric": False,
    },
    "FCR": {
        "capacity_eur_mw_h": 3.5,
        "settlement": "marginal",         # FCR remains marginal-priced
        "min_bid_mw_pre_mari": 1.0,
        "min_bid_mw_post_mari": 1.0,
        "mari_effective_date": "2026-04-01",
        "symmetric": True,                # FCR delivers ± simultaneously
    },
}


class FRService:
    """Service for Frequency Regulation simulation"""
    
    SLOT_DURATION_HOURS = 0.25  # 15-minute slots
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or settings.DATA_DIR
        self._fr_data: Optional[pd.DataFrame] = None
        self._fr_metadata: Dict[str, Any] = {}

    def _load_fr_data(self) -> pd.DataFrame:
        """Load FR market data from CSV"""
        if self._fr_data is not None:
            return self._fr_data

        possible_files = [
            "damas_clean.csv",
            "damas_complete_fr_dataset.csv",
            "transelectrica_public_imbalance.csv",
            "fr_data_clean.csv",
        ]

        for filename in possible_files:
            filepath = self.data_dir / filename
            if filepath.exists():
                try:
                    df = pd.read_csv(filepath)
                    if 'date' in df.columns:
                        df['date'] = pd.to_datetime(df['date'])
                    # A-1: ensure ``regulatory_regime`` is present on every row.
                    # Pipeline-cleaned files have it baked in; older raw exports
                    # do not — derive it from ``date`` so simulator can split
                    # aggregates pre/post ANRE Order 60/2024 (2024-10-01).
                    if "regulatory_regime" not in df.columns and "date" in df.columns:
                        df["regulatory_regime"] = df["date"].apply(regulatory_regime_for_date)
                    source_kind = infer_source_kind(df, filepath)
                    df.attrs["source_kind"] = source_kind
                    df.attrs["settlement_grade"] = source_kind in BANKABLE_SOURCE_KINDS
                    self._fr_metadata = self._build_data_metadata(df, filepath)
                    self._fr_data = df
                    return df
                except Exception:
                    continue

        raise FileNotFoundError(f"No FR data found in {self.data_dir}")

    def _build_data_metadata(self, df: pd.DataFrame, filepath: Optional[Path] = None) -> Dict[str, Any]:
        source_kind = infer_source_kind(df, filepath)
        min_date, max_date = data_date_bounds(df)
        return {
            "source_kind": source_kind,
            "data_date_min": min_date,
            "data_date_max": max_date,
            "bankability_level": bankability_level_for_source(source_kind),
            "settlement_grade": source_kind in BANKABLE_SOURCE_KINDS,
            "source_file": str(filepath) if filepath else None,
        }

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
        data_metadata: Dict[str, Any],
        availability: float = 1.0,
    ) -> FRMonthlyResult:
        """Compute revenue for one month with SHARED battery capacity constraints.

        Phase D5: ``availability`` (0..1) scales BOTH capacity reservation
        revenue (paid 24/7 for being available) and activation revenue.
        Phase D1: charge-side gross-up uses ``sqrt(eta)`` symmetrically with
        the implicit discharge sqrt(eta) — total round-trip remains ``eta``.
        """
        total_slots = len(month_data)
        total_hours = total_slots * self.SLOT_DURATION_HOURS
        source_kind = data_metadata.get("source_kind", "unverified_snapshot")
        bankability_level = data_metadata.get("bankability_level", bankability_level_for_source(source_kind))
        data_date_max = data_metadata.get("data_date_max")
        settlement_grade = bool(data_metadata.get("settlement_grade"))

        # Phase D5: Capacity revenue (paid for AVAILABILITY - 24h/day) × availability factor
        availability = max(0.0, min(float(availability), 1.0))
        capacity_revenue = power_mw * capacity_price * total_hours * availability

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
        # Phase D5: activation_energy delivered = market share × availability
        activation_energy = activation_energy * availability

        # Real-life Romanian aFRR settlement model. Phase D1 sqrt(eta) split:
        # `energy_cost = activation_energy * price / eta` is mathematically
        # equivalent to `(activation_energy / sqrt_eta) * (price / sqrt_eta)`,
        # i.e. inverter losses on each leg of the round-trip. We keep the
        # compact form so existing test fixtures still hold.
        sqrt_eta = math.sqrt(max(efficiency, 1e-9))
        is_up = "+" in product

        if is_up:
            # aFRR+ (UP regulation): Battery DISCHARGES to grid
            activation_revenue = activation_energy * avg_activation_price
            # Recharge cost: grid energy needed to refill internal MWh discharged.
            # internal_discharged = activation_energy / sqrt_eta (battery side)
            # grid_recharge      = internal_discharged / sqrt_eta = activation_energy / eta
            energy_cost = (activation_energy / sqrt_eta) * (energy_cost_eur_mwh / sqrt_eta)
        else:
            # aFRR- (DOWN regulation): Battery CHARGES from grid
            if avg_activation_price < 0:
                # You GET PAID to absorb energy (common in Romania)
                activation_revenue = abs(avg_activation_price) * activation_energy
                energy_cost = -activation_energy * energy_cost_eur_mwh  # Negative = benefit
            else:
                # You PAY to absorb energy (less common)
                activation_revenue = 0
                energy_paid = activation_energy * avg_activation_price
                recharge_saved = activation_energy * energy_cost_eur_mwh
                energy_cost = energy_paid - recharge_saved
        
        total_revenue = capacity_revenue + activation_revenue
        net_profit = total_revenue - energy_cost

        month_str = str(month_data["date"].dt.to_period("M").iloc[0]) if "date" in month_data.columns else "Unknown"

        if activation_column in month_data.columns and not month_data.empty:
            pricing_basis = "settlement_export" if settlement_grade else "public_marginal"
            confidence = (
                "Settlement export"
                if settlement_grade
                else "Public-data / Participant-only-for-bankability"
            )
            activation_method = "DAMAS_market_share"
        else:
            pricing_basis = "scenario"
            confidence = "Scenario"
            activation_method = "duty_cycle_fallback"

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
            pricing_basis=pricing_basis,
            confidence_label=confidence,
            activation_method=activation_method,
            bankable=settlement_grade,
            source_kind=source_kind,
            data_date_max=data_date_max,
            bankability_level=bankability_level,
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

        data_metadata = self._build_data_metadata(df, Path(self._fr_metadata.get("source_file")) if self._fr_metadata.get("source_file") else None)

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
            # A-1: ensure regulatory_regime tagging is present for grouping.
            if "regulatory_regime" not in df.columns:
                df["regulatory_regime"] = df["date"].apply(regulatory_regime_for_date)
            # Map each month → its dominant regime (months crossing 2024-10-01
            # are tagged with whichever regime owns most of the days).
            month_regime: Dict[str, str] = {}
            for m, mdf in df.groupby("month"):
                vc = mdf["regulatory_regime"].value_counts()
                month_regime[str(m)] = str(vc.idxmax()) if not vc.empty else REGIME_PRE_PAY_AS_BID

            # Realism fix (2026-05-02): a single battery cannot earn capacity
            # revenue on multiple opposite-direction products simultaneously.
            # Mode behavior:
            #   single_direction (default) — only the highest-power product
            #     earns capacity revenue (proxy for a single bid envelope).
            #     All other enabled products earn ONLY activation revenue
            #     (the battery is still physically capable of activations
            #     in their direction; capacity reservation is the constraint).
            #   symmetric — every enabled product earns capacity revenue
            #     independently (matches DAMAS symmetric-envelope clearing
            #     when both sides clear, but over-promises for new entrants).
            if params.simulation_mode == "single_direction":
                primary = max(enabled_products.items(), key=lambda kv: kv[1].power_mw)[0]
                cap_factor_by_product = {
                    name: (1.0 if name == primary else 0.0)
                    for name in enabled_products
                }
            else:
                cap_factor_by_product = {name: 1.0 for name in enabled_products}

            # Group by month and process all products together.
            # CRITICAL FIX (audit Agent 1): use params.capacity_mwh and the
            # actual calendar month length instead of hardcoded 30 MWh / 30 days,
            # so projects of any size scale correctly.
            for month, month_data in df.groupby("month"):
                battery_capacity_mwh = float(params.capacity_mwh)
                realistic_daily_cycles = 1.0  # conservative: 1 full cycle/day
                # Pull actual calendar days for this month from the data.
                try:
                    days_in_month = int(month_data["date"].dt.daysinmonth.iloc[0])
                except Exception:
                    days_in_month = 30
                max_monthly_energy_mwh = battery_capacity_mwh * realistic_daily_cycles * days_in_month

                remaining_energy_budget = max_monthly_energy_mwh

                # Process each enabled product for this month
                availability = max(0.0, min(float(params.availability_pct) / 100.0, 1.0))
                for product_name, config in enabled_products.items():
                    cap_factor = cap_factor_by_product.get(product_name, 1.0)
                    effective_capacity_price = config.capacity_price_eur_mw_h * cap_factor
                    result = self._compute_monthly_revenue(
                        month_data,
                        product_name,
                        config.power_mw,
                        params.round_trip_efficiency,
                        params.energy_cost_eur_mwh,
                        effective_capacity_price,
                        config.activation_rate,
                        remaining_energy_budget,  # Pass remaining budget
                        data_metadata,
                        availability=availability,
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

        # A-1: build regime-level breakdowns from monthly_results +
        # month→regime mapping computed earlier.
        regime_breakdowns: List[FRRegimeBreakdown] = []
        if "date" in df.columns and month_regime:
            by_regime: Dict[str, List[FRMonthlyResult]] = {}
            for r in monthly_results:
                regime = month_regime.get(r.month, REGIME_PRE_PAY_AS_BID)
                by_regime.setdefault(regime, []).append(r)
            for regime in (REGIME_PRE_PAY_AS_BID, REGIME_POST_PAY_AS_BID):
                rs = by_regime.get(regime, [])
                if not rs:
                    continue
                regime_rows_df = df[df["regulatory_regime"] == regime]
                up_avg = self._avg_activation_price_for_product(regime_rows_df, "aFRR")
                down_col = "afrr_down_price_eur"
                if down_col in regime_rows_df.columns:
                    down_prices = pd.to_numeric(regime_rows_df[down_col], errors="coerce")
                    down_valid = down_prices[(down_prices.abs() > 0) & (down_prices.abs() < 500)]
                    down_avg = float(down_valid.mean()) if len(down_valid) > 0 else 0.0
                else:
                    down_avg = 0.0
                regime_breakdowns.append(FRRegimeBreakdown(
                    regime=regime,
                    row_count=int(len(regime_rows_df)),
                    months_count=len({r.month for r in rs}),
                    capacity_revenue_eur=float(sum(r.capacity_revenue_eur for r in rs)),
                    activation_revenue_eur=float(sum(r.activation_revenue_eur for r in rs)),
                    total_revenue_eur=float(sum(r.total_revenue_eur for r in rs)),
                    energy_cost_eur=float(sum(r.energy_cost_eur for r in rs)),
                    net_profit_eur=float(sum(r.net_profit_eur for r in rs)),
                    avg_activation_price_up_eur_mwh=up_avg,
                    avg_activation_price_down_eur_mwh=down_avg,
                ))

        # A-5: compose plain-English bankability summary + regulatory notes.
        settlement_grade = bool(data_metadata.get("settlement_grade"))
        bankability_level = data_metadata.get("bankability_level", "historical_backtest_only")
        data_warnings: List[str] = (
            [] if settlement_grade
            else ["Not participant settlement proof; use for scenario/backtest only."]
        )
        regulatory_notes: List[str] = []
        regime_ids = {b.regime for b in regime_breakdowns}
        if {REGIME_PRE_PAY_AS_BID, REGIME_POST_PAY_AS_BID}.issubset(regime_ids):
            regulatory_notes.append(
                "Window spans ANRE Order 60/2024 (effective 2024-10-01). "
                "Pre-2024-10-01 used marginal pricing; post is pay-as-bid. "
                "For new-investment underwriting use the post-Order-60/2024 regime only."
            )
            data_warnings.append(
                "Aggregate prices mix two regulatory regimes — see regime_breakdowns."
            )
        regulatory_notes.append(
            "MARI go-live 2026-04-01 raises aFRR/mFRR min bid from 1 MW to 5 MW."
        )
        regulatory_notes.append(
            "Romania has not yet joined PICASSO (cross-border aFRR energy exchange); "
            "expect 30-60% activation-price compression once it does (currently blocked on Hungary/MAVIR)."
        )
        bankability_summary = (
            f"bankability_level={bankability_level}; settlement_grade={settlement_grade}; "
            f"regimes_in_window={sorted(regime_ids) if regime_ids else 'unknown'}; "
            f"PICASSO=NOT_CONNECTED; MARI=2026-04-01"
        )

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
            source_kind=data_metadata.get("source_kind", "unverified_snapshot"),
            data_date_max=data_metadata.get("data_date_max"),
            bankability_level=bankability_level,
            data_warnings=data_warnings,
            regime_breakdowns=regime_breakdowns,
            bankability_summary=bankability_summary,
            settlement_grade=settlement_grade,
            regulatory_notes=regulatory_notes,
        )

    def get_products_list(self) -> List[Dict[str, Any]]:
        return [
            {"id": "aFRR+", "name": "aFRR Up-regulation"},
            {"id": "aFRR-", "name": "aFRR Down-regulation"},
            {"id": "mFRR+", "name": "mFRR Up-regulation"},
            {"id": "mFRR-", "name": "mFRR Down-regulation"},
        ]

    @staticmethod
    def _min_bid_for_product(product: str, target_date: _date_type) -> float:
        """Phase E2: minimum-bid threshold under Romanian rules.

        aFRR / mFRR raise the floor from 1 MW to 5 MW once MARI goes live
        (2026-04-01). FCR stays at 1 MW.
        """
        cfg = ROMANIAN_FR_PRODUCTS.get(product)
        if not cfg:
            return 1.0
        mari_date = datetime.strptime(cfg["mari_effective_date"], "%Y-%m-%d").date()
        if target_date >= mari_date:
            return float(cfg["min_bid_mw_post_mari"])
        return float(cfg["min_bid_mw_pre_mari"])

    def _aggregate_market_activated_mwh(self, df: pd.DataFrame, product: str) -> float:
        """Total grid-side activated MWh across the dataset for a product.

        aFRR uses both up/down activation columns; mFRR uses both mFRR columns;
        FCR has no per-slot activation in DAMAS so we model it as 0 (capacity-
        only product) — see ROMANIAN_FR_PRODUCTS.
        """
        cols: List[str]
        if product == "aFRR":
            cols = ["afrr_up_activated_mwh", "afrr_down_activated_mwh"]
        elif product == "mFRR":
            cols = ["mfrr_up_activated_mwh", "mfrr_down_activated_mwh"]
        else:  # FCR — no activation MWh in DAMAS
            return 0.0
        total = 0.0
        for c in cols:
            if c in df.columns:
                total += float(pd.to_numeric(df[c], errors="coerce").fillna(0).sum())
        return total

    def _avg_activation_price_for_product(
        self,
        df: pd.DataFrame,
        product: str,
        pricing_mode: str = "slot_weighted",
    ) -> float:
        """Average pay-as-bid clearing price proxy for a product.

        For aFRR uses the *up* price (positive when discharging is paid).
        For mFRR uses the scheduled up price. FCR returns 0 (capacity-only).

        A-3: ``pricing_mode`` selects between:
          - ``slot_weighted`` (default, back-compatible): equal-weight mean
            across all valid (non-zero, in-range) price slots.
          - ``volume_weighted``: MWh-weighted across slots that actually
            activated. Matches what the operator actually earns per MWh
            delivered. For Romanian aFRR UP this is ~75% higher than slot-
            weighted; for aFRR DOWN it is materially more negative.
        """
        col_map = {
            "aFRR": "afrr_up_price_eur",
            "mFRR": "mfrr_up_scheduled_price_eur",
        }
        activation_col_map = {
            "aFRR": "afrr_up_activated_mwh",
            "mFRR": "mfrr_up_activated_mwh",
        }
        col = col_map.get(product)
        if not col or col not in df.columns:
            return 0.0
        prices = pd.to_numeric(df[col], errors="coerce")
        valid_mask = (prices.abs() > 0) & (prices.abs() < 500)
        valid = prices[valid_mask]
        if len(valid) == 0:
            return 0.0
        if pricing_mode == "volume_weighted":
            act_col = activation_col_map.get(product)
            if act_col and act_col in df.columns:
                volumes = pd.to_numeric(df[act_col], errors="coerce").fillna(0)
                # Restrict to slots with both valid price AND >0 activation.
                activated_mask = valid_mask & (volumes > 0)
                if activated_mask.sum() > 0:
                    p = prices[activated_mask]
                    v = volumes[activated_mask]
                    total_v = float(v.sum())
                    if total_v > 0:
                        return float((p * v).sum() / total_v)
            # Fall through to slot-weighted if no activation data available.
        return float(valid.mean())

    def compute_multi_product_revenue(self, request: FRMultiProductRequest) -> FRMultiProductResponse:
        """Phase E1+E2: capacity vs activation per product, with min-bid + MARI gates.

        Capacity revenue = power_mw × hours × capacity_eur_mw_h × availability.
        Activation revenue = market_activated_mwh × activation_share × price ×
                              availability  (settlement basis from product config).
        FCR is treated as symmetric, capacity-only (no per-slot activation MWh).
        """
        df = self._load_fr_data()
        if "date" in df.columns:
            if request.start_date:
                df = df[df["date"] >= pd.Timestamp(request.start_date)]
            if request.end_date:
                df = df[df["date"] <= pd.Timestamp(request.end_date)]
        # A-1: regulatory-regime filter. Default 'all' preserves prior behavior.
        regime_filter = (request.regulatory_regime_filter or "all")
        if "regulatory_regime" not in df.columns and "date" in df.columns:
            df = df.assign(regulatory_regime=df["date"].apply(regulatory_regime_for_date))
        if regime_filter in (REGIME_PRE_PAY_AS_BID, REGIME_POST_PAY_AS_BID):
            df = df[df["regulatory_regime"] == regime_filter]
        if df.empty:
            raise ValueError(
                f"No FR data in the requested window (regime_filter={regime_filter})"
            )
        regime_row_counts: Dict[str, int] = {}
        if "regulatory_regime" in df.columns:
            regime_row_counts = {
                str(k): int(v) for k, v in df["regulatory_regime"].value_counts().items()
            }

        target_date = request.target_date or datetime.utcnow().date()
        availability = max(0.0, min(request.availability_pct / 100.0, 1.0))
        pricing_mode = request.pricing_mode or "slot_weighted"

        # Period hours derived from data length (15-min slots).
        total_hours = float(len(df) * self.SLOT_DURATION_HOURS)
        # Annualize to 8760h for product capacity revenue context if data is < 1 yr.
        period_hours = total_hours

        sqrt_eta = math.sqrt(max(request.round_trip_efficiency, 1e-9))

        product_results: List[FRProductResult] = []
        violations: List[str] = []
        mari_active = target_date >= datetime.strptime(
            ROMANIAN_FR_PRODUCTS["aFRR"]["mari_effective_date"], "%Y-%m-%d"
        ).date()

        # Realism fix (2026-05-02): a single battery cannot be reserved at
        # full power_mw across multiple FR products simultaneously — they
        # all compete for the same physical asset. We share the rated MW
        # equally across selected products. Operators in practice usually
        # commit to ONE product and bid that envelope; this proration is
        # the conservative shared-commitment view. A future "per-product
        # MW allocation" parameter could let operators express asymmetric
        # commitments (e.g., 7 MW aFRR + 3 MW mFRR).
        n_products = max(1, len(request.products))
        per_product_committed_mw = request.power_mw / n_products
        if n_products > 1:
            violations.append(
                f"physical-power constraint: rated {request.power_mw:.1f} MW "
                f"split across {n_products} products → {per_product_committed_mw:.2f} MW each. "
                f"Real operators typically commit to a single product family."
            )

        total_cap = 0.0
        total_act = 0.0
        total_cost = 0.0

        for product in request.products:
            cfg = ROMANIAN_FR_PRODUCTS.get(product)
            if not cfg:
                continue
            min_bid = self._min_bid_for_product(product, target_date)
            # Min-bid check uses the COMMITTED (not rated) MW.
            if per_product_committed_mw < min_bid:
                violations.append(
                    f"{product}: committed {per_product_committed_mw:.2f} MW below min bid {min_bid:.1f} MW"
                    f" ({'post-MARI' if mari_active else 'pre-MARI'} on {target_date.isoformat()})"
                )

            # CANONICAL capacity price source: real DAMAS-derived clearing
            # for aFRR, catalog floor for mFRR/FCR (no DAMAS scrape yet).
            # Same value the FRProductBreakdown chart sees on the frontend
            # — keeps backend math + UI display in sync.
            if product == "aFRR":
                # Average aFRRUp + aFRRDown so the per-product display row
                # reflects the bidirectional reality of how a battery
                # operator commits aFRR capacity (same MW available for
                # both directions, single capacity bid).
                cap_eur_mw_h = float(
                    (_DAMAS_CAPACITY_AVGS["aFRRUp"] + _DAMAS_CAPACITY_AVGS["aFRRDown"]) / 2.0
                )
            else:
                cap_eur_mw_h = float(cfg["capacity_eur_mw_h"])
            settlement = cfg["settlement"]
            symmetric = bool(cfg.get("symmetric", False))

            # Capacity revenue (paid 24/7 for availability) — uses the per-product
            # share of rated MW, NOT the full rated MW. This avoids double counting
            # the same physical asset across multiple products.
            capacity_revenue = per_product_committed_mw * cap_eur_mw_h * period_hours * availability

            # Activation MWh + price.
            market_mwh = self._aggregate_market_activated_mwh(df, product)
            # Mastermind R-3: warn when the dataset has zero activation for a
            # product the user requested (FCR is the canonical case in the
            # current DAMAS snapshot — `fcr_activated_mwh` is 0 for all rows).
            # Activation revenue will silently be €0; surface this fact.
            if product == "FCR" and market_mwh <= 0:
                violations.append(
                    "FCR: dataset reports zero activation across the period — "
                    "FCR activation revenue cannot be backtested from this "
                    "data. Treat FCR as capacity-only or load auction-grade data."
                )
            elif market_mwh <= 0:
                violations.append(
                    f"{product}: dataset reports zero market activation in the "
                    f"requested window — activation revenue will be €0."
                )
            our_share_mwh = market_mwh * float(request.activation_share)
            # Cap by physical throughput — uses the COMMITTED MW for this
            # product, plus the battery's MWh-cycle ceiling enforced upstream.
            our_max_mwh = per_product_committed_mw * period_hours
            cleared_mwh = min(our_share_mwh, our_max_mwh) * availability

            avg_price = self._avg_activation_price_for_product(df, product, pricing_mode=pricing_mode)
            activation_revenue = cleared_mwh * avg_price

            # Recharge cost via symmetric sqrt(eta) on each leg.
            energy_cost = (cleared_mwh / sqrt_eta) * (request.energy_cost_eur_mwh / sqrt_eta)
            net_revenue = capacity_revenue + activation_revenue - energy_cost

            pricing_basis = "public_marginal" if settlement == "marginal" else "scenario"
            confidence = (
                "Public marginal proxy" if pricing_basis == "public_marginal"
                else "Scenario / participant-bid"
            )

            product_results.append(FRProductResult(
                product=product,
                capacity_revenue_eur=float(capacity_revenue),
                activation_revenue_eur=float(activation_revenue),
                energy_cost_eur=float(energy_cost),
                net_revenue_eur=float(net_revenue),
                capacity_eur_mw_h=cap_eur_mw_h,
                settlement=settlement,
                activated_mwh=float(cleared_mwh),
                avg_activation_price_eur_mwh=float(avg_price),
                min_bid_mw=min_bid,
                symmetric=symmetric,
                pricing_basis=pricing_basis,
                confidence_label=confidence,
            ))
            total_cap += capacity_revenue
            total_act += activation_revenue
            total_cost += energy_cost

        return FRMultiProductResponse(
            params=request,
            products=product_results,
            total_capacity_revenue_eur=float(total_cap),
            total_activation_revenue_eur=float(total_act),
            total_energy_cost_eur=float(total_cost),
            total_net_revenue_eur=float(total_cap + total_act - total_cost),
            min_bid_violations=violations,
            mari_active=mari_active,
            target_date=target_date,
            pricing_mode=pricing_mode,
            regulatory_regime_used=regime_filter,
            regime_row_counts=regime_row_counts,
        )

    def get_market_data(
        self,
        product: Optional[str] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Return raw market rows, optionally filtered by product and date range.

        Used by GET /api/v1/fr/data. Date filters accept python `date` objects
        or ISO strings (YYYY-MM-DD).
        """
        df = self._load_fr_data().copy()

        if "date" in df.columns and start_date is not None:
            sd = pd.to_datetime(str(start_date))
            df = df[pd.to_datetime(df["date"]) >= sd]
        if "date" in df.columns and end_date is not None:
            ed = pd.to_datetime(str(end_date))
            df = df[pd.to_datetime(df["date"]) <= ed]

        # Optional product filter — only applies when a product column exists.
        if product and "product" in df.columns:
            df = df[df["product"].astype(str).str.lower() == product.lower()]

        # Cap response size to keep payload reasonable; client can request narrower windows.
        MAX_ROWS = 5000
        truncated = len(df) > MAX_ROWS
        rows = df.head(MAX_ROWS).to_dict(orient="records")
        # Convert pandas Timestamps and numpy types to JSON-friendly primitives.
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()[:10] if hasattr(v, "date") and not hasattr(v, "hour") else v.isoformat()
                elif pd.isna(v):
                    r[k] = None
                elif hasattr(v, "item"):
                    r[k] = v.item()

        return {
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "filter": {
                "product": product,
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None,
            },
            "data_metadata": self._build_data_metadata(
                df,
                Path(self._fr_metadata.get("source_file")) if self._fr_metadata.get("source_file") else None,
            ),
        }

    def get_market_stats(self) -> Dict[str, Any]:
        df = self._load_fr_data()
        stats = {"total_slots": len(df), "date_range": {}, "afrr_stats": {}, "data_metadata": self._build_data_metadata(df, Path(self._fr_metadata.get("source_file")) if self._fr_metadata.get("source_file") else None)}

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

            # Calculate potential revenue for each direction.
            # Capacity price comes from the canonical DAMAS resolver
            # (recent-window mean from scraped tender clearing prices)
            # so this method matches project_annual_revenue and
            # calculate_optimal_bids. Was previously a flat catalog
            # €5/MW/h regardless of direction. Per-direction:
            afrr_up_capacity_eur_mw_h = _DAMAS_CAPACITY_AVGS["aFRRUp"]
            afrr_down_capacity_eur_mw_h = _DAMAS_CAPACITY_AVGS["aFRRDown"]

            # aFRR+ revenue (discharge - get paid for delivery)
            afrr_up_capacity_revenue = power_mw * slot_duration_hours * afrr_up_capacity_eur_mw_h
            if afrr_up_price > 0 and afrr_up_activation > 0:
                afrr_up_activation_revenue = min(afrr_up_activation, power_mw * slot_duration_hours) * afrr_up_price
            else:
                afrr_up_activation_revenue = 0
            afrr_up_potential = afrr_up_capacity_revenue + afrr_up_activation_revenue

            # aFRR- revenue (charge - can get paid if price negative)
            afrr_down_capacity_revenue = power_mw * slot_duration_hours * afrr_down_capacity_eur_mw_h
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
        target_acceptance_rate: float = 0.80,
        capacity_mwh: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculate optimal bid prices for a specific date.

        Uses historical data around that date to recommend:
        - aFRR+ capacity bid price
        - aFRR- capacity bid price
        - Expected acceptance probability
        - Expected revenue

        capacity_mwh anchors the daily energy throughput cap. When omitted,
        falls back to settings.DEFAULT_CAPACITY_MWH (catalog default) — same
        anchor pattern already used by calculate_safe_bid_prices below
        (fr_service.py:1457). The previous hardcoded 30 MWh forced every
        caller to a single hypothetical battery size and was the only
        remaining hardcoded capacity in the optimal-bids path.
        """
        if capacity_mwh is not None and capacity_mwh <= 0:
            raise ValueError("capacity_mwh must be > 0")
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

        # Get activation price at target percentile (kept for activation
        # revenue leg below).
        afrr_up_activation_proxy = float(valid_up.quantile(bid_percentile))
        afrr_down_activation_proxy = float(valid_down.quantile(bid_percentile))

        # CAPACITY BID — anchored on REAL DAMAS tender clearing prices
        # scraped from Transelectrica (see _DAMAS_CAPACITY_AVGS at module top).
        # The strategy multiplier mirrors the bid_percentile shape:
        # higher acceptance (lower percentile) ⇒ slightly under-bid;
        # lower acceptance ⇒ slightly over-bid.
        damas_up = _DAMAS_CAPACITY_AVGS["aFRRUp"]
        damas_down = _DAMAS_CAPACITY_AVGS["aFRRDown"]
        # Strategy multiplier: 0.85 at 90% accept, 1.00 at 80%, 1.15 at 60%.
        # bid_percentile ∈ [0.05, 0.50] → mult ∈ [~0.86, ~1.30].
        bid_strategy_mult = 0.85 + bid_percentile * 0.90
        afrr_up_capacity_bid = damas_up * bid_strategy_mult
        afrr_down_capacity_bid = damas_down * bid_strategy_mult

        # Floor anchored on ROMANIAN_FR_PRODUCTS (5 EUR/MW/h aFRR catalog
        # floor). Cap raised slightly above sampled DAMAS prices so an
        # aggressive bidder can over-bid in stress weeks; well below the
        # prior 60/40 catalog cap.
        afrr_floor = float(ROMANIAN_FR_PRODUCTS["aFRR"]["capacity_eur_mw_h"])
        afrr_up_capacity_bid = min(20.0, max(afrr_floor, afrr_up_capacity_bid))
        afrr_down_capacity_bid = min(20.0, max(afrr_floor, afrr_down_capacity_bid))

        # Estimate daily revenue with battery capacity constraints
        daily_hours = 24
        estimated_acceptance = target_acceptance_rate

        # CAPACITY REVENUE (paid for availability - 24h/day)
        # Pay-as-bid: You get paid YOUR bid price (not the clearing price)
        afrr_up_capacity_revenue = power_mw * daily_hours * afrr_up_capacity_bid * estimated_acceptance
        afrr_down_capacity_revenue = power_mw * daily_hours * afrr_down_capacity_bid * estimated_acceptance

        # ACTIVATION REVENUE (LIMITED by battery capacity)
        # Use the per-call capacity_mwh argument when supplied; otherwise fall
        # back to settings.DEFAULT_CAPACITY_MWH (same anchor pattern as
        # calculate_safe_bid_prices at fr_service.py:1457). The prior
        # hardcoded 30 MWh forced every caller into a single hypothetical
        # battery size and was the last hardcoded capacity in this method.
        battery_capacity_mwh = (
            float(capacity_mwh)
            if capacity_mwh is not None
            else float(settings.DEFAULT_CAPACITY_MWH)
        )
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

            # Get activation price at target percentile — kept for the
            # activation revenue leg below; no longer drives capacity bid.
            afrr_up_proxy = float(valid_up.quantile(bid_percentile))
            afrr_down_proxy = float(valid_down.quantile(bid_percentile))

            # CAPACITY BID — anchored on REAL DAMAS tender clearing prices
            # scraped from Transelectrica. Replaces the prior synthetic
            # "22% of activation price" rule which produced bids ~3-4×
            # too high (€27.81/MW/h average vs real ~€8/MW/h). The
            # `capacity_mult` (0.85 / 1.0 / 1.15 for conservative / balanced
            # / aggressive) is preserved as a strategy lever — bid below
            # market to be accepted more, above market to be paid more
            # when accepted. Same flooring on the catalog floor.
            damas_up = _DAMAS_CAPACITY_AVGS["aFRRUp"]
            damas_down = _DAMAS_CAPACITY_AVGS["aFRRDown"]
            afrr_up_capacity_bid = damas_up * capacity_mult
            afrr_down_capacity_bid = damas_down * capacity_mult

            # Floor anchored on ROMANIAN_FR_PRODUCTS (5 EUR/MW/h aFRR capacity).
            # Cap raised slightly above the real DAMAS sample range so an
            # aggressive bidder can still over-bid in stress weeks; well
            # below the prior 60/40 catalog cap.
            afrr_floor = float(ROMANIAN_FR_PRODUCTS["aFRR"]["capacity_eur_mw_h"])
            afrr_up_capacity_bid = min(20.0, max(afrr_floor, afrr_up_capacity_bid))
            afrr_down_capacity_bid = min(20.0, max(afrr_floor, afrr_down_capacity_bid))

            # Use actual calendar month length from the data instead of a flat 30.
            try:
                days_in_month = int(month_data["date"].dt.daysinmonth.iloc[0])
            except Exception:
                days_in_month = 30
            hours_in_month = days_in_month * 24

            # CAPACITY REVENUE (paid for availability - 24h/day)
            # Revenue = power × hours × YOUR_BID × acceptance_rate
            afrr_up_capacity_rev = power_mw * hours_in_month * afrr_up_capacity_bid * acceptance_rate
            afrr_down_capacity_rev = power_mw * hours_in_month * afrr_down_capacity_bid * acceptance_rate

            # ACTIVATION REVENUE (LIMITED by battery capacity)
            # User directive (2026-05-03): catalog default is 10 MW / 20 MWh
            # with full 20 MWh usable per cycle. The previous hardcoded 30
            # MWh forced this method to a different size than the rest of
            # the model and undercounted activation throughput on a
            # 10 MW / 20 MWh scenario relative to its own params.
            battery_capacity_mwh = float(settings.DEFAULT_CAPACITY_MWH)
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

        # Calculate safe activation bid prices (at target percentile).
        # Activation pricing is still derived from historical activation
        # quantiles — that's the correct source for activation revenue.
        safe_activation_up = float(valid_up.quantile(bid_percentile))
        safe_activation_down = float(valid_down.quantile(bid_percentile))

        # CAPACITY bids — canonical DAMAS resolver. Was previously
        # `safe_activation × capacity_ratio` synthetic formula; that
        # produced bids inconsistent with what the model's other paths
        # (project_annual_revenue, calculate_optimal_bids) used. Now
        # all four paths read from the same source.
        damas_up = get_canonical_capacity_price("aFRRUp").price_eur_mw_h
        damas_down = get_canonical_capacity_price("aFRRDown").price_eur_mw_h
        # "Safe" bidding = bid below market avg to maximize acceptance.
        # 0.85 multiplier mirrors the conservative strategy in
        # project_annual_revenue.
        safe_capacity_up = damas_up * 0.85
        safe_capacity_down = damas_down * 0.85

        # Floor anchored on catalog (5 EUR/MW/h aFRR).
        afrr_floor = float(ROMANIAN_FR_PRODUCTS["aFRR"]["capacity_eur_mw_h"])
        safe_capacity_up = min(20.0, max(afrr_floor, safe_capacity_up))
        safe_capacity_down = min(20.0, max(afrr_floor, safe_capacity_down))

        # Calculate expected annual revenue with safe bidding.
        # battery_capacity_mwh anchored on catalog default (was hardcoded 30).
        monthly_hours = 720
        battery_capacity_mwh = float(settings.DEFAULT_CAPACITY_MWH)
        max_monthly_energy = battery_capacity_mwh * 30  # ~1 cycle/day × 30 days

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
        aggressive_capacity_up = min(60, max(afrr_floor, aggressive_capacity_up))

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
