"""
`ChatService`: the chat system's only entry point into the model
layer.

```text
Chat Service -> Model Router -> Model Registry -> Provider
```

`ChatService` depends solely on `ModelRouter` (never on
`ModelRegistry` or any concrete `ModelProvider`). This is what makes
Phase 4/5's acceptance criteria true: swap `MockProvider` — or the
Phase 5 `QwenProvider` — for any future provider behind the same
`model_key` and nothing in this file changes.

This phase intentionally stops short of chat/message *persistence*
(no reads/writes to the `chats`/`messages` tables here) — that's a
future phase's job. This service is the orchestration seam between
that future persistence layer and the model layer, and — as of Phase
5 — the single place provider/router failures are translated into
safe, uniform errors (`ChatServiceError`) while full diagnostic detail
is logged internally. This is provider-agnostic: whether the
underlying failure came from `MockProvider`, `QwenProvider`, or any
future provider, callers of `ChatService` only ever see
`ChatServiceError`.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from src.model_layer.errors import ModelProviderError
from src.model_layer.provider_interface import ModelProvider
from src.model_layer.registry import ModelNotFoundError
from src.model_layer.router import ModelRouter, ModelUnavailableError, NoProviderForCategoryError
from src.model_layer.schemas import ModelRequest, ModelResponse, StreamingChunk
from src.services.errors import ChatServiceError

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Get a complete response for `request` from whichever provider
        the router resolves `request.model_key` to.

        Raises `ChatServiceError` (safe to show to the caller) for
        every failure mode; full diagnostic detail is logged
        internally before translation.
        """
        provider = await self._resolve_provider(request.model_key)

        try:
            async with self._router.acquire_slot(request.model_key):
                return await provider.generate(request)
        except ModelProviderError as exc:
            logger.error(
                "chat_service_generate_failed",
                extra={"model_key": request.model_key, "error_type": type(exc).__name__},
                exc_info=exc,
            )
            raise ChatServiceError(exc.safe_message) from exc
        except Exception as exc:  # defensive: never let a raw exception escape
            logger.error(
                "chat_service_generate_unexpected_failure",
                extra={"model_key": request.model_key, "error_type": type(exc).__name__},
                exc_info=exc,
            )
            raise ChatServiceError("An unexpected error occurred. Please try again.") from exc

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamingChunk]:
        """Stream a response for `request`.

        Failures before the first chunk raise `ChatServiceError`
        (nothing has been sent to the caller yet, so a normal
        exception is the right signal). Failures after at least one
        chunk has been produced are surfaced as a terminal
        `StreamingChunk(is_final=True, finish_reason="error")` instead
        — raising partway through an already-started stream leaves
        consumers with no clean way to know the stream ended
        abnormally, whereas a well-formed terminal chunk always does.
        This mirrors the provider-level contract documented in
        `src/model_layer/errors.py`, and enforces it even if a
        provider implementation doesn't follow it perfectly.
        """
        provider = await self._resolve_provider(request.model_key)

        try:
            async with self._router.acquire_slot(request.model_key):
                async for chunk in provider.stream(request):
                    yield chunk
        except ModelProviderError as exc:
            logger.error(
                "chat_service_stream_failed",
                extra={"model_key": request.model_key, "error_type": type(exc).__name__},
                exc_info=exc,
            )
            yield StreamingChunk(model_key=request.model_key, delta="", is_final=True, finish_reason="error")
        except Exception as exc:  # defensive: provider misbehaved mid-stream
            logger.error(
                "chat_service_stream_unexpected_failure",
                extra={"model_key": request.model_key, "error_type": type(exc).__name__},
                exc_info=exc,
            )
            yield StreamingChunk(model_key=request.model_key, delta="", is_final=True, finish_reason="error")

    async def _resolve_provider(self, model_key: str) -> ModelProvider:
        try:
            return await self._router.route_request(model_key)
        except ModelNotFoundError as exc:
            logger.warning("chat_service_model_not_found", extra={"model_key": model_key})
            raise ChatServiceError("The requested model is not available.") from exc
        except ModelUnavailableError as exc:
            logger.warning("chat_service_model_unavailable", extra={"model_key": model_key})
            raise ChatServiceError(
                "The selected model is temporarily unavailable. Please try again shortly."
            ) from exc
        except NoProviderForCategoryError as exc:
            logger.warning("chat_service_no_provider_for_category", extra={"model_key": model_key})
            raise ChatServiceError("No model is currently available for this request.") from exc

