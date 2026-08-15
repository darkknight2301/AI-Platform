"""Audit log entity — records security/administrative-relevant actions."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import AuditResult

if TYPE_CHECKING:
    from src.models.user import User


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only record of who did what, to what, and with what result.

    `target_type`/`target_id` intentionally reference records loosely
    (as strings) rather than via foreign keys, since audit entries must
    remain even after the target row (e.g. a deleted user) is gone.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_user_id_timestamp", "actor_user_id", "timestamp"),
        Index("ix_audit_logs_target_type_target_id", "target_type", "target_id"),
    )

    # Nullable: some actions are system-initiated (no human actor).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    action: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(150), nullable=True)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    result: Mapped[AuditResult] = enum_column(AuditResult, name="audit_result", nullable=False)

    # Free-form structured context (e.g. changed fields, before/after
    # values for non-sensitive fields). Never store secrets/tokens here.
    audit_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    actor: Mapped[User | None] = relationship(
        back_populates="audit_logs", foreign_keys=[actor_user_id]
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AuditLog id={self.id} action={self.action!r} result={self.result}>"
