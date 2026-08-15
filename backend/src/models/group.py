"""Group entity — organizational grouping of users."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, TimestampMixin
from src.models._types import UUIDPrimaryKeyMixin, enum_column
from src.models.enums import GroupStatus

if TYPE_CHECKING:
    from src.models.user import User


class Group(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    status: Mapped[GroupStatus] = enum_column(
        GroupStatus, name="group_status", nullable=False, default=GroupStatus.ACTIVE
    )

    users: Mapped[list[User]] = relationship(back_populates="group")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Group id={self.id} name={self.name!r} status={self.status}>"
