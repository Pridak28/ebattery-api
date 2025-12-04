"""
Battery Analytics Pro - FastAPI Application
Main entry point for the backend API
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import pzu, fr, investment

# Initialize FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Professional Battery Energy Storage Analytics API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
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


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": "1.0.0"
    }


@app.get("/api/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "database": "connected",
        "data_available": settings.DATA_DIR.exists()
    }
