"""Pydantic schemas for authentication endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from src.models.enums import Role, UserStatus

_USERNAME_PATTERN = r"^[a-zA-Z0-9_.\-]{3,150}$"


class RegisterRequest(BaseModel):
    """Self-registration input.

    Deliberately has NO `role` field: role is never client-settable at
    registration. Every self-registered account is created with
    `Role.USER`, enforced server-side (see AuthService.register), not
    merely defaulted — there is no code path where a request body can
    influence the assigned role.

    `group_id`, if provided, only associates the pending account with
    an existing, active group for a manager of that group to review —
    it never affects role/privilege. See ADR 0006 for the full group
    assignment policy.
    """

    username: str = Field(min_length=3, max_length=150, pattern=_USERNAME_PATTERN)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    group_id: uuid.UUID | None = None

    @field_validator("password")
    @classmethod
    def _password_complexity(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Password must not have leading/trailing whitespace.")
        if value.isdigit() or value.isalpha():
            raise ValueError("Password must contain a mix of letters and numbers.")
        return value


class LoginRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserPublic(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    status: UserStatus
    role: Role
    group_id: uuid.UUID | None
    created_at: datetime
    last_login_at: datetime | None

    model_config = {"from_attributes": True}
