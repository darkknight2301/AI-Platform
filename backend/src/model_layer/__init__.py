"""
Model layer: the provider-agnostic abstraction between the chat system
and any concrete model backend.

```text
ChatService -> ModelRouter -> ModelRegistry -> ModelProvider -> concrete provider (e.g. MockProvider)
```

Public surface:
  - Domain schemas: ModelRequest, ModelResponse, StreamingChunk, ModelCapabilities
  - ModelProvider: the interface every provider implements
  - ModelRegistry: tracks registered providers (register/enable/disable/list/capabilities)
  - ModelRouter: resolves a model_key/category to a live ModelProvider

See ADR 0007 for the design rationale and `providers/mock_provider.py`
for a working reference implementation. No real (e.g. Qwen) provider
is implemented yet — see `src/model_layer/README.md`.
"""
from src.model_layer.provider_interface import ModelProvider
from src.model_layer.registry import ModelNotFoundError, ModelRegistration, ModelRegistry
from src.model_layer.router import (
    ModelRouter,
    ModelUnavailableError,
    NoProviderForCategoryError,
)
from src.model_layer.schemas import (
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    StreamingChunk,
    TokenUsage,
)

__all__ = [
    "ModelProvider",
    "ModelRegistry",
    "ModelRegistration",
    "ModelNotFoundError",
    "ModelRouter",
    "ModelUnavailableError",
    "NoProviderForCategoryError",
    "ModelRequest",
    "ModelResponse",
    "ModelMessage",
    "StreamingChunk",
    "ModelCapabilities",
    "TokenUsage",
]
