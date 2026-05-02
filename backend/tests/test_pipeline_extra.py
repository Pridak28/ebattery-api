"""Extra unit tests for ``app.market_data.pipeline``.

Targets the coverage gaps left by ``test_pipeline_unit.py``:

* ``run_seed_pzu`` raise path when no source exists
* ``run_seed_damas`` happy path (lines 155-196)
* ``run_seed_damas`` regime-spanning warning path
* ``run_transelectrica_public`` non-skip-network path with monkeypatched
  ``download_days`` / ``build_public_imbalance_dataset`` (lines 206-208,
  212-232)
* ``run_pipeline`` dispatch with seed-damas + unknown-source short circuit
* ``main()`` CLI entry point (lines 272-282) with monkeypatched argv +
  ``run_pipeline``
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

from app.market_data import pipeline as pipeline_mod
from app.market_data.pipeline import (
    run_pipeline,
    run_seed_damas,
    run_seed_pzu,
    run_transelectrica_public,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _damas_csv(path: Path, start: str = "2024-09-30", days: int = 4) -> None:
    """Write a DAMAS-shaped CSV with 96 slots/day spanning the regime change.

    Default range straddles 2024-10-01 so ``regulatory_regime`` has both
    pre- and post-Order-60 rows, exercising the extra warning branch.
    """
    rows = []
    for i in range(days):
        d = (pd.Timestamp(start) + pd.Timedelta(days=i)).date().isoformat()
        for slot in range(96):
            rows.append(
                {
                    "date": d,
                    "slot": slot,
                    "price_eur_mwh": 50.0,
                    "afrr_up_activated_mwh": 1.0,
                    "afrr_down_activated_mwh": 0.5,
                    "afrr_up_price_eur": 120.0,
                    "afrr_down_price_eur": 80.0,
                    "frequency": 50.0,
                }
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _make_synthetic_pzu_csv(path: Path) -> None:
    rows = []
    for day in ("2026-04-30", "2026-05-01"):
        for h in range(24):
            rows.append({"date": day, "hour": h, "price": 50.0 + h, "currency": "EUR", "resolution": "PT60M", "intervals_aggregated": 1})
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# run_seed_pzu raise paths
# ---------------------------------------------------------------------------


def test_run_seed_pzu_raises_when_no_source(tmp_path: Path) -> None:
    """No raw source CSV anywhere AND no processed file → FileNotFoundError
    (covers line 122)."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    backend_root.mkdir(parents=True)
    audit_log = tmp_path / "audit.jsonl"
    with pytest.raises(FileNotFoundError, match="pzu_history_3y.csv"):
        run_seed_pzu(
            repo_root,
            backend_root,
            as_of=date(2026, 5, 1),
            manifest={"datasets": []},
            audit_log=audit_log,
            skip_network=True,
        )


def test_run_seed_pzu_skip_network_false_appends_no_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``skip_network=False`` exercises the ``append_missing_days`` branch
    (lines 129-131). We monkeypatch it to a no-op returning 0 so the test
    never reaches the network."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    src = backend_root / "data" / "pzu_history_3y.csv"
    _make_synthetic_pzu_csv(src)

    def fake_append(processed_path: Path, *, end_date) -> int:
        return 0

    monkeypatch.setattr(pipeline_mod, "append_missing_days", fake_append)

    out = run_seed_pzu(
        repo_root,
        backend_root,
        as_of=date(2026, 5, 1),
        manifest={"datasets": []},
        audit_log=tmp_path / "audit.jsonl",
        skip_network=False,
    )
    ids = [d["dataset_id"] for d in out["datasets"]]
    assert "opcom_pzu" in ids


# ---------------------------------------------------------------------------
# run_seed_damas
# ---------------------------------------------------------------------------


def test_run_seed_damas_happy_path(tmp_path: Path) -> None:
    """Single-regime DAMAS CSV → cleaned CSV written, manifest entry
    upserted, audit event appended (covers lines 155-196 minus the
    regime-spanning branch)."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    src = backend_root / "data" / "damas_complete_fr_dataset.csv"
    # All rows post-2024-10-01 → only ``post_order60_2024_pay_as_bid`` regime
    _damas_csv(src, start="2024-10-15", days=2)
    audit_log = tmp_path / "audit.jsonl"

    out = run_seed_damas(
        repo_root,
        backend_root,
        as_of=date(2024, 11, 1),
        manifest={"datasets": []},
        audit_log=audit_log,
    )
    processed = backend_root / "data_catalog" / "processed" / "damas_clean.csv"
    assert processed.exists()
    df = pd.read_csv(processed)
    assert "regulatory_regime" in df.columns
    # only one regime → no extra-warning text in manifest entry
    entry = next(d for d in out["datasets"] if d["dataset_id"] == "damas_clean")
    assert entry["source_kind"] == "unverified_snapshot"
    assert entry["confidence_label"] == "unverified_snapshot_not_settlement_proof"
    assert entry["schema_version"] == "damas_fr_v2_regime_tagged"
    # validation report + audit event written
    assert (backend_root / "data_catalog" / "audit" / "damas_clean_validation.json").exists()
    assert "damas_clean" in audit_log.read_text(encoding="utf-8")


def test_run_seed_damas_regime_spanning_warning(tmp_path: Path) -> None:
    """DAMAS dataset that straddles 2024-10-01 → the manifest entry surfaces
    the ANRE Order 60/2024 warning (covers the branch on lines 172-179)."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    src = backend_root / "data" / "damas_complete_fr_dataset.csv"
    _damas_csv(src, start="2024-09-30", days=4)  # spans 2024-10-01

    out = run_seed_damas(
        repo_root,
        backend_root,
        as_of=date(2024, 11, 1),
        manifest={"datasets": []},
        audit_log=tmp_path / "audit.jsonl",
    )
    entry = next(d for d in out["datasets"] if d["dataset_id"] == "damas_clean")
    warnings_text = " ".join(entry["warnings"])
    assert "ANRE Order 60/2024" in warnings_text
    assert "pre-pay-as-bid" in warnings_text
    assert "post-pay-as-bid" in warnings_text


# ---------------------------------------------------------------------------
# run_transelectrica_public non-skip-network path
# ---------------------------------------------------------------------------


def test_run_transelectrica_public_non_skip_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """skip_network=False path: ``download_days`` and
    ``build_public_imbalance_dataset`` are monkeypatched. Covers
    lines 206-208 and 212-232."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    backend_root.mkdir(parents=True)
    audit_log = tmp_path / "audit.jsonl"

    raw_root = backend_root / "data_catalog" / "raw" / "transelectrica_public"

    def fake_download(*, start, end, raw_dir, resume=True):
        # Drop a fake snapshot in raw_root so _existing_raw_jsons finds it.
        raw_root.mkdir(parents=True, exist_ok=True)
        snap = raw_root / "estimated_imbalance_2026-05-01.json"
        snap.write_text("{}", encoding="utf-8")
        return [snap]

    def fake_build(raw_paths, *, out_path, fx_ron_per_eur: float = 5.0):
        # Validation requires 24 slots/day or 96 slots/day.
        rows = [
            {
                "date": "2026-05-01",
                "hour": h,
                "slot": h,
                "resolution_minutes": 60,
                "price": 50.0 + h,
                "imbalance_price_eur_mwh": 50.0 + h,
            }
            for h in range(24)
        ]
        df = pd.DataFrame(rows)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        return df

    monkeypatch.setattr(pipeline_mod, "download_days", fake_download)
    monkeypatch.setattr(pipeline_mod, "build_public_imbalance_dataset", fake_build)

    out = run_transelectrica_public(
        repo_root,
        backend_root,
        as_of=date(2026, 5, 1),
        manifest={"datasets": []},
        audit_log=audit_log,
        days=1,
        skip_network=False,
    )
    ids = [d["dataset_id"] for d in out["datasets"]]
    assert "transelectrica_public_imbalance" in ids
    entry = next(d for d in out["datasets"] if d["dataset_id"] == "transelectrica_public_imbalance")
    assert entry["source_kind"] == "public_estimated"
    # validation report + audit event
    assert (backend_root / "data_catalog" / "audit" / "transelectrica_public_imbalance_validation.json").exists()
    audit_text = audit_log.read_text(encoding="utf-8")
    assert "transelectrica_public_imbalance" in audit_text
    assert '"event": "validated"' in audit_text


# ---------------------------------------------------------------------------
# run_pipeline dispatch
# ---------------------------------------------------------------------------


def test_run_pipeline_unknown_source_no_op(tmp_path: Path) -> None:
    """Unknown source string → no orchestrator dispatched, manifest stays empty."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    backend_root.mkdir(parents=True)

    manifest = run_pipeline(
        repo_root=repo_root,
        backend_root=backend_root,
        sources={"bogus", "definitely-not-real"},
        as_of=date(2026, 5, 1),
        transelectrica_days=1,
        skip_network=True,
    )
    assert manifest["datasets"] == []
    # manifest.json + markdown still written
    assert (backend_root / "data_catalog" / "manifest.json").exists()
    assert (repo_root / "DATA_PIPELINE_MANIFEST.md").exists()


def test_run_pipeline_dispatch_seed_damas(tmp_path: Path) -> None:
    """``run_pipeline`` dispatches ``seed-damas`` (covers line 252)."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    src = backend_root / "data" / "damas_complete_fr_dataset.csv"
    _damas_csv(src, start="2024-10-15", days=2)

    manifest = run_pipeline(
        repo_root=repo_root,
        backend_root=backend_root,
        sources={"seed-damas"},
        as_of=date(2024, 11, 1),
        transelectrica_days=1,
        skip_network=True,
    )
    ids = [d["dataset_id"] for d in manifest["datasets"]]
    assert "damas_clean" in ids


def test_run_pipeline_dispatch_damas_clean_alias(tmp_path: Path) -> None:
    """``damas-clean`` alias also triggers ``run_seed_damas``."""
    repo_root = tmp_path / "repo"
    backend_root = repo_root / "backend"
    src = backend_root / "data" / "damas_complete_fr_dataset.csv"
    _damas_csv(src, start="2024-10-15", days=2)

    manifest = run_pipeline(
        repo_root=repo_root,
        backend_root=backend_root,
        sources={"damas-clean"},
        as_of=date(2024, 11, 1),
        transelectrica_days=1,
        skip_network=True,
    )
    ids = [d["dataset_id"] for d in manifest["datasets"]]
    assert "damas_clean" in ids


# ---------------------------------------------------------------------------
# main() CLI entry point
# ---------------------------------------------------------------------------


def test_main_invokes_run_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``main()`` parses argv, computes as_of, calls ``run_pipeline`` and
    prints the dataset count (covers lines 272-282)."""
    captured: dict = {}

    def fake_run_pipeline(*, repo_root, backend_root, sources, as_of, transelectrica_days, skip_network):
        captured["sources"] = set(sources)
        captured["as_of"] = as_of
        captured["transelectrica_days"] = transelectrica_days
        captured["skip_network"] = skip_network
        return {"datasets": [{"dataset_id": "alpha"}, {"dataset_id": "beta"}]}

    monkeypatch.setattr(pipeline_mod, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pipeline",
            "--sources",
            "pzu,seed-damas",
            "--as-of",
            "2026-05-02",
            "--transelectrica-days",
            "7",
            "--skip-network",
        ],
    )
    pipeline_mod.main()
    out = capsys.readouterr().out
    assert "datasets=2" in out
    assert captured["sources"] == {"pzu", "seed-damas"}
    assert captured["as_of"] == date(2026, 5, 2)
    assert captured["transelectrica_days"] == 7
    assert captured["skip_network"] is True


def test_main_default_as_of_is_today(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No ``--as-of`` → defaults to ``date.today()`` (still covers main())."""
    captured: dict = {}

    def fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        return {"datasets": []}

    monkeypatch.setattr(pipeline_mod, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(sys, "argv", ["pipeline", "--sources", "pzu"])
    pipeline_mod.main()
    out = capsys.readouterr().out
    assert "datasets=0" in out
    assert isinstance(captured["as_of"], date)
