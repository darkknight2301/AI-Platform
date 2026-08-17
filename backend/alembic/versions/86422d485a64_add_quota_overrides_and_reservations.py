"""add quota overrides and reservations

Revision ID: 86422d485a64
Revises: d75afe937669
Create Date: 2026-08-16 20:32:23.245793

Phase 7: adds `quota_reservations` (short-lived, concurrency-safety
rows — see src/models/quota_reservation.py) and nullable quota
override columns on `groups`/`users` (NULL = fall through to the next
level in the resolution order: user override > group override >
global default — see src/core/config.py and ADR 0010).

(Autogenerate also proposed dropping/recreating every enum-backed
CHECK constraint — the same reflected-vs-named-constraint
false-positive noted in prior migrations — removed by hand; no enum
constraints actually changed here.)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '86422d485a64'
down_revision: Union[str, Sequence[str], None] = 'd75afe937669'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'quota_reservations',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('estimated_tokens', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.CheckConstraint('estimated_tokens >= 0', name='ck_quota_reservations_estimated_tokens_nonneg'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_quota_reservations_user_id', 'quota_reservations', ['user_id'], unique=False)

    op.add_column('groups', sa.Column('max_active_chats_override', sa.Integer(), nullable=True))
    op.add_column('groups', sa.Column('token_quota_override', sa.Integer(), nullable=True))
    op.create_check_constraint(
        'ck_groups_max_active_chats_override_nonneg', 'groups',
        'max_active_chats_override IS NULL OR max_active_chats_override >= 0',
    )
    op.create_check_constraint(
        'ck_groups_token_quota_override_nonneg', 'groups',
        'token_quota_override IS NULL OR token_quota_override >= 0',
    )

    op.add_column('users', sa.Column('max_active_chats_override', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('token_quota_override', sa.Integer(), nullable=True))
    op.create_check_constraint(
        'ck_users_max_active_chats_override_nonneg', 'users',
        'max_active_chats_override IS NULL OR max_active_chats_override >= 0',
    )
    op.create_check_constraint(
        'ck_users_token_quota_override_nonneg', 'users',
        'token_quota_override IS NULL OR token_quota_override >= 0',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_users_token_quota_override_nonneg', 'users', type_='check')
    op.drop_constraint('ck_users_max_active_chats_override_nonneg', 'users', type_='check')
    op.drop_column('users', 'token_quota_override')
    op.drop_column('users', 'max_active_chats_override')

    op.drop_constraint('ck_groups_token_quota_override_nonneg', 'groups', type_='check')
    op.drop_constraint('ck_groups_max_active_chats_override_nonneg', 'groups', type_='check')
    op.drop_column('groups', 'token_quota_override')
    op.drop_column('groups', 'max_active_chats_override')

    op.drop_index('ix_quota_reservations_user_id', table_name='quota_reservations')
    op.drop_table('quota_reservations')
