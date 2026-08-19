"""Pydantic schemas for user management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.models.enums import GroupStatus, Role, UserStatus


class GroupSummary(BaseModel):
    """Minimal group info visible to a Manager of that group (or an
    Owner). Deliberately excludes the quota/chat-limit override fields
    on `GroupOut` (schemas/admin.py) — those are Owner-only configuration,
    not something a Manager needs to see to run their group's dashboard.
    """

    id: uuid.UUID
    name: str
    status: GroupStatus

    model_config = {"from_attributes": True}


class UserSummary(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    status: UserStatus
    role: Role
    group_id: uuid.UUID | None
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserSummary]
    total: int


class ApprovalActionResponse(BaseModel):
    id: uuid.UUID
    status: UserStatus
    detail: str
