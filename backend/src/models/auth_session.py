"""
Auth session entity.

Access tokens are JWTs, but JWTs alone can't be revoked before their
natural expiry. Every issued token carries a `jti` (JWT ID) that maps
to a row here; logout marks that row revoked, and the auth dependency
checks this table on every request. This is what makes "logout" and
"account suspended mid-session" actually take effect immediately
instead of waiting out the token's expiry.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models._types import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from src.models.user import User


class AuthSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_id_revoked_at", "user_id", "revoked_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="auth_sessions")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AuthSession id={self.id} user_id={self.user_id} revoked={self.revoked_at is not None}>"
