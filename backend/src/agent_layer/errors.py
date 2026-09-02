"""
Agent-layer error hierarchy — same role `model_layer/errors.py` plays
for providers: every concrete adapter maps its own failures onto
these before they cross the `AgentAdapter` boundary, so
`ConversationService` only ever catches one generic type. See ADR
0012.
"""
from __future__ import annotations


class AgentError(Exception):
    """Base class for all agent-layer failures."""

    default_safe_message = "The agent encountered an error. Please try again."

    def __init__(self, message: str | None = None, *, safe_message: str | None = None) -> None:
        super().__init__(message or self.default_safe_message)
        self.safe_message = safe_message or self.default_safe_message


class AgentConfigurationError(AgentError):
    """The agent is misconfigured (e.g. ILA_MODULE_PATH doesn't resolve)."""

    default_safe_message = "This agent is not currently available."


class AgentExecutionError(AgentError):
    """The agent's own code raised while producing a result."""

    default_safe_message = "The agent could not complete this request."


class AgentTimeoutError(AgentError):
    """The agent did not finish within its configured timeout."""

    default_safe_message = "The agent took too long to respond. Please try again."
