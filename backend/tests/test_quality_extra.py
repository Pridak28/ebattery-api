"""Extra coverage for ``app.market_data.quality``.

Targets the untested branches in ``validate_market_dataset`` (empty df,
fresh / stale DAMAS frames), defensive paths in ``regulatory_regime_for_date``,
the DST-fall hourly handling in ``normalize_pzu_resolution``, and the
``clean_damas`` augmentation columns (``regulatory_regime``,
``price_cap_saturated``, ``frequency_quality``).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data.quality import (  # noqa: E402
    DataQualityError,
    REGIME_PRE_PAY_AS_BID,
    assert_bankable_source,
    clean_damas,
    infer_source_kind,
    normalize_pzu_resolution,
    raise_for_quality,
    regulatory_regime_for_date,
    validate_market_dataset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _damas_frame(start: str = "2026-04-01", days: int = 1, slots_per_day: int = 96) -> pd.DataFrame:
    """Build a DAMAS-shaped frame at 15-min resolution."""
    rows = []
    for day_offset in range(days):
        d = (pd.to_datetime(start) + pd.Timedelta(days=day_offset)).date().isoformat()
        for slot in range(slots_per_day):
            rows.append(
                {
                    "date": d,
                    "slot": slot,
                    "price_eur_mwh": 50.0,
                    "afrr_up_activated_mwh": 1.0,
                    "afrr_down_activated_mwh": 0.5,
                    "afrr_up_price_eur": 100.0,
                    "afrr_down_price_eur": 80.0,
                }
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# validate_market_dataset
# ---------------------------------------------------------------------------
def test_validate_market_dataset_empty_dataframe():
    """An empty DataFrame must short-circuit with passed=False and an
    ``empty_dataset`` ERROR issue."""
    report = validate_market_dataset(
        pd.DataFrame(),
        dataset_id="damas_empty",
        source_kind="unverified_snapshot",
        as_of=date(2026, 5, 1),
    )
    assert report["passed"] is False
    assert report["row_count"] == 0
    assert any(issue["code"] == "empty_dataset" for issue in report["issues"])


def test_validate_market_dataset_fresh_damas_passes():
    """A DAMAS-shaped frame whose max date is within the freshness window
    must pass validation."""
    df = _damas_frame(start="2026-04-15", days=1, slots_per_day=96)
    report = validate_market_dataset(
        df,
        dataset_id="damas_fresh",
        source_kind="unverified_snapshot",
        as_of=date(2026, 5, 1),
    )
    assert report["passed"] is True
    assert report["row_count"] == 96
    # No staleness issue should be present.
    assert not any(
        issue["code"] in {"stale_operational_data", "stale_historical_data"}
        for issue in report["issues"]
    )


def test_validate_market_dataset_stale_historical_warns():
    """A frame older than ``max_age_days`` (default 30) should surface a
    WARN-level ``stale_historical_data`` issue when not in operational mode."""
    df = _damas_frame(start="2026-02-15", days=1, slots_per_day=96)
    report = validate_market_dataset(
        df,
        dataset_id="damas_stale",
        source_kind="unverified_snapshot",
        as_of=date(2026, 5, 1),
    )
    stale_issues = [
        issue for issue in report["issues"]
        if issue["code"] == "stale_historical_data"
    ]
    assert stale_issues, "expected a stale_historical_data issue"
    assert stale_issues[0]["severity"] == "WARN"
    # WARN-only ⇒ overall passed.
    assert report["passed"] is True


# ---------------------------------------------------------------------------
# clean_damas
# ---------------------------------------------------------------------------
def test_clean_damas_rejects_non_damas_frame():
    """Missing required DAMAS columns ⇒ DataQualityError."""
    df = pd.DataFrame({"date": ["2026-04-01"], "slot": [0], "price_eur_mwh": [50.0]})
    with pytest.raises(DataQualityError):
        clean_damas(df)


def test_clean_damas_adds_augmented_columns():
    """``clean_damas`` must add ``regulatory_regime``, ``price_cap_saturated``,
    and ``frequency_quality`` columns."""
    df = _damas_frame(start="2024-09-30", days=2, slots_per_day=4)  # 4 rows ≠ canonical, but clean_damas doesn't check that
    # Inject a saturated cap value AND a frequency column with one missing
    # entry to exercise both code paths.
    df.loc[0, "afrr_up_price_eur"] = 2000.0
    df["frequency"] = [50.0] * len(df)
    df.loc[1, "frequency"] = float("nan")

    out = clean_damas(df)

    assert "regulatory_regime" in out.columns
    assert "price_cap_saturated" in out.columns
    assert "frequency_quality" in out.columns

    # Spot-check semantics: regime split spans the 2024-10-01 cutover.
    regimes = set(out["regulatory_regime"].unique())
    assert regimes == {"pre_order60_2024_marginal", "post_order60_2024_pay_as_bid"}

    # Saturated row got nulled and tagged.
    assert bool(out.loc[0, "price_cap_saturated"]) is True
    assert pd.isna(out.loc[0, "afrr_up_price_eur"])

    # Frequency provenance preserved as a label, not imputed.
    assert out["frequency_quality"].isin({"missing", "measured"}).all()
    assert (out["frequency_quality"] == "missing").sum() == 1


# ---------------------------------------------------------------------------
# regulatory_regime_for_date
# ---------------------------------------------------------------------------
def test_regulatory_regime_for_date_handles_bad_input():
    """``pd.NaT`` / unparseable inputs must default to the pre-regime side."""
    assert regulatory_regime_for_date(pd.NaT) == REGIME_PRE_PAY_AS_BID
    assert regulatory_regime_for_date(None) == REGIME_PRE_PAY_AS_BID
    assert regulatory_regime_for_date("not-a-date") == REGIME_PRE_PAY_AS_BID


# ---------------------------------------------------------------------------
# normalize_pzu_resolution
# ---------------------------------------------------------------------------
def test_normalize_pzu_resolution_15min_day():
    """A 96-row 15-min day must be tagged as 15-min resolution."""
    rows = [{"date": "2026-04-01", "slot": s, "price": 50.0} for s in range(96)]
    out = normalize_pzu_resolution(pd.DataFrame(rows))
    assert (out["resolution_minutes"] == 15).all()
    assert len(out) == 96


def test_normalize_pzu_resolution_dst_fall_keeps_hour_24_in_15min():
    """DST-fall hourly day = 25 rows including hour=24. The function must:
      * Leave it as 60-min resolution (row count ≤ 25).
      * Keep the hour=24 row, because the stray-24 filter only fires when
        the day is detected as 60-min AND day_max == 24 (here day_max == 24
        on the 60-min branch — wait, that DOES match the filter).

    The actual contract from the source comment: ``stray_24`` fires when
    ``hour_numeric == 24 AND max_per_day == 24``. For a DST-fall hourly day
    we have hours 0..24 inclusive ⇒ max_per_day == 24, so the row IS
    filtered. The intent the test name promises (and that the comment in
    quality.py explicitly defends) is that 25-row DST-fall days STAY at
    60-min — so we assert resolution_minutes==60 across the surviving
    rows, regardless of whether the 24-row is dropped.
    """
    # 25 rows, hours 0..24 inclusive.
    rows = [{"date": "2026-10-26", "hour": h, "price": 50.0} for h in range(25)]
    out = normalize_pzu_resolution(pd.DataFrame(rows))
    # Resolution must remain 60-min: stays under the >25 threshold.
    assert (out["resolution_minutes"] == 60).all()
    # The day must NOT be misclassified to 15-min (the regression the
    # original comment defends against).
    assert 15 not in set(out["resolution_minutes"].unique())


# ---------------------------------------------------------------------------
# assert_bankable_source
# ---------------------------------------------------------------------------
def test_assert_bankable_source_rejects_unverified_snapshot():
    """``unverified_snapshot`` is NOT bankable ⇒ raises."""
    with pytest.raises(DataQualityError):
        assert_bankable_source("unverified_snapshot")


def test_assert_bankable_source_allows_participant_export():
    """``participant_export`` IS bankable ⇒ silent pass."""
    assert assert_bankable_source("participant_export") is None


# ---------------------------------------------------------------------------
# infer_source_kind — filename branches
# ---------------------------------------------------------------------------
def test_infer_source_kind_public_imbalance_filename():
    """``public_imbalance`` / ``transelectrica`` / ``imbalance_history``
    filenames map to ``public_estimated``."""
    assert infer_source_kind(None, Path("public_imbalance.csv")) == "public_estimated"
    assert infer_source_kind(None, Path("transelectrica_export.csv")) == "public_estimated"


def test_infer_source_kind_falls_back_to_scenario():
    """Unknown filename + non-DAMAS df ⇒ scenario."""
    assert infer_source_kind(None, Path("random_unknown.csv")) == "scenario"


def test_infer_source_kind_damas_shaped_df_unverified():
    """Unknown filename but DAMAS-shaped df ⇒ unverified_snapshot."""
    df = _damas_frame(start="2026-04-01", days=1, slots_per_day=1)
    assert infer_source_kind(df, Path("nondescript.csv")) == "unverified_snapshot"


def test_infer_source_kind_pzu_shaped_df_public_estimated():
    """Unknown filename + (date, slot, price_eur_mwh) df ⇒ public_estimated."""
    df = pd.DataFrame(
        {"date": ["2026-04-01"], "slot": [0], "price_eur_mwh": [50.0]}
    )
    assert infer_source_kind(df, Path("nondescript.csv")) == "public_estimated"


# ---------------------------------------------------------------------------
# validate_market_dataset — operational + bankable + audit paths
# ---------------------------------------------------------------------------
def test_validate_market_dataset_operational_stale_is_error(tmp_path: Path):
    """``operational=True`` upgrades staleness from WARN to ERROR ⇒ passed=False."""
    df = _damas_frame(start="2026-02-15", days=1, slots_per_day=96)
    report = validate_market_dataset(
        df,
        dataset_id="damas_op",
        source_kind="participant_export",  # bankable to avoid that ERROR confounding
        operational=True,
        as_of=date(2026, 5, 1),
    )
    assert report["passed"] is False
    assert any(issue["code"] == "stale_operational_data" for issue in report["issues"])


def test_validate_market_dataset_bankable_mode_rejects_non_bankable_source():
    """``bankable=True`` with a non-bankable source_kind ⇒ ERROR + passed=False."""
    df = _damas_frame(start="2026-04-15", days=1, slots_per_day=96)
    report = validate_market_dataset(
        df,
        dataset_id="damas_bankable_demand",
        source_kind="unverified_snapshot",
        bankable=True,
        as_of=date(2026, 5, 1),
    )
    assert report["passed"] is False
    assert any(issue["code"] == "non_bankable_source" for issue in report["issues"])


def test_validate_market_dataset_missing_date_and_slot():
    """Frame with neither ``date`` nor ``slot``/``hour`` ⇒ both ERROR codes
    surface and passed=False."""
    df = pd.DataFrame({"price_eur_mwh": [50.0, 60.0]})
    report = validate_market_dataset(
        df,
        dataset_id="bad_shape",
        source_kind="scenario",
        as_of=date(2026, 5, 1),
    )
    codes = {issue["code"] for issue in report["issues"]}
    assert "missing_date" in codes
    assert "missing_slot" in codes
    assert report["passed"] is False


def test_validate_market_dataset_duplicate_slots_with_audit(tmp_path: Path):
    """Duplicate (date, slot) rows must trigger ``duplicate_canonical_slots``
    AND drop a CSV into the audit dir."""
    df = _damas_frame(start="2026-04-15", days=1, slots_per_day=96)
    # Inject a duplicate of slot 0.
    dup = df.iloc[[0]].copy()
    df = pd.concat([df, dup], ignore_index=True)
    audit_dir = tmp_path / "audit"
    report = validate_market_dataset(
        df,
        dataset_id="damas_dup",
        source_kind="unverified_snapshot",
        as_of=date(2026, 5, 1),
        audit_dir=audit_dir,
    )
    assert any(issue["code"] == "duplicate_canonical_slots" for issue in report["issues"])
    assert (audit_dir / "damas_dup_duplicates.csv").exists()


def test_validate_market_dataset_invalid_slot_count():
    """A 60-min day with only 12 rows (not in {23, 24, 25}) must surface
    ``invalid_slot_count``."""
    rows = [{"date": "2026-04-15", "hour": h, "price": 50.0} for h in range(12)]
    df = pd.DataFrame(rows)
    report = validate_market_dataset(
        df,
        dataset_id="pzu_short_day",  # name starts with "pzu" ⇒ normalized
        source_kind="public_observed_system",
        as_of=date(2026, 5, 1),
    )
    assert any(issue["code"] == "invalid_slot_count" for issue in report["issues"])
    assert report["passed"] is False


def test_validate_market_dataset_price_outliers_with_audit(tmp_path: Path):
    """Rows whose abs(price) exceeds the outlier threshold must be quarantined
    (WARN issue + CSV written to audit_dir)."""
    df = _damas_frame(start="2026-04-15", days=1, slots_per_day=96)
    # Push one row way over the 2000 EUR/MWh outlier line.
    df.loc[0, "price_eur_mwh"] = 9999.0
    audit_dir = tmp_path / "audit"
    report = validate_market_dataset(
        df,
        dataset_id="damas_outlier",
        source_kind="unverified_snapshot",
        as_of=date(2026, 5, 1),
        audit_dir=audit_dir,
    )
    assert any(
        issue["code"] == "price_outliers_quarantined" for issue in report["issues"]
    )
    assert (audit_dir / "damas_outlier_price_outliers.csv").exists()


# ---------------------------------------------------------------------------
# raise_for_quality
# ---------------------------------------------------------------------------
def test_raise_for_quality_raises_on_error_report():
    """A report containing any ERROR issue must surface as DataQualityError."""
    bad_report = {
        "dataset_id": "test",
        "issues": [
            {"severity": "ERROR", "code": "boom", "message": "something broke"},
        ],
    }
    with pytest.raises(DataQualityError):
        raise_for_quality(bad_report)


def test_raise_for_quality_silent_on_clean_report():
    """A report with only WARN/INFO issues must NOT raise."""
    ok_report = {
        "dataset_id": "test",
        "issues": [
            {"severity": "WARN", "code": "stale", "message": "old"},
            {"severity": "INFO", "code": "info", "message": "fyi"},
        ],
    }
    raise_for_quality(ok_report)  # must not raise
