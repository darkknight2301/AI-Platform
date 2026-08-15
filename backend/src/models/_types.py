"""
Shared column/type helpers used by ORM models.
"""
from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column


def enum_column(enum_cls: type[enum.Enum], *, name: str, **kwargs: Any):
    """Build a portable enum column.

    Stored as VARCHAR + CHECK constraint (native_enum=False) rather
    than a native PostgreSQL ENUM type, so:
      - the same schema works against SQLite in tests, and
      - adding a new enum value later is a plain migration, not an
        `ALTER TYPE ... ADD VALUE` (which has its own transactional
        restrictions in PostgreSQL).
    """
    return mapped_column(
        SAEnum(
            enum_cls,
            name=name,
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            length=32,
        ),
        **kwargs,
    )


class UUIDPrimaryKeyMixin:
    """Shared UUID surrogate primary key.

    UUIDs are used for all entities so IDs are safe to expose
    externally (e.g. in API responses/URLs) without leaking sequential
    volume information, and so they can be generated client- or
    worker-side before an insert if ever needed.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
