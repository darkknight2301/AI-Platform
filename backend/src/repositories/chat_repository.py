"""Data access for the `chats` table."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chat import Chat
from src.models.enums import ChatStatus


async def get_by_id(session: AsyncSession, chat_id: uuid.UUID) -> Chat | None:
    return await session.get(Chat, chat_id)


async def list_by_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: ChatStatus | None = None,
    exclude_deleted_by_default: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[Chat]:
    stmt = select(Chat).where(Chat.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Chat.status == status)
    elif exclude_deleted_by_default:
        stmt = stmt.where(Chat.status != ChatStatus.DELETED)
    stmt = stmt.order_by(Chat.updated_at.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())
