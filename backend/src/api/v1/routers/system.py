"""
Developer-role endpoints: application logs, model status, diagnostics,
performance information.

Access requires Role.DEVELOPER or above (Owner is a superset — see
`require_min_role`). Deliberately does NOT expose chat content or user
PII: "Do not automatically grant unrestricted private chat access" —
Developer access is operational (logs/metrics/model config), not
conversational data.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import require_min_role
from src.core.config import get_settings
from src.core.logging import recent_log_entries
from src.core.middleware import metrics
from src.db.session import get_db
from src.models.enums import Role
from src.repositories import model_repository
from src.schemas.system import (
    DiagnosticsResponse,
    LogEntryOut,
    ModelStatusOut,
    ModelStatusResponse,
    PerformanceResponse,
    RecentLogsResponse,
)

router = APIRouter(
    prefix="/system",
    tags=["system"],
    dependencies=[Depends(require_min_role(Role.DEVELOPER))],
)


@router.get("/logs", response_model=RecentLogsResponse)
async def get_recent_logs(limit: int = 100) -> RecentLogsResponse:
    entries = list(recent_log_entries)[-limit:]
    return RecentLogsResponse(entries=[LogEntryOut(**e) for e in entries])


@router.get("/models", response_model=ModelStatusResponse)
async def get_model_status(session: AsyncSession = Depends(get_db)) -> ModelStatusResponse:
    models = await model_repository.list_all(session)
    return ModelStatusResponse(models=[ModelStatusOut.model_validate(m) for m in models])


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def get_diagnostics(session: AsyncSession = Depends(get_db)) -> DiagnosticsResponse:
    settings = get_settings()
    try:
        await session.execute(text("SELECT 1"))
        db_reachable = True
    except Exception:
        db_reachable = False

    return DiagnosticsResponse(
        environment=settings.environment.value,
        database_reachable=db_reachable,
        server_time=datetime.now(UTC),
        uptime_seconds=metrics.uptime_seconds,
    )


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance() -> PerformanceResponse:
    return PerformanceResponse(
        total_requests=metrics.total_requests,
        requests_by_status_class=dict(metrics.status_class_counts),
        average_response_time_ms=metrics.average_response_time_ms,
        uptime_seconds=metrics.uptime_seconds,
    )
