"""Pydantic schemas for chat CRUD endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import ChatStatus


class ChatCreateRequest(BaseModel):
    model_key: str = Field(min_length=1, max_length=150)
    title: str | None = Field(default=None, max_length=500)


class ChatUpdateRequest(BaseModel):
    """All fields optional; only provided fields are changed."""

    title: str | None = Field(default=None, max_length=500)
    status: ChatStatus | None = None
    model_key: str | None = Field(default=None, min_length=1, max_length=150)


class ChatSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: ChatStatus
    model_id: uuid.UUID
    model_key: str
    revision: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatListResponse(BaseModel):
    chats: list[ChatSummary]
    total: int
