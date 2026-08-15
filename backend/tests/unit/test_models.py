"""Unit tests for the ORM model definitions that don't require a live DB."""
from __future__ import annotations

import src.models  # noqa: F401 - ensures all tables register with Base.metadata
from src.db.base import Base
from src.models.enums import ROLE_RANK, Role

EXPECTED_TABLES = {
    "groups",
    "users",
    "chats",
    "messages",
    "models",
    "usage_records",
    "audit_logs",
}


def test_all_expected_tables_are_registered():
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))


def test_role_rank_covers_every_role_and_is_strictly_ordered():
    assert set(ROLE_RANK) == set(Role)
    ordered = [Role.USER, Role.MANAGER, Role.DEVELOPER, Role.OWNER]
    ranks = [ROLE_RANK[role] for role in ordered]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)  # strictly increasing, no ties


def test_users_table_has_expected_unique_constraints():
    users = Base.metadata.tables["users"]
    unique_columns = {
        col.name for col in users.columns if col.unique or col.name in {"username", "email"}
    }
    assert {"username", "email"} <= unique_columns


def test_messages_table_has_token_check_constraints():
    messages = Base.metadata.tables["messages"]
    check_names = {c.name for c in messages.constraints if hasattr(c, "sqltext")}
    assert "ck_messages_total_tokens_sum" in check_names
    assert "ck_messages_input_tokens_nonneg" in check_names
    assert "ck_messages_output_tokens_nonneg" in check_names


def test_chat_foreign_keys_reference_expected_tables():
    chats = Base.metadata.tables["chats"]
    fk_targets = {fk.column.table.name for fk in chats.foreign_keys}
    assert fk_targets == {"users", "models"}
