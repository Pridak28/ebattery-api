from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.fr import FRSimulationParams
from app.services.fr_service import FRService


def test_fr_service_returns_source_metadata(tmp_path):
    df = pd.DataFrame({
        "date": ["2026-04-01"] * 96,
        "slot": list(range(96)),
        "price_eur_mwh": [50.0] * 96,
        "afrr_up_activated_mwh": [1.0] * 96,
        "afrr_down_activated_mwh": [0.0] * 96,
        "afrr_up_price_eur": [100.0] * 96,
        "afrr_down_price_eur": [80.0] * 96,
        "source_kind": ["unverified_snapshot"] * 96,
    })
    df.to_csv(tmp_path / "damas_clean.csv", index=False)
    svc = FRService(data_dir=tmp_path)
    res = svc.simulate(FRSimulationParams())
    assert res.source_kind == "unverified_snapshot"
    assert res.bankability_level == "historical_backtest_only"
    assert res.data_date_max == "2026-04-01"
    assert res.monthly_results[0].source_kind == "unverified_snapshot"
