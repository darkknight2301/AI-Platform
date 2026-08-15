"""Data access for the `users` table."""
from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import UserStatus
from src.models.user import User


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_by_username_or_email(session: AsyncSession, identifier: str) -> User | None:
    stmt = select(User).where(or_(User.username == identifier, User.email == identifier))
    return await session.scalar(stmt)


async def username_or_email_taken(session: AsyncSession, username: str, email: str) -> bool:
    stmt = select(User.id).where(or_(User.username == username, User.email == email))
    return await session.scalar(stmt) is not None


async def list_by_group(
    session: AsyncSession, group_id: uuid.UUID, *, status: UserStatus | None = None
) -> list[User]:
    stmt = select(User).where(User.group_id == group_id)
    if status is not None:
        stmt = stmt.where(User.status == status)
    stmt = stmt.order_by(User.created_at)
    return list((await session.scalars(stmt)).all())


async def list_all(session: AsyncSession, *, status: UserStatus | None = None) -> list[User]:
    stmt = select(User)
    if status is not None:
        stmt = stmt.where(User.status == status)
    stmt = stmt.order_by(User.created_at)
    return list((await session.scalars(stmt)).all())
