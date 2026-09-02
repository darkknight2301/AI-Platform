"""Chat entity — a conversation thread belonging to a user."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import ChatStatus

if TYPE_CHECKING:
    from src.models.ai_model import AIModel
    from src.models.message import Message
    from src.models.usage import Usage
    from src.models.user import User


class Chat(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chats"
    __table_args__ = (
        # Listing "my recent chats" is the dominant chat query pattern.
        Index("ix_chats_user_id_updated_at", "user_id", "updated_at"),
        Index("ix_chats_user_id_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # NULL for an ordinary model-backed chat (today's only case).
    # Set to an agent's registered key (e.g. "ila-agent") when this
    # chat is handled by src/agent_layer/ instead of the model layer.
    # `model_id` is still always populated even then — it points at
    # that agent's placeholder `AIModel` row (see ModelCategory.AGENT,
    # agent_layer/bootstrap.py) purely so this column's FK/NOT NULL
    # contract never has to change. See ADR 0012.
    agent_key: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False, default="New chat")
    status: Mapped[ChatStatus] = enum_column(
        ChatStatus, name="chat_status", nullable=False, default=ChatStatus.ACTIVE
    )

    # Incremented on every meaningful edit (title change, message
    # added, etc.) for optimistic-concurrency/change-detection use by
    # future sync or collaborative-editing features.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Free-form snapshot of additional chat state (e.g. active branch,
    # draft input, pinned settings) that doesn't warrant its own column.
    state_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    user: Mapped[User] = relationship(back_populates="chats")
    model: Mapped[AIModel] = relationship(back_populates="chats")
    messages: Mapped[list[Message]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    usage_records: Mapped[list[Usage]] = relationship(back_populates="chat")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Chat id={self.id} user_id={self.user_id} status={self.status}>"
