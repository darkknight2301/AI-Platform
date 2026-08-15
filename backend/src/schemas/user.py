"""Pydantic schemas for user management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from src.models.enums import Role, UserStatus


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
