"""
Application configuration settings
"""
import os
from pathlib import Path
from typing import Any, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Default CORS origins used when CORS_ORIGINS_RAW does not provide overrides.
# Env-supplied origins are merged with these defaults so local dev keeps
# working in production deployments.
_DEFAULT_CORS_ORIGINS: List[str] = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://ebattery-analytics.netlify.app",
]


def _default_data_dir() -> Path:
    """Resolve the default DATA_DIR.

    Allows overriding via the DATA_DIR env var so Render / Docker deployments
    can point at a different mount. Falls back to in-repo backend/data
    (which is a symlink to BOT BATTERY/data on contributor machines).
    """
    env_value = os.environ.get("DATA_DIR")
    if env_value:
        return Path(env_value).expanduser()
    backend_root = Path(__file__).resolve().parent.parent
    catalog_processed = backend_root / "data_catalog" / "processed"
    if catalog_processed.exists():
        return catalog_processed
    deploy_safe_data = backend_root / "data 2"
    if deploy_safe_data.exists():
        return deploy_safe_data
    return backend_root / "data"


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API Settings
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Battery Analytics Pro"
    DEBUG: bool = True

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_flag(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "dev", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value

    # CORS — comma-separated string parsed via the CORS_ORIGINS property
    # to avoid pydantic JSON-decoding a list-typed env var.
    CORS_ORIGINS_RAW: str = ""

    # Data paths — configurable via DATA_DIR env var.
    DATA_DIR: Path = Field(default_factory=_default_data_dir)

    # Optional HTTPS URL fetched at startup when DATA_DIR is empty (Render).
    BACKEND_DATA_URL: str = ""

    # Default battery parameters — anchored on user's quote:
    # €3,500,000 EPC for 10 MW / 20 MWh (= €175/kWh installed).
    # User directive (2026-05-03): the install is sized so the FULL 20 MWh
    # is the usable per-cycle throughput (oversize the nameplate so the
    # warranty band still covers 20 MWh, or run outside the warranty band
    # by spec). RTE = 0.97 (3% per round-trip) per the user's vendor target.
    DEFAULT_POWER_MW: float = 10.0
    DEFAULT_CAPACITY_MWH: float = 20.0
    DEFAULT_EFFICIENCY: float = 0.97

    # Phase D physical-realism defaults. AC-to-AC round-trip efficiency
    # applied as sqrt(eta) on charge AND discharge so the round-trip
    # preserves eta. SOC band 0-100% reflects the user's "use full 20 MWh"
    # directive — equivalent to oversizing the install so the warranty
    # band covers the full 20 MWh of usable energy.
    DEFAULT_RTE_AC_AC: float = 0.97
    DEFAULT_SOC_MIN: float = 0.0
    DEFAULT_SOC_MAX: float = 1.0
    # 1.5% of 10 MW rated power — matches InvestmentParams.auxiliary_load_mw default.
    # Earlier value 0.3 MW (3%) was high-end; 0.15 MW is mid-industry for new BESS.
    DEFAULT_AUXILIARY_LOAD_MW: float = 0.15
    DEFAULT_AVAILABILITY_PCT: float = 97.5
    DEFAULT_EFC_BUDGET: int = 6000
    DEFAULT_WARRANTY_YEARS: int = 15
    DEFAULT_AUGMENTATION_PCT_OF_EPC: float = 10.0
    DEFAULT_SELF_DISCHARGE_PCT_PER_MONTH: float = 2.0

    # Pydantic v2 — replaces deprecated ``class Config`` (removed in v3).
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    @property
    def CORS_ORIGINS(self) -> List[str]:
        merged: List[str] = list(_DEFAULT_CORS_ORIGINS)
        if self.CORS_ORIGINS_RAW:
            for origin in self.CORS_ORIGINS_RAW.split(","):
                cleaned = origin.strip()
                if cleaned and cleaned not in merged:
                    merged.append(cleaned)
        return merged


settings = Settings()
