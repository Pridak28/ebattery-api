from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from app.market_data.manifest import append_audit_event, load_manifest, manifest_entry_for_path, upsert_manifest_entry, write_manifest
from app.market_data.quality import clean_damas, normalize_pzu_resolution, raise_for_quality, validate_market_dataset
from app.market_data.schemas import SOURCE_KIND_PUBLIC_ESTIMATED, SOURCE_KIND_PUBLIC_OBSERVED_SYSTEM, SOURCE_KIND_UNVERIFIED_SNAPSHOT
from app.market_data.sources.opcom_pzu import append_missing_days
from app.market_data.sources.transelectrica_public import PUBLIC_ESTIMATED_IMBALANCE_URL, build_public_imbalance_dataset, download_days


def backend_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def catalog_root(backend_root: Path) -> Path:
    return backend_root / "data_catalog"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _split_sources(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_manifest_markdown(path: Path, manifest: dict) -> None:
    lines = [
        "# Battery Analytics Pro Data Pipeline Manifest",
        "",
        "Generated from `backend/data_catalog/manifest.json`.",
        "",
        "This catalog separates public/system data from participant settlement exports. Bankable simulations require `source_kind=participant_export` or `source_kind=settlement_export`.",
        "",
        "| Dataset | Source kind | Bankability | Rows | Max delivery date | Artifact | Confidence |",
        "|---|---|---|---:|---|---|---|",
    ]
    for item in manifest.get("datasets", []):
        lines.append(
            "| {dataset_id} | {source_kind} | {bankability_level} | {row_count} | {max_delivery_date} | `{artifact_path}` | {confidence_label} |".format(
                dataset_id=item.get("dataset_id"),
                source_kind=item.get("source_kind"),
                bankability_level=item.get("bankability_level"),
                row_count=item.get("row_count"),
                max_delivery_date=item.get("max_delivery_date"),
                artifact_path=item.get("artifact_path"),
                confidence_label=item.get("confidence_label"),
            )
        )
    lines.extend(
        [
            "",
            "## Source-Kind Rules",
            "",
            "- `public_estimated`, `public_observed_system`, `public_aggregate`, and `derived_public`: scenario/calibration only.",
            "- `unverified_snapshot`: historical backtest only until source/export proof is attached.",
            "- `participant_export` and `settlement_export`: eligible for bankable mode after validation.",
            "- `fr_data_clean.csv` is treated as `derived_public` even when it has aFRR-like columns.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _candidate_source_files(backend_root: Path, filename: str) -> list[Path]:
    """Lookup order: catalog raw → canonical ``data/`` (symlink to BOT BATTERY)
    → ``data 2/`` (stale duplicate, last-resort fallback).

    Mastermind D-4 fix: previous order put ``data 2/`` ahead of ``data/``,
    which made manifest ``raw_paths`` point at the duplicate dir — misleading
    for lineage / hash provenance.
    """
    return [
        backend_root / "data_catalog" / "raw" / "manual" / filename,
        backend_root / "data" / filename,
        backend_root / "data 2" / filename,
    ]


def _find_source(backend_root: Path, filename: str) -> Path:
    for path in _candidate_source_files(backend_root, filename):
        if path.exists():
            return path
    raise FileNotFoundError(f"Could not find {filename} in data_catalog/raw/manual, data, or data 2")


def _existing_raw_jsons(raw_root: Path) -> list[Path]:
    if not raw_root.exists():
        return []
    return sorted(raw_root.rglob("estimated_imbalance_*.json"))


def run_seed_pzu(repo_root: Path, backend_root: Path, *, as_of: date, manifest: dict, audit_log: Path, skip_network: bool) -> dict:
    root = catalog_root(backend_root)
    processed_path = root / "processed" / "pzu_history_3y.csv"
    try:
        source_path = _find_source(backend_root, "pzu_history_3y.csv")
        raw_paths = [source_path]
    except FileNotFoundError:
        source_path = None
        raw_paths = []
    if not processed_path.exists():
        if source_path is None:
            raise FileNotFoundError("No source pzu_history_3y.csv available to seed processed catalog")
        df = pd.read_csv(source_path)
        df = normalize_pzu_resolution(df)
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(processed_path, index=False)
    rows_added = 0
    if not skip_network:
        rows_added = append_missing_days(processed_path, end_date=as_of)
        df = normalize_pzu_resolution(pd.read_csv(processed_path))
        df.to_csv(processed_path, index=False)
    df = pd.read_csv(processed_path)
    report = validate_market_dataset(df, dataset_id="opcom_pzu", source_kind=SOURCE_KIND_PUBLIC_OBSERVED_SYSTEM, operational=not skip_network, as_of=as_of, audit_dir=root / "audit")
    _write_json(root / "audit" / "opcom_pzu_validation.json", report)
    append_audit_event(audit_log, {"dataset_id": "opcom_pzu", "event": "validated", "rows_added": rows_added, "passed": report["passed"], "max_delivery_date": report.get("max_delivery_date")})
    raise_for_quality(report)
    entry = manifest_entry_for_path(
        dataset_id="opcom_pzu",
        path=processed_path,
        root=repo_root,
        raw_paths=raw_paths,
        source_kind=SOURCE_KIND_PUBLIC_OBSERVED_SYSTEM,
        source_url="https://www.opcom.ro/rapoarte-pzu-raportPIP-export-csv/",
        retrieval_command="python -m app.market_data.pipeline --sources pzu",
        schema_version="opcom_pzu_v2_resolution_explicit",
        currency="EUR",
        pricing_basis="public_day_ahead_closing_price",
        confidence_label="public_market_report",
        warnings=[issue["message"] for issue in report["issues"] if issue["severity"] in {"WARN", "INFO"}],
    )
    return upsert_manifest_entry(manifest, entry)


def run_seed_damas(repo_root: Path, backend_root: Path, *, as_of: date, manifest: dict, audit_log: Path) -> dict:
    root = catalog_root(backend_root)
    source_path = _find_source(backend_root, "damas_complete_fr_dataset.csv")
    raw = pd.read_csv(source_path)
    cleaned = clean_damas(raw, audit_dir=root / "audit")
    cleaned["source_kind"] = SOURCE_KIND_UNVERIFIED_SNAPSHOT
    cleaned["settlement_grade"] = False
    processed_path = root / "processed" / "damas_clean.csv"
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(processed_path, index=False)
    report = validate_market_dataset(cleaned, dataset_id="damas_clean", source_kind=SOURCE_KIND_UNVERIFIED_SNAPSHOT, operational=False, bankable=False, as_of=as_of, audit_dir=root / "audit")
    _write_json(root / "audit" / "damas_clean_validation.json", report)
    raise_for_quality(report)
    append_audit_event(audit_log, {"dataset_id": "damas_clean", "event": "validated", "passed": report["passed"], "max_delivery_date": report.get("max_delivery_date"), "source_kind": SOURCE_KIND_UNVERIFIED_SNAPSHOT})
    # A-2: surface ANRE Order 60/2024 regime change as an explicit manifest
    # warning so consumers don't silently mix marginal-priced (pre-2024-10-01)
    # rows with pay-as-bid (post) rows.
    extra_warnings: list[str] = []
    regime_counts = cleaned["regulatory_regime"].value_counts().to_dict() if "regulatory_regime" in cleaned.columns else {}
    if len(regime_counts) > 1:
        extra_warnings.append(
            "Dataset spans the ANRE Order 60/2024 regime change "
            f"(effective 2024-10-01). Rows pre-pay-as-bid: {regime_counts.get('pre_order60_2024_marginal', 0)}, "
            f"post-pay-as-bid: {regime_counts.get('post_order60_2024_pay_as_bid', 0)}. "
            "Pre/post settlement mechanics differ materially — split aggregates per regime."
        )
    pipeline_warnings = [issue["message"] for issue in report["issues"] if issue["severity"] in {"WARN", "INFO"}]
    pipeline_warnings.extend(extra_warnings)
    entry = manifest_entry_for_path(
        dataset_id="damas_clean",
        path=processed_path,
        root=repo_root,
        raw_paths=[source_path],
        source_kind=SOURCE_KIND_UNVERIFIED_SNAPSHOT,
        retrieval_command="python -m app.market_data.pipeline --sources seed-damas",
        transform_script="backend/app/market_data/quality.py",
        schema_version="damas_fr_v2_regime_tagged",
        currency="EUR",
        pricing_basis="historical_public_or_unverified_activation_snapshot",
        confidence_label="unverified_snapshot_not_settlement_proof",
        warnings=pipeline_warnings,
    )
    return upsert_manifest_entry(manifest, entry)


def run_transelectrica_public(repo_root: Path, backend_root: Path, *, as_of: date, manifest: dict, audit_log: Path, days: int, skip_network: bool) -> dict:
    root = catalog_root(backend_root)
    raw_dir = root / "raw" / "transelectrica_public" / as_of.isoformat()
    processed_path = root / "processed" / "transelectrica_public_imbalance.csv"
    if skip_network:
        raw_paths = _existing_raw_jsons(root / "raw" / "transelectrica_public")
    else:
        start = as_of - timedelta(days=max(days - 1, 0))
        download_days(start=start, end=as_of, raw_dir=raw_dir, resume=True)
        raw_paths = _existing_raw_jsons(root / "raw" / "transelectrica_public")
    if not raw_paths:
        append_audit_event(audit_log, {"dataset_id": "transelectrica_public_imbalance", "event": "skipped", "reason": "no public raw snapshots available"})
        return manifest
    df = build_public_imbalance_dataset(raw_paths, out_path=processed_path)
    report = validate_market_dataset(df, dataset_id="transelectrica_public_imbalance", source_kind=SOURCE_KIND_PUBLIC_ESTIMATED, operational=not skip_network, as_of=as_of, audit_dir=root / "audit")
    _write_json(root / "audit" / "transelectrica_public_imbalance_validation.json", report)
    append_audit_event(audit_log, {"dataset_id": "transelectrica_public_imbalance", "event": "validated", "raw_snapshot_count": len(raw_paths), "passed": report["passed"], "max_delivery_date": report.get("max_delivery_date")})
    raise_for_quality(report)
    entry = manifest_entry_for_path(
        dataset_id="transelectrica_public_imbalance",
        path=processed_path,
        root=repo_root,
        raw_paths=raw_paths,
        source_kind=SOURCE_KIND_PUBLIC_ESTIMATED,
        source_url=PUBLIC_ESTIMATED_IMBALANCE_URL,
        retrieval_command="python -m app.market_data.pipeline --sources transelectrica-public",
        transform_script="backend/app/market_data/sources/transelectrica_public.py",
        schema_version="transelectrica_public_imbalance_v1",
        currency="EUR",
        pricing_basis="public_estimated_imbalance_price",
        confidence_label="public_system_estimated_not_participant_settlement",
        warnings=[issue["message"] for issue in report["issues"] if issue["severity"] in {"WARN", "INFO"}],
    )
    return upsert_manifest_entry(manifest, entry)


def run_entsoe(backend_root: Path, audit_log: Path, manifest: dict) -> dict:
    if not os.getenv("ENTSOE_API_KEY"):
        append_audit_event(audit_log, {"dataset_id": "entsoe_afrr_reconciliation", "event": "skipped", "reason": "ENTSOE_API_KEY not configured"})
    else:
        append_audit_event(audit_log, {"dataset_id": "entsoe_afrr_reconciliation", "event": "not_implemented", "reason": "token exists, but source mapping is not confirmed"})
    return manifest


def run_pipeline(*, repo_root: Path, backend_root: Path, sources: Iterable[str], as_of: date, transelectrica_days: int, skip_network: bool) -> dict:
    root = catalog_root(backend_root)
    manifest_path = root / "manifest.json"
    audit_log = root / "audit" / "market_data_refresh.jsonl"
    manifest = load_manifest(manifest_path)
    source_set = set(sources)
    if "seed-pzu" in source_set or "pzu" in source_set:
        manifest = run_seed_pzu(repo_root, backend_root, as_of=as_of, manifest=manifest, audit_log=audit_log, skip_network=skip_network or "seed-pzu" in source_set)
    if "seed-damas" in source_set or "damas-clean" in source_set:
        manifest = run_seed_damas(repo_root, backend_root, as_of=as_of, manifest=manifest, audit_log=audit_log)
    if "transelectrica-public" in source_set:
        manifest = run_transelectrica_public(repo_root, backend_root, as_of=as_of, manifest=manifest, audit_log=audit_log, days=transelectrica_days, skip_network=skip_network)
    if "entsoe" in source_set:
        manifest = run_entsoe(backend_root, audit_log, manifest)
    write_manifest(manifest_path, manifest)
    _write_manifest_markdown(repo_root / "DATA_PIPELINE_MANIFEST.md", manifest)
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh and validate Battery Analytics Pro market data")
    parser.add_argument("--sources", default="pzu,seed-damas,transelectrica-public,entsoe")
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--transelectrica-days", type=int, default=14)
    parser.add_argument("--skip-network", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    as_of = _parse_date(args.as_of) or date.today()
    manifest = run_pipeline(
        repo_root=repo_root_from_here(),
        backend_root=backend_root_from_here(),
        sources=_split_sources(args.sources),
        as_of=as_of,
        transelectrica_days=args.transelectrica_days,
        skip_network=args.skip_network,
    )
    print(f"updated backend/data_catalog/manifest.json datasets={len(manifest.get('datasets', []))}")


if __name__ == "__main__":
    main()
