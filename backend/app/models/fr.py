"""
Frequency Regulation (FR) Pydantic Models
"""
from datetime import date
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class FRProductConfig(BaseModel):
    """Configuration for a single FR product"""
    enabled: bool = True
    power_mw: float = Field(10.0, ge=0, le=1000, description="Allocated power in MW")
    # Romanian aFRR capacity clears in the €5-8/MW/h range historically.
    # The earlier €15/MW/h default produced unrealistically high revenue
    # (~3× too much). Operators set this per-bid based on their target
    # acceptance rate; €6 is a defensible mid-market default for new entrants.
    capacity_price_eur_mw_h: float = Field(6.0, ge=0, le=500, description="Capacity price EUR/MW/h (Romanian mid-market default)")
    activation_rate: float = Field(
        0.03,
        ge=0.0,
        le=0.50,
        description=(
            "Market share of Romanian aFRR activations captured by this asset. "
            "Defensible range for a 10 MW new entrant: 1.4-2% (fleet-proportional vs ~500-700 MW Romanian aFRR fleet). "
            "Above ~0.9% the 10 MW / 20 MWh battery's own throughput cap (7,300 MWh/yr) binds, "
            "so values >0.9% all produce identical revenue — the previous 10% default was numerically harmless but misleading. "
            "Source: 12-month DAMAS backfill 2025-05 to 2026-05 = 799k MWh/yr Romania-wide aFRR activations."
        )
    )


class FRSimulationParams(BaseModel):
    """Parameters for FR simulation.

    User directive (2026-05-03): full 20 MWh usable per cycle, 3% per
    round-trip loss (RTE = 0.97).
    """
    capacity_mwh: float = Field(20.0, ge=0.1, le=2000, description="Battery capacity in MWh")
    round_trip_efficiency: float = Field(0.97, ge=0.5, le=1.0, description="Round-trip efficiency — user directive: 0.97 (3% loss)")

    # Product configurations - each with own capacity price and activation rate
    afrr_up: FRProductConfig = Field(default_factory=lambda: FRProductConfig(power_mw=10.0))
    afrr_down: FRProductConfig = Field(default_factory=lambda: FRProductConfig(power_mw=10.0))
    mfrr_up: FRProductConfig = Field(default_factory=lambda: FRProductConfig(enabled=False, power_mw=0.0))
    mfrr_down: FRProductConfig = Field(default_factory=lambda: FRProductConfig(enabled=False, power_mw=0.0))

    # Energy cost for recharging
    energy_cost_eur_mwh: float = Field(80.0, ge=0, description="Energy cost for charging")

    # Phase D5 — availability factor (97-98% typical for new BESS).
    availability_pct: float = Field(97.5, ge=0.0, le=100.0, description="Annual uptime % (capacity + activation revenue scale)")

    # Realism note (2026-05-02): physically a battery delivers ONE direction
    # per ISP, but Romanian DAMAS pays capacity reservation fees for BOTH
    # direction envelopes when the operator's bids clear on both sides.
    # This is a market convention, not a physical impossibility — the
    # operator is paid for STANDING-BY in both directions, not for
    # delivering both simultaneously.
    # Modes:
    #   "symmetric" (default) — capacity counted per direction (matches
    #       Romanian DAMAS symmetric-envelope reality when both bids clear).
    #       Realistic for operators who bid both stacks competitively.
    #   "single_direction" — capacity counted only on the highest-power
    #       direction. Conservative; matches operators who commit to one
    #       direction only (e.g., UP-only providers).
    simulation_mode: Literal["single_direction", "symmetric"] = Field(
        "symmetric",
        description="Default 'symmetric' matches Romanian DAMAS dual-envelope payment convention. Use 'single_direction' to model up-only or down-only bidders."
    )

    # Battery rated power (used to detect over-allocation). Defaults to the
    # max enabled product power; explicit override is recommended.
    power_mw_rated: Optional[float] = Field(
        None,
        ge=0.0,
        description="Battery rated power in MW. Sum of enabled per-direction product powers may not exceed this (per direction). If None, inferred as max(enabled product power_mw)."
    )

    # Date range
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class FRMonthlyResult(BaseModel):
    """Monthly FR simulation result.

    Per audit/ROMANIAN_BESS_AUDIT_RISK_INVESTIGATION_2026-05-01.md every result
    must declare its `pricing_basis` and `confidence_label` so investors do not
    confuse public/system-level data with participant settlement.
    """
    month: str
    product: str  # 'aFRR+', 'aFRR-', 'mFRR+', 'mFRR-'

    # Slots and availability
    total_slots: int = 0

    # Revenue breakdown
    capacity_revenue_eur: float = 0.0
    activation_revenue_eur: float = 0.0
    total_revenue_eur: float = 0.0

    # Energy
    activation_energy_mwh: float = 0.0
    energy_cost_eur: float = 0.0

    # Net result
    net_profit_eur: float = 0.0

    # Metrics
    avg_capacity_price_eur_mw: float = 0.0
    avg_activation_price_eur_mwh: float = 0.0

    # Audit metadata — see ROMANIAN_BESS_AUDIT_RISK_INVESTIGATION_2026-05-01.md
    pricing_basis: str = "public_marginal"  # public_marginal | participant_bid | settlement_export | scenario
    confidence_label: str = "Public-data / Participant-only-for-bankability"
    activation_method: str = "DAMAS_market_share"
    bankable: bool = False  # True only when settlement_export evidence is supplied
    source_kind: str = "unverified_snapshot"
    data_date_max: Optional[str] = None
    bankability_level: str = "historical_backtest_only"


class FRProductSummary(BaseModel):
    """Summary for a single product across all months"""
    product: str
    total_capacity_revenue_eur: float
    total_activation_revenue_eur: float
    total_revenue_eur: float
    total_energy_cost_eur: float
    total_net_profit_eur: float
    months_count: int


class FRMultiProductRequest(BaseModel):
    """Phase E — multi-product (aFRR / mFRR / FCR) request."""
    products: List[Literal["aFRR", "mFRR", "FCR"]] = Field(
        default_factory=lambda: ["aFRR"],
        description="FR products to include in revenue calculation",
    )
    power_mw: float = Field(10.0, ge=0.1, le=1000, description="Total bid power MW per product")
    capacity_mwh: float = Field(20.0, ge=0.1, le=2000, description="Battery usable capacity")
    round_trip_efficiency: float = Field(0.97, ge=0.5, le=1.0, description="Round-trip efficiency — user directive: 0.97 (3% loss)")
    availability_pct: float = Field(97.5, ge=0.0, le=100.0)
    energy_cost_eur_mwh: float = Field(80.0, ge=0, description="Recharge energy price")
    activation_share: float = Field(0.10, ge=0.0, le=1.0, description="Share of market activation captured (bid stack proxy)")
    target_date: Optional[date] = Field(
        None,
        description="Reference date for MARI rule check; defaults to today.",
    )
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # A-3: pricing aggregation mode. Romanian aFRR has a heavily skewed price
    # distribution (volume-weighted UP avg ~€399/MWh vs slot-equal-weighted
    # ~€228/MWh). Operators care about *what they actually earn per MWh
    # delivered* — that's volume-weighted on the activated subset. Slot-weighted
    # is the simple time-average and is preserved as default for back-compat.
    pricing_mode: Literal["slot_weighted", "volume_weighted"] = Field(
        "slot_weighted",
        description=(
            "How average activation price is computed. 'slot_weighted' = "
            "equal-weight across all valid slots (default, back-compatible). "
            "'volume_weighted' = MWh-weighted across ACTIVATED slots only — "
            "matches what the operator actually earns; ~75% higher for Romanian "
            "aFRR UP, ~5× more negative for Romanian aFRR DOWN."
        ),
    )
    # A-1: regime filter so consumers can analyze pre/post Order 60/2024
    # mechanics in isolation without re-uploading data.
    regulatory_regime_filter: Optional[Literal["pre_order60_2024_marginal", "post_order60_2024_pay_as_bid", "all"]] = Field(
        "all",
        description=(
            "Restrict analysis to one regulatory regime. 'all' (default) uses "
            "the full window; 'post_order60_2024_pay_as_bid' uses only data "
            "from 2024-10-01 onward — the regime that actually applies to new "
            "BESS investments today."
        ),
    )


class FRProductResult(BaseModel):
    """Per-product breakdown for the multi-product endpoint."""
    product: Literal["aFRR", "mFRR", "FCR"]
    capacity_revenue_eur: float
    activation_revenue_eur: float
    energy_cost_eur: float
    net_revenue_eur: float
    capacity_eur_mw_h: float
    settlement: Literal["pay_as_bid", "marginal"]
    activated_mwh: float
    avg_activation_price_eur_mwh: float
    min_bid_mw: float
    symmetric: bool = False
    pricing_basis: str
    confidence_label: str


class FRMultiProductResponse(BaseModel):
    """Phase E response — combined revenue across selected FR products."""
    params: FRMultiProductRequest
    products: List[FRProductResult]
    total_capacity_revenue_eur: float
    total_activation_revenue_eur: float
    total_energy_cost_eur: float
    total_net_revenue_eur: float
    min_bid_violations: List[str] = Field(
        default_factory=list,
        description="Products where requested power_mw < min bid for the target_date (pre-/post-MARI).",
    )
    mari_active: bool
    target_date: date
    # A-3 / A-1: surface the aggregation mode + regime filter actually used so
    # consumers know exactly which slice of the dataset produced these numbers.
    pricing_mode: Literal["slot_weighted", "volume_weighted"] = "slot_weighted"
    regulatory_regime_used: str = "all"
    regime_row_counts: dict = Field(
        default_factory=dict,
        description="{regime_id: row_count} after the regime filter — empty if no regime column in source.",
    )


class FRRegimeBreakdown(BaseModel):
    """A-1: per-regulatory-regime aggregate for the simulated window."""
    regime: Literal["pre_order60_2024_marginal", "post_order60_2024_pay_as_bid"]
    row_count: int
    months_count: int
    capacity_revenue_eur: float
    activation_revenue_eur: float
    total_revenue_eur: float
    energy_cost_eur: float
    net_profit_eur: float
    avg_activation_price_up_eur_mwh: float = 0.0
    avg_activation_price_down_eur_mwh: float = 0.0


class FRSimulationResponse(BaseModel):
    """Complete FR simulation response"""
    params: FRSimulationParams
    monthly_results: List[FRMonthlyResult]
    product_summaries: List[FRProductSummary]

    # Totals
    total_revenue_eur: float
    total_energy_cost_eur: float
    total_net_profit_eur: float
    total_capacity_revenue_eur: float = 0.0
    total_activation_revenue_eur: float = 0.0
    avg_monthly_net_profit_eur: float = 0.0
    annual_net_profit_eur: float = 0.0
    # Annualized metrics (12-month projection)
    annual_revenue_eur: float = 0.0
    annual_capacity_revenue_eur: float = 0.0
    annual_activation_revenue_eur: float = 0.0
    annual_energy_cost_eur: float = 0.0
    months_count: int = 0
    source_kind: str = "unverified_snapshot"
    data_date_max: Optional[str] = None
    bankability_level: str = "historical_backtest_only"
    data_warnings: List[str] = Field(default_factory=list)

    # A-1: per-regime breakdown so investors see how much of the headline
    # revenue comes from pre- vs post- ANRE Order 60/2024 mechanics.
    regime_breakdowns: List[FRRegimeBreakdown] = Field(
        default_factory=list,
        description="Aggregates split by regulatory regime (pre/post ANRE Order 60/2024).",
    )

    # A-5: bankability surface. Existing ``bankability_level`` is buried in
    # the response; these top-level fields make the regulatory + data quality
    # provenance impossible to miss.
    bankability_summary: str = Field(
        default="",
        description="One-line plain-English summary of bankability + regime + data caveats.",
    )
    settlement_grade: bool = Field(
        default=False,
        description="True only when underlying data is participant-settlement-grade. Mostly False for public/scenario backtests.",
    )
    regulatory_notes: List[str] = Field(
        default_factory=list,
        description="Plain-English regulatory notes investors should read alongside revenue numbers (Order 60/2024, MARI 2026-04-01, PICASSO go-live, etc.).",
    )
