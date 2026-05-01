from __future__ import annotations

import json
from pathlib import Path

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
