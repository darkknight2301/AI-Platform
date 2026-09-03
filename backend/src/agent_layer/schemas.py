"""
Agent-layer domain schemas — the only objects that cross the boundary
between `ConversationService` and an `AgentAdapter` (see
`agent_interface.py`). Deliberately not reusing `model_layer.schemas`'s
`ModelRequest`/`ModelResponse` — an agent's inputs/outputs aren't
provider-shaped (see ADR 0012's reasoning for why ILA isn't a
`ModelProvider`).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.model_layer.schemas import ModelMessage, TokenUsage


class ILAGenerateParams(BaseModel):
    """Exact positional parameters `ILA.generate()` requires (see
    `backend/src/ila/`), minus `query` (that's `SendMessageRequest.content`,
    already collected) and `output_file` is included here since it's
    per-call, not per-agent config. No defaults on `mode`/`function_name`/
    `step`/`output_file` — ILA's signature has none either, and this
    platform doesn't invent any (see ila_adapter.py's docstring)."""

    mode: str
    function_name: str
    step: str
    test_case_desc: str = ""
    overwrite_step: bool = False
    output_file: str


class AgentRequest(BaseModel):
    """One agent invocation.

    `history` is the same active-thread context
    `ConversationService._to_model_messages` already builds for a
    normal model call — reused as-is so an agent has the same
    conversational context a model would, without a second history
    representation.
    """

    agent_key: str
    query: str
    history: list[ModelMessage] = Field(default_factory=list)
    # Populated only for agents whose call signature needs structured
    # params beyond `query` — currently just ILA. None for any agent
    # that doesn't need this (e.g. FakeAgentAdapter).
    ila_params: ILAGenerateParams | None = None
    # Opaque, per-user/session identifiers an adapter may want (e.g.
    # to scope a workspace) — never assumed to mean anything specific
    # by AgentRegistry/ConversationService.
    context: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """A complete (non-streamed) agent result.

    `usage` defaults to zero — an agent that made no model calls (or
    doesn't report usage) legitimately consumed no quota-relevant
    tokens; one that does call models should populate this from
    whatever those calls actually cost.
    """

    agent_key: str
    output: str
    usage: TokenUsage = Field(default_factory=lambda: TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0))
    workspace_id: str | None = None
    finish_reason: str = "stop"
    # Whatever the underlying agent actually returned, kept verbatim
    # for debugging/future use — never assumed to have any particular
    # shape (see ila_adapter.py's `_coerce_output`).
    raw_output: Any = None
