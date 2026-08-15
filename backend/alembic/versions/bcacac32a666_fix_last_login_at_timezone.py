"""fix last login at timezone

Revision ID: bcacac32a666
Revises: bea116010b54
Create Date: 2026-08-15 14:57:03.135188

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bcacac32a666'
down_revision: Union[str, Sequence[str], None] = 'bea116010b54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Fixes `users.last_login_at`, which was originally created without
    an explicit timezone-aware type and defaulted to
    TIMESTAMP WITHOUT TIME ZONE. The application always writes
    timezone-aware UTC datetimes; storing them in a tz-naive column
    caused a runtime DBAPI error under asyncpg. All other columns
    involved in this table already used DateTime(timezone=True).

    (Autogenerate also proposed dropping/recreating every enum-backed
    CHECK constraint — the same reflected-vs-named-constraint
    false-positive noted in bea116010b54 — removed by hand; no enum
    constraints actually changed here.)
    """
    op.alter_column(
        'users',
        'last_login_at',
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'users',
        'last_login_at',
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_nullable=True,
    )
