"""
Unit tests for the Phase 4 model abstraction layer: registry, router,
and the mock provider. No database or HTTP layer involved — this is
pure in-process object composition.
"""
from __future__ import annotations

import asyncio

import pytest

from src.model_layer.provider_interface import ModelProvider
from src.model_layer.providers.mock_provider import MockProvider
from src.model_layer.registry import ModelNotFoundError, ModelRegistry
from src.model_layer.router import (
    ModelRouter,
    ModelUnavailableError,
    NoProviderForCategoryError,
)
from src.model_layer.schemas import ModelMessage, ModelRequest
from src.models.enums import ModelCategory


def _request(model_key: str = "mock-coder-1", content: str = "hello there") -> ModelRequest:
    return ModelRequest(
        model_key=model_key,
        messages=[ModelMessage(role="user", content=content)],
    )


# --- Registry -----------------------------------------------------------

def test_register_and_get():
    registry = ModelRegistry()
    provider = MockProvider(category=ModelCategory.CODER)
    registry.register(model_key="mock-coder-1", provider=provider, category=ModelCategory.CODER)

    registration = registry.get("mock-coder-1")
    assert registration.model_key == "mock-coder-1"
    assert registration.provider is provider
    assert registration.enabled is True


def test_register_duplicate_key_rejected():
    registry = ModelRegistry()
    registry.register(
        model_key="dup",
        provider=MockProvider(category=ModelCategory.NLP),
        category=ModelCategory.NLP,
    )
    with pytest.raises(ValueError):
        registry.register(
            model_key="dup",
            provider=MockProvider(category=ModelCategory.NLP),
            category=ModelCategory.NLP,
        )


def test_get_unknown_model_raises():
    registry = ModelRegistry()
    with pytest.raises(ModelNotFoundError):
        registry.get("does-not-exist")


def test_enable_disable():
    registry = ModelRegistry()
    registry.register(
        model_key="togglable",
        provider=MockProvider(category=ModelCategory.CODER),
        category=ModelCategory.CODER,
        enabled=True,
    )
    registry.disable("togglable")
    assert registry.get("togglable").enabled is False

    registry.enable("togglable")
    assert registry.get("togglable").enabled is True


def test_list_models_filters_by_category_and_enabled():
    registry = ModelRegistry()
    registry.register(
        model_key="coder-1",
        provider=MockProvider(category=ModelCategory.CODER),
        category=ModelCategory.CODER,
    )
    registry.register(
        model_key="nlp-1",
        provider=MockProvider(category=ModelCategory.NLP),
        category=ModelCategory.NLP,
        enabled=False,
    )

    assert {m.model_key for m in registry.list_models()} == {"coder-1", "nlp-1"}
    assert {m.model_key for m in registry.list_models(category=ModelCategory.CODER)} == {"coder-1"}
    assert {m.model_key for m in registry.list_models(enabled_only=True)} == {"coder-1"}


@pytest.mark.asyncio
async def test_check_availability_respects_enabled_flag():
    registry = ModelRegistry()
    registry.register(
        model_key="avail-test",
        provider=MockProvider(category=ModelCategory.CODER),
        category=ModelCategory.CODER,
        enabled=False,
    )
    assert await registry.check_availability("avail-test") is False

    registry.enable("avail-test")
    assert await registry.check_availability("avail-test") is True


def test_get_capabilities_reads_from_provider():
    registry = ModelRegistry()
    registry.register(
        model_key="cap-test",
        provider=MockProvider(category=ModelCategory.NLP, streaming=True),
        category=ModelCategory.NLP,
    )
    caps = registry.get_capabilities("cap-test")
    assert caps.category == ModelCategory.NLP
    assert caps.streaming is True


# --- Router ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_router_resolves_provider_by_key():
    registry = ModelRegistry()
    provider = MockProvider(category=ModelCategory.CODER)
    registry.register(model_key="r-1", provider=provider, category=ModelCategory.CODER)
    router = ModelRouter(registry)

    resolved = await router.route("r-1")
    assert resolved is provider


@pytest.mark.asyncio
async def test_router_raises_for_unknown_model():
    router = ModelRouter(ModelRegistry())
    with pytest.raises(ModelNotFoundError):
        await router.route("nope")


@pytest.mark.asyncio
async def test_router_raises_for_disabled_model():
    registry = ModelRegistry()
    registry.register(
        model_key="disabled-1",
        provider=MockProvider(category=ModelCategory.CODER),
        category=ModelCategory.CODER,
        enabled=False,
    )
    router = ModelRouter(registry)
    with pytest.raises(ModelUnavailableError):
        await router.route("disabled-1")


@pytest.mark.asyncio
async def test_router_route_by_category_picks_enabled_provider():
    registry = ModelRegistry()
    disabled_provider = MockProvider(category=ModelCategory.NLP)
    enabled_provider = MockProvider(category=ModelCategory.NLP)
    registry.register(
        model_key="nlp-disabled", provider=disabled_provider,
        category=ModelCategory.NLP, enabled=False,
    )
    registry.register(
        model_key="nlp-enabled", provider=enabled_provider, category=ModelCategory.NLP
    )
    router = ModelRouter(registry)

    resolved = await router.route_by_category(ModelCategory.NLP)
    assert resolved is enabled_provider


@pytest.mark.asyncio
async def test_router_route_by_category_raises_when_none_available():
    router = ModelRouter(ModelRegistry())
    with pytest.raises(NoProviderForCategoryError):
        await router.route_by_category(ModelCategory.CODER)


# --- Mock provider ----------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_provider_generate_echoes_and_reports_usage():
    provider = MockProvider(category=ModelCategory.CODER)
    response = await provider.generate(_request(content="print hello world"))

    assert "print hello world" in response.content
    assert response.usage.total_tokens == response.usage.input_tokens + response.usage.output_tokens
    assert response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_mock_provider_stream_yields_chunks_then_final_usage():
    provider = MockProvider(category=ModelCategory.NLP)
    chunks = [c async for c in provider.stream(_request(content="a b c"))]

    assert len(chunks) >= 2
    assert all(not c.is_final for c in chunks[:-1])
    assert chunks[-1].is_final is True
    assert chunks[-1].usage is not None
    assert chunks[-1].finish_reason == "stop"

    reconstructed = "".join(c.delta for c in chunks)
    assert "a b c" in reconstructed


@pytest.mark.asyncio
async def test_mock_provider_canned_response_used_verbatim():
    provider = MockProvider(category=ModelCategory.CODER, canned_response="42")
    response = await provider.generate(_request())
    assert response.content == "42"


@pytest.mark.asyncio
async def test_mock_provider_health_check_true():
    provider = MockProvider(category=ModelCategory.CODER)
    assert await provider.health_check() is True


def test_mock_provider_satisfies_provider_interface():
    provider = MockProvider(category=ModelCategory.CODER)
    assert isinstance(provider, ModelProvider)


# --- Phase 11: per-model concurrency (queueing) --------------------------

@pytest.mark.asyncio
async def test_acquire_slot_bounds_concurrency(monkeypatch):
    """With a limit of 1, a second acquire for the same model_key must
    block until the first is released — proving requests queue at the
    router seam rather than all running unbounded."""
    from src.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MODEL_MAX_CONCURRENT_REQUESTS_PER_MODEL", "1")
    try:
        registry = ModelRegistry()
        registry.register(
            model_key="mock-coder-1",
            provider=MockProvider(category=ModelCategory.CODER),
            category=ModelCategory.CODER,
        )
        router = ModelRouter(registry)

        in_flight = 0
        max_in_flight = 0

        async def _hold_slot(duration: float):
            nonlocal in_flight, max_in_flight
            async with router.acquire_slot("mock-coder-1"):
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                await asyncio.sleep(duration)
                in_flight -= 1

        await asyncio.gather(_hold_slot(0.05), _hold_slot(0.05))
        assert max_in_flight == 1
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_acquire_slot_allows_configured_concurrency(monkeypatch):
    from src.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MODEL_MAX_CONCURRENT_REQUESTS_PER_MODEL", "2")
    try:
        registry = ModelRegistry()
        registry.register(
            model_key="mock-coder-1",
            provider=MockProvider(category=ModelCategory.CODER),
            category=ModelCategory.CODER,
        )
        router = ModelRouter(registry)

        in_flight = 0
        max_in_flight = 0

        async def _hold_slot(duration: float):
            nonlocal in_flight, max_in_flight
            async with router.acquire_slot("mock-coder-1"):
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                await asyncio.sleep(duration)
                in_flight -= 1

        await asyncio.gather(_hold_slot(0.05), _hold_slot(0.05))
        assert max_in_flight == 2
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_different_model_keys_have_independent_slots(monkeypatch):
    from src.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MODEL_MAX_CONCURRENT_REQUESTS_PER_MODEL", "1")
    try:
        registry = ModelRegistry()
        registry.register(
            model_key="mock-coder-1",
            provider=MockProvider(category=ModelCategory.CODER),
            category=ModelCategory.CODER,
        )
        registry.register(
            model_key="mock-nlp-1",
            provider=MockProvider(category=ModelCategory.NLP),
            category=ModelCategory.NLP,
        )
        router = ModelRouter(registry)

        async def _hold(model_key: str, duration: float):
            async with router.acquire_slot(model_key):
                await asyncio.sleep(duration)

        # Should complete quickly since the two model_keys don't share a
        # slot — if they incorrectly did, this would take ~2x as long.
        start = asyncio.get_event_loop().time()
        await asyncio.gather(_hold("mock-coder-1", 0.05), _hold("mock-nlp-1", 0.05))
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 0.09
    finally:
        get_settings.cache_clear()
