"""add workspaces table (Web IDE, ADR 0012)

Revision ID: a7c4e0b91d3f
Revises: f3a9c1d7e2b4
Create Date: 2026-09-02 00:00:00.000000

One row per chat that has ever requested a workspace (unique FK on
chat_id). No credentials stored here — see src/models/workspace.py's
module docstring; ssh_username pairs with one backend-held key
referenced by WORKSPACE_SSH_KEY_PATH, never a per-row secret.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c4e0b91d3f'
down_revision: Union[str, Sequence[str], None] = 'f3a9c1d7e2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'workspaces',
        sa.Column('chat_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('ssh_port', sa.Integer(), nullable=False),
        sa.Column('ssh_username', sa.String(length=150), nullable=False),
        sa.Column('target_path', sa.String(length=1000), nullable=False),
        sa.Column('code_server_port', sa.Integer(), nullable=True),
        sa.Column(
            'status',
            sa.Enum(
                'PENDING', 'ACTIVE', 'STOPPED', 'ERROR',
                name='workspace_status', native_enum=False, create_constraint=True, length=32,
            ),
            nullable=False,
        ),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workspaces_chat_id'), 'workspaces', ['chat_id'], unique=True)
    op.create_index(op.f('ix_workspaces_user_id'), 'workspaces', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_workspaces_user_id'), table_name='workspaces')
    op.drop_index(op.f('ix_workspaces_chat_id'), table_name='workspaces')
    op.drop_table('workspaces')
