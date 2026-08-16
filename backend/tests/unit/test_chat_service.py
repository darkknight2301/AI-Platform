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
from src.model_layer.router import ModelRouter
from src.model_layer.schemas import ModelMessage, ModelRequest
from src.models.enums import ModelCategory
from src.services.chat_service import ChatService
from src.services.errors import ChatServiceError


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
    with pytest.raises(ChatServiceError) as exc_info:
        await chat_service.complete(request)
    assert "temporarily unavailable" in str(exc_info.value)


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


@pytest.mark.asyncio
async def test_chat_service_unknown_model_raises_safe_error():
    chat_service = ChatService(ModelRouter(ModelRegistry()))
    with pytest.raises(ChatServiceError) as exc_info:
        await chat_service.complete(
            ModelRequest(model_key="ghost", messages=[ModelMessage(role="user", content="hi")])
        )
    assert "not available" in str(exc_info.value)


class _AlwaysFailsProvider:
    """Minimal ModelProvider test double that fails uniformly — used to
    prove ChatService's error handling is provider-agnostic, not
    something specific to MockProvider or QwenProvider."""

    def __init__(self, exc: Exception, *, fail_after_first_chunk: bool = False) -> None:
        self._exc = exc
        self._fail_after_first_chunk = fail_after_first_chunk

    @property
    def capabilities(self):
        from src.model_layer.schemas import ModelCapabilities

        return ModelCapabilities(category=ModelCategory.CODER, streaming=True)

    async def generate(self, request):
        raise self._exc

    async def stream(self, request):
        if self._fail_after_first_chunk:
            from src.model_layer.schemas import StreamingChunk

            yield StreamingChunk(model_key=request.model_key, delta="partial", is_final=False)
        raise self._exc

    async def health_check(self) -> bool:
        return True


def _registry_with_failing_provider(exc: Exception, **kwargs) -> ModelRegistry:
    registry = ModelRegistry()
    registry.register(
        model_key="failing-model",
        provider=_AlwaysFailsProvider(exc, **kwargs),
        category=ModelCategory.CODER,
    )
    return registry


@pytest.mark.asyncio
async def test_chat_service_wraps_generic_provider_exception_safely():
    """Even a provider that raises a totally generic (non-ModelProviderError)
    exception must never leak past ChatService — the defensive catch-all."""
    chat_service = ChatService(ModelRouter(_registry_with_failing_provider(RuntimeError("db password: hunter2"))))
    with pytest.raises(ChatServiceError) as exc_info:
        await chat_service.complete(
            ModelRequest(model_key="failing-model", messages=[ModelMessage(role="user", content="hi")])
        )
    assert "hunter2" not in str(exc_info.value)
    assert "unexpected error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_chat_service_streaming_interruption_yields_terminal_error_chunk():
    """A failure mid-stream must surface as a well-formed terminal chunk,
    not a raw exception bubbling out of the async generator."""
    chat_service = ChatService(
        ModelRouter(
            _registry_with_failing_provider(RuntimeError("boom"), fail_after_first_chunk=True)
        )
    )
    chunks = [
        c
        async for c in chat_service.stream(
            ModelRequest(model_key="failing-model", messages=[ModelMessage(role="user", content="hi")])
        )
    ]
    assert chunks[0].delta == "partial"
    assert chunks[-1].is_final is True
    assert chunks[-1].finish_reason == "error"
    assert "boom" not in "".join(str(c) for c in chunks)
