"""
Application configuration settings
"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API Settings
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Battery Analytics Pro"
    DEBUG: bool = True

    # CORS Settings
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",  # Next.js dev server
        "http://localhost:8000",  # FastAPI dev server
        "https://ebattery-analytics.netlify.app",  # Production Netlify
    ]

    # Data paths - use relative path for deployment
    DATA_DIR: Path = Path(__file__).parent.parent / "data"

    # Default battery parameters
    DEFAULT_POWER_MW: float = 15.0
    DEFAULT_CAPACITY_MWH: float = 30.0
    DEFAULT_EFFICIENCY: float = 0.88

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
