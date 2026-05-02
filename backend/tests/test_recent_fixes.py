"""Recent-feature lock-in tests (gap audit 2026-05-02).

Coverage:
  A-1 — regulatory regime split on ANRE Order 60/2024 effective date
  A-3 — slot_weighted vs volume_weighted activation pricing modes
  A-4 — PICASSO go-live one-time compression cliff in FR cashflow
  A-5 — bankability surface (summary + regulatory notes + regime breakdowns)
  B-2 — compliance-gate cascade behaviour
  B-3 — Law 123 Art. 66^3 storage tariff exemption avoided-cost calc
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data.quality import (  # noqa: E402
    REGIME_POST_PAY_AS_BID,
    REGIME_PRE_PAY_AS_BID,
    regulatory_regime_for_date,
)
from app.models.fr import FRSimulationParams  # noqa: E402
from app.models.investment import ComplianceGates, InvestmentParams  # noqa: E402
from app.services.fr_service import FRService  # noqa: E402
from app.services.investment_service import InvestmentService  # noqa: E402
from app.services.tariff_exemption import (  # noqa: E402
    TariffExemptionRequest,
    compute_tariff_exemption,
)


# ----------------------------- A-1 -------------------------------------------
def test_a1_regime_split_pre_order60_on_2024_09_30():
    assert regulatory_regime_for_date("2024-09-30") == REGIME_PRE_PAY_AS_BID
    assert regulatory_regime_for_date("2024-09-30") == "pre_order60_2024_marginal"


def test_a1_regime_split_post_order60_on_2024_10_01():
    assert regulatory_regime_for_date("2024-10-01") == REGIME_POST_PAY_AS_BID
    assert regulatory_regime_for_date("2024-10-01") == "post_order60_2024_pay_as_bid"


def test_a1_regime_split_post_order60_on_2024_10_02():
    assert regulatory_regime_for_date("2024-10-02") == REGIME_POST_PAY_AS_BID
    assert regulatory_regime_for_date("2024-10-02") == "post_order60_2024_pay_as_bid"


# ----------------------------- A-4 -------------------------------------------
def test_a4_picasso_cliff_drops_year3_revenue_and_y1_intact():
    """Year 3 revenue is hit by both gradual compression (1 yr at 8%) AND the
    one-time PICASSO step (-25%). Year 1 is unaffected; year 2 still has no
    PICASSO and no gradual compression yet, so the YoY ratio Y3/Y2 should
    track ~0.75 × 0.92 within the cap-factor decay (±5%).
    """
    svc = InvestmentService()
    params = InvestmentParams(
        picasso_go_live_year=3,
        picasso_one_time_compression_pct=25.0,
    )
    response = svc.analyze(params)
    cf = response.fr_cashflow
    assert len(cf) >= 3

    # Y1 (index 0): no PICASSO drop applied. Capacity factor = 0.975 means
    # gross_revenue is ~97.5% of an undegraded baseline — verify there is no
    # PICASSO multiplier on Y1 by checking Y1/cap_factor_y1 rounds back to a
    # baseline that Y2 also (approximately) lands on.
    y1 = cf[0].gross_revenue_eur
    y2 = cf[1].gross_revenue_eur
    y3 = cf[2].gross_revenue_eur
    assert y1 > 0
    assert y2 > 0
    assert y3 > 0

    # Y2 must NOT have the PICASSO drop: Y2/Y1 should be close to the
    # cap-factor ratio (~0.985). Definitely > 0.85 — proves no PICASSO yet.
    assert y2 / y1 > 0.85, "Y2 unexpectedly carries a PICASSO drop"

    # Y3 ratio target: 0.75 (PICASSO) × 0.92 (one yr gradual compression)
    # × cap-factor ratio (~0.984) ≈ 0.679. Tolerance ±5%.
    expected_ratio = 0.75 * 0.92
    actual_ratio = y3 / y2
    assert abs(actual_ratio - expected_ratio) / expected_ratio < 0.05, (
        f"Y3/Y2 ratio {actual_ratio:.4f} not within 5% of expected {expected_ratio:.4f}"
    )


# ----------------------------- A-3 -------------------------------------------
def test_a3_pricing_mode_slot_vs_volume_weighted():
    """Build a 3-slot DataFrame with prices [100, 200, 300] €/MWh and
    activations [1, 1, 10] MWh.

      - slot_weighted  → mean(100,200,300) = 200
      - volume_weighted → (100×1 + 200×1 + 300×10) / 12 = 275
    """
    svc = FRService()
    df = pd.DataFrame({
        "afrr_up_price_eur": [100.0, 200.0, 300.0],
        "afrr_up_activated_mwh": [1.0, 1.0, 10.0],
    })

    slot = svc._avg_activation_price_for_product(df, "aFRR", pricing_mode="slot_weighted")
    vol = svc._avg_activation_price_for_product(df, "aFRR", pricing_mode="volume_weighted")

    assert abs(slot - 200.0) < 1e-6
    assert abs(vol - 275.0) < 1e-6


# ----------------------------- A-5 -------------------------------------------
def test_a5_bankability_surface_spans_regime_change():
    """A 2024-09 → 2024-12 simulation window straddles ANRE Order 60/2024
    (effective 2024-10-01), so we expect both regimes to appear in
    `regime_breakdowns`, plus PICASSO + MARI mentions in regulatory notes.
    Default DAMAS is unverified_snapshot → settlement_grade is False.
    """
    svc = FRService()
    params = FRSimulationParams(
        start_date=date(2024, 9, 1),
        end_date=date(2024, 12, 1),
    )
    response = svc.simulate(params)

    assert response.bankability_summary
    assert len(response.bankability_summary) > 0
    assert response.settlement_grade is False

    notes = response.regulatory_notes
    assert isinstance(notes, list) and len(notes) > 0
    assert any("PICASSO" in n for n in notes), f"No PICASSO note in {notes}"
    assert any("MARI" in n for n in notes), f"No MARI note in {notes}"

    breakdowns = response.regime_breakdowns
    assert len(breakdowns) == 2, (
        f"Expected 2 regime breakdowns spanning ANRE Order 60/2024, got {len(breakdowns)}: "
        f"{[b.regime for b in breakdowns]}"
    )
    regime_ids = {b.regime for b in breakdowns}
    assert REGIME_PRE_PAY_AS_BID in regime_ids
    assert REGIME_POST_PAY_AS_BID in regime_ids


# ----------------------------- B-3 -------------------------------------------
def test_b3_tariff_exemption_default_rates_for_10mw_20mwh():
    """10 MW / 20 MWh × 1 cycle/day × 365 days = 7,300 MWh annual throughput.
    Default mid-band rates sum to ~31.2 €/MWh (TL 13 + Tg 3 + Td 0 +
    SS 1.7 + CV 7 + CHE 7.5). Avoided cost ≈ 7,300 × 31.2 ≈ 227,760 €/yr.
    """
    req = TariffExemptionRequest(
        power_mw=10.0,
        capacity_mwh=20.0,
        cycles_per_day=1.0,
        operating_days_per_year=365,
    )
    result = compute_tariff_exemption(req)

    assert result.annual_throughput_mwh == 7300.0
    assert 30.0 < result.rate_eur_mwh < 35.0
    assert 200_000 < result.avoided_cost_eur < 250_000
    assert result.revenue_classification == "avoided_regulated_cost"
    assert any("Law 123" in basis for basis in result.legal_basis)


# ----------------------------- B-2 -------------------------------------------
def test_b2_compliance_gates_default_blocks_all_revenue():
    """Default ComplianceGates() has every gate at 'not_declared' — the
    no-license short-circuit should fire and block ALL revenue."""
    gates = ComplianceGates()
    blocked = gates.revenue_streams_blocked()
    assert blocked == ["ALL revenue (no ANRE-recognized activity)"]


def test_b2_compliance_gates_license_only_then_blocks_on_brp():
    """ANRE license qualified but BRP/PRE not declared → blocks ALL market
    revenue (the second short-circuit)."""
    gates = ComplianceGates(
        anre_license_status="qualified",
        brp_pre_responsibility="not_declared",
    )
    blocked = gates.revenue_streams_blocked()
    assert blocked == ["ALL market revenue (no BRP/PRE)"]


def test_b2_compliance_gates_fully_qualified_blocks_nothing():
    """Every gate qualified → empty blocked list."""
    fields = list(ComplianceGates.model_fields.keys())
    fully_qualified_kwargs = {name: "qualified" for name in fields}
    gates = ComplianceGates(**fully_qualified_kwargs)
    assert gates.revenue_streams_blocked() == []
