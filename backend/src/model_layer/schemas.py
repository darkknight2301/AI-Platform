"""
Model-layer domain schemas.

These are the ONLY objects that cross the boundary between the chat
system and a model provider (see `provider_interface.py`). Nothing
above the `ModelRouter` should ever construct or depend on a
provider-specific request/response shape — that is precisely what
keeps adding a new provider a localized change (see ADR 0007).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.models.enums import ModelCategory


class ModelMessage(BaseModel):
    """One turn of conversational input, provider-agnostic.

    Deliberately mirrors `MessageRole` values as plain strings rather
    than importing `src.models.MessageRole` directly, so the model
    layer has no compile-time dependency on the persistence schema —
    the chat service is responsible for translating between the two.
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ModelRequest(BaseModel):
    """A provider-agnostic request to generate a completion.

    `model_key` identifies which registered model should handle this
    request (see `ModelRegistry`) — the request itself carries no
    provider-specific fields. `options` is an open bag for
    provider-specific tuning (temperature, top_p, etc.) that a
    provider may interpret as it sees fit; the chat service never
    needs to know which options a given provider supports.
    """

    model_key: str
    messages: list[ModelMessage]
    max_output_tokens: int | None = None
    stream: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ModelResponse(BaseModel):
    """A complete (non-streamed) provider response."""

    model_key: str
    content: str
    usage: TokenUsage
    finish_reason: Literal["stop", "length", "error"] = "stop"
    raw_provider_metadata: dict[str, Any] = Field(default_factory=dict)


class StreamingChunk(BaseModel):
    """One increment of a streamed response.

    `usage` and a terminal `finish_reason` are only populated on the
    final chunk (`is_final=True`) — mirrors how most streaming model
    APIs report usage only once generation completes.
    """

    model_key: str
    delta: str
    is_final: bool = False
    finish_reason: Literal["stop", "length", "error"] | None = None
    usage: TokenUsage | None = None


class ModelCapabilities(BaseModel):
    """What a given provider/model can do — read by the registry and,
    eventually, by the chat service to decide what's offerable to a
    user without hardcoding per-model behavior in application code.
    """

    category: ModelCategory
    streaming: bool = False
    function_calling: bool = False
    max_context_tokens: int | None = None
    supports_system_prompt: bool = True
