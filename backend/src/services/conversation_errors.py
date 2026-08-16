"""Service-layer error types for chat/message business logic."""
from __future__ import annotations


class ChatNotFoundError(Exception):
    """No chat exists with the given id."""


class ChatAccessDeniedError(Exception):
    """The chat exists but the requester does not own it.

    Ownership is strict: only the chat's own user may read or act on
    it. There is deliberately no Owner/Manager override — see ADR 0009.
    Routers map this to 403, and `ChatNotFoundError` to 404 — kept as
    distinct exception types (not the same "not found" for both) so
    tests and callers can tell the difference even though both often
    render as an opaque error to the end user.
    """


class MessageNotFoundError(Exception):
    """No message exists with the given id."""


class InvalidMessageOperationError(Exception):
    """The requested operation isn't valid for this message's current
    state (e.g. editing a non-user message, or a non-active revision)."""


class ModelNotConfiguredError(Exception):
    """The requested model_key does not exist or is not enabled in the
    `models` table (see Phase 2/3's AIModel) — distinct from the model
    layer's own `ModelNotFoundError`/`ModelUnavailableError`, which are
    about the runtime provider registry, not this administrative
    configuration check."""
