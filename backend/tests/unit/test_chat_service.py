"""
Phase 4 acceptance test: the chat service processes a request through
a mock provider without knowing anything about that provider's
implementation.

`ChatService` is constructed with only a `ModelRouter` — never a
`MockProvider` reference — so these tests are the concrete proof of
"the chat service should communicate with the mock provider without
knowing its implementation."
"""
from __future__ import annotations

import pytest

from src.model_layer.providers.mock_provider import MockProvider
from src.model_layer.registry import ModelRegistry
from src.model_layer.router import ModelRouter, ModelUnavailableError
from src.model_layer.schemas import ModelMessage, ModelRequest
from src.models.enums import ModelCategory
from src.services.chat_service import ChatService


def _build_chat_service(*, model_key: str = "mock-coder-1", enabled: bool = True) -> ChatService:
    registry = ModelRegistry()
    registry.register(
        model_key=model_key,
        provider=MockProvider(category=ModelCategory.CODER),
        category=ModelCategory.CODER,
        enabled=enabled,
    )
    router = ModelRouter(registry)
    return ChatService(router)


@pytest.mark.asyncio
async def test_chat_service_completes_via_mock_provider():
    chat_service = _build_chat_service()
    request = ModelRequest(
        model_key="mock-coder-1",
        messages=[ModelMessage(role="user", content="write a haiku about testing")],
    )

    response = await chat_service.complete(request)

    assert response.model_key == "mock-coder-1"
    assert "write a haiku about testing" in response.content
    assert response.usage.total_tokens > 0


@pytest.mark.asyncio
async def test_chat_service_streams_via_mock_provider():
    chat_service = _build_chat_service()
    request = ModelRequest(
        model_key="mock-coder-1",
        messages=[ModelMessage(role="user", content="stream this")],
        stream=True,
    )

    chunks = [c async for c in chat_service.stream(request)]
    assert chunks[-1].is_final is True
    assert "".join(c.delta for c in chunks).strip().endswith("stream this")


@pytest.mark.asyncio
async def test_chat_service_propagates_unavailable_model():
    chat_service = _build_chat_service(enabled=False)
    request = ModelRequest(
        model_key="mock-coder-1",
        messages=[ModelMessage(role="user", content="hi")],
    )
    with pytest.raises(ModelUnavailableError):
        await chat_service.complete(request)


@pytest.mark.asyncio
async def test_chat_service_switching_providers_requires_no_service_change():
    """Registering a second, differently-configured mock provider under a
    new key and routing to it needs zero changes to ChatService — the
    concrete proof of 'adding a new provider requires localized changes'."""
    registry = ModelRegistry()
    registry.register(
        model_key="provider-a",
        provider=MockProvider(category=ModelCategory.CODER, canned_response="from A"),
        category=ModelCategory.CODER,
    )
    registry.register(
        model_key="provider-b",
        provider=MockProvider(category=ModelCategory.NLP, canned_response="from B"),
        category=ModelCategory.NLP,
    )
    chat_service = ChatService(ModelRouter(registry))

    resp_a = await chat_service.complete(
        ModelRequest(model_key="provider-a", messages=[ModelMessage(role="user", content="x")])
    )
    resp_b = await chat_service.complete(
        ModelRequest(model_key="provider-b", messages=[ModelMessage(role="user", content="x")])
    )

    assert resp_a.content == "from A"
    assert resp_b.content == "from B"
