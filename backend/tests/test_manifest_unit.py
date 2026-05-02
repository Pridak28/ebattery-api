"""Unit tests for ``app.market_data.manifest`` helpers.

These tests exercise the pure helpers (`sha256_file`, `data_date_bounds`,
`read_tabular`, `load_manifest`, `write_manifest`, `_display_path`,
`upsert_manifest_entry`, `manifest_entry_for_path`, `append_audit_event`)
using ``tmp_path`` for filesystem isolation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market_data.manifest import (
    MANIFEST_SCHEMA_VERSION,
    _display_path,
    append_audit_event,
    data_date_bounds,
    load_manifest,
    manifest_entry_for_path,
    read_tabular,
    sha256_file,
    upsert_manifest_entry,
    utc_now_iso,
    write_manifest,
)


# ---------------------------------------------------------------------------
# sha256_file
# ---------------------------------------------------------------------------


def test_hash_file_deterministic(tmp_path: Path) -> None:
    """Same content → same hash; different content → different hash."""
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    c = tmp_path / "c.csv"
    a.write_text("date,price\n2026-05-01,50\n", encoding="utf-8")
    b.write_text("date,price\n2026-05-01,50\n", encoding="utf-8")
    c.write_text("date,price\n2026-05-02,99\n", encoding="utf-8")

    h_a = sha256_file(a)
    h_b = sha256_file(b)
    h_c = sha256_file(c)
    assert h_a == h_b
    assert h_a != h_c
    # 64-char hex digest
    assert isinstance(h_a, str) and len(h_a) == 64


def test_hash_file_missing_returns_none(tmp_path: Path) -> None:
    """Non-existent path returns None, not a raise."""
    assert sha256_file(tmp_path / "nope.csv") is None


def test_hash_file_directory_returns_none(tmp_path: Path) -> None:
    """A directory is not a file → returns None."""
    sub = tmp_path / "subdir"
    sub.mkdir()
    assert sha256_file(sub) is None


# ---------------------------------------------------------------------------
# data_date_bounds
# ---------------------------------------------------------------------------


def test_data_date_bounds_with_data() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-04-30", "2026-05-01", "2026-05-02"],
            "price": [10, 20, 30],
        }
    )
    lo, hi = data_date_bounds(df)
    assert lo == "2026-04-30"
    assert hi == "2026-05-02"


def test_data_date_bounds_empty() -> None:
    """Empty DataFrame → (None, None)."""
    df = pd.DataFrame({"date": [], "price": []})
    assert data_date_bounds(df) == (None, None)


def test_data_date_bounds_no_date_column() -> None:
    """DataFrame without `date` column → graceful (None, None)."""
    df = pd.DataFrame({"hour": [1, 2, 3], "price": [10, 20, 30]})
    assert data_date_bounds(df) == (None, None)


def test_data_date_bounds_all_unparseable() -> None:
    """All values fail to_datetime → (None, None) (covers line 52)."""
    df = pd.DataFrame({"date": ["junk", "garbage", ""]})
    assert data_date_bounds(df) == (None, None)


def test_data_date_bounds_none_input() -> None:
    """``df is None`` short-circuits → (None, None)."""
    assert data_date_bounds(None) == (None, None)


def test_data_date_bounds_custom_column() -> None:
    df = pd.DataFrame({"delivery": ["2026-01-01", "2026-12-31"]})
    assert data_date_bounds(df, date_col="delivery") == ("2026-01-01", "2026-12-31")


# ---------------------------------------------------------------------------
# read_tabular
# ---------------------------------------------------------------------------


def test_read_tabular_csv(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    df = read_tabular(p)
    assert df is not None
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


def test_read_tabular_missing_returns_none(tmp_path: Path) -> None:
    assert read_tabular(tmp_path / "nope.csv") is None


def test_read_tabular_unknown_extension_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "data.txt"
    p.write_text("x", encoding="utf-8")
    assert read_tabular(p) is None


def test_read_tabular_bad_csv_returns_none(tmp_path: Path) -> None:
    """Malformed CSV / file open failure → returns None (covers exception path)."""
    p = tmp_path / "broken.csv"
    # Write bytes that pandas cannot decode as utf-8 csv
    p.write_bytes(b"\xff\xfe,\x00\x01\nbad\n")
    # pandas may or may not raise; if it does the function swallows it.
    result = read_tabular(p)
    # Either parsed something or returned None — we just ensure no exception.
    assert result is None or isinstance(result, pd.DataFrame)


def test_read_tabular_excel_failure_returns_none(tmp_path: Path) -> None:
    """``.xlsx`` extension on a non-excel file → exception swallowed → None."""
    p = tmp_path / "fake.xlsx"
    p.write_text("not really excel", encoding="utf-8")
    assert read_tabular(p) is None


# ---------------------------------------------------------------------------
# load_manifest / write_manifest
# ---------------------------------------------------------------------------


def test_load_manifest_missing_returns_default(tmp_path: Path) -> None:
    out = load_manifest(tmp_path / "no_such.json")
    assert out["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert out["datasets"] == []


def test_load_manifest_corrupt_returns_default(tmp_path: Path) -> None:
    """Invalid JSON falls back to default skeleton (covers lines 64-67)."""
    p = tmp_path / "manifest.json"
    p.write_text("{not valid json", encoding="utf-8")
    out = load_manifest(p)
    assert out["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert out["datasets"] == []


def test_load_manifest_valid(tmp_path: Path) -> None:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"datasets": [{"dataset_id": "x"}]}), encoding="utf-8")
    out = load_manifest(p)
    assert out["datasets"] == [{"dataset_id": "x"}]


def test_write_manifest_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "manifest.json"
    write_manifest(p, {"datasets": [{"dataset_id": "x"}]})
    assert p.exists()
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["datasets"] == [{"dataset_id": "x"}]
    assert on_disk["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    # generated_at_utc was injected
    assert "generated_at_utc" in on_disk


# ---------------------------------------------------------------------------
# _display_path
# ---------------------------------------------------------------------------


def test_display_path_no_root(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    assert _display_path(p, None) == str(p)


def test_display_path_with_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    f = root / "sub" / "x.csv"
    f.parent.mkdir()
    f.write_text("x", encoding="utf-8")
    out = _display_path(f, root)
    assert out == "sub/x.csv"


def test_display_path_unrelated_root_falls_back(tmp_path: Path) -> None:
    """When ``path`` is not under ``root`` the relative_to call raises and we
    fall back to ``str(path)`` (covers lines 93-94)."""
    other = tmp_path / "elsewhere" / "x.csv"
    other.parent.mkdir()
    other.write_text("x", encoding="utf-8")
    foreign_root = tmp_path / "different_root"
    foreign_root.mkdir()
    out = _display_path(other, foreign_root)
    assert out == str(other)


# ---------------------------------------------------------------------------
# upsert_manifest_entry
# ---------------------------------------------------------------------------


def test_upsert_manifest_entry_replaces_by_id() -> None:
    manifest: dict = {"datasets": []}
    e1 = {"dataset_id": "foo", "artifact_hash_sha256": "aaaa"}
    e2 = {"dataset_id": "foo", "artifact_hash_sha256": "bbbb"}
    upsert_manifest_entry(manifest, e1)
    upsert_manifest_entry(manifest, e2)
    assert len(manifest["datasets"]) == 1
    assert manifest["datasets"][0]["artifact_hash_sha256"] == "bbbb"


def test_upsert_manifest_entry_appends_new() -> None:
    manifest: dict = {"datasets": [{"dataset_id": "alpha", "artifact_hash_sha256": "xxxx"}]}
    upsert_manifest_entry(manifest, {"dataset_id": "beta", "artifact_hash_sha256": "yyyy"})
    ids = sorted(d["dataset_id"] for d in manifest["datasets"])
    assert ids == ["alpha", "beta"]


def test_upsert_manifest_entry_sorts_by_id() -> None:
    """Result is sorted by ``dataset_id`` after upsert."""
    manifest: dict = {"datasets": []}
    upsert_manifest_entry(manifest, {"dataset_id": "zeta"})
    upsert_manifest_entry(manifest, {"dataset_id": "alpha"})
    upsert_manifest_entry(manifest, {"dataset_id": "mu"})
    ids = [d["dataset_id"] for d in manifest["datasets"]]
    assert ids == ["alpha", "mu", "zeta"]


# ---------------------------------------------------------------------------
# manifest_entry_for_path
# ---------------------------------------------------------------------------


def test_manifest_entry_for_path_basic(tmp_path: Path) -> None:
    """End-to-end: writes a small CSV, calls helper, checks shape."""
    p = tmp_path / "data.csv"
    df = pd.DataFrame({"date": ["2026-04-30", "2026-05-01"], "price": [10.0, 20.0]})
    df.to_csv(p, index=False)

    entry = manifest_entry_for_path(
        dataset_id="my_ds",
        path=p,
        source_kind="public_observed_system",
        root=tmp_path,
    )

    assert entry["dataset_id"] == "my_ds"
    assert entry["artifact_path"] == "data.csv"  # relative to root
    assert isinstance(entry["artifact_hash_sha256"], str)
    assert len(entry["artifact_hash_sha256"]) == 64
    assert entry["row_count"] == 2
    assert entry["min_delivery_date"] == "2026-04-30"
    assert entry["max_delivery_date"] == "2026-05-01"
    assert entry["source_kind"] == "public_observed_system"
    # bankability_level comes from schemas.bankability_level_for_source
    assert isinstance(entry["bankability_level"], str)
    assert entry["bankability_level"]  # non-empty
    # default confidence_label falls back to source_kind
    assert entry["confidence_label"] == "public_observed_system"
    assert entry["raw_paths"] == []
    assert entry["raw_hashes_sha256"] == {}
    assert entry["warnings"] == []
    assert entry["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION


def test_manifest_entry_for_path_missing_file_returns_nones(tmp_path: Path) -> None:
    """If the artifact does not exist the helper still returns a dict but
    with row_count=None / hash=None / dates=None."""
    entry = manifest_entry_for_path(
        dataset_id="ghost",
        path=tmp_path / "no_such.csv",
        source_kind="public_estimated",
    )
    assert entry["dataset_id"] == "ghost"
    assert entry["row_count"] is None
    assert entry["artifact_hash_sha256"] is None
    assert entry["min_delivery_date"] is None
    assert entry["max_delivery_date"] is None


def test_manifest_entry_for_path_with_raw_paths_and_extra(tmp_path: Path) -> None:
    """``raw_paths`` are hashed and ``extra`` fields are merged in (covers line 142)."""
    art = tmp_path / "art.csv"
    raw1 = tmp_path / "raw_a.csv"
    raw2 = tmp_path / "raw_b.csv"
    pd.DataFrame({"date": ["2026-05-01"], "price": [5]}).to_csv(art, index=False)
    raw1.write_text("hello\n", encoding="utf-8")
    raw2.write_text("world\n", encoding="utf-8")

    entry = manifest_entry_for_path(
        dataset_id="ds",
        path=art,
        source_kind="public_estimated",
        root=tmp_path,
        raw_paths=[raw1, raw2],
        source_url="http://example.com",
        retrieval_command="cmd",
        transform_script="script.py",
        currency="EUR",
        pricing_basis="public",
        confidence_label="custom_label",
        warnings=["careful"],
        extra={"custom_field": 42, "another": [1, 2]},
    )
    assert entry["confidence_label"] == "custom_label"
    assert entry["source_url"] == "http://example.com"
    assert entry["retrieval_command"] == "cmd"
    assert entry["transform_script"] == "script.py"
    assert entry["currency"] == "EUR"
    assert entry["warnings"] == ["careful"]
    # raw paths hashed
    assert sorted(entry["raw_paths"]) == ["raw_a.csv", "raw_b.csv"]
    assert all(isinstance(h, str) and len(h) == 64 for h in entry["raw_hashes_sha256"].values())
    # extra merged
    assert entry["custom_field"] == 42
    assert entry["another"] == [1, 2]


# ---------------------------------------------------------------------------
# append_audit_event
# ---------------------------------------------------------------------------


def test_append_audit_event_writes_jsonl(tmp_path: Path) -> None:
    """Multiple calls append valid JSON lines under nested directories."""
    log = tmp_path / "audit" / "events.jsonl"
    append_audit_event(log, {"dataset_id": "a", "event": "started"})
    append_audit_event(log, {"dataset_id": "b", "event": "ok", "extra": [1, 2, 3]})
    append_audit_event(log, {"dataset_id": "c", "event": "ok"})

    assert log.exists()
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["dataset_id"] == "a"
    assert parsed[1]["extra"] == [1, 2, 3]
    assert parsed[2]["dataset_id"] == "c"
    # every line gets a created_at_utc
    for p in parsed:
        assert "created_at_utc" in p


# ---------------------------------------------------------------------------
# utc_now_iso (sanity check, no clock mocking)
# ---------------------------------------------------------------------------


def test_utc_now_iso_format() -> None:
    s = utc_now_iso()
    # ``2026-05-02T12:34:56+00:00`` — no microseconds, has timezone
    assert "T" in s
    assert s.endswith("+00:00")
    assert "." not in s  # no microseconds
