"""
Shared enum definitions used across ORM models.

Enums are stored as non-native (VARCHAR + CHECK constraint) columns
rather than native PostgreSQL ENUM types. This keeps the schema
portable (works identically against SQLite in tests) and makes future
value additions a plain data migration instead of an `ALTER TYPE`.

Role is intentionally a simple, ordered set of values rather than a
per-permission table. The application's authorization layer (a later
phase) is expected to build a single, central permission-mapping
utility on top of `Role`/`ROLE_RANK`, so individual endpoints never
need to hardcode `if role == "OWNER"`-style checks — they compare
rank or consult one shared mapping instead. No such logic is
implemented in this phase; only the data model is established.
"""
from __future__ import annotations

import enum


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING = "PENDING"


class Role(str, enum.Enum):
    USER = "USER"
    MANAGER = "MANAGER"
    DEVELOPER = "DEVELOPER"
    OWNER = "OWNER"


# Relative privilege ranking, lowest to highest. A future authorization
# layer can compare ranks (e.g. `ROLE_RANK[user.role] >= ROLE_RANK[Role.MANAGER]`)
# instead of hardcoding role-name checks throughout the application.
ROLE_RANK: dict[Role, int] = {
    Role.USER: 0,
    Role.MANAGER: 1,
    Role.DEVELOPER: 2,
    Role.OWNER: 3,
}


class GroupStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ChatStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class MessageRole(str, enum.Enum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class ModelCategory(str, enum.Enum):
    CODER = "CODER"
    NLP = "NLP"
    # Not a model — see src/agent_layer/. Used only so a chat backed by
    # an agent (e.g. ILA) can still satisfy Chat.model_id's FK via one
    # placeholder `AIModel` row (agent_layer/bootstrap.py), the same
    # way any other category does. Never registered in ModelRegistry;
    # ModelRouter/ModelProvider never see this value. See ADR 0012.
    AGENT = "AGENT"


class AuditResult(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
