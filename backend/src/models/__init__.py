"""
ORM model package.

Every model module is imported here so that:
  - `Base.metadata` is fully populated for Alembic autogenerate, and
  - application code can import models from `src.models` directly.
"""
from src.models.ai_model import AIModel
from src.models.audit_log import AuditLog
from src.models.auth_session import AuthSession
from src.models.chat import Chat
from src.models.enums import (
    AuditResult,
    ChatStatus,
    GroupStatus,
    MessageRole,
    ModelCategory,
    Role,
    UserStatus,
)
from src.models.group import Group
from src.models.message import Message
from src.models.quota_reservation import QuotaReservation
from src.models.usage import Usage
from src.models.user import User

__all__ = [
    "AIModel",
    "AuditLog",
    "AuditResult",
    "AuthSession",
    "Chat",
    "ChatStatus",
    "Group",
    "GroupStatus",
    "Message",
    "MessageRole",
    "ModelCategory",
    "QuotaReservation",
    "Role",
    "Usage",
    "User",
    "UserStatus",
]
