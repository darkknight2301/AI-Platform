"""
The `ModelProvider` interface: the single contract every concrete
provider (mock, or a future Qwen/other backend) must implement.

Nothing outside `src/model_layer/providers/` should ever import a
concrete provider class directly — everything above this interface
(`ModelRouter`, `ChatService`, etc.) depends only on `ModelProvider`.
This is what "adding a new provider should require localized changes"
(Phase 4 acceptance criterion) actually means in code: a new provider
is a new file implementing this ABC, plus one registration call — no
changes to the router, registry interface, or chat service.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from src.model_layer.schemas import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    StreamingChunk,
)


class ModelProvider(ABC):
    """Abstract base class for all model backends.

    A provider is stateless from the caller's perspective: all
    per-request context comes in via `ModelRequest`. Implementations
    may hold their own internal state (an HTTP client, a loaded model
    handle, etc.) but must not depend on anything from the persistence
    layer (`src.models`) or the web layer (`src.api`) — that
    dependency direction is exactly what the model layer exists to
    prevent.
    """

    @property
    @abstractmethod
    def capabilities(self) -> ModelCapabilities:
        """Static capability description for this provider instance."""

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Produce a complete response for `request`."""

    @abstractmethod
    def stream(self, request: ModelRequest) -> AsyncIterator[StreamingChunk]:
        """Produce a response as a stream of `StreamingChunk`s.

        Implementations that don't support streaming should still
        implement this (e.g. by yielding the full response as a
        single final chunk) rather than raising, so callers can treat
        every provider uniformly; `capabilities.streaming` tells a
        caller whether true incremental streaming is available.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Whether this provider is currently reachable/usable.

        Distinct from the registry's `enabled` flag: `enabled` is an
        administrative decision (see `ModelRegistry`), `health_check`
        is the provider's own live-status signal (e.g. can it reach
        its backend right now). The registry's `check_availability`
        considers both.
        """
