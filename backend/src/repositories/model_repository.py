"""Data access for the `models` (AIModel) table."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ai_model import AIModel


async def get_by_id(session: AsyncSession, model_id: uuid.UUID) -> AIModel | None:
    return await session.get(AIModel, model_id)


async def get_by_key(session: AsyncSession, model_key: str) -> AIModel | None:
    stmt = select(AIModel).where(AIModel.model_key == model_key)
    return await session.scalar(stmt)


async def list_all(session: AsyncSession, *, enabled_only: bool = False) -> list[AIModel]:
    stmt = select(AIModel)
    if enabled_only:
        stmt = stmt.where(AIModel.is_enabled.is_(True))
    stmt = stmt.order_by(AIModel.display_name)
    return list((await session.scalars(stmt)).all())
