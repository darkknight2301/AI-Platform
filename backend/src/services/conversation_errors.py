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


class ChatLimitExceededError(Exception):
    """The requester already has the maximum number of active chats
    allowed by their effective limit (user override > group override >
    global default — see ADR 0010). Never triggers deletion of any
    existing chat; the caller must archive/delete one first, or an
    Owner must raise their limit."""

    def __init__(self, *, limit: int, current: int) -> None:
        super().__init__(f"Active chat limit reached ({current}/{limit}).")
        self.limit = limit
        self.current = current


class TokenQuotaExceededError(Exception):
    """The requester's effective token quota (for the current renewal
    window) has no room left for even a conservative reservation. See
    ADR 0010 for the renewal policy and reservation mechanism."""

    def __init__(self, *, quota: int, used: int) -> None:
        super().__init__(f"Token quota exceeded ({used}/{quota}).")
        self.quota = quota
        self.used = used
