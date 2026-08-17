"""
Data access for Phase 7 quota enforcement: active-chat counts, windowed
token-usage sums, quota reservations, and the advisory-lock primitive
that makes check-then-act sequences safe under concurrency.

See `src/services/quota_service.py` for how these are composed, and
ADR 0010 for the full design.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.chat import Chat
from src.models.enums import ChatStatus
from src.models.quota_reservation import QuotaReservation
from src.models.usage import Usage


def advisory_lock_key(user_id: uuid.UUID) -> int:
    """Deterministically map a user id to a bigint suitable for
    `pg_advisory_xact_lock`, which takes a single signed 64-bit key.
    A theoretical hash collision between two different users only
    causes extra serialization between them, never an incorrect
    accept/reject decision — quota correctness never depends on the
    lock key being collision-free.
    """
    return int.from_bytes(user_id.bytes[:8], "big", signed=True)


async def acquire_user_lock(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Acquire a transaction-scoped advisory lock for `user_id`.

    Automatically released at COMMIT or ROLLBACK — never held past the
    end of the current transaction, and specifically never held across
    a model-provider call (see `quota_service.reserve_tokens`, which
    acquires it only for the brief check-and-insert-reservation step).
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": advisory_lock_key(user_id)})


async def count_active_chats(session: AsyncSession, user_id: uuid.UUID) -> int:
    stmt = select(func.count(Chat.id)).where(
        Chat.user_id == user_id, Chat.status == ChatStatus.ACTIVE
    )
    return (await session.scalar(stmt)) or 0


async def sum_usage_tokens_since(
    session: AsyncSession, user_id: uuid.UUID, since: datetime
) -> int:
    stmt = select(func.coalesce(func.sum(Usage.total_tokens), 0)).where(
        Usage.user_id == user_id, Usage.timestamp >= since
    )
    return (await session.scalar(stmt)) or 0


async def sum_open_reservations(session: AsyncSession, user_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.sum(QuotaReservation.estimated_tokens), 0)).where(
        QuotaReservation.user_id == user_id
    )
    return (await session.scalar(stmt)) or 0


async def earliest_usage_timestamp_since(
    session: AsyncSession, user_id: uuid.UUID, since: datetime
) -> datetime | None:
    """Timestamp of the oldest usage row still counted in the window —
    used to tell the frontend when the rolling window will next free up
    capacity (see `quota_service.get_token_quota_status`)."""
    stmt = select(func.min(Usage.timestamp)).where(
        Usage.user_id == user_id, Usage.timestamp >= since
    )
    return await session.scalar(stmt)


async def create_reservation(
    session: AsyncSession, *, user_id: uuid.UUID, estimated_tokens: int
) -> QuotaReservation:
    reservation = QuotaReservation(user_id=user_id, estimated_tokens=estimated_tokens)
    session.add(reservation)
    await session.flush()
    return reservation


async def delete_reservation(session: AsyncSession, reservation_id: uuid.UUID) -> None:
    reservation = await session.get(QuotaReservation, reservation_id)
    if reservation is not None:
        await session.delete(reservation)
