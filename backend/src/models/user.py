"""User entity."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import Role, UserStatus

if TYPE_CHECKING:
    from src.models.audit_log import AuditLog
    from src.models.auth_session import AuthSession
    from src.models.chat import Chat
    from src.models.group import Group
    from src.models.usage import Usage


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "max_active_chats_override IS NULL OR max_active_chats_override >= 0",
            name="ck_users_max_active_chats_override_nonneg",
        ),
        CheckConstraint(
            "token_quota_override IS NULL OR token_quota_override >= 0",
            name="ck_users_token_quota_override_nonneg",
        ),
    )

    username: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[UserStatus] = enum_column(
        UserStatus, name="user_status", nullable=False, default=UserStatus.PENDING
    )
    role: Mapped[Role] = enum_column(Role, name="role", nullable=False, default=Role.USER)

    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Quota overrides (Phase 7). NULL means "fall through to the
    # group override, else the global default." See ADR 0010.
    max_active_chats_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_quota_override: Mapped[int | None] = mapped_column(Integer, nullable=True)

    group: Mapped[Group | None] = relationship(back_populates="users")
    chats: Mapped[list[Chat]] = relationship(back_populates="user", cascade="all, delete-orphan")
    usage_records: Mapped[list[Usage]] = relationship(back_populates="user")
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="actor", foreign_keys="AuditLog.actor_user_id"
    )
    auth_sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User id={self.id} username={self.username!r} role={self.role}>"
