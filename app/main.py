"""
Battery Analytics Pro - FastAPI Application
Main entry point for the backend API
"""
import io
import logging
import tarfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import pzu, fr, investment, data

logger = logging.getLogger("battery_analytics.startup")
logging.basicConfig(level=logging.INFO)


def _data_dir_is_populated(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return any(path.iterdir())
    except OSError:
        return False


def _bootstrap_data() -> None:
    """If DATA_DIR is empty, try to materialize it from BACKEND_DATA_URL.

    Tolerant: if the fetch fails (or no URL is configured), logs an actionable
    error and lets the app boot. Endpoints needing data will then return their
    normal "file not found" errors instead of 500ing the whole service.
    """
    data_dir: Path = settings.DATA_DIR
    if _data_dir_is_populated(data_dir):
        logger.info("DATA_DIR ready at %s", data_dir)
        return

    url = settings.BACKEND_DATA_URL.strip()
    if not url:
        logger.error(
            "DATA_DIR=%s is missing or empty and BACKEND_DATA_URL is not set. "
            "Set BACKEND_DATA_URL to an HTTPS archive (.zip / .tar.gz) or a "
            "single-file URL to bootstrap data on startup.",
            data_dir,
        )
        return

    logger.info("Bootstrapping DATA_DIR=%s from %s", data_dir, url)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with urlopen(url, timeout=120) as resp:  # noqa: S310 — operator-controlled URL
            payload = resp.read()
        parsed_path = urlparse(url).path.lower()
        if parsed_path.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                zf.extractall(data_dir)
        elif parsed_path.endswith((".tar.gz", ".tgz", ".tar")):
            mode = "r:gz" if parsed_path.endswith((".tar.gz", ".tgz")) else "r:"
            with tarfile.open(fileobj=io.BytesIO(payload), mode=mode) as tf:
                tf.extractall(data_dir)
        else:
            filename = Path(parsed_path).name or "data.bin"
            (data_dir / filename).write_bytes(payload)
        logger.info("DATA_DIR populated successfully at %s", data_dir)
    except Exception as exc:  # noqa: BLE001 — log and keep serving
        logger.error(
            "Failed to bootstrap DATA_DIR from BACKEND_DATA_URL=%s: %s. "
            "Endpoints needing data will return errors until this is fixed.",
            url,
            exc,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _bootstrap_data()
    yield


# Initialize FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Professional Battery Energy Storage Analytics API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(pzu.router, prefix=f"{settings.API_V1_PREFIX}/pzu", tags=["PZU"])
app.include_router(fr.router, prefix=f"{settings.API_V1_PREFIX}/fr", tags=["Frequency Regulation"])
app.include_router(investment.router, prefix=f"{settings.API_V1_PREFIX}/investment", tags=["Investment"])
app.include_router(data.router, prefix=f"{settings.API_V1_PREFIX}/data", tags=["Data"])


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": "1.0.0",
    }


@app.get("/api/health")
async def health_check():
    """Detailed health check"""
    populated = False
    if settings.DATA_DIR.exists():
        try:
            populated = any(settings.DATA_DIR.iterdir())
        except OSError:
            populated = False
    return {
        "status": "healthy",
        "data_available": populated,
        "data_dir": str(settings.DATA_DIR),
    }
