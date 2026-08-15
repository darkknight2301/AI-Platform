"""User entity."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import Role, UserStatus

if TYPE_CHECKING:
    from src.models.audit_log import AuditLog
    from src.models.chat import Chat
    from src.models.group import Group
    from src.models.usage import Usage


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

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

    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)

    group: Mapped[Group | None] = relationship(back_populates="users")
    chats: Mapped[list[Chat]] = relationship(back_populates="user", cascade="all, delete-orphan")
    usage_records: Mapped[list[Usage]] = relationship(back_populates="user")
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="actor", foreign_keys="AuditLog.actor_user_id"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User id={self.id} username={self.username!r} role={self.role}>"
