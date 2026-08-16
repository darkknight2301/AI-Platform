"""
Data access for the `messages` table, including the revision-slot
helpers the conversation service builds on. See the module docstring
in `src/models/message.py` for the revision model these implement.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.enums import MessageRole
from src.models.message import Message


async def get_by_id(session: AsyncSession, message_id: uuid.UUID) -> Message | None:
    return await session.get(Message, message_id)


async def list_active_thread(
    session: AsyncSession, chat_id: uuid.UUID, *, limit: int = 200, offset: int = 0
) -> list[Message]:
    """The current conversation: one row per slot, in fixed position order."""
    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id, Message.is_active.is_(True))
        .order_by(Message.sequence_number)
        .limit(limit)
        .offset(offset)
    )
    return list((await session.scalars(stmt)).all())


async def list_active_thread_before(
    session: AsyncSession, chat_id: uuid.UUID, *, before_sequence_number: int
) -> list[Message]:
    """Active messages strictly before a given slot position — used to build
    the model context for a regenerate/edit call without including the
    slot being replaced."""
    stmt = (
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.is_active.is_(True),
            Message.sequence_number < before_sequence_number,
        )
        .order_by(Message.sequence_number)
    )
    return list((await session.scalars(stmt)).all())


async def get_active_at_sequence(
    session: AsyncSession, chat_id: uuid.UUID, sequence_number: int
) -> Message | None:
    stmt = select(Message).where(
        Message.chat_id == chat_id,
        Message.is_active.is_(True),
        Message.sequence_number == sequence_number,
    )
    return await session.scalar(stmt)


async def list_slot_revisions(session: AsyncSession, root_id: uuid.UUID) -> list[Message]:
    """All revisions of the slot that `root_id` belongs to (root_id may be
    the root itself or any revision's id — both resolve to the same slot
    via `root_message_id`)."""
    stmt = (
        select(Message)
        .where((Message.root_message_id == root_id) | (Message.id == root_id))
        .order_by(Message.revision)
    )
    return list((await session.scalars(stmt)).all())


async def get_next_sequence_number(session: AsyncSession, chat_id: uuid.UUID) -> int:
    """Next fixed slot position for a NEW slot (new user prompt or its
    paired assistant reply) — never used when adding a revision to an
    existing slot, which reuses the slot's existing sequence_number."""
    stmt = select(func.coalesce(func.max(Message.sequence_number), -1)).where(
        Message.chat_id == chat_id
    )
    current_max = await session.scalar(stmt)
    return (current_max or -1) + 1


async def get_max_revision_in_slot(session: AsyncSession, root_id: uuid.UUID) -> int:
    stmt = select(func.max(Message.revision)).where(
        (Message.root_message_id == root_id) | (Message.id == root_id)
    )
    result = await session.scalar(stmt)
    return result or 1


async def deactivate_slot(session: AsyncSession, root_id: uuid.UUID) -> None:
    """Mark every revision in a slot inactive — the caller is responsible
    for then inserting or activating exactly one new/other active row."""
    stmt = (
        update(Message)
        .where((Message.root_message_id == root_id) | (Message.id == root_id))
        .values(is_active=False)
    )
    await session.execute(stmt)


def resolve_root_id(message: Message) -> uuid.UUID:
    """The slot identifier for any given revision row."""
    return message.root_message_id or message.id


def to_model_role(role: MessageRole) -> str:
    """Map the persistence-layer role enum to the model layer's plain
    string literal (see src.model_layer.schemas.ModelMessage) — keeps
    the model layer decoupled from the ORM enum type."""
    return role.value.lower()
