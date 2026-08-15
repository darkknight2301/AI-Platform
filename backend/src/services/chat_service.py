"""
`ChatService`: the chat system's only entry point into the model
layer.

```text
Chat Service -> Model Router -> Model Registry -> Provider
```

`ChatService` depends solely on `ModelRouter` (never on
`ModelRegistry` or any concrete `ModelProvider`). This is what makes
Phase 4's acceptance criterion true: "The chat service should
communicate with the mock provider without knowing its
implementation" — swap `MockProvider` for a real Qwen provider behind
the same `model_key` and nothing in this file changes.

This phase intentionally stops short of chat/message *persistence*
(no reads/writes to the `chats`/`messages` tables here) — that's the
chat-persistence phase's job. This service is the orchestration seam
between that future persistence layer and the model layer.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from src.model_layer.router import ModelRouter
from src.model_layer.schemas import ModelRequest, ModelResponse, StreamingChunk


class ChatService:
    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Get a complete response for `request` from whichever provider
        the router resolves `request.model_key` to."""
        provider = await self._router.route_request(request.model_key)
        return await provider.generate(request)

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamingChunk]:
        """Stream a response for `request`."""
        provider = await self._router.route_request(request.model_key)
        async for chunk in provider.stream(request):
            yield chunk
