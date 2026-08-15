"""Data access for the `groups` table."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import GroupStatus
from src.models.group import Group


async def get_by_id(session: AsyncSession, group_id: uuid.UUID) -> Group | None:
    return await session.get(Group, group_id)


async def get_active_by_id(session: AsyncSession, group_id: uuid.UUID) -> Group | None:
    stmt = select(Group).where(Group.id == group_id, Group.status == GroupStatus.ACTIVE)
    return await session.scalar(stmt)


async def list_all(session: AsyncSession) -> list[Group]:
    stmt = select(Group).order_by(Group.name)
    return list((await session.scalars(stmt)).all())
