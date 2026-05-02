from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.market_data.schemas import bankability_level_for_source


MANIFEST_SCHEMA_VERSION = "battery_analytics_market_data_manifest_v1"
DEFAULT_TIMEZONE = "Europe/Bucharest"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str | None:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tabular(path: Path) -> pd.DataFrame | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        if path.suffix.lower() in {".xlsx", ".xls"}:
            return pd.read_excel(path)
    except Exception:
        return None
    return None


def data_date_bounds(df: pd.DataFrame, date_col: str = "date") -> tuple[str | None, str | None]:
    if df is None or df.empty or date_col not in df.columns:
        return None, None
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if dates.empty:
        return None, None
    return dates.min().date().isoformat(), dates.max().date().isoformat()


def load_manifest(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "generated_at_utc": utc_now_iso(),
            "datasets": [],
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "generated_at_utc": utc_now_iso(),
            "datasets": [],
        }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["generated_at_utc"] = utc_now_iso()
    manifest["manifest_schema_version"] = MANIFEST_SCHEMA_VERSION
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def upsert_manifest_entry(manifest: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    datasets = [item for item in manifest.get("datasets", []) if item.get("dataset_id") != entry["dataset_id"]]
    datasets.append(entry)
    manifest["datasets"] = sorted(datasets, key=lambda item: item.get("dataset_id", ""))
    return manifest


def _display_path(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def manifest_entry_for_path(
    *,
    dataset_id: str,
    path: Path,
    source_kind: str,
    root: Path | None = None,
    raw_paths: list[Path] | None = None,
    source_url: str | None = None,
    retrieval_command: str | None = None,
    transform_script: str | None = None,
    schema_version: str = "v1",
    currency: str | None = None,
    pricing_basis: str | None = None,
    confidence_label: str | None = None,
    warnings: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(path)
    raw_paths = [Path(p) for p in raw_paths or []]
    df = read_tabular(path)
    min_date, max_date = data_date_bounds(df) if df is not None else (None, None)
    entry: dict[str, Any] = {
        "dataset_id": dataset_id,
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_path": _display_path(path, root),
        "artifact_hash_sha256": sha256_file(path),
        "raw_paths": [_display_path(p, root) for p in raw_paths],
        "raw_hashes_sha256": {_display_path(p, root): sha256_file(p) for p in raw_paths},
        "source_kind": source_kind,
        "bankability_level": bankability_level_for_source(source_kind),
        "confidence_label": confidence_label or source_kind,
        "source_url": source_url,
        "retrieval_command": retrieval_command,
        "transform_script": transform_script,
        "schema_version": schema_version,
        "timezone": DEFAULT_TIMEZONE,
        "currency": currency,
        "pricing_basis": pricing_basis,
        "row_count": int(len(df)) if df is not None else None,
        "min_delivery_date": min_date,
        "max_delivery_date": max_date,
        "generated_at_utc": utc_now_iso(),
        "warnings": warnings or [],
    }
    if extra:
        entry.update(extra)
    return entry


def append_audit_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at_utc": utc_now_iso(), **event}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")
