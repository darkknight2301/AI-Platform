"""
`ModelRegistry`: the single source of truth for which providers exist,
whether each is enabled, and what it can do.

This is what "avoid hardcoding model selection throughout the code"
means in practice: nothing above this module ever writes
`if model_key == "qwen-coder"` — code asks the registry for a provider
by key (or asks the router, which asks the registry) and the registry
answers from data it was given via `register()`, not from a hardcoded
mapping baked into application logic.

The registry is intentionally in-memory and process-local. It is NOT
the `models` database table (`src.models.ai_model.AIModel`) — that
table is the durable, admin-editable record of which models an Owner
has configured (see Phase 2/3); this registry is the runtime index a
process builds (typically at startup) mapping each configured model's
key to a live `ModelProvider` instance. Keeping them separate means
the persistence layer has no dependency on any provider SDK/runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.model_layer.provider_interface import ModelProvider
from src.model_layer.schemas import ModelCapabilities
from src.models.enums import ModelCategory


class ModelNotFoundError(KeyError):
    """Raised when a requested model_key has never been registered."""


@dataclass(frozen=True)
class ModelRegistration:
    model_key: str
    provider: ModelProvider
    category: ModelCategory
    enabled: bool = True
    metadata: dict = field(default_factory=dict)

    @property
    def capabilities(self) -> ModelCapabilities:
        return self.provider.capabilities


class ModelRegistry:
    """In-memory registry of model_key -> provider.

    Not a singleton by design — tests construct their own instance so
    registrations from one test can't leak into another. A single
    shared instance for the running application is wired up wherever
    the app composes its dependencies (a later phase, once a real
    provider exists to register).
    """

    def __init__(self) -> None:
        self._registrations: dict[str, ModelRegistration] = {}

    def register(
        self,
        *,
        model_key: str,
        provider: ModelProvider,
        category: ModelCategory,
        enabled: bool = True,
        metadata: dict | None = None,
    ) -> ModelRegistration:
        if model_key in self._registrations:
            raise ValueError(f"Model '{model_key}' is already registered.")
        registration = ModelRegistration(
            model_key=model_key,
            provider=provider,
            category=category,
            enabled=enabled,
            metadata=metadata or {},
        )
        self._registrations[model_key] = registration
        return registration

    def unregister(self, model_key: str) -> None:
        self._registrations.pop(model_key, None)

    def enable(self, model_key: str) -> None:
        self._set_enabled(model_key, True)

    def disable(self, model_key: str) -> None:
        self._set_enabled(model_key, False)

    def _set_enabled(self, model_key: str, enabled: bool) -> None:
        current = self._get_or_raise(model_key)
        # ModelRegistration is frozen (immutable) so external code
        # can't mutate a registration behind the registry's back;
        # enabling/disabling goes through this one method instead.
        self._registrations[model_key] = ModelRegistration(
            model_key=current.model_key,
            provider=current.provider,
            category=current.category,
            enabled=enabled,
            metadata=current.metadata,
        )

    def get(self, model_key: str) -> ModelRegistration:
        return self._get_or_raise(model_key)

    def list_models(
        self, *, category: ModelCategory | None = None, enabled_only: bool = False
    ) -> list[ModelRegistration]:
        results = list(self._registrations.values())
        if category is not None:
            results = [r for r in results if r.category == category]
        if enabled_only:
            results = [r for r in results if r.enabled]
        return results

    async def check_availability(self, model_key: str) -> bool:
        """Whether `model_key` is enabled AND its provider reports healthy."""
        registration = self._get_or_raise(model_key)
        if not registration.enabled:
            return False
        return await registration.provider.health_check()

    def get_capabilities(self, model_key: str) -> ModelCapabilities:
        return self._get_or_raise(model_key).capabilities

    def _get_or_raise(self, model_key: str) -> ModelRegistration:
        try:
            return self._registrations[model_key]
        except KeyError as exc:
            raise ModelNotFoundError(model_key) from exc
