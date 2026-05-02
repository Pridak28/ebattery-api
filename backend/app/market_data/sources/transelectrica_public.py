from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from app.market_data.schemas import SOURCE_KIND_PUBLIC_ESTIMATED


PUBLIC_ESTIMATED_IMBALANCE_URL = (
    "https://newmarkets.transelectrica.ro/usy-durom-publicreportg01/"
    "00121002500000000000000000000100/publicReport/estimatedImbalancePrices"
)
TZ_EET = ZoneInfo("Europe/Bucharest")
TZ_UTC = ZoneInfo("UTC")


@dataclass(frozen=True)
class DayWindow:
    day: date
    start_utc: datetime
    end_utc: datetime

    @staticmethod
    def for_day(day: date) -> "DayWindow":
        start_local = datetime(day.year, day.month, day.day, tzinfo=TZ_EET)
        end_local = start_local + timedelta(days=1)
        return DayWindow(day=day, start_utc=start_local.astimezone(TZ_UTC), end_utc=end_local.astimezone(TZ_UTC))

    def iso_bounds(self) -> tuple[str, str]:
        def fmt(dt: datetime) -> str:
            return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return fmt(self.start_utc), fmt(self.end_utc)


def daterange(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _records_from_payload(payload: dict, window: DayWindow, fx_ron_per_eur: float) -> list[dict]:
    records: list[dict] = []
    for item in payload.get("itemList") or []:
        interval = item.get("timeInterval") or {}
        try:
            start_dt = datetime.fromisoformat(str(interval.get("from")).replace("Z", "+00:00"))
        except Exception:
            start_dt = window.start_utc
        start_local = start_dt.astimezone(TZ_EET)
        price_positive_ron = item.get("estimatedPricePositiveImbalance")
        try:
            price_eur = float(price_positive_ron) / fx_ron_per_eur
        except Exception:
            price_eur = None
        records.append(
            {
                "date": start_local.date().isoformat(),
                "slot": int(item.get("ISP", 1)) - 1,
                "time_local": start_local.isoformat(timespec="minutes"),
                "resolution_minutes": 15,
                "price_eur_mwh": price_eur,
                "price_negative_ron_mwh": item.get("estimatedPriceNegativeImbalance"),
                "price_positive_ron_mwh": price_positive_ron,
                "sum_qup_mwh": item.get("sumQup"),
                "sum_qdn_mwh": item.get("sumQdn"),
                "fcr": item.get("fcr"),
                "estimated_system_imbalance_mwh": item.get("estimatedSystemImbalance"),
                "realized_consumption_mwh": item.get("realizedConsumption"),
                "source_kind": SOURCE_KIND_PUBLIC_ESTIMATED,
                "settlement_grade": False,
                "pricing_basis": "public_estimated_system_imbalance",
            }
        )
    return records


def fetch_day_payload(session: requests.Session, window: DayWindow) -> dict:
    start_iso, end_iso = window.iso_bounds()
    response = session.get(
        PUBLIC_ESTIMATED_IMBALANCE_URL,
        params={"timeInterval.from": start_iso, "timeInterval.to": end_iso, "pageInfo.pageSize": 1000},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def download_days(*, start: date, end: date, raw_dir: Path, resume: bool = True, session: requests.Session | None = None) -> list[Path]:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    session.headers.update({"User-Agent": "BatteryAnalyticsPro/1.0 public-market-data", "Accept": "application/json"})
    written: list[Path] = []
    for day in daterange(start, end):
        out_path = raw_dir / f"estimated_imbalance_{day.isoformat()}.json"
        if resume and out_path.exists():
            written.append(out_path)
            continue
        payload = fetch_day_payload(session, DayWindow.for_day(day))
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(out_path)
    return written


def build_public_imbalance_dataset(raw_paths: Iterable[Path], *, out_path: Path, fx_ron_per_eur: float = 5.0) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for raw_path in raw_paths:
        raw_path = Path(raw_path)
        if not raw_path.exists():
            continue
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        day_text = raw_path.stem.rsplit("_", 1)[-1]
        try:
            day = datetime.strptime(day_text, "%Y-%m-%d").date()
        except Exception:
            day = date.today()
        frame = pd.DataFrame.from_records(_records_from_payload(payload, DayWindow.for_day(day), fx_ron_per_eur))
        if not frame.empty:
            frames.append(frame)
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df = df.drop_duplicates(["date", "slot"], keep="last").sort_values(["date", "slot"]).reset_index(drop=True)
    else:
        df = pd.DataFrame(columns=["date", "slot", "time_local", "resolution_minutes", "price_eur_mwh", "source_kind", "settlement_grade"])
    df.attrs["source_kind"] = SOURCE_KIND_PUBLIC_ESTIMATED
    df.attrs["settlement_grade"] = False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    return df
