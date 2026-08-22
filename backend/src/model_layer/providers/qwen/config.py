"""
Externalized configuration for Qwen providers.

All values are sourced from environment variables via `load_qwen_config`
— nothing here hardcodes a machine-specific path, host, or port.
Defaults (where present) are generic conventions (e.g. "loopback +
common port"), never an absolute filesystem path tied to a particular
machine/user.

This is also the single source of configuration truth for local model
execution (`docs/model-serving.md`): the same `QWEN_*_MODEL_PATH` /
`QWEN_*_DEVICE` / `QWEN_*_DTYPE` / `QWEN_*_GPU_MEMORY_FRACTION` /
`QWEN_*_CONTEXT_LENGTH` env vars this module reads for the HTTP
client's own use are read again by
`backend/scripts/run_local_model_server.sh` to start the actual vLLM
server process — deliberately, so there is never a second, divergent
place to configure "the same model."

Kept entirely inside `providers/qwen/` (not `src/core/config.py`) so
Qwen-specific configuration concerns never leak into the application's
central settings module — see ADR 0008.
"""
from __future__ import annotations

import os

from pydantic import BaseModel, Field


class QwenProviderConfig(BaseModel):
    """Runtime configuration for one Qwen model deployment.

    Covers every axis Phase 5 requires: model path, endpoint, context
    length, maximum output, temperature, streaming, and
    hardware/runtime configuration (device/dtype/GPU memory fraction).
    """

    model_key: str
    display_name: str

    # Model identity / weights location. This provider talks to an
    # already-running inference server (see `provider.py`) rather than
    # loading weights in-process itself, so `model_path` is forwarded
    # as the `model` field of each request (and kept for
    # descriptive/admin purposes) — it is NOT used to read files from
    # disk here. As of local execution (`docs/model-serving.md`),
    # `model_path` IS the path/identifier
    # `backend/scripts/run_local_model_server.sh` passes to `vllm
    # serve` to load the actual weights — so it now does double duty:
    # descriptive metadata here, and the real weights location for the
    # separate process that reads this same env var.
    model_path: str | None = None

    endpoint_url: str
    api_key: str | None = Field(default=None, repr=False)

    context_length: int
    max_output_tokens: int
    default_temperature: float | None = None

    streaming_enabled: bool = True
    request_timeout_seconds: float = 60.0

    # Hardware/runtime configuration. Historically informational for
    # this HTTP-client provider (the values that mattered lived on
    # whatever inference server was configured). As of local execution
    # (`docs/model-serving.md`), these ARE load-bearing: the same env
    # vars are read by `backend/scripts/run_local_model_server.sh` and
    # translated into `vllm serve` flags (`--device`, `--dtype`,
    # `--gpu-memory-utilization`), so this class remains the single
    # source of truth for both this HTTP client's descriptive metadata
    # and the local server process's actual startup configuration —
    # never a second, divergent config file.
    device: str | None = None
    dtype: str | None = None
    gpu_memory_fraction: float | None = None


def _get(prefix: str, name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{prefix}{name}", default)


def _get_bool(prefix: str, name: str, default: bool) -> bool:
    raw = _get(prefix, name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_float(prefix: str, name: str, default: float | None) -> float | None:
    raw = _get(prefix, name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _get_int(prefix: str, name: str, default: int) -> int:
    raw = _get(prefix, name)
    if raw is None or raw == "":
        return default
    return int(raw)


def load_qwen_config(
    *,
    prefix: str,
    model_key: str,
    display_name: str,
    default_endpoint_url: str,
    default_context_length: int,
    default_max_output_tokens: int,
) -> QwenProviderConfig:
    """Build a `QwenProviderConfig` from `{prefix}*` environment variables.

    Example, for `prefix="QWEN_CODER_"`: `QWEN_CODER_ENDPOINT_URL`,
    `QWEN_CODER_MODEL_PATH`, `QWEN_CODER_CONTEXT_LENGTH`,
    `QWEN_CODER_MAX_OUTPUT_TOKENS`, `QWEN_CODER_TEMPERATURE`,
    `QWEN_CODER_STREAMING_ENABLED`, `QWEN_CODER_REQUEST_TIMEOUT_SECONDS`,
    `QWEN_CODER_DEVICE`, `QWEN_CODER_DTYPE`,
    `QWEN_CODER_GPU_MEMORY_FRACTION`, `QWEN_CODER_API_KEY`.
    """
    return QwenProviderConfig(
        model_key=model_key,
        display_name=display_name,
        model_path=_get(prefix, "MODEL_PATH"),
        endpoint_url=_get(prefix, "ENDPOINT_URL", default_endpoint_url),
        api_key=_get(prefix, "API_KEY"),
        context_length=_get_int(prefix, "CONTEXT_LENGTH", default_context_length),
        max_output_tokens=_get_int(prefix, "MAX_OUTPUT_TOKENS", default_max_output_tokens),
        default_temperature=_get_float(prefix, "TEMPERATURE", None),
        streaming_enabled=_get_bool(prefix, "STREAMING_ENABLED", True),
        request_timeout_seconds=_get_float(prefix, "REQUEST_TIMEOUT_SECONDS", 60.0) or 60.0,
        device=_get(prefix, "DEVICE"),
        dtype=_get(prefix, "DTYPE"),
        gpu_memory_fraction=_get_float(prefix, "GPU_MEMORY_FRACTION", None),
    )
