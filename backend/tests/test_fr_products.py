"""Phase E FR multi-product tests (gap audit 2026-05-01).

Coverage:
  E1 — capacity vs activation revenue split per product
  E2 — min-bid threshold pre-MARI (1 MW) vs post-MARI 2026-04-01 (5 MW)
  E2 — FCR is symmetric, capacity-only (zero per-slot activation MWh)
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.fr import FRMultiProductRequest  # noqa: E402
from app.services.fr_service import FRService, ROMANIAN_FR_PRODUCTS  # noqa: E402


@pytest.fixture
def synthetic_fr_service(tmp_path: Path) -> FRService:
    """Stand up an FRService with a tiny synthetic CSV so we don't depend on
    the deployed dataset."""
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=96, freq="15min"),  # 24h
        "slot": list(range(96)),
        "price_eur_mwh": [100.0] * 96,
        "afrr_up_price_eur": [200.0] * 96,
        "afrr_down_price_eur": [-30.0] * 96,
        "afrr_up_activated_mwh": [1.0] * 96,
        "afrr_down_activated_mwh": [0.5] * 96,
        "mfrr_up_activated_mwh": [0.5] * 96,
        "mfrr_down_activated_mwh": [0.2] * 96,
        "mfrr_up_scheduled_price_eur": [220.0] * 96,
        "mfrr_down_scheduled_price_eur": [-50.0] * 96,
    })
    csv_path = tmp_path / "damas_complete_fr_dataset.csv"
    df.to_csv(csv_path, index=False)
    return FRService(data_dir=tmp_path)


def test_e1_capacity_revenue_uses_product_rate(synthetic_fr_service):
    """aFRR capacity = 10 MW × 24 h × 5 €/MW/h × 97.5% availability ≈ €1170."""
    req = FRMultiProductRequest(
        products=["aFRR"],
        power_mw=10.0,
        capacity_mwh=20.0,
        round_trip_efficiency=0.88,
        availability_pct=97.5,
        energy_cost_eur_mwh=80.0,
        activation_share=0.10,
        target_date=date(2025, 1, 1),  # pre-MARI
    )
    response = synthetic_fr_service.compute_multi_product_revenue(req)
    afrr = next(p for p in response.products if p.product == "aFRR")
    expected_cap = 10.0 * 24.0 * 5.0 * 0.975
    assert math.isclose(afrr.capacity_revenue_eur, expected_cap, rel_tol=1e-3)


def test_e1_activation_revenue_uses_pay_as_bid(synthetic_fr_service):
    """aFRR activation = capped at our_max × availability × avg_price."""
    req = FRMultiProductRequest(
        products=["aFRR"],
        power_mw=10.0,
        capacity_mwh=20.0,
        availability_pct=100.0,
        activation_share=1.0,  # take 100% of market activation for verification
        target_date=date(2025, 1, 1),
    )
    response = synthetic_fr_service.compute_multi_product_revenue(req)
    afrr = next(p for p in response.products if p.product == "aFRR")
    # Market: aFRR up + down = (1.0 + 0.5) × 96 = 144 MWh activated; capped by
    # our power × hours = 10 × 24 = 240 MWh; so cleared = 144 MWh.
    assert afrr.activated_mwh > 0
    assert afrr.avg_activation_price_eur_mwh == 200.0
    assert afrr.settlement == "pay_as_bid"


def test_e2_min_bid_pre_mari_is_1_mw():
    pre_mari = FRService._min_bid_for_product("aFRR", date(2025, 12, 31))
    assert pre_mari == 1.0


def test_e2_min_bid_post_mari_is_5_mw():
    post_mari = FRService._min_bid_for_product("aFRR", date(2026, 4, 1))
    assert post_mari == 5.0


def test_e2_min_bid_violation_flagged_post_mari(synthetic_fr_service):
    req = FRMultiProductRequest(
        products=["aFRR"],
        power_mw=2.0,
        capacity_mwh=4.0,
        availability_pct=97.5,
        activation_share=0.10,
        target_date=date(2026, 4, 1),  # MARI active
    )
    response = synthetic_fr_service.compute_multi_product_revenue(req)
    assert response.mari_active is True
    assert any("aFRR" in v for v in response.min_bid_violations)


def test_e2_no_violation_pre_mari_for_2_mw(synthetic_fr_service):
    req = FRMultiProductRequest(
        products=["aFRR"],
        power_mw=2.0,
        capacity_mwh=4.0,
        availability_pct=97.5,
        activation_share=0.10,
        target_date=date(2025, 6, 1),
    )
    response = synthetic_fr_service.compute_multi_product_revenue(req)
    assert response.mari_active is False
    assert response.min_bid_violations == []


def test_e2_fcr_is_symmetric_and_marginal():
    fcr_cfg = ROMANIAN_FR_PRODUCTS["FCR"]
    assert fcr_cfg["symmetric"] is True
    assert fcr_cfg["settlement"] == "marginal"


def test_e2_fcr_activated_mwh_is_zero(synthetic_fr_service):
    """FCR has no per-slot activation MWh in DAMAS — capacity-only product."""
    req = FRMultiProductRequest(
        products=["FCR"],
        power_mw=10.0,
        capacity_mwh=20.0,
        availability_pct=97.5,
        target_date=date(2025, 1, 1),
    )
    response = synthetic_fr_service.compute_multi_product_revenue(req)
    fcr = next(p for p in response.products if p.product == "FCR")
    assert fcr.activated_mwh == 0.0
    assert fcr.symmetric is True
