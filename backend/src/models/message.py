"""Message entity — a single turn within a chat."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import MessageRole

if TYPE_CHECKING:
    from src.models.chat import Chat
    from src.models.usage import Usage


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Fetching a chat's messages in order is the dominant query pattern.
        Index("ix_messages_chat_id_created_at", "chat_id", "created_at"),
        CheckConstraint("input_tokens >= 0", name="ck_messages_input_tokens_nonneg"),
        CheckConstraint("output_tokens >= 0", name="ck_messages_output_tokens_nonneg"),
        CheckConstraint(
            "total_tokens = input_tokens + output_tokens", name="ck_messages_total_tokens_sum"
        ),
        CheckConstraint("revision >= 1", name="ck_messages_revision_positive"),
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

    # Incremented when a message is edited/regenerated, so history can
    # be preserved without deleting prior content at the application layer.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    chat: Mapped[Chat] = relationship(back_populates="messages")
    usage_records: Mapped[list[Usage]] = relationship(back_populates="message")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Message id={self.id} chat_id={self.chat_id} role={self.role}>"
