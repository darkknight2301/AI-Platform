"""
Unit tests for `QwenProvider`. No real inference server involved —
every test injects an `httpx.AsyncClient` built on `httpx.MockTransport`
so we can simulate backend responses (success, timeouts, 4xx/5xx,
malformed bodies, dropped connections) deterministically and offline.

These tests also double as the "isolation" check: nothing here reaches
into `src.services` or `src.api` — `QwenProvider` is exercised purely
through the `ModelProvider` interface it implements.
"""
from __future__ import annotations

import json

import httpx
import pytest

from src.model_layer.errors import (
    InvalidModelRequestError,
    ModelLoadingError,
    ModelRuntimeError,
    ModelTimeoutError,
    ModelUnavailableProviderError,
)
from src.model_layer.providers.qwen.config import QwenProviderConfig
from src.model_layer.providers.qwen.provider import QwenProvider
from src.model_layer.schemas import ModelMessage, ModelRequest
from src.models.enums import ModelCategory


def _config(**overrides) -> QwenProviderConfig:
    defaults = dict(
        model_key="qwen2.5-coder-7b",
        display_name="Qwen 2.5 Coder 7B",
        model_path="Qwen/Qwen2.5-Coder-7B-Instruct",
        endpoint_url="http://test-backend/v1",
        context_length=32768,
        max_output_tokens=4096,
        default_temperature=0.7,
        streaming_enabled=True,
        request_timeout_seconds=30.0,
    )
    defaults.update(overrides)
    return QwenProviderConfig(**defaults)


def _provider(handler, **config_overrides) -> QwenProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test-backend/v1")
    return QwenProvider(
        model_key="qwen2.5-coder-7b",
        category=ModelCategory.CODER,
        config=_config(**config_overrides),
        http_client=client,
    )


def _request(content: str = "write a function") -> ModelRequest:
    return ModelRequest(
        model_key="qwen2.5-coder-7b",
        messages=[ModelMessage(role="user", content=content)],
    )


# --- capabilities -----------------------------------------------------------

def test_capabilities_reflect_config():
    provider = _provider(lambda r: httpx.Response(200), streaming_enabled=False, context_length=16384)
    caps = provider.capabilities
    assert caps.category == ModelCategory.CODER
    assert caps.streaming is False
    assert caps.max_context_tokens == 16384


# --- generate: success -------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_success():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "Qwen/Qwen2.5-Coder-7B-Instruct"
        assert body["stream"] is False
        assert body["temperature"] == 0.7
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "def add(a, b): return a + b"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
                "model": "qwen2.5-coder-7b",
            },
        )

    provider = _provider(handler)
    response = await provider.generate(_request())

    assert response.content == "def add(a, b): return a + b"
    assert response.usage.total_tokens == 12
    assert response.finish_reason == "stop"
    assert response.raw_provider_metadata["provider"] == "qwen"


@pytest.mark.asyncio
async def test_generate_respects_max_output_tokens_cap():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}},
        )

    provider = _provider(handler, max_output_tokens=100)
    req = ModelRequest(
        model_key="qwen2.5-coder-7b",
        messages=[ModelMessage(role="user", content="hi")],
        max_output_tokens=99999,  # caller asks for way more than configured cap
    )
    await provider.generate(req)
    assert captured["body"]["max_tokens"] == 100


# --- generate: failure handling -----------------------------------------------

@pytest.mark.asyncio
async def test_generate_connection_failure_maps_to_unavailable():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("connection refused", request=request)

    provider = _provider(handler)
    with pytest.raises(ModelUnavailableProviderError):
        await provider.generate(_request())


@pytest.mark.asyncio
async def test_generate_timeout_maps_to_timeout_error():
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("timed out", request=request)

    provider = _provider(handler)
    with pytest.raises(ModelTimeoutError):
        await provider.generate(_request())


@pytest.mark.asyncio
async def test_generate_400_maps_to_invalid_request():
    provider = _provider(lambda r: httpx.Response(400, json={"error": "bad request"}))
    with pytest.raises(InvalidModelRequestError):
        await provider.generate(_request())


@pytest.mark.asyncio
async def test_generate_503_maps_to_loading_error():
    provider = _provider(lambda r: httpx.Response(503, json={"error": "loading"}))
    with pytest.raises(ModelLoadingError):
        await provider.generate(_request())


@pytest.mark.asyncio
async def test_generate_500_maps_to_runtime_error():
    provider = _provider(lambda r: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(ModelRuntimeError):
        await provider.generate(_request())


@pytest.mark.asyncio
async def test_generate_malformed_response_body_maps_to_runtime_error():
    provider = _provider(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
    with pytest.raises(ModelRuntimeError):
        await provider.generate(_request())


@pytest.mark.asyncio
async def test_generate_error_safe_messages_contain_no_internal_detail():
    provider = _provider(lambda r: httpx.Response(500, text="Traceback: secret/internal/path.py line 42"))
    with pytest.raises(ModelRuntimeError) as exc_info:
        await provider.generate(_request())
    assert "secret" not in exc_info.value.safe_message
    assert "Traceback" not in exc_info.value.safe_message


# --- streaming: success -------------------------------------------------------

def _sse(*events: dict) -> bytes:
    lines = [f"data: {json.dumps(e)}\n\n" for e in events]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


@pytest.mark.asyncio
async def test_stream_success_yields_chunks_then_final_usage():
    events = [
        {"choices": [{"delta": {"content": "def "}}]},
        {"choices": [{"delta": {"content": "add(): pass"}}]},
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
        },
    ]
    provider = _provider(lambda r: httpx.Response(200, content=_sse(*events)))

    chunks = [c async for c in provider.stream(_request())]

    assert chunks[0].delta == "def "
    assert chunks[1].delta == "add(): pass"
    assert chunks[-1].is_final is True
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage.total_tokens == 10


@pytest.mark.asyncio
async def test_stream_without_explicit_finish_synthesizes_terminal_chunk():
    events = [{"choices": [{"delta": {"content": "partial"}}]}]
    provider = _provider(lambda r: httpx.Response(200, content=_sse(*events)))

    chunks = [c async for c in provider.stream(_request())]
    assert chunks[-1].is_final is True
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_skips_malformed_line_without_dying():
    body = b'data: {"not": "valid choices shape"}\n\ndata: {"choices": [{"delta": {"content": "ok"}}]}\n\ndata: [DONE]\n\n'
    provider = _provider(lambda r: httpx.Response(200, content=body))

    chunks = [c async for c in provider.stream(_request())]
    non_final = [c for c in chunks if not c.is_final]
    assert len(non_final) == 1
    assert non_final[0].delta == "ok"


# --- streaming: failure handling -----------------------------------------------

@pytest.mark.asyncio
async def test_stream_connection_failure_before_any_chunk_raises():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("refused", request=request)

    provider = _provider(handler)
    with pytest.raises(ModelUnavailableProviderError):
        async for _ in provider.stream(_request()):
            pass


@pytest.mark.asyncio
async def test_stream_backend_error_status_raises_before_first_chunk():
    provider = _provider(lambda r: httpx.Response(503, json={"error": "loading"}))
    with pytest.raises(ModelLoadingError):
        async for _ in provider.stream(_request()):
            pass


@pytest.mark.asyncio
async def test_health_check_true_on_200():
    provider = _provider(lambda r: httpx.Response(200, json={"data": []}))
    assert await provider.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_on_connection_error():
    def handler(request: httpx.Request):
        raise httpx.ConnectError("refused", request=request)

    provider = _provider(handler)
    assert await provider.health_check() is False


def test_api_key_included_as_bearer_header_when_configured():
    config = _config(api_key="sk-test-123")
    headers = QwenProvider._build_headers(config)
    assert headers["Authorization"] == "Bearer sk-test-123"


def test_no_authorization_header_when_api_key_not_configured():
    config = _config(api_key=None)
    headers = QwenProvider._build_headers(config)
    assert "Authorization" not in headers
