"""Pydantic schemas for Owner-only administrative endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.models.enums import (
    AuditResult,
    GroupStatus,
    ModelCategory,
    Role,
    UserStatus,
)


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    status: GroupStatus = GroupStatus.ACTIVE


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    status: GroupStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class UserAdminUpdate(BaseModel):
    """Owner-only update to a user's role/status/group.

    All fields optional; only provided fields are changed. This is the
    one place role or group can be changed after registration — never
    directly by the affected user.
    """

    role: Role | None = None
    status: UserStatus | None = None
    group_id: uuid.UUID | None = None


class ModelCreate(BaseModel):
    model_key: str = Field(min_length=1, max_length=150)
    display_name: str = Field(min_length=1, max_length=255)
    category: ModelCategory
    provider: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    is_enabled: bool = True
    capabilities: list[str] = Field(default_factory=list)
    config_metadata: dict[str, Any] = Field(default_factory=dict)


class ModelUpdate(BaseModel):
    display_name: str | None = None
    is_enabled: bool | None = None
    capabilities: list[str] | None = None
    config_metadata: dict[str, Any] | None = None


class ModelOut(BaseModel):
    id: uuid.UUID
    model_key: str
    display_name: str
    category: ModelCategory
    provider: str
    version: str
    is_enabled: bool
    capabilities: list[str]
    config_metadata: dict[str, Any]

    model_config = {"from_attributes": True}


class AuditLogOut(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    timestamp: datetime
    request_id: str | None
    result: AuditResult
    audit_metadata: dict[str, Any]

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    entries: list[AuditLogOut]
    total: int


class GlobalConfigOut(BaseModel):
    """Non-secret configuration visible to Owners.

    Never includes `secret_key` or any credential/connection-string
    value — see SECURITY.md.
    """

    app_name: str
    environment: str
    rate_limit_requests_per_minute: int
    access_token_expire_minutes: int
