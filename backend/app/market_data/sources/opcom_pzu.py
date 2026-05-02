from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential


URL_PATTERN = "https://www.opcom.ro/rapoarte-pzu-raportPIP-export-csv/{day}/{month}/{year}/ro"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def download_opcom_day(d: date, ron_to_eur: float = 5.0) -> Optional[pd.DataFrame]:
    url = URL_PATTERN.format(day=d.day, month=d.month, year=d.year)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    if not response.text or "Interval" not in response.text:
        return None
    lines = response.text.split("\n")
    header_idx = next((i for i, line in enumerate(lines) if "Interval" in line and "Pret de Inchidere" in line), None)
    if header_idx is None:
        return None
    df = pd.read_csv(StringIO("\n".join(lines[header_idx:])), quotechar='"')
    price_col = next((col for col in df.columns if "Pret de Inchidere" in col and "lei/MWh" in col), None)
    if "Interval" not in df.columns or price_col is None:
        return None
    if "Zona de tranzactionare" in df.columns:
        df = df[df["Zona de tranzactionare"] == "Romania"].copy()
    if df.empty:
        return None
    return pd.DataFrame(
        {
            "date": d.isoformat(),
            "hour": df["Interval"].astype(int) - 1,
            "price": df[price_col].astype(float) / ron_to_eur,
            "currency": "EUR",
        }
    )


def append_missing_days(csv_path: Path, *, end_date: Optional[date] = None, ron_to_eur: float = 5.0) -> int:
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"existing PZU history not found: {csv_path}")
    end_date = end_date or date.today()
    history = pd.read_csv(csv_path)
    history["date"] = pd.to_datetime(history["date"]).dt.date
    last = history["date"].max()
    rows_added = 0
    cur = last + timedelta(days=1)
    while cur <= end_date:
        try:
            day_df = download_opcom_day(cur, ron_to_eur=ron_to_eur)
        except Exception as exc:
            print(f"[opcom_pzu] {cur}: {exc}")
            day_df = None
        if day_df is not None and not day_df.empty:
            day_df.to_csv(csv_path, mode="a", header=False, index=False)
            rows_added += len(day_df)
        cur += timedelta(days=1)
    return rows_added
