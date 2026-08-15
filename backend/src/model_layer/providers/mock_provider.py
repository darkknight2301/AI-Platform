"""
`MockProvider`: a fully working `ModelProvider` implementation with no
external dependency — no model download, no network call, no API key.

This exists to prove the abstraction end-to-end (Phase 4's acceptance
criterion: "A mock provider should be able to process a model
request... without knowing its implementation") and as a template for
a real provider later: a concrete Qwen provider is a new file in this
package implementing the same `ModelProvider` interface, registered
the same way — see `src/model_layer/README.md`.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from src.model_layer.provider_interface import ModelProvider
from src.model_layer.schemas import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    StreamingChunk,
    TokenUsage,
)
from src.models.enums import ModelCategory


def _approximate_token_count(text: str) -> int:
    """Whitespace-token approximation — good enough for a mock provider;
    a real provider would report the backend's actual token accounting."""
    return max(1, len(text.split()))


class MockProvider(ModelProvider):
    """Deterministic in-process provider for tests and local development.

    `canned_response`, if set, is returned verbatim; otherwise the
    provider echoes back the last user message with a fixed prefix, so
    tests can assert on predictable output without configuring
    anything.
    """

    def __init__(
        self,
        *,
        category: ModelCategory,
        canned_response: str | None = None,
        simulated_latency_seconds: float = 0.0,
        streaming: bool = True,
    ) -> None:
        self._category = category
        self._canned_response = canned_response
        self._simulated_latency_seconds = simulated_latency_seconds
        self._streaming = streaming

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            category=self._category,
            streaming=self._streaming,
            function_calling=False,
            max_context_tokens=8192,
            supports_system_prompt=True,
        )

    def _build_content(self, request: ModelRequest) -> str:
        if self._canned_response is not None:
            return self._canned_response
        last_user_message = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), ""
        )
        return f"[mock:{request.model_key}] {last_user_message}"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        if self._simulated_latency_seconds:
            await asyncio.sleep(self._simulated_latency_seconds)

        content = self._build_content(request)
        input_tokens = sum(_approximate_token_count(m.content) for m in request.messages)
        output_tokens = _approximate_token_count(content)

        return ModelResponse(
            model_key=request.model_key,
            content=content,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            finish_reason="stop",
            raw_provider_metadata={"provider": "mock"},
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamingChunk]:
        content = self._build_content(request)
        words = content.split(" ")
        input_tokens = sum(_approximate_token_count(m.content) for m in request.messages)
        output_tokens = 0

        for i, word in enumerate(words):
            if self._simulated_latency_seconds:
                await asyncio.sleep(self._simulated_latency_seconds)
            delta = word if i == 0 else f" {word}"
            output_tokens += _approximate_token_count(word)
            yield StreamingChunk(model_key=request.model_key, delta=delta, is_final=False)

        yield StreamingChunk(
            model_key=request.model_key,
            delta="",
            is_final=True,
            finish_reason="stop",
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
        )

    async def health_check(self) -> bool:
        return True
