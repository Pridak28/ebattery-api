"""Lifecycle + bootstrap coverage for ``app.main``.

Existing ``tests/test_api_routes.py`` already exercises the live ``/`` and
``/api/health`` endpoints via TestClient. This module covers the
startup-bootstrap helpers (``_data_dir_is_populated``, ``_bootstrap_data``)
and the explicit-import-cleanly contract that the rest of the suite
implicitly relies on.

All bootstrap paths are mocked: no real network. Filesystem mutations go
through ``tmp_path`` only.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import main as main_module  # noqa: E402
from app.main import _bootstrap_data, _data_dir_is_populated, app  # noqa: E402


# ---------------------------------------------------------------------------
# Module-level smoke
# ---------------------------------------------------------------------------
def test_app_imports_cleanly():
    """``from app.main import app`` must yield a non-None FastAPI instance."""
    assert app is not None
    assert app.title  # smoke — FastAPI fills this


# ---------------------------------------------------------------------------
# _data_dir_is_populated
# ---------------------------------------------------------------------------
def test_data_dir_is_populated_empty_then_populated(tmp_path: Path):
    """Empty dir ⇒ False; after writing a file ⇒ True."""
    assert _data_dir_is_populated(tmp_path) is False
    (tmp_path / "marker.txt").write_text("hello")
    assert _data_dir_is_populated(tmp_path) is True


def test_data_dir_is_populated_missing_dir(tmp_path: Path):
    """Non-existent path ⇒ False (not an exception)."""
    assert _data_dir_is_populated(tmp_path / "does-not-exist") is False


# ---------------------------------------------------------------------------
# _bootstrap_data: short-circuit when DATA_DIR already populated
# ---------------------------------------------------------------------------
def test_bootstrap_data_noop_when_data_dir_populated(tmp_path: Path):
    """If DATA_DIR already has files, _bootstrap_data must NOT call urlopen."""
    (tmp_path / "existing.csv").write_text("col\n1\n")
    fake_settings = type("S", (), {"DATA_DIR": tmp_path, "BACKEND_DATA_URL": "https://example.com/data.zip"})()
    with patch.object(main_module, "settings", fake_settings), \
         patch.object(main_module, "urlopen") as mock_urlopen:
        _bootstrap_data()
    mock_urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# _bootstrap_data: empty URL + empty DATA_DIR ⇒ logs error and continues
# ---------------------------------------------------------------------------
def test_bootstrap_data_logs_when_url_missing(tmp_path: Path, caplog):
    """No BACKEND_DATA_URL configured + empty DATA_DIR ⇒ error log, no raise."""
    fake_settings = type("S", (), {"DATA_DIR": tmp_path, "BACKEND_DATA_URL": "   "})()
    with patch.object(main_module, "settings", fake_settings), \
         patch.object(main_module, "urlopen") as mock_urlopen, \
         caplog.at_level("ERROR", logger="battery_analytics.startup"):
        _bootstrap_data()  # must not raise
    mock_urlopen.assert_not_called()
    assert any("BACKEND_DATA_URL" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# _bootstrap_data: zip extraction happy path
# ---------------------------------------------------------------------------
def test_bootstrap_data_extracts_zip_archive(tmp_path: Path):
    """When BACKEND_DATA_URL ends in .zip, the payload must be extracted into
    DATA_DIR. We mock ``urlopen`` to return BytesIO over an in-memory zip."""
    # Build an in-memory zip with a single dummy file.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("payload.csv", "col\n1\n2\n")
    buf.seek(0)

    data_dir = tmp_path / "data"
    fake_settings = type(
        "S",
        (),
        {"DATA_DIR": data_dir, "BACKEND_DATA_URL": "https://example.com/data.zip"},
    )()

    class FakeResp:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload
        def read(self) -> bytes:
            return self._payload
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    with patch.object(main_module, "settings", fake_settings), \
         patch.object(main_module, "urlopen", return_value=FakeResp(buf.getvalue())):
        _bootstrap_data()

    extracted = data_dir / "payload.csv"
    assert extracted.exists(), f"expected {extracted} to be extracted"
    assert extracted.read_text().startswith("col")


# ---------------------------------------------------------------------------
# _bootstrap_data: urlopen raises ⇒ logs error and continues
# ---------------------------------------------------------------------------
def test_bootstrap_data_handles_urlopen_exception(tmp_path: Path, caplog):
    """If urlopen raises, _bootstrap_data must swallow it (log + continue)."""
    data_dir = tmp_path / "data"
    fake_settings = type(
        "S",
        (),
        {"DATA_DIR": data_dir, "BACKEND_DATA_URL": "https://example.com/data.zip"},
    )()

    def _boom(*args, **kwargs):
        raise RuntimeError("network down")

    with patch.object(main_module, "settings", fake_settings), \
         patch.object(main_module, "urlopen", side_effect=_boom), \
         caplog.at_level("ERROR", logger="battery_analytics.startup"):
        _bootstrap_data()  # must not raise

    assert any("Failed to bootstrap" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Live HTTP endpoints — explicit shape contract
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_root_endpoint_shape(client: TestClient):
    """``GET /`` must return the documented health envelope."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "service" in body
    assert body["version"] == "1.0.0"


def test_api_health_endpoint_shape(client: TestClient):
    """``GET /api/health`` must surface ``data_available`` (bool) and
    ``data_dir`` (str)."""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["data_available"], bool)
    assert isinstance(body["data_dir"], str)
