from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.market_data.manifest import data_date_bounds
from app.market_data.schemas import (
    BANKABLE_SOURCE_KINDS,
    PUBLIC_OR_UNVERIFIED_SOURCE_KINDS,
    REQUIRED_DAMAS_COLUMNS,
    SOURCE_KIND_DERIVED_PUBLIC,
    SOURCE_KIND_PUBLIC_ESTIMATED,
    SOURCE_KIND_PUBLIC_OBSERVED_SYSTEM,
    SOURCE_KIND_SCENARIO,
    SOURCE_KIND_UNVERIFIED_SNAPSHOT,
    bankability_level_for_source,
    is_damas_shaped,
)


PRICE_OUTLIER_THRESHOLD_EUR = 2000.0
FRESHNESS_LIMIT_DAYS = 30

# D-WARN-1: aFRR price-feed cap saturation thresholds. The €2000 boundary is
# the platform-imposed price ceiling/floor — values that hit it are not real
# clearing prices but censored sentinels and must be treated as missing.
PRICE_CAP_SATURATION_LOWER = 1999.79
PRICE_CAP_SATURATION_UPPER = 2000.01
PRICE_CAP_SATURATION_NEG = -1999.79


def _log_warning(message: str) -> None:
    """Lightweight stderr warning logger (no logging framework configured here)."""
    print(f"[quality.py WARN] {message}", file=sys.stderr)


class DataQualityError(RuntimeError):
    pass


def infer_source_kind(df: pd.DataFrame | None = None, path: Path | str | None = None) -> str:
    if df is not None:
        attr_kind = df.attrs.get("source_kind")
        if attr_kind:
            return str(attr_kind)
        if "source_kind" in df.columns:
            values = df["source_kind"].dropna().astype(str).unique()
            if len(values) == 1:
                return values[0]
    name = Path(path).name.lower() if path else ""
    if "fr_data_clean" in name:
        return SOURCE_KIND_DERIVED_PUBLIC
    if "pzu" in name:
        return SOURCE_KIND_PUBLIC_OBSERVED_SYSTEM
    if "public_imbalance" in name or "transelectrica" in name or "imbalance_history" in name:
        return SOURCE_KIND_PUBLIC_ESTIMATED
    if "damas_complete_fr_dataset" in name or "damas_clean" in name:
        return SOURCE_KIND_UNVERIFIED_SNAPSHOT
    if df is not None and is_damas_shaped(df.columns):
        return SOURCE_KIND_UNVERIFIED_SNAPSHOT
    if df is not None and {"date", "slot", "price_eur_mwh"}.issubset(df.columns):
        return SOURCE_KIND_PUBLIC_ESTIMATED
    return SOURCE_KIND_SCENARIO


def assert_bankable_source(source_kind: str) -> None:
    if source_kind not in BANKABLE_SOURCE_KINDS:
        raise DataQualityError(
            f"source_kind={source_kind!r} is not settlement/bankable. "
            "Bankable mode requires participant_export or settlement_export."
        )


def normalize_pzu_resolution(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    # D-WARN-4: drop stray hour=24 rows from upstream PZU 60-min exports. These
    # are a DST artifact (typically a single row per DST-fall day mis-encoded as
    # hour=24) and break downstream slot indexing. We restrict the filter to
    # 60-min days only — in 15-min exports, slot indices legitimately reach 24
    # and beyond (and the column is `hour` overloaded as `slot`). A 60-min day
    # is identified by having no other slot value > 24 on the same date.
    if "hour" in out.columns and "date" in out.columns:
        hour_numeric = pd.to_numeric(out["hour"], errors="coerce")
        max_per_day = hour_numeric.groupby(out["date"]).transform("max")
        stray_24 = (hour_numeric == 24) & (max_per_day == 24)
        if stray_24.any():
            out = out[~stray_24].copy()
    if "slot" not in out.columns and "hour" in out.columns:
        out["slot"] = pd.to_numeric(out["hour"], errors="coerce")
    if "date" not in out.columns or "slot" not in out.columns:
        return out
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date.astype(str)
    out["slot"] = pd.to_numeric(out["slot"], errors="coerce")
    out["resolution_minutes"] = 60
    # Resolution detection uses row count alone:
    #   - 60-min legit counts: 23 (DST spring), 24, 25 (DST fall, hour=24 valid)
    #   - 15-min legit counts: 92 (DST spring), 96, 100 (DST fall)
    # The earlier `max_slot > 23` heuristic mis-classified DST-fall hourly days
    # (25 rows with hour=24) as 15-min, breaking slot-count validation.
    for _, idx in out.groupby("date", dropna=False).groups.items():
        sub = out.loc[idx]
        if len(sub) > 25:
            out.loc[idx, "resolution_minutes"] = 15
    return out


# A-1 / A-2: Romanian aFRR regulatory regime change. ANRE Order 60/2024
# entered into force on 2024-10-01, switching balancing-energy settlement from
# marginal pricing to pay-as-bid. Pre- and post- behaviour are materially
# different markets — captured prices, distributions, and bidder strategies
# all change. Surface this on every DAMAS row so the simulator can split
# aggregates per regime, and so users see a clear regime label.
ANRE_ORDER_60_2024_EFFECTIVE_DATE = "2024-10-01"
REGIME_PRE_PAY_AS_BID = "pre_order60_2024_marginal"
REGIME_POST_PAY_AS_BID = "post_order60_2024_pay_as_bid"


def regulatory_regime_for_date(d) -> str:
    """Return ``REGIME_PRE_PAY_AS_BID`` or ``REGIME_POST_PAY_AS_BID`` for a date.

    Accepts strings (``YYYY-MM-DD``), ``datetime.date``, ``datetime.datetime``,
    or pandas ``Timestamp``. Anything that fails to parse maps to the pre-regime
    side conservatively.
    """
    try:
        ts = pd.to_datetime(d, errors="coerce")
        if pd.isna(ts):
            return REGIME_PRE_PAY_AS_BID
        return (
            REGIME_POST_PAY_AS_BID
            if ts.date() >= pd.to_datetime(ANRE_ORDER_60_2024_EFFECTIVE_DATE).date()
            else REGIME_PRE_PAY_AS_BID
        )
    except Exception:  # noqa: BLE001 — defensive
        return REGIME_PRE_PAY_AS_BID


def clean_damas(df: pd.DataFrame, audit_dir: Path | None = None) -> pd.DataFrame:
    if not is_damas_shaped(df.columns):
        missing = [col for col in REQUIRED_DAMAS_COLUMNS if col not in df.columns]
        raise DataQualityError(f"DAMAS-shaped frame expected; missing columns: {missing}")
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date.astype(str)
    out["slot"] = pd.to_numeric(out["slot"], errors="coerce").astype("Int64")
    dup_mask = out.duplicated(["date", "slot"], keep="last")
    duplicates = out[out.duplicated(["date", "slot"], keep=False)].copy()
    out = out[~dup_mask].reset_index(drop=True)
    for col in REQUIRED_DAMAS_COLUMNS:
        if col != "date" and col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # D-WARN-1: detect aFRR price-feed cap saturation. Rows whose
    # ``afrr_up_price_eur`` or ``afrr_down_price_eur`` sit at the platform's
    # ±€2000 ceiling are not real clearing prices — they are censored sentinels
    # produced when the price feed clips. Convert those values to NaN so they do
    # not contaminate aggregates, and surface a per-row boolean so downstream
    # consumers (and the QA pipeline) can audit the affected slots.
    cap_mask = pd.Series(False, index=out.index)
    for cap_col in ("afrr_up_price_eur", "afrr_down_price_eur"):
        if cap_col in out.columns:
            values = pd.to_numeric(out[cap_col], errors="coerce")
            col_mask = (
                values.between(PRICE_CAP_SATURATION_LOWER, PRICE_CAP_SATURATION_UPPER)
                | (values <= PRICE_CAP_SATURATION_NEG)
            )
            col_mask = col_mask.fillna(False)
            if col_mask.any():
                out.loc[col_mask, cap_col] = float("nan")
            cap_mask = cap_mask | col_mask
    out["price_cap_saturated"] = cap_mask
    cap_count = int(cap_mask.sum())
    out.attrs["_price_cap_saturated_count"] = cap_count
    if cap_count > 0:
        _log_warning(
            f"D-WARN-1: nulled {cap_count} aFRR price rows saturating the ±€2000 cap "
            "(set to NaN; price_cap_saturated=True)"
        )

    # A-1: tag every row with the regulatory regime in force on its delivery
    # date. Allows the simulator to aggregate per-regime metrics and to refuse
    # to merge incompatible price distributions silently.
    out["regulatory_regime"] = out["date"].apply(regulatory_regime_for_date)

    # D-WARN-3: do NOT impute missing frequency. ~25 % of DAMAS rows have no
    # ``frequency`` measurement; silently filling them would falsify physical
    # context. Instead label provenance per row and surface the missing % so
    # downstream consumers can decide how to treat each subset.
    if "frequency" in out.columns and len(out) > 0:
        freq_missing = out["frequency"].isna()
        out["frequency_quality"] = freq_missing.map({True: "missing", False: "measured"})
        out.attrs["frequency_missing_pct"] = float(freq_missing.sum() / len(out) * 100)

    if audit_dir is not None:
        audit_dir.mkdir(parents=True, exist_ok=True)
        if not duplicates.empty:
            duplicates.to_csv(audit_dir / "damas_duplicates.csv", index=False)
    return out


def _issue(issues: list[dict[str, Any]], severity: str, code: str, message: str, **extra: Any) -> None:
    issues.append({"severity": severity, "code": code, "message": message, **extra})


def _slot_count_allowed(resolution_minutes: int) -> set[int]:
    if resolution_minutes == 15:
        return {92, 96, 100}
    if resolution_minutes == 60:
        return {23, 24, 25}
    return set()


def validate_market_dataset(
    df: pd.DataFrame,
    *,
    dataset_id: str,
    source_kind: str | None = None,
    operational: bool = False,
    bankable: bool = False,
    as_of: date | None = None,
    max_age_days: int = FRESHNESS_LIMIT_DAYS,
    audit_dir: Path | None = None,
) -> dict[str, Any]:
    source_kind = source_kind or infer_source_kind(df)
    as_of = as_of or date.today()
    issues: list[dict[str, Any]] = []

    if df is None or df.empty:
        _issue(issues, "ERROR", "empty_dataset", "Dataset is empty.")
        return {
            "dataset_id": dataset_id,
            "source_kind": source_kind,
            "bankability_level": bankability_level_for_source(source_kind),
            "row_count": 0,
            "min_delivery_date": None,
            "max_delivery_date": None,
            "issues": issues,
            "passed": False,
        }

    out = normalize_pzu_resolution(df) if dataset_id.lower().startswith("pzu") else df.copy()
    min_date, max_date = data_date_bounds(out)
    if max_date:
        age_days = (as_of - pd.Timestamp(max_date).date()).days
        if operational and age_days > max_age_days:
            _issue(issues, "ERROR", "stale_operational_data", f"Max delivery date {max_date} is {age_days} days old.", age_days=age_days)
        elif age_days > max_age_days:
            _issue(issues, "WARN", "stale_historical_data", f"Max delivery date {max_date} is {age_days} days old; label as historical/backtest.", age_days=age_days)

    if bankable and source_kind not in BANKABLE_SOURCE_KINDS:
        _issue(issues, "ERROR", "non_bankable_source", "Bankable mode requires participant_export or settlement_export.", source_kind=source_kind)
    if source_kind in PUBLIC_OR_UNVERIFIED_SOURCE_KINDS:
        _issue(issues, "INFO", "not_settlement_grade", f"source_kind={source_kind} is not participant settlement proof.", source_kind=source_kind)

    slot_col = "slot" if "slot" in out.columns else ("hour" if "hour" in out.columns else None)
    if "date" not in out.columns:
        _issue(issues, "ERROR", "missing_date", "Dataset has no date column.")
    if slot_col is None:
        _issue(issues, "ERROR", "missing_slot", "Dataset has no slot/hour column.")
    if "date" in out.columns and slot_col is not None:
        dup_mask = out.duplicated(["date", slot_col], keep=False)
        if dup_mask.any():
            _issue(issues, "ERROR", "duplicate_canonical_slots", f"Found {int(dup_mask.sum())} duplicate slot rows.", duplicate_rows=int(dup_mask.sum()))
            if audit_dir is not None:
                audit_dir.mkdir(parents=True, exist_ok=True)
                out.loc[dup_mask].to_csv(audit_dir / f"{dataset_id}_duplicates.csv", index=False)
        if "resolution_minutes" in out.columns:
            resolutions = sorted(int(x) for x in pd.to_numeric(out["resolution_minutes"], errors="coerce").dropna().astype(int).unique())
            if len(resolutions) > 1:
                _issue(issues, "WARN", "mixed_resolution", f"Dataset contains mixed resolutions: {resolutions}.", resolutions=resolutions)
        else:
            max_slot = pd.to_numeric(out[slot_col], errors="coerce").max()
            out["resolution_minutes"] = 15 if pd.notna(max_slot) and max_slot > 23 else 60
        counts = out.groupby("date", dropna=False)[slot_col].count()
        resolution_by_day = out.groupby("date", dropna=False)["resolution_minutes"].first()
        bad_days = []
        for day_value, count in counts.items():
            try:
                resolution = int(resolution_by_day.loc[day_value])
            except Exception:
                resolution = 0
            allowed = _slot_count_allowed(resolution)
            if allowed and int(count) not in allowed:
                bad_days.append({"date": str(day_value), "slot_count": int(count), "resolution_minutes": resolution})
        if bad_days:
            _issue(issues, "ERROR", "invalid_slot_count", "Found days with invalid slot counts.", bad_days=bad_days[:20], bad_day_count=len(bad_days))

    activation_cols = [col for col in out.columns if "activated_mwh" in str(col).lower()]
    for col in activation_cols:
        values = pd.to_numeric(out[col], errors="coerce")
        neg_mask = values < 0
        if neg_mask.any():
            _issue(issues, "ERROR", "negative_activation_volume", f"{col} contains {int(neg_mask.sum())} negative rows.", column=col)

    price_cols = [col for col in out.columns if "price" in str(col).lower() or str(col).lower() == "price"]
    outlier_mask = pd.Series(False, index=out.index)
    outlier_cols = []
    for col in price_cols:
        values = pd.to_numeric(out[col], errors="coerce")
        mask = values.abs() > PRICE_OUTLIER_THRESHOLD_EUR
        if mask.any():
            outlier_mask |= mask
            outlier_cols.append(str(col))
    if outlier_mask.any():
        _issue(issues, "WARN", "price_outliers_quarantined", f"Found {int(outlier_mask.sum())} rows with abs(price) > {PRICE_OUTLIER_THRESHOLD_EUR} EUR/MWh.", columns=outlier_cols)
        if audit_dir is not None:
            audit_dir.mkdir(parents=True, exist_ok=True)
            out.loc[outlier_mask].to_csv(audit_dir / f"{dataset_id}_price_outliers.csv", index=False)

    passed = not any(issue["severity"] == "ERROR" for issue in issues)
    return {
        "dataset_id": dataset_id,
        "source_kind": source_kind,
        "bankability_level": bankability_level_for_source(source_kind),
        "row_count": int(len(out)),
        "min_delivery_date": min_date,
        "max_delivery_date": max_date,
        "issues": issues,
        "passed": passed,
    }


def raise_for_quality(report: dict[str, Any]) -> None:
    errors = [issue for issue in report.get("issues", []) if issue.get("severity") == "ERROR"]
    if errors:
        detail = "; ".join(f"{item['code']}: {item['message']}" for item in errors[:5])
        raise DataQualityError(f"{report.get('dataset_id')} failed validation: {detail}")
