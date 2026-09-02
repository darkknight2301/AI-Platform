"""add agent support (agent_key columns, AGENT category, ila-agent row)

Revision ID: f3a9c1d7e2b4
Revises: 86422d485a64
Create Date: 2026-09-02 00:00:00.000000

Adds the schema pieces ADR 0012 (ILA agent integration) needs:
  - `chats.agent_key` / `usage_records.agent_key` — nullable, NULL for
    every existing row and every ordinary model-backed chat going
    forward (see src/models/chat.py, src/models/usage.py).
  - "AGENT" added to the model_category CHECK constraint (the column
    is a portable VARCHAR+CHECK enum, not a native Postgres ENUM type
    — see src/models/_types.py's enum_column — so this is a plain
    constraint swap, not ALTER TYPE ... ADD VALUE).
  - One placeholder `models` row (model_key="ila-agent") purely so
    Chat.model_id/Usage.model_id's existing NOT NULL FK never has to
    change. This row is intentionally never registered in
    ModelRegistry — see src/agent_layer/bootstrap.py.

Reversible: downgrade drops the columns/row and restores the original
CHECK constraint.
"""
import uuid
from datetime import UTC, datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a9c1d7e2b4'
down_revision: Union[str, Sequence[str], None] = '86422d485a64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ILA_AGENT_MODEL_ID = uuid.UUID("2f1a2e0a-9b3d-4b8b-9a7f-6e2a7c1d5f10")


def upgrade() -> None:
    op.add_column('chats', sa.Column('agent_key', sa.String(length=150), nullable=True))
    op.create_index('ix_chats_agent_key', 'chats', ['agent_key'])

    op.add_column('usage_records', sa.Column('agent_key', sa.String(length=150), nullable=True))
    op.create_index('ix_usage_records_agent_key', 'usage_records', ['agent_key'])

    op.drop_constraint('model_category', 'models', type_='check')
    op.create_check_constraint(
        'model_category', 'models', "category IN ('CODER', 'NLP', 'AGENT')"
    )

    models_table = sa.table(
        "models",
        sa.column("id", sa.Uuid()),
        sa.column("model_key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("category", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("version", sa.String()),
        sa.column("is_enabled", sa.Boolean()),
        sa.column("capabilities", sa.JSON()),
        sa.column("config_metadata", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        models_table,
        [
            {
                "id": ILA_AGENT_MODEL_ID,
                "model_key": "ila-agent",
                "display_name": "ILA Agent",
                "category": "AGENT",
                "provider": "ila-agent",
                "version": "n/a",
                "is_enabled": False,
                "capabilities": ["agent"],
                "config_metadata": {
                    "note": (
                        "Placeholder row only — satisfies Chat.model_id/Usage.model_id's "
                        "FK. Never registered in ModelRegistry; actual routing is via "
                        "Chat.agent_key -> AgentRegistry, see src/agent_layer/. ADR 0012."
                    )
                },
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM models WHERE model_key = 'ila-agent'")

    op.drop_constraint('model_category', 'models', type_='check')
    op.create_check_constraint(
        'model_category', 'models', "category IN ('CODER', 'NLP')"
    )

    op.drop_index('ix_usage_records_agent_key', table_name='usage_records')
    op.drop_column('usage_records', 'agent_key')

    op.drop_index('ix_chats_agent_key', table_name='chats')
    op.drop_column('chats', 'agent_key')
