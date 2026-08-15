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

from src.model_layer.provider_interface import ModelProvider
from src.model_layer.registry import ModelNotFoundError, ModelRegistry
from src.models.enums import ModelCategory


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
    """

    def __init__(self, registry: ModelRegistry) -> None:
        self._registry = registry

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
