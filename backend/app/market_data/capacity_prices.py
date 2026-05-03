"""Canonical capacity-price resolver for Romanian aFRR.

ONE source of truth for the model's aFRR capacity bid prices. Replaces
the previous patchwork where 4 different code paths computed bids
independently:

  - fr_service.calculate_optimal_bids()  (synthetic 22% × activation)
  - fr_service.project_annual_revenue()  (synthetic 22% × activation)
  - fr_service.calculate_safe_bid_prices()  (synthetic 20-25% × activation)
  - fr_service.compute_multi_product_revenue()  (catalog flat €5/MW/h)

All four were producing different numbers. This module enforces one
canonical answer per (direction, mode), tagged with a bankability label
so downstream consumers know how defensible it is.

Source ladder (most → least defensible):
    PARTICIPANT_SETTLEMENT  — TSO-signed settlement export. Bankable.
    PUBLIC_DAMAS_SAMPLE     — scraped from DAMAS II tender stats.
                              Defensible for backtest / pitch deck;
                              NOT bankable without participant proof.
    CATALOG_FLOOR           — ROMANIAN_FR_PRODUCTS catalog floor (€5/€3.5).
                              Used as fallback floor only.

Default `mode="public_damas_sample"` returns the recent-window mean
(samples from the last 270 days) — this is the "compressed market"
calibration the user requested (€5-7/MW/h aFRRUp, €1-4/MW/h aFRRDown).

Bankable mode (`mode="bankable"`) requires participant settlement data
and raises if absent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

import pandas as pd

# ===================================================================
#  Constants
# ===================================================================
DAMAS_CSV_PATH = (
    Path(__file__).resolve().parents[2]
    / "data_catalog" / "processed" / "damas_capacity_clearing.csv"
)
SETTLEMENT_CSV_PATH = (
    Path(__file__).resolve().parents[2]
    / "data_catalog" / "processed" / "damas_capacity_settlement.csv"
)

# Catalog fallback (used as floor; ROMANIAN_FR_PRODUCTS values).
CATALOG_FLOOR_AFRR_EUR_MW_H = 5.0
CATALOG_FLOOR_MFRR_EUR_MW_H = 7.5
CATALOG_FLOOR_FCR_EUR_MW_H = 3.5

# Recent window for "default" mode — last 270 days from today.
# Captures the post-summer-2025 compression without throwing away too
# much of our sample.
RECENT_WINDOW_DAYS = 270

# Hard fallback if no scraped data exists at all.
FALLBACK_AFRR_UP_EUR_MW_H = 6.57   # mean of post-Aug 2025 samples
FALLBACK_AFRR_DOWN_EUR_MW_H = 2.59

DirectionType = Literal["aFRRUp", "aFRRDown"]
ModeType = Literal["public_damas_sample", "catalog_floor", "bankable"]


@dataclass(frozen=True)
class CapacityPrice:
    """Resolved capacity price + provenance the caller needs to label."""
    price_eur_mw_h: float
    direction: str
    source: str                  # "PARTICIPANT_SETTLEMENT" | "PUBLIC_DAMAS_SAMPLE" | "CATALOG_FLOOR"
    bankability_label: str       # "Bankable" | "Public-data / Backtest-only" | "Floor-only"
    n_samples: int
    window_start: Optional[date]
    window_end: Optional[date]
    note: str

    def to_dict(self) -> dict:
        return {
            "price_eur_mw_h": round(self.price_eur_mw_h, 4),
            "direction": self.direction,
            "source": self.source,
            "bankability_label": self.bankability_label,
            "n_samples": self.n_samples,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "note": self.note,
        }


# ===================================================================
#  Resolution
# ===================================================================
def _parse_dd_mm_yyyy(s: str) -> Optional[date]:
    """DAMAS dates are formatted '27. 4. 2025' (with spaces)."""
    if not isinstance(s, str):
        return None
    try:
        parts = [int(x.strip()) for x in s.split(".") if x.strip()]
        if len(parts) == 3:
            d, m, y = parts
            return date(y, m, d)
    except (ValueError, TypeError):
        pass
    return None


def _load_recent_damas_samples(
    csv_path: Path = DAMAS_CSV_PATH,
    direction: DirectionType = "aFRRUp",
    asof: Optional[date] = None,
    window_days: int = RECENT_WINDOW_DAYS,
) -> tuple[list[float], Optional[date], Optional[date]]:
    """Read scraped DAMAS samples for `direction` within the recent window.

    Returns (prices, window_start, window_end).
    """
    if not csv_path.exists():
        return [], None, None
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return [], None, None
    if direction not in df["service"].unique():
        return [], None, None
    df = df[df["service"] == direction].copy()
    df["_d"] = df["delivery_date"].map(_parse_dd_mm_yyyy)
    df = df[df["_d"].notna()]
    if df.empty:
        return [], None, None
    if asof is None:
        asof = date.today()
    cutoff = asof - timedelta(days=window_days)
    recent = df[df["_d"] >= cutoff]
    if recent.empty:
        # Recent window has no samples — fall back to all available.
        recent = df
    prices = recent["avg_clearing_price_eur_mw_h"].astype(float).tolist()
    return prices, recent["_d"].min(), recent["_d"].max()


def _load_settlement_samples(
    direction: DirectionType,
    csv_path: Path = SETTLEMENT_CSV_PATH,
) -> list[float]:
    """Settlement-grade source. Currently always empty — we do not
    have participant settlement data. When the project entity becomes
    a registered participant and exports its settlement records, drop
    them at SETTLEMENT_CSV_PATH and this resolver will pick them up
    automatically.
    """
    if not csv_path.exists():
        return []
    try:
        df = pd.read_csv(csv_path)
        if "service" in df.columns and "price_eur_mw_h" in df.columns:
            df = df[df["service"] == direction]
            return df["price_eur_mw_h"].astype(float).tolist()
    except Exception:
        pass
    return []


def get_canonical_capacity_price(
    direction: DirectionType,
    mode: ModeType = "public_damas_sample",
    asof: Optional[date] = None,
) -> CapacityPrice:
    """Resolve the canonical aFRR capacity price for `direction`.

    All callers in fr_service should route through this function so the
    model returns one consistent capacity price across PNL projection,
    optimal-bid recommendation, and safe-bid recommendation.

    Modes:
      - "public_damas_sample" (default): mean of DAMAS scraped samples in
        the last RECENT_WINDOW_DAYS. Bankability label = "Public-data /
        Backtest-only". Suitable for backtests, pitch decks, internal
        modeling. NOT bankable.
      - "catalog_floor": returns ROMANIAN_FR_PRODUCTS catalog floor
        (€5/MW/h aFRR). Used as floor by callers; raises bankability
        warning.
      - "bankable": requires participant settlement export at
        SETTLEMENT_CSV_PATH. Raises ValueError if absent.
    """
    if direction not in ("aFRRUp", "aFRRDown"):
        raise ValueError(f"Unknown direction: {direction!r}")

    if mode == "bankable":
        prices = _load_settlement_samples(direction)
        if not prices:
            raise ValueError(
                f"Bankable mode requires participant settlement data at "
                f"{SETTLEMENT_CSV_PATH}; none found. The project entity must "
                f"be registered as a market participant and export its DAMAS "
                f"settlement records before this mode is callable."
            )
        return CapacityPrice(
            price_eur_mw_h=sum(prices) / len(prices),
            direction=direction,
            source="PARTICIPANT_SETTLEMENT",
            bankability_label="Bankable",
            n_samples=len(prices),
            window_start=None,
            window_end=None,
            note="Participant settlement export (TSO-signed).",
        )

    if mode == "catalog_floor":
        return CapacityPrice(
            price_eur_mw_h=CATALOG_FLOOR_AFRR_EUR_MW_H,
            direction=direction,
            source="CATALOG_FLOOR",
            bankability_label="Floor-only",
            n_samples=0,
            window_start=None,
            window_end=None,
            note="ROMANIAN_FR_PRODUCTS catalog floor (€5 aFRR). NOT a defensible bid.",
        )

    # Default: PUBLIC_DAMAS_SAMPLE
    prices, w_start, w_end = _load_recent_damas_samples(
        direction=direction, asof=asof,
    )
    if prices:
        avg = sum(prices) / len(prices)
        note = (
            f"Mean of {len(prices)} DAMAS public-tender samples "
            f"({w_start} → {w_end}). Recent-window default keeps the "
            f"calibration honest as Romanian aFRR capacity prices have "
            f"compressed since spring 2025. NOT bankable without "
            f"participant settlement proof."
        )
    else:
        avg = (FALLBACK_AFRR_UP_EUR_MW_H if direction == "aFRRUp"
               else FALLBACK_AFRR_DOWN_EUR_MW_H)
        note = (
            "No DAMAS samples available; using compiled-in fallback "
            "(post-Aug 2025 mean). Re-run scripts/scrape_damas_capacity.py "
            "to refresh."
        )
    return CapacityPrice(
        price_eur_mw_h=avg,
        direction=direction,
        source="PUBLIC_DAMAS_SAMPLE",
        bankability_label="Public-data / Backtest-only",
        n_samples=len(prices),
        window_start=w_start,
        window_end=w_end,
        note=note,
    )


def get_canonical_capacity_prices_summary(
    asof: Optional[date] = None,
) -> dict:
    """Convenience: both directions in one call. For API exposure."""
    up = get_canonical_capacity_price("aFRRUp", asof=asof)
    down = get_canonical_capacity_price("aFRRDown", asof=asof)
    return {
        "aFRRUp": up.to_dict(),
        "aFRRDown": down.to_dict(),
        "bankability_label": up.bankability_label,  # both share same label
        "source": up.source,
    }
