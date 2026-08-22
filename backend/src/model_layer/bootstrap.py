"""
Wires the two initial Qwen models (Phase 5) into a `ModelRegistry`.

This module — together with `providers/qwen/` — is the ONLY place
outside `providers/qwen/` itself that imports a concrete Qwen provider
class. The composition root (`src/main.py`) calls
`register_default_providers` and `close_providers` from here; it never
imports a provider class directly. Nothing in `src/services/`,
`src/api/`, `src/models/`, or the frontend imports anything from this
module or from `providers/qwen/` — see ADR 0008.

Each model is only registered if explicitly enabled via
`QWEN_CODER_ENABLED` / `QWEN_NLP_ENABLED` (default: disabled), so a
default `.env` doesn't require a running inference server just to
start the application.

Each model is served locally: `QwenCoderProvider`/`QwenNLPProvider`
(`providers/qwen/local_providers.py`) are thin, per-model subclasses
of `QwenProvider` — an OpenAI-compatible HTTP client — pointed at a
vLLM server this repository's own tooling starts on the same machine
(`backend/scripts/run_local_model_server.sh`, `docs/model-serving.md`),
loading locally pre-downloaded weights. See those files for the local
execution architecture; nothing in this module changes based on where
the server actually runs.
"""
from __future__ import annotations

import logging
import os

from src.model_layer.providers.qwen.config import load_qwen_config
from src.model_layer.providers.qwen.local_providers import QwenCoderProvider, QwenNLPProvider
from src.model_layer.registry import ModelRegistry

logger = logging.getLogger(__name__)

# Stable, well-known keys for the two Phase 5 initial models — owned by
# their respective provider classes (`local_providers.py`) and
# re-exported here for backward compatibility with existing imports
# (tests, alembic seed data comments). Also used as the `model_key` in
# the corresponding seed row in the `models` table (see
# alembic/versions/..._seed_qwen_models.py) — keep all three in sync;
# see ADR 0008.
QWEN_CODER_MODEL_KEY = QwenCoderProvider.MODEL_KEY
QWEN_NLP_MODEL_KEY = QwenNLPProvider.MODEL_KEY


def _is_enabled(env_var: str) -> bool:
    return os.environ.get(env_var, "false").strip().lower() in ("1", "true", "yes", "on")


def register_default_providers(registry: ModelRegistry) -> None:
    """Register whichever of the two initial Qwen models are enabled.

    Safe to call with neither enabled (the common case for local dev/
    tests without a running inference server) — the registry simply
    ends up with no Qwen entries, and anything routing through it will
    get a normal `ModelNotFoundError`/`NoProviderForCategoryError`.
    """
    _maybe_register_coder(registry)
    _maybe_register_nlp(registry)


def _maybe_register_coder(registry: ModelRegistry) -> None:
    if not _is_enabled("QWEN_CODER_ENABLED"):
        logger.info("qwen_provider_not_registered", extra={"model_key": QWEN_CODER_MODEL_KEY})
        return

    config = load_qwen_config(
        prefix="QWEN_CODER_",
        model_key=QWEN_CODER_MODEL_KEY,
        display_name=QwenCoderProvider.DISPLAY_NAME,
        default_endpoint_url="http://localhost:8001/v1",
        default_context_length=32768,
        default_max_output_tokens=4096,
    )
    provider = QwenCoderProvider(config=config)
    registry.register(
        model_key=QWEN_CODER_MODEL_KEY,
        provider=provider,
        category=QwenCoderProvider.CATEGORY,
        enabled=True,
        metadata={"display_name": config.display_name},
    )
    logger.info("qwen_provider_registered", extra={"model_key": QWEN_CODER_MODEL_KEY})


def _maybe_register_nlp(registry: ModelRegistry) -> None:
    if not _is_enabled("QWEN_NLP_ENABLED"):
        logger.info("qwen_provider_not_registered", extra={"model_key": QWEN_NLP_MODEL_KEY})
        return

    config = load_qwen_config(
        prefix="QWEN_NLP_",
        model_key=QWEN_NLP_MODEL_KEY,
        display_name=QwenNLPProvider.DISPLAY_NAME,
        default_endpoint_url="http://localhost:8002/v1",
        default_context_length=32768,
        default_max_output_tokens=4096,
    )
    provider = QwenNLPProvider(config=config)
    registry.register(
        model_key=QWEN_NLP_MODEL_KEY,
        provider=provider,
        category=QwenNLPProvider.CATEGORY,
        enabled=True,
        metadata={"display_name": config.display_name},
    )
    logger.info("qwen_provider_registered", extra={"model_key": QWEN_NLP_MODEL_KEY})


async def close_providers(registry: ModelRegistry) -> None:
    """Gracefully close any provider-owned HTTP clients at shutdown."""
    for registration in registry.list_models():
        aclose = getattr(registration.provider, "aclose", None)
        if aclose is not None:
            await aclose()
