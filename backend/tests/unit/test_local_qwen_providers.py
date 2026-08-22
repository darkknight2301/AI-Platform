"""Unit tests for `QwenCoderProvider`/`QwenNLPProvider`
(`local_providers.py`) — proves each subclass wires the correct fixed
identity (model_key/category/display_name) onto the unchanged
`QwenProvider` HTTP/streaming logic, and that `bootstrap.py`'s
re-exported MODEL_KEY constants stay in sync with the classes that now
own them.
"""
from __future__ import annotations

import httpx
import pytest

from src.model_layer.bootstrap import QWEN_CODER_MODEL_KEY, QWEN_NLP_MODEL_KEY
from src.model_layer.providers.qwen.config import QwenProviderConfig
from src.model_layer.providers.qwen.local_providers import QwenCoderProvider, QwenNLPProvider
from src.model_layer.providers.qwen.provider import QwenProvider
from src.model_layer.schemas import ModelMessage, ModelRequest
from src.models.enums import ModelCategory


def _config(**overrides) -> QwenProviderConfig:
    defaults = dict(
        model_key="unused",  # QwenCoderProvider/QwenNLPProvider set the real key themselves
        display_name="unused",
        model_path="/models/qwen",
        endpoint_url="http://localhost:8001/v1",
        context_length=32768,
        max_output_tokens=4096,
    )
    defaults.update(overrides)
    return QwenProviderConfig(**defaults)


def test_qwen_coder_provider_class_constants():
    assert QwenCoderProvider.MODEL_KEY == QWEN_CODER_MODEL_KEY
    assert QwenCoderProvider.CATEGORY == ModelCategory.CODER


def test_qwen_nlp_provider_class_constants():
    assert QwenNLPProvider.MODEL_KEY == QWEN_NLP_MODEL_KEY
    assert QwenNLPProvider.CATEGORY == ModelCategory.NLP


def test_qwen_coder_provider_is_a_qwen_provider_with_fixed_identity():
    provider = QwenCoderProvider(config=_config())
    assert isinstance(provider, QwenProvider)
    assert provider.capabilities.category == ModelCategory.CODER


def test_qwen_nlp_provider_is_a_qwen_provider_with_fixed_identity():
    provider = QwenNLPProvider(config=_config())
    assert isinstance(provider, QwenProvider)
    assert provider.capabilities.category == ModelCategory.NLP


@pytest.mark.asyncio
async def test_qwen_coder_provider_generate_uses_inherited_http_logic():
    """No new HTTP/streaming logic was written for this subclass — it
    should behave identically to a plain QwenProvider hitting the same
    (now-local) OpenAI-compatible endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "def foo(): ..."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://localhost:8001/v1")
    provider = QwenCoderProvider(config=_config(), http_client=client)
    request = ModelRequest(
        model_key=QwenCoderProvider.MODEL_KEY,
        messages=[ModelMessage(role="user", content="write a function")],
    )
    response = await provider.generate(request)
    assert response.content == "def foo(): ..."
    assert response.usage.total_tokens == 7
    await provider.aclose()
