"""
Stored-energy tariff exemption — Law 123 Art. 66³ + ANRE Order 56/2025.

Romanian battery storage qualifies for an exemption from regulated charges
on the slice of energy that is withdrawn → stored → reinjected to the grid
(i.e. the "trading" leg of arbitrage / FR activation, not the auxiliary /
loss / final-consumption draws).

This module computes that exemption as an AVOIDED COST, not as gross market
revenue — investors and lenders should treat it accordingly. Audit ref:
``audit/ROMANIAN_BESS_LAW_REVENUE_IMPLEMENTATION_AUDIT_2026-05-01.md``,
"Tariff / Certificate Exemptions" section.

Anchors:
- Law 123/2012 Art. 66³ (storage exemption framework).
- ANRE Order 56/2025 (operationalises the exemption rules).
- ANRE Order 18/2024 (transmission/distribution tariff schedule context).

The default per-MWh values below are audit-anchored mid-bands for 2024-2026
Romanian regulated charges (transmission Tl/Tg, distribution Td, system-
service component, green certificate CV contribution, cogeneration CHE
contribution). They MUST be checked against ANRE's current orders before
bankable use; the model only claims to be a defensible scenario, not a
settlement-grade calculation.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TariffExemptionRates(BaseModel):
    """Per-MWh avoided regulated charges (EUR/MWh).

    All values applied to the storage round-trip throughput (the energy that
    is withdrawn THEN reinjected). Final consumption / aux draws are NOT
    eligible — the law and ANRE Order 56/2025 explicitly distinguish.
    """
    transmission_tl_eur_mwh: float = Field(
        13.0, ge=0.0, le=200.0,
        description="Transmission consumption component (Tl) — biggest single slice.",
    )
    transmission_tg_eur_mwh: float = Field(
        3.0, ge=0.0, le=200.0,
        description="Transmission generation component (Tg).",
    )
    distribution_td_eur_mwh: float = Field(
        0.0, ge=0.0, le=200.0,
        description="Distribution component (Td) — only for projects connected at MV/LV. Default 0 = transmission-grid connected.",
    )
    system_services_eur_mwh: float = Field(
        1.7, ge=0.0, le=50.0,
        description="System services tariff component.",
    )
    green_certificate_eur_mwh: float = Field(
        7.0, ge=0.0, le=50.0,
        description="Green certificate (CV) contribution — per Law 220/2008 framework.",
    )
    cogeneration_eur_mwh: float = Field(
        7.5, ge=0.0, le=50.0,
        description="High-efficiency cogeneration contribution (CHE).",
    )

    def total_eur_mwh(self) -> float:
        return float(
            self.transmission_tl_eur_mwh
            + self.transmission_tg_eur_mwh
            + self.distribution_td_eur_mwh
            + self.system_services_eur_mwh
            + self.green_certificate_eur_mwh
            + self.cogeneration_eur_mwh
        )

    def breakdown(self) -> Dict[str, float]:
        return {
            "transmission_tl": self.transmission_tl_eur_mwh,
            "transmission_tg": self.transmission_tg_eur_mwh,
            "distribution_td": self.distribution_td_eur_mwh,
            "system_services": self.system_services_eur_mwh,
            "green_certificate": self.green_certificate_eur_mwh,
            "cogeneration": self.cogeneration_eur_mwh,
        }


class TariffExemptionRequest(BaseModel):
    power_mw: float = Field(10.0, ge=0.1, le=1000.0)
    capacity_mwh: float = Field(20.0, ge=0.1, le=2000.0)
    cycles_per_day: float = Field(1.0, ge=0.0, le=4.0, description="Effective full cycles per calendar day")
    operating_days_per_year: int = Field(365, ge=1, le=366)
    rates: Optional[TariffExemptionRates] = None


class TariffExemptionResult(BaseModel):
    """Avoided-cost result. NOT market revenue — accounting/regulatory benefit."""
    annual_throughput_mwh: float
    rate_eur_mwh: float
    avoided_cost_eur: float
    breakdown_eur_mwh: Dict[str, float]
    revenue_classification: str = Field(
        "avoided_regulated_cost",
        description="NOT 'market_revenue' — investors must keep this line separate.",
    )
    legal_basis: List[str] = Field(
        default_factory=lambda: [
            "Law 123/2012 Art. 66³ — storage exemption framework",
            "ANRE Order 56/2025 — exemption rules and metering requirements",
        ]
    )
    requires_metering_qualification: bool = Field(
        True,
        description="Eligibility requires ANRE-conformant metering that distinguishes stored vs reinjected energy.",
    )
    warnings: List[str] = Field(
        default_factory=lambda: [
            "Default rates are mid-band 2024-2026 estimates; replace with current ANRE published tariffs before bankable use.",
            "Eligibility is conditional on the metering qualification gate (compliance_gates.storage_tariff_exemption_metering).",
            "Avoided cost is recognized as accounting / regulatory benefit, not gross market revenue.",
        ]
    )


def compute_tariff_exemption(req: TariffExemptionRequest) -> TariffExemptionResult:
    """Compute annual avoided regulated charges for a given BESS sizing.

    Throughput is bounded by the smaller of (a) cycles × capacity × days
    and (b) an implicit power × hours × days ceiling. We use the cycle-based
    figure here; the platform's other simulators already enforce throughput
    caps separately, and this module's job is the avoided-cost accounting.
    """
    rates = req.rates or TariffExemptionRates()
    rate_per_mwh = rates.total_eur_mwh()
    annual_throughput_mwh = float(
        req.cycles_per_day * req.capacity_mwh * req.operating_days_per_year
    )
    avoided_cost_eur = annual_throughput_mwh * rate_per_mwh

    return TariffExemptionResult(
        annual_throughput_mwh=annual_throughput_mwh,
        rate_eur_mwh=rate_per_mwh,
        avoided_cost_eur=avoided_cost_eur,
        breakdown_eur_mwh=rates.breakdown(),
    )
