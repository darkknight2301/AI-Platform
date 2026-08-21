"""Data access for the `audit_logs` table."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
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


async def count_recent(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    action: str,
    result: AuditResult,
    since: datetime,
) -> int:
    stmt = select(func.count()).select_from(AuditLog).where(
        AuditLog.target_type == target_type,
        AuditLog.target_id == target_id,
        AuditLog.action == action,
        AuditLog.result == result,
        AuditLog.timestamp >= since,
    )
    return (await session.scalar(stmt)) or 0
    stmt = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def list_by_actor(
    session: AsyncSession, actor_user_id: uuid.UUID, *, limit: int = 100, offset: int = 0
) -> list[AuditLog]:
    """Entries where `actor_user_id` is the acting user.

    Used for the Manager dashboard's "Authorized activity" panel: a
    Manager only ever needs to see the actions *they themselves*
    performed (approvals/rejections). Scoping by actor_user_id is
    inherently safe here — there is no query-parameter or path
    variable a Manager could manipulate to see another actor's
    entries, unlike a group_id-based filter would require.
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.actor_user_id == actor_user_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(stmt)).all())
