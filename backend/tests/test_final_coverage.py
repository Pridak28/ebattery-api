"""Final coverage closeout for app.market_data.quality and app.models.investment.

Targets the residual uncovered defensive branches and the InvestorSummary
model so combined backend coverage clears the 94% bar.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data.quality import (  # noqa: E402
    REGIME_PRE_PAY_AS_BID,
    _log_warning,
    _slot_count_allowed,
    clean_damas,
    normalize_pzu_resolution,
    regulatory_regime_for_date,
    validate_market_dataset,
)
from app.models.investment import (  # noqa: E402
    ComplianceGates,
    InvestorSummary,
)


# ---------------------------------------------------------------------------
# quality.py — defensive branches
# ---------------------------------------------------------------------------


def test_log_warning_writes_to_stderr(capsys):
    """Cover line 38 — _log_warning emits the prefixed message on stderr."""
    _log_warning("hello world")
    captured = capsys.readouterr()
    assert "[quality.py WARN] hello world" in captured.err


def test_normalize_pzu_resolution_returns_early_without_required_columns():
    """Cover line 95 — early return when neither date nor slot exist after init."""
    # Frame has neither 'date' nor 'slot' nor 'hour' — falls through to the
    # 'date' missing guard at line 94 and returns the copy unchanged.
    df = pd.DataFrame({"price_eur_mwh": [50.0, 60.0]})
    out = normalize_pzu_resolution(df)
    assert "resolution_minutes" not in out.columns
    assert list(out.columns) == ["price_eur_mwh"]
    assert len(out) == 2


def test_normalize_pzu_resolution_returns_early_with_only_date():
    """Cover line 95 — early return when only date exists (no slot/hour)."""
    df = pd.DataFrame({"date": ["2026-01-01", "2026-01-02"], "x": [1, 2]})
    out = normalize_pzu_resolution(df)
    assert "resolution_minutes" not in out.columns


def test_regulatory_regime_for_date_exception_fallback():
    """Cover lines 138-139 — defensive except path returns pre-regime.

    Passing a list/array makes ``pd.to_datetime`` return a DatetimeIndex.
    ``pd.isna`` then yields a boolean array, and ``if pd.isna(ts):`` raises
    ``ValueError`` ("truth value of an array is ambiguous"), which is caught
    by the defensive ``except Exception`` branch.
    """
    result = regulatory_regime_for_date(["2024-01-01", "2025-01-01"])
    assert result == REGIME_PRE_PAY_AS_BID


def test_clean_damas_writes_duplicates_audit(tmp_path):
    """Cover line 200 — audit_dir + non-empty duplicates triggers CSV write."""
    rows = []
    # Two duplicate (date, slot) pairs with different metric values.
    for slot in range(96):
        rows.append(
            {
                "date": "2026-04-01",
                "slot": slot,
                "price_eur_mwh": 50.0,
                "afrr_up_activated_mwh": 1.0,
                "afrr_down_activated_mwh": 0.5,
                "afrr_up_price_eur": 100.0,
                "afrr_down_price_eur": 80.0,
                "frequency": 50.0,
            }
        )
    # Inject duplicate slot=0 row to force the audit dump branch.
    rows.append(
        {
            "date": "2026-04-01",
            "slot": 0,
            "price_eur_mwh": 99.0,
            "afrr_up_activated_mwh": 2.0,
            "afrr_down_activated_mwh": 1.0,
            "afrr_up_price_eur": 110.0,
            "afrr_down_price_eur": 90.0,
            "frequency": 50.0,
        }
    )
    df = pd.DataFrame(rows)
    audit_dir = tmp_path / "audit"
    cleaned = clean_damas(df, audit_dir=audit_dir)
    assert len(cleaned) == 96  # duplicates collapsed
    audit_file = audit_dir / "damas_duplicates.csv"
    assert audit_file.exists()
    audit_content = pd.read_csv(audit_file)
    assert len(audit_content) >= 2  # both members of the dup-pair are dumped


def test_slot_count_allowed_unknown_resolution_returns_empty_set():
    """Cover line 213 — unknown resolution returns empty allowed set."""
    assert _slot_count_allowed(30) == set()
    assert _slot_count_allowed(0) == set()
    assert _slot_count_allowed(5) == set()


def test_validate_market_dataset_missing_date_column_emits_error():
    """Cover line 260 — missing date column raises ERROR issue."""
    df = pd.DataFrame({"slot": [0, 1, 2], "price_eur_mwh": [10, 20, 30]})
    report = validate_market_dataset(df, dataset_id="custom_set")
    codes = {issue["code"]: issue["severity"] for issue in report["issues"]}
    assert codes.get("missing_date") == "ERROR"
    assert report["passed"] is False


def test_validate_market_dataset_invalid_slot_count_emits_error():
    """Cover the invalid_slot_count branch + the resolution-lookup try/except.

    Build a frame whose slot count for the day is outside the allowed
    {23,24,25} for 60-min and {92,96,100} for 15-min — only 50 slots — to
    force the bad-day branch (line 289) and exercise the resolution lookup
    (lines 281-284).
    """
    rows = []
    for slot in range(50):  # not in any allowed bucket
        rows.append({"date": "2026-04-01", "slot": slot, "price_eur_mwh": 40.0})
    df = pd.DataFrame(rows)
    df["resolution_minutes"] = 60  # forces _slot_count_allowed -> {23,24,25}
    report = validate_market_dataset(df, dataset_id="custom_set")
    codes = [issue["code"] for issue in report["issues"]]
    assert "invalid_slot_count" in codes
    assert report["passed"] is False


def test_validate_market_dataset_resolution_lookup_exception_fallback():
    """Cover lines 283-284 — resolution_by_day .loc[day] raises => resolution=0.

    Trick: poison resolution_minutes with NaN so the per-day .first() returns
    NaN and the int() cast raises, hitting the defensive except.
    """
    rows = []
    for slot in range(96):
        rows.append(
            {
                "date": "2026-04-02",
                "slot": slot,
                "price_eur_mwh": 30.0,
                "resolution_minutes": float("nan"),
            }
        )
    df = pd.DataFrame(rows)
    # All resolution_minutes NaN -> dropna().unique() empty -> sorted() == []
    # so len(resolutions) == 1 path is skipped, but resolution_by_day.first()
    # still returns NaN per day; int(NaN) raises ValueError -> resolution = 0
    # -> _slot_count_allowed(0) == set() -> day skipped. No error issued, but
    # the except branch executes.
    report = validate_market_dataset(df, dataset_id="custom_set")
    # No invalid_slot_count because allowed-set is empty when resolution=0
    codes = [issue["code"] for issue in report["issues"]]
    assert "invalid_slot_count" not in codes


# ---------------------------------------------------------------------------
# investment.py — ComplianceGates branches
# ---------------------------------------------------------------------------


def test_compliance_gates_missing_returns_only_unqualified():
    """Cover lines 78-82 — missing() lists every gate not yet 'qualified'."""
    gates = ComplianceGates(
        anre_license_status="qualified",
        opcom_short_term_participant="qualified",
        brp_pre_responsibility="in_progress",
        # all others default to 'not_declared'
    )
    missing = gates.missing()
    assert "anre_license_status" not in missing
    assert "opcom_short_term_participant" not in missing
    assert "brp_pre_responsibility" in missing  # in_progress != qualified
    assert "fse_bsp_convention" in missing  # not_declared


def test_compliance_gates_missing_when_all_qualified_returns_empty():
    """Boundary — fully qualified project leaves missing() empty."""
    fields = ComplianceGates.model_fields.keys()
    gates = ComplianceGates(**{name: "qualified" for name in fields})
    assert gates.missing() == []


def test_revenue_streams_blocked_no_license_returns_all_revenue_block():
    """ANRE license missing => single 'ALL revenue' block, short-circuit."""
    gates = ComplianceGates()  # all not_declared
    blocked = gates.revenue_streams_blocked()
    assert blocked == ["ALL revenue (no ANRE-recognized activity)"]


def test_revenue_streams_blocked_no_brp_pre_returns_all_market_block():
    """License OK but no BRP/PRE => 'ALL market revenue' short-circuit (line 91)."""
    fields = {name: "not_declared" for name in ComplianceGates.model_fields.keys()}
    fields["anre_license_status"] = "qualified"
    fields["brp_pre_responsibility"] = "in_progress"
    gates = ComplianceGates(**fields)
    blocked = gates.revenue_streams_blocked()
    assert blocked == ["ALL market revenue (no BRP/PRE)"]


def test_revenue_streams_blocked_only_pzu_idm_when_opcom_missing():
    """Cover line 94 — only OPCOM short-term missing => only PZU/IDM blocked."""
    fields = {name: "qualified" for name in ComplianceGates.model_fields.keys()}
    fields["opcom_short_term_participant"] = "in_progress"
    gates = ComplianceGates(**fields)
    blocked = gates.revenue_streams_blocked()
    assert blocked == ["PZU / IDM arbitrage"]


def test_revenue_streams_blocked_afrr_mfrr_block_when_fse_missing():
    """Cover line 100 — FSE missing triggers aFRR/mFRR block, not all-revenue."""
    fields = {name: "qualified" for name in ComplianceGates.model_fields.keys()}
    fields["fse_bsp_convention"] = "in_progress"
    gates = ComplianceGates(**fields)
    blocked = gates.revenue_streams_blocked()
    assert "aFRR / mFRR capacity + activation" in blocked
    assert "ALL revenue (no ANRE-recognized activity)" not in blocked
    assert "ALL market revenue (no BRP/PRE)" not in blocked


def test_revenue_streams_blocked_afrr_mfrr_block_when_damas_missing():
    """Cover line 100 via the DAMAS branch of the OR."""
    fields = {name: "qualified" for name in ComplianceGates.model_fields.keys()}
    fields["damas_access"] = "in_progress"
    gates = ComplianceGates(**fields)
    blocked = gates.revenue_streams_blocked()
    assert "aFRR / mFRR capacity + activation" in blocked


def test_revenue_streams_blocked_afrr_mfrr_block_when_capacity_register_missing():
    """Cover line 100 via the capacity-reserve register branch."""
    fields = {name: "qualified" for name in ComplianceGates.model_fields.keys()}
    fields["capacity_reserve_auction_register"] = "not_declared"
    gates = ComplianceGates(**fields)
    blocked = gates.revenue_streams_blocked()
    assert "aFRR / mFRR capacity + activation" in blocked


def test_revenue_streams_blocked_fcr_block_when_rsf_missing():
    """Cover line 102 — RSF missing => FCR (RSF) block."""
    fields = {name: "qualified" for name in ComplianceGates.model_fields.keys()}
    fields["rsf_fcr_qualification"] = "in_progress"
    gates = ComplianceGates(**fields)
    blocked = gates.revenue_streams_blocked()
    assert blocked == ["FCR (RSF)"]


def test_revenue_streams_blocked_storage_tariff_block_when_metering_missing():
    """Cover line 104 — storage tariff metering missing => storage exemption block."""
    fields = {name: "qualified" for name in ComplianceGates.model_fields.keys()}
    fields["storage_tariff_exemption_metering"] = "not_declared"
    gates = ComplianceGates(**fields)
    blocked = gates.revenue_streams_blocked()
    assert blocked == [
        "Storage tariff exemption (avoided cost) per Law 123 Art. 66³"
    ]


def test_revenue_streams_blocked_combined_blocks_when_multiple_missing():
    """Cascade — license+brp OK, several downstream gates missing."""
    fields = {name: "qualified" for name in ComplianceGates.model_fields.keys()}
    fields["opcom_short_term_participant"] = "in_progress"
    fields["fse_bsp_convention"] = "in_progress"
    fields["rsf_fcr_qualification"] = "not_declared"
    fields["storage_tariff_exemption_metering"] = "not_declared"
    gates = ComplianceGates(**fields)
    blocked = gates.revenue_streams_blocked()
    assert "PZU / IDM arbitrage" in blocked
    assert "aFRR / mFRR capacity + activation" in blocked
    assert "FCR (RSF)" in blocked
    assert "Storage tariff exemption (avoided cost) per Law 123 Art. 66³" in blocked
    # No short-circuit blocks
    assert "ALL revenue (no ANRE-recognized activity)" not in blocked
    assert "ALL market revenue (no BRP/PRE)" not in blocked


# ---------------------------------------------------------------------------
# investment.py — InvestorSummary instantiation (lines 385-425)
# ---------------------------------------------------------------------------


def test_investor_summary_instantiation_with_required_fields():
    summary = InvestorSummary(
        generated_at_utc="2026-05-02T00:00:00Z",
        project_sizing="10 MW / 20 MWh",
        capex_eur=3_500_000.0,
        fr_y1_net_profit_eur=500_000.0,
        pzu_y1_net_profit_eur=200_000.0,
        combined_y1_net_profit_eur=700_000.0,
        fr_lifetime_irr_pct=12.5,
        pzu_lifetime_irr_pct=6.5,
        irr_tier="high",
        bankability_level="public_observed",
        settlement_grade=False,
        pricing_basis="public_marginal",
        revenue_source="simulation",
        dscr_y1=1.5,
        dscr_worst_year=1.1,
        dscr_violation_count=1,
        picasso_compression_modeled=True,
        compliance_gates_qualified_count=3,
        most_blocking_gate="brp_pre_responsibility",
        blocked_revenue_streams=["PZU / IDM arbitrage"],
        fr_capacity_revenue_y1=300_000.0,
        fr_activation_revenue_y1=200_000.0,
        pzu_arbitrage_y1=200_000.0,
        tariff_exemption_y1=10_000.0,
        disclaimer="Numbers are illustrative; verify before commitment.",
        audit_reference="audit/REPORT.md",
    )
    assert summary.irr_tier == "high"
    assert summary.compliance_gates_total == 11  # default
    assert summary.most_blocking_gate == "brp_pre_responsibility"
    assert summary.blocked_revenue_streams == ["PZU / IDM arbitrage"]
    # Round-trip serialization exercises every declared field.
    payload = summary.model_dump()
    assert payload["capex_eur"] == 3_500_000.0
    assert payload["fr_lifetime_irr_pct"] == 12.5
    assert payload["compliance_gates_total"] == 11


def test_investor_summary_irr_tier_unknown_when_irr_missing():
    summary = InvestorSummary(
        generated_at_utc="2026-05-02T00:00:00Z",
        project_sizing="10 MW / 20 MWh",
        capex_eur=3_500_000.0,
        fr_y1_net_profit_eur=0.0,
        pzu_y1_net_profit_eur=0.0,
        combined_y1_net_profit_eur=0.0,
        irr_tier="unknown",
        bankability_level="scenario",
        settlement_grade=False,
        pricing_basis="scenario",
        revenue_source="fallback_estimate",
        dscr_y1=0.0,
        dscr_worst_year=0.0,
        dscr_violation_count=0,
        picasso_compression_modeled=False,
        compliance_gates_qualified_count=0,
        fr_capacity_revenue_y1=0.0,
        fr_activation_revenue_y1=0.0,
        pzu_arbitrage_y1=0.0,
        tariff_exemption_y1=0.0,
        disclaimer="N/A",
        audit_reference="audit/REPORT.md",
    )
    assert summary.fr_lifetime_irr_pct is None
    assert summary.pzu_lifetime_irr_pct is None
    assert summary.most_blocking_gate is None
    assert summary.blocked_revenue_streams == []


def test_investor_summary_irr_tier_rejects_invalid_literal():
    with pytest.raises(ValueError):
        InvestorSummary(
            generated_at_utc="2026-05-02T00:00:00Z",
            project_sizing="10 MW / 20 MWh",
            capex_eur=0.0,
            fr_y1_net_profit_eur=0.0,
            pzu_y1_net_profit_eur=0.0,
            combined_y1_net_profit_eur=0.0,
            irr_tier="amazing",  # not in Literal set
            bankability_level="scenario",
            settlement_grade=False,
            pricing_basis="scenario",
            revenue_source="simulation",
            dscr_y1=0.0,
            dscr_worst_year=0.0,
            dscr_violation_count=0,
            picasso_compression_modeled=False,
            compliance_gates_qualified_count=0,
            fr_capacity_revenue_y1=0.0,
            fr_activation_revenue_y1=0.0,
            pzu_arbitrage_y1=0.0,
            tariff_exemption_y1=0.0,
            disclaimer="N/A",
            audit_reference="audit/REPORT.md",
        )
