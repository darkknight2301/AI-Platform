"""Data access for the `usage_records` table."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.usage import Usage
from src.models.user import User


async def list_by_user(session: AsyncSession, user_id: uuid.UUID) -> list[Usage]:
    stmt = select(Usage).where(Usage.user_id == user_id).order_by(Usage.timestamp.desc())
    return list((await session.scalars(stmt)).all())


async def list_by_group(session: AsyncSession, group_id: uuid.UUID) -> list[Usage]:
    stmt = (
        select(Usage)
        .join(User, User.id == Usage.user_id)
        .where(User.group_id == group_id)
        .order_by(Usage.timestamp.desc())
    )
    return list((await session.scalars(stmt)).all())


async def list_all(session: AsyncSession, *, limit: int = 200, offset: int = 0) -> list[Usage]:
    stmt = select(Usage).order_by(Usage.timestamp.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())
