"""
Concrete, per-model providers: `QwenCoderProvider` and `QwenNLPProvider`.

Both subclass `QwenProvider` (`provider.py`) unchanged — that class was
already exactly the right client for this: an OpenAI-compatible
chat-completions HTTP client with streaming, error mapping, and
token-usage extraction. Local execution doesn't change that logic; it
changes what sits on the other end of `config.endpoint_url` — instead
of an assumed-external, possibly-third-party inference server, it is
now a vLLM server this repository's own tooling starts on the SAME
machine, loading locally pre-downloaded weights from
`config.model_path` (see `backend/scripts/run_local_model_server.sh`
and `docs/model-serving.md`). No new SDK, no new wire protocol — vLLM's
own OpenAI-compatible server speaks exactly the API `QwenProvider`
already calls.

These two classes exist so each model's identity (its stable
`model_key`, category, and display name) is owned by its own class
instead of being assembled by hand at each call site in
`bootstrap.py`. They do not duplicate `provider.py`'s ~230 lines of
HTTP/streaming/error-mapping logic — there is no genuine per-model
difference in request/response shape to justify that (both are
Qwen2.5-family OpenAI-compatible chat models); duplicating it here
would be duplication for its own sake, not a real abstraction.

The `MODEL_KEY` constants below are the single source of truth for
each model's stable key — also referenced by
`alembic/versions/bdeda3f7a191_seed_initial_qwen_models.py`'s seed
data and re-exported from `bootstrap.py` for backward compatibility
with existing imports/tests. Keep the two in sync if either changes.
"""
from __future__ import annotations

from src.model_layer.providers.qwen.config import QwenProviderConfig
from src.model_layer.providers.qwen.provider import QwenProvider
from src.models.enums import ModelCategory


class QwenCoderProvider(QwenProvider):
    """Qwen 2.5 Coder 7B, served locally via vLLM. See module docstring."""

    MODEL_KEY = "qwen2.5-coder-7b"
    DISPLAY_NAME = "Qwen 2.5 Coder 7B"
    CATEGORY = ModelCategory.CODER

    def __init__(self, *, config: QwenProviderConfig, **kwargs) -> None:
        super().__init__(model_key=self.MODEL_KEY, category=self.CATEGORY, config=config, **kwargs)


class QwenNLPProvider(QwenProvider):
    """Qwen 2.5 NLP/Instruct 7B, served locally via vLLM. See module docstring."""

    MODEL_KEY = "qwen2.5-nlp-instruct-7b"
    DISPLAY_NAME = "Qwen 2.5 NLP/Instruct 7B"
    CATEGORY = ModelCategory.NLP

    def __init__(self, *, config: QwenProviderConfig, **kwargs) -> None:
        super().__init__(model_key=self.MODEL_KEY, category=self.CATEGORY, config=config, **kwargs)
