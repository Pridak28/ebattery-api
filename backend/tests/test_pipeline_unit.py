"""Unit tests for ``app.market_data.pipeline`` helpers and orchestrators.

These tests use ``tmp_path`` for filesystem isolation and never reach out to
the network (skip_network=True everywhere it matters). They cover:

* the pure helpers (`_candidate_source_files`, `_find_source`,
  `_existing_raw_jsons`, `_parse_date`, `_split_sources`, `_write_json`,
  `_write_manifest_markdown`)
* the ``run_seed_pzu`` orchestrator with a synthetic 1-day PZU CSV
* the ``run_pipeline`` dispatcher with ``skip_network=True`` and a
  ``transelectrica-public`` source set that has zero raw snapshots so it
  short-circuits without network.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data import pipeline as pipeline_mod
from app.market_data.pipeline import (
    _candidate_source_files,
    _existing_raw_jsons,
    _find_source,
    _parse_date,
    _split_sources,
    _write_json,
    _write_manifest_markdown,
    backend_root_from_here,
    catalog_root,
    repo_root_from_here,
    run_entsoe,
    run_pipeline,
    run_seed_pzu,
    run_transelectrica_public,
)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_candidate_source_files_priority(tmp_path: Path) -> None:
    """Lookup order is catalog raw/manual → data → data 2 (D-4 fix)."""
    backend_root = tmp_path / "backend"
    candidates = _candidate_source_files(backend_root, "foo.csv")

    assert candidates == [
        backend_root / "data_catalog" / "raw" / "manual" / "foo.csv",
        backend_root / "data" / "foo.csv",
        backend_root / "data 2" / "foo.csv",
    ]
    # ``data 2`` (stale duplicate) must come AFTER ``data`` so that lineage
    # picks the canonical symlink first.
    paths = [str(p) for p in candidates]
    assert paths.index(str(backend_root / "data" / "foo.csv")) < paths.index(
        str(backend_root / "data 2" / "foo.csv")
    )


def test_find_source_returns_first_match(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    target = backend_root / "data" / "file.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,hour,price\n", encoding="utf-8")
    found = _find_source(backend_root, "file.csv")
    assert found == target


def test_find_source_prefers_catalog_manual_over_data(tmp_path: Path) -> None:
    """If both catalog raw/manual and data have the file, catalog wins."""
    backend_root = tmp_path / "backend"
    in_data = backend_root / "data" / "file.csv"
    in_manual = backend_root / "data_catalog" / "raw" / "manual" / "file.csv"
    for p in (in_data, in_manual):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    assert _find_source(backend_root, "file.csv") == in_manual


def test_find_source_raises_when_missing(tmp_path: Path) -> None:
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    with pytest.raises(FileNotFoundError):
        _find_source(backend_root, "missing.csv")


def test_parse_date_iso_and_none() -> None:
    assert _parse_date("2026-05-02") == date(2026, 5, 2)
    assert _parse_date(None) is None
    assert _parse_date("") is None


def test_parse_date_invalid_raises() -> None:
    # ``datetime.strptime`` raises ``ValueError`` on bad strings — verify
    # the function surfaces the error rather than silently swallowing it.
    with pytest.raises(ValueError):
        _parse_date("not-a-date")


def test_split_sources_comma_list() -> None:
    assert _split_sources("pzu,seed-damas") == {"pzu", "seed-damas"}
    # whitespace tolerant + drops empty entries
    assert _split_sources("pzu, seed-damas , ,entsoe") == {"pzu", "seed-damas", "entsoe"}
    assert _split_sources("") == set()


def test_existing_raw_jsons_lists(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    # files in the root + a nested date-partition
    (raw_root / "estimated_imbalance_2026-05-01.json").write_text("{}", encoding="utf-8")
    (raw_root / "estimated_imbalance_2026-04-30.json").write_text("{}", encoding="utf-8")
    nested = raw_root / "2026-05-01"
    nested.mkdir()
    (nested / "estimated_imbalance_nested.json").write_text("{}", encoding="utf-8")
    # an unrelated file should NOT show up
    (raw_root / "other.json").write_text("{}", encoding="utf-8")

    found = _existing_raw_jsons(raw_root)
    assert all("estimated_imbalance_" in p.name for p in found)
    assert len(found) == 3
    # function returns sorted
    assert found == sorted(found)


def test_existing_raw_jsons_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert _existing_raw_jsons(tmp_path / "does-not-exist") == []


def test_write_json_writes_payload(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out.json"
    payload = {"b": 1, "a": [1, 2, 3], "when": date(2026, 5, 2)}
    _write_json(target, payload)

    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    data = json.loads(text)
    # date serialized via ``default=str``
    assert data == {"a": [1, 2, 3], "b": 1, "when": "2026-05-02"}
    # sort_keys=True → keys are alphabetical in the raw text
    assert text.find('"a"') < text.find('"b"') < text.find('"when"')


def test_write_manifest_markdown_renders_table(tmp_path: Path) -> None:
    target = tmp_path / "MANIFEST.md"
    manifest = {
        "datasets": [
            {
                "dataset_id": "opcom_pzu",
                "source_kind": "public_observed_system",
                "bankability_level": "scenario",
                "row_count": 24,
                "max_delivery_date": "2026-05-01",
                "artifact_path": "backend/data_catalog/processed/pzu_history_3y.csv",
                "confidence_label": "public_market_report",
            }
        ]
    }
    _write_manifest_markdown(target, manifest)
    text = target.read_text(encoding="utf-8")
    assert "Battery Analytics Pro Data Pipeline Manifest" in text
    assert "opcom_pzu" in text
    assert "public_observed_system" in text
    assert "pzu_history_3y.csv" in text
    assert "Source-Kind Rules" in text


def test_write_manifest_markdown_empty_datasets(tmp_path: Path) -> None:
    """Header rows render even when ``datasets`` is missing/empty."""
    target = tmp_path / "MANIFEST.md"
    _write_manifest_markdown(target, {})
    text = target.read_text(encoding="utf-8")
    assert "| Dataset | Source kind |" in text
    assert "Source-Kind Rules" in text


# ---------------------------------------------------------------------------
# helpers tied to module location
# ---------------------------------------------------------------------------


def test_backend_and_repo_root_helpers() -> None:
    backend_root = backend_root_from_here()
    repo_root = repo_root_from_here()
    assert backend_root.name == "backend"
    assert backend_root.parent == repo_root
    assert catalog_root(backend_root) == backend_root / "data_catalog"


# ---------------------------------------------------------------------------
# orchestrators (no network)
# ---------------------------------------------------------------------------


def _make_synthetic_pzu_csv(path: Path) -> None:
    """48 rows: two complete 24-hour days. Validation requires every day to
    have a full slot count (24 for hourly), so partial days would trip the
    ``invalid_slot_count`` ERROR."""
    rows: list[dict] = []
    for day in ("2026-04-30", "2026-05-01"):
        for h in range(24):
            rows.append(
                {
                    "date": day,
                    "hour": h,
                    "price": 50.0 + h,
                    "currency": "EUR",
                    "resolution": "PT60M",
                    "intervals_aggregated": 1,
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def test_run_seed_pzu_with_tmp_data(tmp_path: Path) -> None:
    """``run_seed_pzu`` reads ``data/pzu_history_3y.csv``, writes a processed
    CSV under ``data_catalog/processed/`` and upserts a manifest entry."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    src = backend_root / "data" / "pzu_history_3y.csv"
    _make_synthetic_pzu_csv(src)

    audit_log = tmp_path / "audit.jsonl"
    manifest: dict = {"datasets": []}

    out = run_seed_pzu(
        repo_root,
        backend_root,
        as_of=date(2026, 5, 1),
        manifest=manifest,
        audit_log=audit_log,
        skip_network=True,
    )

    processed = backend_root / "data_catalog" / "processed" / "pzu_history_3y.csv"
    assert processed.exists(), "processed PZU csv must be written"
    df = pd.read_csv(processed)
    assert len(df) == 48
    # normalize_pzu_resolution adds slot + resolution_minutes
    assert {"slot", "resolution_minutes"}.issubset(df.columns)

    # manifest got an opcom_pzu entry
    ids = [d["dataset_id"] for d in out["datasets"]]
    assert "opcom_pzu" in ids
    entry = next(d for d in out["datasets"] if d["dataset_id"] == "opcom_pzu")
    assert entry["source_kind"] == "public_observed_system"
    assert entry["max_delivery_date"] == "2026-05-01"

    # validation report + audit log written
    assert (backend_root / "data_catalog" / "audit" / "opcom_pzu_validation.json").exists()
    assert audit_log.exists()
    audit_lines = [line for line in audit_log.read_text().splitlines() if line]
    assert any("opcom_pzu" in line for line in audit_lines)


def test_run_seed_pzu_uses_existing_processed(tmp_path: Path) -> None:
    """If a processed file already exists, ``run_seed_pzu`` does not require
    a raw source CSV (raw_paths can be empty)."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    processed = backend_root / "data_catalog" / "processed" / "pzu_history_3y.csv"
    processed.parent.mkdir(parents=True)
    rows = [
        {"date": "2026-04-30", "hour": h, "price": 50.0, "slot": h, "resolution_minutes": 60}
        for h in range(24)
    ]
    pd.DataFrame(rows).to_csv(processed, index=False)

    out = run_seed_pzu(
        repo_root,
        backend_root,
        as_of=date(2026, 5, 1),
        manifest={"datasets": []},
        audit_log=tmp_path / "audit.jsonl",
        skip_network=True,
    )
    assert any(d["dataset_id"] == "opcom_pzu" for d in out["datasets"])


def test_run_transelectrica_public_skips_when_no_raw(tmp_path: Path) -> None:
    """With ``skip_network=True`` and an empty raw dir, the orchestrator
    short-circuits and just appends a ``skipped`` audit event."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    audit_log = tmp_path / "audit.jsonl"
    manifest_in: dict = {"datasets": []}

    out = run_transelectrica_public(
        repo_root,
        backend_root,
        as_of=date(2026, 5, 1),
        manifest=manifest_in,
        audit_log=audit_log,
        days=1,
        skip_network=True,
    )
    # manifest unchanged
    assert out is manifest_in
    assert out["datasets"] == []
    # ``skipped`` audit event written
    text = audit_log.read_text(encoding="utf-8")
    assert "transelectrica_public_imbalance" in text
    assert "skipped" in text


def test_run_entsoe_skipped_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    audit_log = tmp_path / "audit.jsonl"
    manifest: dict = {"datasets": []}
    out = run_entsoe(tmp_path, audit_log, manifest)
    assert out is manifest
    text = audit_log.read_text(encoding="utf-8")
    assert "entsoe_afrr_reconciliation" in text
    assert "ENTSOE_API_KEY" in text


def test_run_entsoe_not_implemented_with_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTSOE_API_KEY", "fake-token")
    audit_log = tmp_path / "audit.jsonl"
    manifest: dict = {"datasets": []}
    out = run_entsoe(tmp_path, audit_log, manifest)
    assert out is manifest
    text = audit_log.read_text(encoding="utf-8")
    assert "not_implemented" in text


def test_run_pipeline_dispatch_skip_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end-ish: ``run_pipeline`` with ``transelectrica-public`` +
    ``entsoe`` writes the manifest JSON and the markdown manifest without
    touching the network."""
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    backend_root.mkdir(parents=True)

    manifest = run_pipeline(
        repo_root=repo_root,
        backend_root=backend_root,
        sources={"transelectrica-public", "entsoe"},
        as_of=date(2026, 5, 1),
        transelectrica_days=1,
        skip_network=True,
    )
    # manifest.json written under data_catalog
    manifest_path = backend_root / "data_catalog" / "manifest.json"
    assert manifest_path.exists()
    on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "datasets" in on_disk
    # markdown manifest written at repo root
    md_path = repo_root / "DATA_PIPELINE_MANIFEST.md"
    assert md_path.exists()
    assert "Battery Analytics Pro Data Pipeline Manifest" in md_path.read_text(encoding="utf-8")

    # Both audit events landed
    audit_text = (backend_root / "data_catalog" / "audit" / "market_data_refresh.jsonl").read_text(encoding="utf-8")
    assert "transelectrica_public_imbalance" in audit_text
    assert "entsoe_afrr_reconciliation" in audit_text


def test_run_pipeline_dispatch_seed_pzu(tmp_path: Path) -> None:
    """``run_pipeline`` dispatches to ``run_seed_pzu`` when ``pzu`` is in
    sources, and writes the manifest with the opcom_pzu entry."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    _make_synthetic_pzu_csv(backend_root / "data" / "pzu_history_3y.csv")

    manifest = run_pipeline(
        repo_root=repo_root,
        backend_root=backend_root,
        sources={"pzu"},
        as_of=date(2026, 5, 1),
        transelectrica_days=1,
        skip_network=True,
    )
    ids = [d["dataset_id"] for d in manifest["datasets"]]
    assert "opcom_pzu" in ids


# ---------------------------------------------------------------------------
# CLI / argparse glue
# ---------------------------------------------------------------------------


def test_parse_args_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["pipeline"])
    args = pipeline_mod._parse_args()
    assert args.sources == "pzu,seed-damas,transelectrica-public,entsoe"
    assert args.as_of is None
    assert args.transelectrica_days == 14
    assert args.skip_network is False


def test_parse_args_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pipeline",
            "--sources",
            "pzu",
            "--as-of",
            "2026-05-02",
            "--transelectrica-days",
            "3",
            "--skip-network",
        ],
    )
    args = pipeline_mod._parse_args()
    assert args.sources == "pzu"
    assert args.as_of == "2026-05-02"
    assert args.transelectrica_days == 3
    assert args.skip_network is True
