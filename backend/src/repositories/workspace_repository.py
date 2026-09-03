"""Data access for the `workspaces` table."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.workspace import Workspace


async def get_by_id(session: AsyncSession, workspace_id: uuid.UUID) -> Workspace | None:
    return await session.get(Workspace, workspace_id)


async def get_by_chat_id(session: AsyncSession, chat_id: uuid.UUID) -> Workspace | None:
    stmt = select(Workspace).where(Workspace.chat_id == chat_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
