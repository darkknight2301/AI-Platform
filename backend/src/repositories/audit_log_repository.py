"""Data access for the `audit_logs` table."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit_log import AuditLog
from src.models.enums import AuditResult


async def create(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    result: AuditResult,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor_user_id,
        action=action,
        result=result,
        target_type=target_type,
        target_id=target_id,
        request_id=request_id,
        audit_metadata=metadata or {},
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_all(session: AsyncSession, *, limit: int = 100, offset: int = 0) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())
