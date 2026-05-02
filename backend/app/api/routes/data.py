from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.config import settings


router = APIRouter()


def _catalog_root() -> Path:
    return Path(__file__).resolve().parents[3] / "data_catalog"


@router.get("/manifest")
async def get_data_manifest():
    path = _catalog_root() / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="data manifest not found; run python -m app.market_data.pipeline")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/status")
async def get_data_status():
    catalog = _catalog_root()
    manifest_path = catalog / "manifest.json"
    datasets = []
    if manifest_path.exists():
        try:
            datasets = json.loads(manifest_path.read_text(encoding="utf-8")).get("datasets", [])
        except Exception:
            datasets = []
    return {
        "data_dir": str(settings.DATA_DIR),
        "catalog_root": str(catalog),
        "manifest_exists": manifest_path.exists(),
        "datasets": datasets,
    }


# ---------------------------------------------------------------------------
# Extended health-check — sub-system diagnostics
# ---------------------------------------------------------------------------
def _manifest_dataset(manifest: Optional[dict], dataset_id: str) -> Optional[dict]:
    if not manifest:
        return None
    for ds in manifest.get("datasets", []) or []:
        if ds.get("dataset_id") == dataset_id:
            return ds
    return None


def _days_stale(max_date_iso: Optional[str], today: date) -> Optional[int]:
    if not max_date_iso:
        return None
    try:
        return (today - date.fromisoformat(max_date_iso[:10])).days
    except Exception:
        return None


def _check_pzu(manifest: Optional[dict], today: date) -> Dict[str, Any]:
    """Lightweight PZU dataset diagnostics — prefer manifest, fall back to file scan."""
    out: Dict[str, Any] = {
        "available": False,
        "row_count": None,
        "min_date": None,
        "max_date": None,
        "days_stale": None,
    }
    try:
        ds = _manifest_dataset(manifest, "opcom_pzu")
        if ds:
            out["available"] = True
            out["row_count"] = ds.get("row_count")
            out["min_date"] = ds.get("min_delivery_date")
            out["max_date"] = ds.get("max_delivery_date")
            out["days_stale"] = _days_stale(out["max_date"], today)
            return out
        # Fallback: peek at the CSV without loading it all.
        path = settings.DATA_DIR / "pzu_history_3y.csv"
        if path.exists():
            df = pd.read_csv(path, usecols=["date"])
            if not df.empty:
                dates = pd.to_datetime(df["date"], errors="coerce").dropna()
                out["available"] = True
                out["row_count"] = int(len(df))
                out["min_date"] = dates.min().date().isoformat() if len(dates) else None
                out["max_date"] = dates.max().date().isoformat() if len(dates) else None
                out["days_stale"] = _days_stale(out["max_date"], today)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _check_damas(manifest: Optional[dict], today: date) -> Dict[str, Any]:
    """DAMAS diagnostics — manifest header + cheap scan for regime + FCR totals."""
    out: Dict[str, Any] = {
        "available": False,
        "row_count": None,
        "min_date": None,
        "max_date": None,
        "days_stale": None,
        "regime_pre_count": 0,
        "regime_post_count": 0,
        "fcr_activated_total_mwh": 0.0,
    }
    try:
        ds = _manifest_dataset(manifest, "damas_clean")
        if ds:
            out["available"] = True
            out["row_count"] = ds.get("row_count")
            out["min_date"] = ds.get("min_delivery_date")
            out["max_date"] = ds.get("max_delivery_date")
            out["days_stale"] = _days_stale(out["max_date"], today)
        path = settings.DATA_DIR / "damas_clean.csv"
        if path.exists():
            usecols = ["regulatory_regime", "fcr_activated_mwh"]
            df = pd.read_csv(path, usecols=lambda c: c in usecols)
            if not out["available"]:
                out["available"] = True
            if "regulatory_regime" in df.columns:
                vc = df["regulatory_regime"].value_counts(dropna=True).to_dict()
                out["regime_pre_count"] = int(vc.get("pre_order60_2024_marginal", 0))
                out["regime_post_count"] = int(vc.get("post_order60_2024_pay_as_bid", 0))
            if "fcr_activated_mwh" in df.columns:
                out["fcr_activated_total_mwh"] = float(
                    pd.to_numeric(df["fcr_activated_mwh"], errors="coerce").fillna(0).sum()
                )
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _smoke_pzu() -> Dict[str, Any]:
    try:
        from app.services.pzu_service import PZUService
        from app.models.pzu import PZUSimulationParams

        params = PZUSimulationParams(
            power_mw=10,
            capacity_mwh=20,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 1),
        )
        result = PZUService().simulate(params)
        return {"ok": True, "total_profit_eur": float(result.total_profit_eur)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _smoke_fr() -> Dict[str, Any]:
    try:
        from app.services.fr_service import FRService
        from app.models.fr import FRSimulationParams, FRProductConfig

        params = FRSimulationParams(
            capacity_mwh=20,
            afrr_up=FRProductConfig(enabled=True, power_mw=10),
            afrr_down=FRProductConfig(enabled=True, power_mw=10),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 1),
        )
        result = FRService().simulate(params)
        return {"ok": True, "total_profit_eur": float(result.total_net_profit_eur)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _compliance_gates_default() -> Dict[str, Any]:
    try:
        from app.models.investment import ComplianceGates

        return ComplianceGates().model_dump()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


@router.get("/health-detailed")
async def get_health_detailed():
    """Extended health-check exposing per-sub-system diagnostics.

    Each sub-system runs in its own try/except so one broken piece never
    crashes the endpoint. Designed to be FAST (<2s): smoke simulations use
    a 60-day window.
    """
    today = date.today()
    catalog = _catalog_root()
    manifest_path = catalog / "manifest.json"

    manifest: Optional[dict] = None
    manifest_present = manifest_path.exists()
    if manifest_present:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = None

    payload: Dict[str, Any] = {
        "app_version": "1.0.0",
        "data_dir": str(settings.DATA_DIR),
        "manifest_present": manifest_present,
        "as_of": today.isoformat(),
    }

    for key, fn in (
        ("pzu", lambda: _check_pzu(manifest, today)),
        ("damas", lambda: _check_damas(manifest, today)),
        ("simulator_pzu_smoke", _smoke_pzu),
        ("simulator_fr_smoke", _smoke_fr),
        ("compliance_gates_default", _compliance_gates_default),
    ):
        try:
            payload[key] = fn()
        except Exception as exc:  # noqa: BLE001 — defense in depth
            payload[key] = {"error": f"{type(exc).__name__}: {exc}"}

    return payload
