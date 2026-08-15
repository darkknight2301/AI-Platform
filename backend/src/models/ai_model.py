"""
AI model registry entity.

Represents a configured, usable model backend (e.g. "Qwen Coder
2.5"), independent of any specific provider implementation — this is
pure data; the actual provider abstraction lives in
`src/model_layer/` (see ADR 0002) and is not implemented yet.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import ModelCategory

if TYPE_CHECKING:
    from src.models.chat import Chat
    from src.models.usage import Usage


class AIModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A registered model backend available for chats/usage.

    `model_key` is the stable external identifier (e.g.
    "qwen-coder-2.5") referenced by configuration and, later, by the
    model layer's registry/router. `id` is the internal surrogate key
    used for foreign keys.
    """

    __tablename__ = "models"

    model_key: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[ModelCategory] = enum_column(
        ModelCategory, name="model_category", nullable=False
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # List of capability strings, e.g. ["streaming", "function_calling"].
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Free-form provider/runtime configuration (context window, default
    # sampling params, endpoint identifiers, etc.) — not secrets.
    config_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    chats: Mapped[list[Chat]] = relationship(back_populates="model")
    usage_records: Mapped[list[Usage]] = relationship(back_populates="model")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AIModel id={self.id} key={self.model_key!r} category={self.category}>"
