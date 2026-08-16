"""
`QwenProvider`: talks to an already-running, OpenAI-compatible
inference server (e.g. vLLM, TGI, or similar) hosting a Qwen model.

This file — plus `config.py` in this package — is the ONLY place in
the codebase that knows anything Qwen-specific: request/response
shapes, HTTP error mapping, SSE parsing. Everything it exposes
upward crosses through the provider-agnostic `ModelProvider` interface
and `src.model_layer.errors` exception hierarchy (see ADR 0008).

This provider does not load or download any model weights itself —
`model_path` is forwarded to the backend as the `model` field and kept
for descriptive/admin purposes only (see `config.py`).
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Literal

import httpx

from src.model_layer.errors import (
    InvalidModelRequestError,
    ModelLoadingError,
    ModelProviderError,
    ModelRuntimeError,
    ModelTimeoutError,
    ModelUnavailableProviderError,
)
from src.model_layer.provider_interface import ModelProvider
from src.model_layer.providers.qwen.config import QwenProviderConfig
from src.model_layer.schemas import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    StreamingChunk,
    TokenUsage,
)
from src.models.enums import ModelCategory

logger = logging.getLogger(__name__)

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_HEALTH_PATH = "/models"


def _approximate_token_count(text: str) -> int:
    return max(1, len(text.split())) if text else 0


def _map_finish_reason(raw: str | None) -> Literal["stop", "length", "error"]:
    if raw == "length":
        return "length"
    if raw and "error" in raw:
        return "error"
    return "stop"


class QwenProvider(ModelProvider):
    def __init__(
        self,
        *,
        model_key: str,
        category: ModelCategory,
        config: QwenProviderConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_key = model_key
        self._category = category
        self._config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=config.endpoint_url,
            timeout=config.request_timeout_seconds,
            headers=self._build_headers(config),
        )

    @staticmethod
    def _build_headers(config: QwenProviderConfig) -> dict[str, str]:
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        return headers

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            category=self._category,
            streaming=self._config.streaming_enabled,
            function_calling=False,
            max_context_tokens=self._config.context_length,
            supports_system_prompt=True,
        )

    async def health_check(self) -> bool:
        try:
            response = await self._client.get(_HEALTH_PATH, timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    # --- request building --------------------------------------------------

    def _build_payload(self, request: ModelRequest, *, stream: bool) -> dict:
        max_tokens = request.max_output_tokens or self._config.max_output_tokens
        max_tokens = min(max_tokens, self._config.max_output_tokens)

        payload: dict = {
            "model": self._config.model_path or self._model_key,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": max_tokens,
            "stream": stream,
        }
        temperature = request.options.get("temperature", self._config.default_temperature)
        if temperature is not None:
            payload["temperature"] = temperature
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _log_error(self, kind: str, exc: Exception) -> None:
        logger.error(
            "qwen_provider_error",
            extra={"model_key": self._model_key, "error_kind": kind, "error_type": type(exc).__name__},
            exc_info=exc,
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        if response.status_code == 400:
            exc = InvalidModelRequestError(f"Backend rejected request: status={response.status_code}")
            self._log_error("invalid_request", exc)
            raise exc
        if response.status_code == 404:
            exc = ModelUnavailableProviderError(f"Model not found on backend: status={response.status_code}")
            self._log_error("not_found", exc)
            raise exc
        if response.status_code == 503:
            exc = ModelLoadingError(f"Backend not ready: status={response.status_code}")
            self._log_error("loading", exc)
            raise exc
        if response.status_code in (408, 504):
            exc = ModelTimeoutError(f"Backend timed out: status={response.status_code}")
            self._log_error("timeout_status", exc)
            raise exc
        exc = ModelRuntimeError(f"Backend error: status={response.status_code}")
        self._log_error("backend_error", exc)
        raise exc

    # --- ModelProvider interface --------------------------------------------

    async def generate(self, request: ModelRequest) -> ModelResponse:
        payload = self._build_payload(request, stream=False)
        try:
            response = await self._client.post(_CHAT_COMPLETIONS_PATH, json=payload)
        except httpx.ConnectError as exc:
            self._log_error("connect_error", exc)
            raise ModelUnavailableProviderError("Qwen backend connection failed.") from exc
        except httpx.TimeoutException as exc:
            self._log_error("timeout", exc)
            raise ModelTimeoutError("Qwen backend request timed out.") from exc
        except httpx.HTTPError as exc:
            self._log_error("http_error", exc)
            raise ModelRuntimeError("Qwen backend request failed.") from exc

        self._raise_for_status(response)

        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage_raw = data.get("usage") or {}
            input_tokens = usage_raw.get("prompt_tokens", 0)
            output_tokens = usage_raw.get("completion_tokens", 0)
            usage = TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=usage_raw.get("total_tokens", input_tokens + output_tokens),
            )
            finish_reason = _map_finish_reason(choice.get("finish_reason"))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self._log_error("malformed_response", exc)
            raise ModelRuntimeError("Qwen backend returned an unexpected response shape.") from exc

        return ModelResponse(
            model_key=request.model_key,
            content=content,
            usage=usage,
            finish_reason=finish_reason,
            raw_provider_metadata={"provider": "qwen"},
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamingChunk]:
        payload = self._build_payload(request, stream=True)
        input_tokens_estimate = sum(_approximate_token_count(m.content) for m in request.messages)
        output_tokens = 0

        try:
            async with self._client.stream("POST", _CHAT_COMPLETIONS_PATH, json=payload) as response:
                if response.status_code != 200:
                    await response.aread()
                    self._raise_for_status(response)

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        event = json.loads(data_str)
                        choice = event["choices"][0]
                        delta = choice.get("delta", {}).get("content", "") or ""
                        finish_reason_raw = choice.get("finish_reason")
                    except (KeyError, IndexError, TypeError, ValueError) as exc:
                        # A single malformed SSE line shouldn't kill an
                        # otherwise-healthy stream — log and skip it.
                        self._log_error("malformed_stream_chunk", exc)
                        continue

                    if delta:
                        output_tokens += _approximate_token_count(delta)
                        yield StreamingChunk(model_key=request.model_key, delta=delta, is_final=False)

                    if finish_reason_raw:
                        usage_raw = event.get("usage")
                        usage = (
                            TokenUsage(
                                input_tokens=usage_raw.get("prompt_tokens", input_tokens_estimate),
                                output_tokens=usage_raw.get("completion_tokens", output_tokens),
                                total_tokens=usage_raw.get(
                                    "total_tokens", input_tokens_estimate + output_tokens
                                ),
                            )
                            if usage_raw
                            else TokenUsage(
                                input_tokens=input_tokens_estimate,
                                output_tokens=output_tokens,
                                total_tokens=input_tokens_estimate + output_tokens,
                            )
                        )
                        yield StreamingChunk(
                            model_key=request.model_key,
                            delta="",
                            is_final=True,
                            finish_reason=_map_finish_reason(finish_reason_raw),
                            usage=usage,
                        )
                        return

                # Stream ended without an explicit finish_reason (backend
                # closed the connection cleanly but without a final
                # event) — synthesize a terminal chunk so callers always
                # get one, per the streaming-interruption contract.
                yield StreamingChunk(
                    model_key=request.model_key,
                    delta="",
                    is_final=True,
                    finish_reason="stop",
                    usage=TokenUsage(
                        input_tokens=input_tokens_estimate,
                        output_tokens=output_tokens,
                        total_tokens=input_tokens_estimate + output_tokens,
                    ),
                )
        except ModelProviderError:
            # Already a clean, mapped error raised via _raise_for_status
            # before any chunk was yielded — propagate as-is.
            raise
        except httpx.ConnectError as exc:
            self._log_error("stream_connect_error", exc)
            raise ModelUnavailableProviderError("Qwen backend connection failed.") from exc
        except httpx.TimeoutException as exc:
            self._log_error("stream_timeout", exc)
            raise ModelTimeoutError("Qwen backend request timed out.") from exc
        except httpx.HTTPError as exc:
            # A genuine mid-stream network failure. Per the streaming
            # contract (src/model_layer/errors.py), once we may have
            # already yielded content, we terminate gracefully with an
            # error chunk rather than raising into the consumer.
            self._log_error("stream_interrupted", exc)
            yield StreamingChunk(model_key=request.model_key, delta="", is_final=True, finish_reason="error")
