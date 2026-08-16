"""seed initial qwen models

Revision ID: bdeda3f7a191
Revises: bcacac32a666
Create Date: 2026-08-16 00:41:56.958100

Seeds the `models` table with the two Phase 5 initial models. This is
descriptive/admin-visible metadata only — it does NOT configure how
the application actually talks to a Qwen backend at runtime (that's
entirely environment-variable driven, see `.env.example` and
`src/model_layer/providers/qwen/config.py`). `is_enabled=True` here
reflects "an Owner has configured this model to exist"; whether a
request to it actually succeeds depends on whether a real inference
server is reachable, which is a separate, runtime concern (see
`ModelRegistry.check_availability` / `ModelProvider.health_check`).

`model_key` values here MUST stay in sync with
`QWEN_CODER_MODEL_KEY` / `QWEN_NLP_MODEL_KEY` in
`src/model_layer/bootstrap.py` — see ADR 0008.
"""
import uuid
from datetime import datetime, UTC
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bdeda3f7a191'
down_revision: Union[str, Sequence[str], None] = 'bcacac32a666'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QWEN_CODER_ID = uuid.UUID("b9187490-3b71-40d3-b329-2464584fa35b")
QWEN_NLP_ID = uuid.UUID("1b9a059d-1ecb-43b8-bda3-6006425325c8")


def upgrade() -> None:
    """Upgrade schema."""
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
                "id": QWEN_CODER_ID,
                "model_key": "qwen2.5-coder-7b",
                "display_name": "Qwen 2.5 Coder 7B",
                "category": "CODER",
                "provider": "qwen",
                "version": "2.5-coder-7b-instruct",
                "is_enabled": True,
                "capabilities": ["streaming"],
                "config_metadata": {
                    "note": (
                        "Runtime endpoint/path/temperature/hardware config is supplied "
                        "via QWEN_CODER_* environment variables, not this row."
                    )
                },
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": QWEN_NLP_ID,
                "model_key": "qwen2.5-nlp-instruct-7b",
                "display_name": "Qwen 2.5 NLP/Instruct 7B",
                "category": "NLP",
                "provider": "qwen",
                "version": "2.5-7b-instruct",
                "is_enabled": True,
                "capabilities": ["streaming"],
                "config_metadata": {
                    "note": (
                        "Runtime endpoint/path/temperature/hardware config is supplied "
                        "via QWEN_NLP_* environment variables, not this row."
                    )
                },
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DELETE FROM models WHERE model_key IN "
        "('qwen2.5-coder-7b', 'qwen2.5-nlp-instruct-7b')"
    )
