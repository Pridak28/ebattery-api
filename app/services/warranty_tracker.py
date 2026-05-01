"""
Phase D3 — Throughput-warranty + augmentation tracker.

Vendor warranties are written as "X equivalent full cycles (EFC) over Y years".
Typical Romanian-grade Li-ion BESS: 6,000 EFC over 15 years (~400 EFC/yr).
Exceeding the EFC budget voids warranty AND requires capacity augmentation
(extra battery racks). Industry rule of thumb: +10% of EPC at year 5 and
year 10 maintains rated capacity through year 15.

Used by ``investment_service._create_cashflow`` to:
  1. accumulate EFC year-over-year,
  2. flag the year warranty breaches the budget,
  3. inject augmentation CAPEX outflows in the right years.

This module has zero state — pure functions tested in
``tests/test_physical_realism.py``.
"""
from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, Field


class WarrantyConfig(BaseModel):
    """Vendor warranty terms + augmentation policy."""
    efc_budget: int = Field(6000, ge=1, description="Equivalent full cycles allowed across asset life")
    warranty_years: int = Field(15, ge=1, le=30, description="Asset / warranty horizon")
    augmentation_cost_pct_of_epc: float = Field(
        10.0, ge=0.0, le=50.0,
        description="Augmentation CAPEX as % of EPC, applied at year 5 and year 10",
    )
    augmentation_years: List[int] = Field(
        default_factory=lambda: [5, 10],
        description="Years where augmentation CAPEX hits the cashflow",
    )


class WarrantyYearResult(BaseModel):
    """Per-year warranty + augmentation snapshot."""
    year: int
    annual_efc: float
    cumulative_efc: float
    warranty_status: Literal["ok", "exceeded"]
    augmentation_cost_eur: float = 0.0


def track_throughput(
    annual_efc: float,
    year: int,
    cumulative_efc: float,
    epc_eur: float,
    cfg: WarrantyConfig,
) -> Dict[str, float]:
    """Step the warranty tracker forward by one year.

    Parameters
    ----------
    annual_efc:
        Equivalent full cycles consumed in this year.
    year:
        1-indexed year number.
    cumulative_efc:
        EFC consumed up to (but not including) this year.
    epc_eur:
        Battery EPC value (used to size augmentation cost).
    cfg:
        Warranty configuration.

    Returns
    -------
    dict with:
      - cumulative_efc (after the year)
      - warranty_exceeded (bool)
      - augmentation_cost_eur (>0 only on configured augmentation years)
    """
    new_cumulative = float(cumulative_efc) + float(annual_efc)
    exceeded = new_cumulative > cfg.efc_budget
    aug_cost = 0.0
    if year in cfg.augmentation_years and epc_eur > 0:
        aug_cost = float(epc_eur) * cfg.augmentation_cost_pct_of_epc / 100.0
    return {
        "cumulative_efc": new_cumulative,
        "warranty_exceeded": bool(exceeded),
        "augmentation_cost_eur": aug_cost,
    }


def project_warranty(
    annual_efc: float,
    epc_eur: float,
    cfg: WarrantyConfig,
) -> List[WarrantyYearResult]:
    """Project the full year-by-year warranty + augmentation schedule.

    Convenience helper for tests + frontend. Total augmentation cost over the
    asset life equals ``len(cfg.augmentation_years) * augmentation_cost_pct_of_epc / 100 * epc_eur``.
    """
    out: List[WarrantyYearResult] = []
    cumulative = 0.0
    for year in range(1, cfg.warranty_years + 1):
        step = track_throughput(annual_efc, year, cumulative, epc_eur, cfg)
        cumulative = step["cumulative_efc"]
        out.append(WarrantyYearResult(
            year=year,
            annual_efc=float(annual_efc),
            cumulative_efc=cumulative,
            warranty_status="exceeded" if step["warranty_exceeded"] else "ok",
            augmentation_cost_eur=step["augmentation_cost_eur"],
        ))
    return out
