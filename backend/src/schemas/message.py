"""Pydantic schemas for message send/edit/regenerate/history endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.models.enums import MessageRole


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    stream: bool = False


class EditMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    stream: bool = False


class RegenerateMessageRequest(BaseModel):
    stream: bool = False


class MessageOut(BaseModel):
    id: uuid.UUID
    chat_id: uuid.UUID
    role: MessageRole
    content: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    revision: int
    revision_count: int
    root_message_id: uuid.UUID | None
    is_active: bool
    sequence_number: int
    response_time_ms: int | None
    model_key: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageExchangeResponse(BaseModel):
    """Returned by the non-streaming send/edit/regenerate endpoints: both
    halves of the exchange, since sending a prompt or regenerating
    always produces/updates an assistant reply. `assistant_message` is
    only None when editing a prompt that had no paired reply yet."""

    user_message: MessageOut | None = None
    assistant_message: MessageOut | None = None


class MessageRevisionsResponse(BaseModel):
    revisions: list[MessageOut]
    active_message_id: uuid.UUID


class ChatHistoryResponse(BaseModel):
    chat_id: uuid.UUID
    messages: list[MessageOut]


class StreamEventOut(BaseModel):
    """Wire shape for every SSE `data:` line on a streaming endpoint —
    the "common streaming format" every provider's output is translated
    into (see src.model_layer.schemas.StreamingChunk, ADR 0008/0009)."""

    delta: str
    is_final: bool = False
    finish_reason: Literal["stop", "length", "error"] | None = None
    message_id: uuid.UUID | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
