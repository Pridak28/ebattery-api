from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data.quality import assert_bankable_source, infer_source_kind, normalize_pzu_resolution, validate_market_dataset


def test_fr_data_clean_is_derived_public_even_with_afrr_columns():
    df = pd.DataFrame({
        "date": ["2026-04-01"],
        "slot": [0],
        "price_eur_mwh": [100.0],
        "afrr_up_activated_mwh": [1.0],
        "afrr_down_activated_mwh": [0.0],
        "afrr_up_price_eur": [200.0],
        "afrr_down_price_eur": [150.0],
    })
    assert infer_source_kind(df, Path("fr_data_clean.csv")) == "derived_public"


def test_bankable_source_gate():
    with pytest.raises(Exception):
        assert_bankable_source("public_estimated")
    assert_bankable_source("participant_export") is None
    assert_bankable_source("settlement_export") is None


def test_negative_activation_volume_fails():
    df = pd.DataFrame({
        "date": ["2026-04-01"] * 96,
        "slot": list(range(96)),
        "price_eur_mwh": [50.0] * 96,
        "afrr_up_activated_mwh": [1.0] * 95 + [-1.0],
        "afrr_down_activated_mwh": [0.0] * 96,
        "afrr_up_price_eur": [100.0] * 96,
        "afrr_down_price_eur": [80.0] * 96,
    })
    report = validate_market_dataset(df, dataset_id="damas_test", source_kind="unverified_snapshot", as_of=date(2026, 5, 1))
    assert not report["passed"]
    assert any(issue["code"] == "negative_activation_volume" for issue in report["issues"])


def test_pzu_mixed_resolution_is_explicit():
    rows = [{"date": "2026-04-01", "hour": hour, "price": 50.0} for hour in range(24)]
    rows += [{"date": "2026-04-02", "hour": slot, "price": 55.0} for slot in range(96)]
    df = normalize_pzu_resolution(pd.DataFrame(rows))
    assert set(df["resolution_minutes"].unique()) == {15, 60}
    report = validate_market_dataset(df, dataset_id="pzu_history", source_kind="public_observed_system", as_of=date(2026, 5, 1))
    assert report["passed"]
    assert any(issue["code"] == "mixed_resolution" for issue in report["issues"])
