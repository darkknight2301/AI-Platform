"""
Health check endpoint.

Used by load balancers / orchestration (and Nginx, indirectly) to
determine whether an application instance is ready to serve traffic.
Intentionally lightweight: no DB round-trip is required for the
foundation-phase check so it stays cheap and dependency-free.
"""
from __future__ import annotations

from fastapi import APIRouter

from src.core.config import get_settings
from src.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        environment=settings.environment.value,
        version="0.1.0",
    )
