"""
ApexLedger Backend — FastAPI application entry point.

Start the server:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import ai_chat, auth, coa, gl, system
from app.core.config import settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler.

    Runs startup tasks (e.g. update check, cron scheduler init) before
    yielding, and cleanup tasks after the app shuts down.
    """
    # --- Startup ---
    # Future: start APScheduler, run initial update check, etc.
    yield
    # --- Shutdown ---
    # Future: graceful scheduler shutdown, connection pool disposal.


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Open-Core On-Premise AI-Native Accounting Platform",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow the React frontend on any local origin during development.
# Tighten this in production deployments.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
app.include_router(auth.router, prefix="/api/v1")
app.include_router(gl.router, prefix="/api/v1")
app.include_router(coa.router, prefix="/api/v1")
app.include_router(ai_chat.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")


@app.get("/health", tags=["System"])
async def health_check():
    """Root health-check endpoint."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "mode": settings.app_mode.value,
    }
