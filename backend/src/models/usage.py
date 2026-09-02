"""Usage entity — per-request token accounting."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models._types import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.models.ai_model import AIModel
    from src.models.chat import Chat
    from src.models.message import Message
    from src.models.user import User


class Usage(UUIDPrimaryKeyMixin, Base):
    """One row per model request, used for accounting/reporting.

    Deliberately denormalized against `chat_id`/`user_id` (in addition
    to being reachable via `message_id`) so usage reports and quota
    checks can query this table directly without joining through
    `messages` -> `chats` for every read.
    """

    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_user_id_timestamp", "user_id", "timestamp"),
        Index("ix_usage_model_id_timestamp", "model_id", "timestamp"),
        Index("ix_usage_chat_id_timestamp", "chat_id", "timestamp"),
        CheckConstraint("input_tokens >= 0", name="ck_usage_input_tokens_nonneg"),
        CheckConstraint("output_tokens >= 0", name="ck_usage_output_tokens_nonneg"),
        CheckConstraint(
            "total_tokens = input_tokens + output_tokens", name="ck_usage_total_tokens_sum"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chats.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Mirrors Chat.agent_key — set when this usage row came from an
    # agent run (e.g. ILA) rather than a direct model call. NULL for
    # every usage row today. See ADR 0012.
    agent_key: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    user: Mapped[User] = relationship(back_populates="usage_records")
    chat: Mapped[Chat | None] = relationship(back_populates="usage_records")
    message: Mapped[Message | None] = relationship(back_populates="usage_records")
    model: Mapped[AIModel] = relationship(back_populates="usage_records")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Usage id={self.id} user_id={self.user_id} total_tokens={self.total_tokens}>"
