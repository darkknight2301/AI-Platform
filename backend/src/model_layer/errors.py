"""
Provider-agnostic error hierarchy for the model layer.

Every concrete provider (Qwen or otherwise) maps its own
implementation-specific failures (HTTP errors, connection issues,
malformed responses, ...) onto these exceptions before they cross the
`ModelProvider` interface boundary. `ChatService` and everything above
it only ever catches these generic types — never a provider-specific
exception class — which is exactly what keeps failure handling from
leaking a specific provider's implementation details into the chat
system.

Each exception carries a `safe_message` meant for end users (generic,
no internal details) separate from the exception's own `str()` /
logged message (which may include diagnostic detail for operators,
via the provider's own logging — see `providers/qwen/provider.py` for
an example). Callers should log `exc_info=True` and surface only
`safe_message` to users.

## Streaming interruption contract

A provider's `stream()` may raise one of these exceptions before it
has yielded any chunk (e.g. the initial connection fails) — callers
should treat that like any other pre-response failure. Once at least
one chunk has been yielded, a provider should NOT raise; instead it
should yield one final `StreamingChunk` with `is_final=True,
finish_reason="error"` and then stop, so a partially-delivered
response always ends with a well-formed terminal marker rather than an
unhandled exception mid-iteration. `ChatService.stream` additionally
guards against a provider violating this contract (see
`src/services/chat_service.py`).
"""
from __future__ import annotations


class ModelProviderError(Exception):
    """Base class for all model-provider-layer failures."""

    default_safe_message = "The model encountered an error. Please try again."

    def __init__(self, message: str, *, safe_message: str | None = None) -> None:
        super().__init__(message)
        self.safe_message = safe_message or self.default_safe_message


class ModelUnavailableProviderError(ModelProviderError):
    """The provider's backend could not be reached at all (e.g. connection
    refused, DNS failure, backend process not running)."""

    default_safe_message = "The selected model is temporarily unavailable. Please try again shortly."


class ModelTimeoutError(ModelProviderError):
    """The backend did not respond within the configured timeout."""

    default_safe_message = "The model took too long to respond. Please try again."


class InvalidModelRequestError(ModelProviderError):
    """The backend rejected the request as malformed/invalid (e.g. HTTP 400)."""

    default_safe_message = "The request could not be processed. Please adjust it and try again."


class ModelLoadingError(ModelProviderError):
    """The backend is reachable but the model isn't ready yet (e.g. still
    loading weights — commonly surfaced as HTTP 503 by inference servers)."""

    default_safe_message = "The model is still starting up. Please try again in a moment."


class ModelRuntimeError(ModelProviderError):
    """An unexpected failure during generation not covered by a more
    specific category above (backend 5xx, malformed response body, etc.)."""

    default_safe_message = "The model encountered an unexpected error. Please try again."


class ModelStreamInterruptedError(ModelProviderError):
    """A streaming response was interrupted after some content was already
    delivered. Providers should generally prefer yielding a terminal
    error chunk (see module docstring) over raising this — it exists
    for callers (e.g. `ChatService`) that need to signal the same
    condition through a non-generator code path."""

    default_safe_message = "The response was interrupted. Please try again."
