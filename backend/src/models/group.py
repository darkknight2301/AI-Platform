"""Group entity — organizational grouping of users."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import GroupStatus

if TYPE_CHECKING:
    from src.models.user import User


class Group(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint(
            "max_active_chats_override IS NULL OR max_active_chats_override >= 0",
            name="ck_groups_max_active_chats_override_nonneg",
        ),
        CheckConstraint(
            "token_quota_override IS NULL OR token_quota_override >= 0",
            name="ck_groups_token_quota_override_nonneg",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    status: Mapped[GroupStatus] = enum_column(
        GroupStatus, name="group_status", nullable=False, default=GroupStatus.ACTIVE
    )

    # Quota overrides (Phase 7). NULL means "use the global default"
    # (see src.core.config.Settings.default_max_active_chats /
    # default_token_quota). See ADR 0010 for the resolution order:
    # user override > group override > global default.
    max_active_chats_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_quota_override: Mapped[int | None] = mapped_column(Integer, nullable=True)

    users: Mapped[list[User]] = relationship(back_populates="group")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Group id={self.id} name={self.name!r} status={self.status}>"
