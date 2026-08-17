"""
Quota reservation entity (Phase 7).

A short-lived row representing "this many tokens are provisionally
committed for an in-flight model call". It exists only for the
duration of one generation: created (inside a lock, after checking
quota) immediately before calling the model, deleted immediately after
the call finishes (success or failure) — see
`src/services/quota_service.py` and ADR 0010.

Its purpose is purely concurrency safety: a second, truly-concurrent
request must see the first request's reservation when it computes
"current usage" for its own quota check, or two simultaneous requests
could both pass a check that neither alone would have failed. Actual
token accounting is always the provider-reported usage recorded in
`usage_records` (Phase 2/3) on success — this table is never read for
historical/billing purposes, only for the live in-flight check.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.models._types import UUIDPrimaryKeyMixin


class QuotaReservation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "quota_reservations"
    __table_args__ = (
        CheckConstraint("estimated_tokens >= 0", name="ck_quota_reservations_estimated_tokens_nonneg"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<QuotaReservation id={self.id} user_id={self.user_id} est={self.estimated_tokens}>"
