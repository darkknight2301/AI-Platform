"""
`ModelRouter`: decides which provider handles a given request.

```text
Chat Service -> Model Router -> Model Registry -> Provider
```

The router is the only component that turns a `ModelRequest` into a
concrete `ModelProvider` call. `ChatService` depends on the router,
never on the registry or a provider directly — this is what lets the
chat system add categories or change routing policy without knowing
about any specific provider.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from src.core.config import get_settings
from src.model_layer.provider_interface import ModelProvider
from src.model_layer.registry import ModelNotFoundError, ModelRegistry
from src.models.enums import ModelCategory

logger = logging.getLogger(__name__)


class ModelUnavailableError(RuntimeError):
    """Raised when the resolved model exists but cannot currently serve requests."""


class NoProviderForCategoryError(LookupError):
    """Raised when routing by category finds no enabled provider."""


class ModelRouter:
    """Resolves a `model_key` (or a category) to a usable `ModelProvider`.

    Routing policy today is deliberately simple — exact key lookup, or
    "first enabled provider in this category" — because Phase 4's goal
    is the seam itself, not a sophisticated routing algorithm. Future
    policies (load-based, capability-based, per-user overrides) are a
    matter of changing this class's internals; callers are unaffected
    either way, since they only ever see `ModelProvider`.

    Phase 11 adds one more responsibility here: bounding how many
    requests are in flight to a given model at once
    (`MODEL_MAX_CONCURRENT_REQUESTS_PER_MODEL`). This is deliberately
    *not* a web-tier concept (it's not connection pooling, rate
    limiting, or anything in `core/middleware.py`) — it exists so a
    burst of API traffic queues at this seam instead of hammering the
    actual model backend past what it can handle. See
    `docs/PERFORMANCE.md`, "API scalability vs model inference
    scalability".
    """

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry
        self._settings = get_settings()
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def _semaphore_for(self, model_key: str) -> asyncio.Semaphore:
        sem = self._semaphores.get(model_key)
        if sem is None:
            limit = max(1, self._settings.model_max_concurrent_requests_per_model)
            sem = asyncio.Semaphore(limit)
            self._semaphores[model_key] = sem
        return sem

    @asynccontextmanager
    async def acquire_slot(self, model_key: str):
        """Async context manager: hold one of `model_key`'s concurrency
        slots for the duration of a single generate/stream call. Blocks
        (queues) if all slots are in use — that queueing *is* the
        point. Logs when a request actually had to wait, so queue
        pressure is visible in the structured logs without adding a
        dedicated metrics system."""
        sem = self._semaphore_for(model_key)
        start = time.monotonic()
        await sem.acquire()
        wait_ms = (time.monotonic() - start) * 1000
        if wait_ms > 5:
            logger.info(
                "model_request_queued",
                extra={"model_key": model_key, "queue_wait_ms": round(wait_ms, 2)},
            )
        try:
            yield
        finally:
            sem.release()

    async def route(self, model_key: str) -> ModelProvider:
        """Resolve an explicit model key to its provider.

        Raises `ModelNotFoundError` if never registered,
        `ModelUnavailableError` if registered but disabled/unhealthy.
        """
        registration = self._registry.get(model_key)  # raises ModelNotFoundError
        if not await self._registry.check_availability(model_key):
            raise ModelUnavailableError(
                f"Model '{model_key}' is registered but not currently available "
                f"(enabled={registration.enabled})."
            )
        return registration.provider

    async def route_by_category(self, category: ModelCategory) -> ModelProvider:
        """Resolve to any enabled, healthy provider in `category`.

        Used when a caller cares about capability (e.g. "give me a
        CODER model") rather than a specific model_key.
        """
        candidates = self._registry.list_models(category=category, enabled_only=True)
        for candidate in candidates:
            if await self._registry.check_availability(candidate.model_key):
                return candidate.provider
        raise NoProviderForCategoryError(
            f"No available, enabled provider for category '{category.value}'."
        )

    async def route_request(self, model_key: str) -> ModelProvider:
        """Convenience alias matching the "Chat Service -> Router" call shape."""
        return await self.route(model_key)


__all__ = [
    "ModelRouter",
    "ModelUnavailableError",
    "NoProviderForCategoryError",
    "ModelNotFoundError",
]
