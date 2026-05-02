from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.market_data.quality import DataQualityError, clean_damas, validate_market_dataset
from app.market_data.schemas import (
    SOURCE_KIND_PARTICIPANT_EXPORT,
    SOURCE_KIND_PUBLIC_AGGREGATE,
    SOURCE_KIND_SETTLEMENT_EXPORT,
    SOURCE_KIND_UNVERIFIED_SNAPSHOT,
    is_damas_shaped,
)


ALLOWED_MANUAL_SOURCE_KINDS = {
    SOURCE_KIND_PUBLIC_AGGREGATE,
    SOURCE_KIND_UNVERIFIED_SNAPSHOT,
    SOURCE_KIND_PARTICIPANT_EXPORT,
    SOURCE_KIND_SETTLEMENT_EXPORT,
}


def read_manual_export(path: Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported DAMAS export type: {path.suffix}")


def import_manual_export(*, input_path: Path, output_path: Path, source_kind: str = SOURCE_KIND_UNVERIFIED_SNAPSHOT, audit_dir: Path | None = None) -> pd.DataFrame:
    if source_kind not in ALLOWED_MANUAL_SOURCE_KINDS:
        raise ValueError(f"Unsupported source_kind={source_kind!r}")
    raw = read_manual_export(input_path)
    if not is_damas_shaped(raw.columns):
        raise DataQualityError(f"{input_path} is not DAMAS-shaped.")
    cleaned = clean_damas(raw, audit_dir=audit_dir)
    cleaned["source_kind"] = source_kind
    cleaned["settlement_grade"] = source_kind in {SOURCE_KIND_PARTICIPANT_EXPORT, SOURCE_KIND_SETTLEMENT_EXPORT}
    report = validate_market_dataset(cleaned, dataset_id="manual_damas_export", source_kind=source_kind, bankable=bool(cleaned["settlement_grade"].iloc[0]), audit_dir=audit_dir)
    if not report["passed"]:
        raise DataQualityError(f"manual DAMAS import failed validation: {report['issues']}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(output_path, index=False)
    return cleaned


def run_participant_placeholder() -> None:
    raise RuntimeError(
        "Participant DAMAS import is not configured. Provide a participant_export "
        "or settlement_export file before enabling bankable mode."
    )
