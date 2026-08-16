"""add message revision tracking

Revision ID: d75afe937669
Revises: bdeda3f7a191
Create Date: 2026-08-16 05:47:30.272611

Adds Phase 6's revision-tracking columns to `messages`:
`root_message_id`, `is_active`, `sequence_number`, `response_time_ms`,
`model_id`. See the module docstring in `src/models/message.py` for
the full revision model these support.

(Autogenerate also proposed dropping/recreating every enum-backed
CHECK constraint — the same reflected-vs-named-constraint
false-positive noted in prior migrations — removed by hand; no enum
constraints actually changed here.)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd75afe937669'
down_revision: Union[str, Sequence[str], None] = 'bdeda3f7a191'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('root_message_id', sa.Uuid(), nullable=True))
    op.add_column('messages', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('messages', sa.Column('sequence_number', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('messages', sa.Column('response_time_ms', sa.Integer(), nullable=True))
    op.add_column('messages', sa.Column('model_id', sa.Uuid(), nullable=True))

    op.create_index('ix_messages_chat_id_active_sequence', 'messages', ['chat_id', 'is_active', 'sequence_number'], unique=False)
    op.create_index('ix_messages_model_id', 'messages', ['model_id'], unique=False)
    op.create_index('ix_messages_root_message_id', 'messages', ['root_message_id'], unique=False)

    op.create_foreign_key(
        'fk_messages_model_id_models', 'messages', 'models', ['model_id'], ['id'], ondelete='SET NULL'
    )
    op.create_foreign_key(
        'fk_messages_root_message_id_messages', 'messages', 'messages', ['root_message_id'], ['id'], ondelete='CASCADE'
    )
    op.create_check_constraint('ck_messages_sequence_number_nonneg', 'messages', 'sequence_number >= 0')

    # Columns were added with server defaults so existing rows (none
    # in a fresh environment, but keep this safe in general) get valid
    # values; drop the server defaults afterward since the ORM sets
    # values explicitly on insert going forward.
    op.alter_column('messages', 'is_active', server_default=None)
    op.alter_column('messages', 'sequence_number', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_messages_sequence_number_nonneg', 'messages', type_='check')
    op.drop_constraint('fk_messages_root_message_id_messages', 'messages', type_='foreignkey')
    op.drop_constraint('fk_messages_model_id_models', 'messages', type_='foreignkey')
    op.drop_index('ix_messages_root_message_id', table_name='messages')
    op.drop_index('ix_messages_model_id', table_name='messages')
    op.drop_index('ix_messages_chat_id_active_sequence', table_name='messages')
    op.drop_column('messages', 'model_id')
    op.drop_column('messages', 'response_time_ms')
    op.drop_column('messages', 'sequence_number')
    op.drop_column('messages', 'is_active')
    op.drop_column('messages', 'root_message_id')
