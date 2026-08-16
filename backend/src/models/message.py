"""Message entity — a single turn within a chat.

## Revision model (Phase 6)

A "slot" is a logical position in the conversation (one user prompt,
or the one assistant reply that follows it). Editing a prompt or
regenerating a reply never mutates or deletes an existing row — it
inserts a NEW row in the same slot and flips `is_active` so exactly
one row per slot is current at a time. This is what "do not overwrite
history; maintain revisions" means concretely: every previous v1/v2/v3
remains a real, queryable row.

- `root_message_id` is NULL on the first row of a slot (the root) and
  equals the root's `id` on every later revision in that slot — so
  "all revisions of this slot" is a single indexed equality lookup
  (`root_message_id = :root_id OR id = :root_id`), not a linked-list
  walk.
- `sequence_number` is assigned once, on the root, and copied to every
  revision in that slot. It defines the slot's fixed position in the
  conversation, independent of *when* a particular revision was
  created — so editing an early prompt doesn't reorder the thread.
- `is_active` marks the current revision for that slot. Activating a
  different revision (see `POST /messages/{id}/activate`) is the
  server-persisted undo/redo primitive: exactly one row per slot
  flips to active, nothing is deleted either way.
- The "active thread" sent to a model, or shown as chat history, is
  `WHERE chat_id = :chat_id AND is_active = true ORDER BY sequence_number`.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import MessageRole

if TYPE_CHECKING:
    from src.models.ai_model import AIModel
    from src.models.chat import Chat
    from src.models.usage import Usage


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Fetching a chat's messages in order is the dominant query pattern.
        Index("ix_messages_chat_id_created_at", "chat_id", "created_at"),
        # The active-thread query: WHERE chat_id=... AND is_active=true ORDER BY sequence_number.
        Index("ix_messages_chat_id_active_sequence", "chat_id", "is_active", "sequence_number"),
        CheckConstraint("input_tokens >= 0", name="ck_messages_input_tokens_nonneg"),
        CheckConstraint("output_tokens >= 0", name="ck_messages_output_tokens_nonneg"),
        CheckConstraint(
            "total_tokens = input_tokens + output_tokens", name="ck_messages_total_tokens_sum"
        ),
        CheckConstraint("revision >= 1", name="ck_messages_revision_positive"),
        CheckConstraint("sequence_number >= 0", name="ck_messages_sequence_number_nonneg"),
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[MessageRole] = enum_column(MessageRole, name="message_role", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Correlates a message with the backend request that produced it
    # (e.g. for tracing/log correlation). Not unique: a retried request
    # may be recorded against more than one message revision.
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Which revision, within its slot, this row is (1 = the original).
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # NULL on a slot's root row; equals the root's id on every later
    # revision in that slot. See module docstring.
    root_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Exactly one row per slot has is_active=True at any time.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Fixed position of this slot within the chat, shared by every
    # revision in the slot. NOT the same as created_at, which changes
    # with each new revision.
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Wall-clock generation time for an assistant reply. NULL for user
    # messages (there's nothing to time).
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Which model actually produced this specific revision (assistant
    # messages only) — distinct from Chat.model_id, which is the
    # chat's *current* model and may change over the conversation.
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True
    )

    chat: Mapped[Chat] = relationship(back_populates="messages")
    usage_records: Mapped[list[Usage]] = relationship(back_populates="message")
    model: Mapped[AIModel | None] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Message id={self.id} chat_id={self.chat_id} role={self.role} rev={self.revision}>"
