"""Unit tests for app/market_data/sources/* — pure transforms + local file IO.

Network calls (requests.get / requests.Session.get) are mocked via
``unittest.mock``; no real HTTP requests fire from this module.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data.quality import DataQualityError
from app.market_data.schemas import (
    SOURCE_KIND_PARTICIPANT_EXPORT,
    SOURCE_KIND_PUBLIC_AGGREGATE,
    SOURCE_KIND_PUBLIC_ESTIMATED,
    SOURCE_KIND_SCENARIO,
    SOURCE_KIND_UNVERIFIED_SNAPSHOT,
)
from app.market_data.sources import damas_import, opcom_pzu, transelectrica_public
from app.market_data.sources.transelectrica_public import (
    DayWindow,
    _records_from_payload,
    build_public_imbalance_dataset,
    daterange,
    download_days,
    fetch_day_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _damas_csv_text() -> str:
    """Minimal DAMAS-shaped CSV: 96 slots for one day."""
    rows = ["date,slot,price_eur_mwh,afrr_up_activated_mwh,afrr_down_activated_mwh,afrr_up_price_eur,afrr_down_price_eur"]
    for slot in range(96):
        rows.append(f"2026-04-01,{slot},50.0,1.0,0.5,120.0,80.0")
    return "\n".join(rows) + "\n"


def _make_response(text: str = "", json_payload: dict | None = None, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_payload is not None:
        resp.json.return_value = json_payload
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# damas_import tests
# ---------------------------------------------------------------------------


def test_damas_read_manual_export_csv(tmp_path: Path) -> None:
    p = tmp_path / "manual.csv"
    p.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    df = damas_import.read_manual_export(p)
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


def test_damas_read_manual_export_unsupported_suffix(tmp_path: Path) -> None:
    p = tmp_path / "manual.txt"
    p.write_text("garbage", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported DAMAS export type"):
        damas_import.read_manual_export(p)


def test_damas_import_rejects_bad_source_kind(tmp_path: Path) -> None:
    src = tmp_path / "in.csv"
    src.write_text(_damas_csv_text(), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported source_kind"):
        damas_import.import_manual_export(
            input_path=src,
            output_path=tmp_path / "out.csv",
            source_kind=SOURCE_KIND_SCENARIO,
        )


def test_damas_import_raises_on_non_damas_shape(tmp_path: Path) -> None:
    src = tmp_path / "non_damas.csv"
    src.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(DataQualityError, match="not DAMAS-shaped"):
        damas_import.import_manual_export(
            input_path=src,
            output_path=tmp_path / "out.csv",
            source_kind=SOURCE_KIND_UNVERIFIED_SNAPSHOT,
        )


def test_damas_import_happy_path_writes_csv(tmp_path: Path) -> None:
    src = tmp_path / "manual.csv"
    src.write_text(_damas_csv_text(), encoding="utf-8")
    out = tmp_path / "out" / "cleaned.csv"
    df = damas_import.import_manual_export(
        input_path=src,
        output_path=out,
        source_kind=SOURCE_KIND_PUBLIC_AGGREGATE,
        audit_dir=tmp_path / "audit",
    )
    assert out.exists()
    assert "source_kind" in df.columns
    assert (df["source_kind"] == SOURCE_KIND_PUBLIC_AGGREGATE).all()
    # public_aggregate is not bankable
    assert (df["settlement_grade"] == False).all()  # noqa: E712


def test_damas_run_participant_placeholder_raises() -> None:
    with pytest.raises(RuntimeError, match="Participant DAMAS import is not configured"):
        damas_import.run_participant_placeholder()


# ---------------------------------------------------------------------------
# opcom_pzu tests
# ---------------------------------------------------------------------------


_OPCOM_CSV = (
    "Some preamble line\n"
    "Another header line\n"
    'Interval,"Pret de Inchidere [lei/MWh]","Zona de tranzactionare"\n'
    + "\n".join(f'{i},"{500.0 + i}","Romania"' for i in range(1, 25))
    + "\n"
    + "\n".join(f'{i},"{999.0}","Hungary"' for i in range(1, 25))
    + "\n"
)


def test_opcom_download_day_parses_csv() -> None:
    fake_response = _make_response(text=_OPCOM_CSV)
    with patch("app.market_data.sources.opcom_pzu.requests.get", return_value=fake_response) as mock_get:
        df = opcom_pzu.download_opcom_day(date(2026, 4, 15), ron_to_eur=5.0)
    assert mock_get.called
    assert df is not None
    assert len(df) == 24
    assert list(df.columns) == ["date", "hour", "price", "currency"]
    assert (df["currency"] == "EUR").all()
    assert df["hour"].iloc[0] == 0  # interval 1 -> hour 0
    assert df["hour"].iloc[-1] == 23
    # Romania filter applied: first row is interval 1 -> price 501 RON / 5.0
    assert df["price"].iloc[0] == pytest.approx(501.0 / 5.0)
    assert (df["date"] == "2026-04-15").all()


def test_opcom_download_day_returns_none_when_no_interval() -> None:
    fake_response = _make_response(text="random,header,without,signal\n1,2,3,4\n")
    with patch("app.market_data.sources.opcom_pzu.requests.get", return_value=fake_response):
        result = opcom_pzu.download_opcom_day(date(2026, 4, 15))
    assert result is None


def test_opcom_download_day_returns_none_when_empty_text() -> None:
    fake_response = _make_response(text="")
    with patch("app.market_data.sources.opcom_pzu.requests.get", return_value=fake_response):
        result = opcom_pzu.download_opcom_day(date(2026, 4, 15))
    assert result is None


def test_opcom_append_missing_days_appends_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "pzu_history.csv"
    # seed history ending 2026-04-14
    seed = pd.DataFrame({
        "date": ["2026-04-14"] * 24,
        "hour": list(range(24)),
        "price": [40.0] * 24,
        "currency": ["EUR"] * 24,
    })
    seed.to_csv(csv_path, index=False)

    # download_opcom_day will be called twice (15th, 16th); return synthetic frames.
    def fake_download(d, ron_to_eur=5.0):
        return pd.DataFrame({
            "date": [d.isoformat()] * 2,
            "hour": [0, 1],
            "price": [10.0, 20.0],
            "currency": ["EUR", "EUR"],
        })

    with patch("app.market_data.sources.opcom_pzu.download_opcom_day", side_effect=fake_download):
        added = opcom_pzu.append_missing_days(csv_path, end_date=date(2026, 4, 16))
    assert added == 4  # 2 rows * 2 days
    final = pd.read_csv(csv_path)
    assert len(final) == 24 + 4


def test_opcom_append_missing_days_handles_download_exception(tmp_path: Path) -> None:
    csv_path = tmp_path / "pzu_history.csv"
    seed = pd.DataFrame({
        "date": ["2026-04-14"],
        "hour": [0],
        "price": [40.0],
        "currency": ["EUR"],
    })
    seed.to_csv(csv_path, index=False)

    with patch(
        "app.market_data.sources.opcom_pzu.download_opcom_day",
        side_effect=RuntimeError("boom"),
    ):
        added = opcom_pzu.append_missing_days(csv_path, end_date=date(2026, 4, 15))
    assert added == 0


def test_opcom_append_missing_days_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        opcom_pzu.append_missing_days(tmp_path / "missing.csv", end_date=date(2026, 4, 15))


# ---------------------------------------------------------------------------
# transelectrica_public tests
# ---------------------------------------------------------------------------


def test_daywindow_for_day_iso_bounds() -> None:
    win = DayWindow.for_day(date(2026, 4, 15))
    assert win.day == date(2026, 4, 15)
    start, end = win.iso_bounds()
    # Bucharest 2026-04-15 00:00 EEST (DST) == 2026-04-14 21:00 UTC
    assert start.endswith("Z")
    assert end.endswith("Z")
    # Sanity: end is one day after start
    s = datetime.fromisoformat(start.replace("Z", "+00:00"))
    e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    assert (e - s).total_seconds() == 24 * 3600


def test_daterange_yields_inclusive() -> None:
    out = list(daterange(date(2026, 4, 15), date(2026, 4, 17)))
    assert out == [date(2026, 4, 15), date(2026, 4, 16), date(2026, 4, 17)]


def test_records_from_payload_normalizes_fields() -> None:
    win = DayWindow.for_day(date(2026, 4, 15))
    payload = {
        "itemList": [
            {
                "ISP": 1,
                "timeInterval": {"from": "2026-04-14T21:00:00.000Z", "to": "2026-04-14T21:15:00.000Z"},
                "estimatedPricePositiveImbalance": 500.0,
                "estimatedPriceNegativeImbalance": 100.0,
                "sumQup": 12.5,
                "sumQdn": 5.5,
                "fcr": 1.0,
                "estimatedSystemImbalance": -3.0,
                "realizedConsumption": 6000.0,
            },
            {
                "ISP": 2,
                "timeInterval": {"from": "garbage", "to": "garbage"},
                "estimatedPricePositiveImbalance": "not-a-number",
            },
        ]
    }
    records = _records_from_payload(payload, win, fx_ron_per_eur=5.0)
    assert len(records) == 2
    r0 = records[0]
    assert r0["slot"] == 0  # ISP 1 -> slot 0
    assert r0["resolution_minutes"] == 15
    assert r0["price_eur_mwh"] == pytest.approx(100.0)  # 500 / 5
    assert r0["price_positive_ron_mwh"] == 500.0
    assert r0["source_kind"] == SOURCE_KIND_PUBLIC_ESTIMATED
    assert r0["settlement_grade"] is False
    assert r0["pricing_basis"] == "public_estimated_system_imbalance"
    # Bad row: bad timestamp falls back, bad price -> None
    assert records[1]["price_eur_mwh"] is None
    assert records[1]["slot"] == 1


def test_records_from_payload_empty_list() -> None:
    win = DayWindow.for_day(date(2026, 4, 15))
    assert _records_from_payload({}, win, 5.0) == []
    assert _records_from_payload({"itemList": None}, win, 5.0) == []


def test_fetch_day_payload_uses_session(tmp_path: Path) -> None:
    payload = {"itemList": []}
    session = MagicMock()
    session.get.return_value = _make_response(json_payload=payload)
    win = DayWindow.for_day(date(2026, 4, 15))
    out = fetch_day_payload(session, win)
    assert out == payload
    session.get.assert_called_once()
    # ensure params include the bound iso strings
    _, kwargs = session.get.call_args
    assert "params" in kwargs
    assert "timeInterval.from" in kwargs["params"]
    assert "timeInterval.to" in kwargs["params"]


def test_download_days_writes_payload_files(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    fake_payload = {"itemList": [{"ISP": 1, "estimatedPricePositiveImbalance": 200.0}]}

    fake_session = MagicMock()
    fake_session.headers = MagicMock()
    fake_session.headers.update = MagicMock()
    fake_session.get.return_value = _make_response(json_payload=fake_payload)

    paths = download_days(
        start=date(2026, 4, 15),
        end=date(2026, 4, 16),
        raw_dir=raw_dir,
        resume=True,
        session=fake_session,
    )
    assert len(paths) == 2
    for p in paths:
        assert p.exists()
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded == fake_payload

    # Second pass with resume=True should not call session.get again.
    fake_session.get.reset_mock()
    paths2 = download_days(
        start=date(2026, 4, 15),
        end=date(2026, 4, 16),
        raw_dir=raw_dir,
        resume=True,
        session=fake_session,
    )
    assert len(paths2) == 2
    assert fake_session.get.call_count == 0


def test_build_public_imbalance_dataset_concats(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    def _payload(utc_day: str, price_pos: float) -> dict:
        # 2026-04-DD T21:00 UTC == next-day 00:00 Bucharest (EEST, +03:00)
        return {
            "itemList": [
                {
                    "ISP": i + 1,
                    "timeInterval": {"from": f"2026-04-{utc_day}T{21 + (i // 4):02d}:{(i % 4) * 15:02d}:00.000Z"},
                    "estimatedPricePositiveImbalance": price_pos + i,
                }
                for i in range(4)
            ]
        }

    p1 = raw_dir / "estimated_imbalance_2026-04-15.json"
    p2 = raw_dir / "estimated_imbalance_2026-04-16.json"
    p1.write_text(json.dumps(_payload("14", 500.0)), encoding="utf-8")
    p2.write_text(json.dumps(_payload("15", 600.0)), encoding="utf-8")

    out = tmp_path / "out" / "imbalance.csv"
    df = build_public_imbalance_dataset([p1, p2, raw_dir / "missing.json"], out_path=out, fx_ron_per_eur=5.0)
    assert out.exists()
    assert len(df) == 8
    assert set(df["date"]) == {"2026-04-15", "2026-04-16"}
    assert df.attrs["source_kind"] == SOURCE_KIND_PUBLIC_ESTIMATED
    assert df.attrs["settlement_grade"] is False
    # price_eur_mwh = ron_price / 5.0
    first = df[(df["date"] == "2026-04-15") & (df["slot"] == 0)].iloc[0]
    assert first["price_eur_mwh"] == pytest.approx(100.0)


def test_build_public_imbalance_dataset_empty_inputs(tmp_path: Path) -> None:
    out = tmp_path / "out" / "empty.csv"
    df = build_public_imbalance_dataset([], out_path=out, fx_ron_per_eur=5.0)
    assert out.exists()
    assert df.empty
    assert "price_eur_mwh" in df.columns
    assert df.attrs["source_kind"] == SOURCE_KIND_PUBLIC_ESTIMATED
