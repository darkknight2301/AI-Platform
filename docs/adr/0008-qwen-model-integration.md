# 0008 — Qwen model integration: isolation, configuration, failure handling

## Status
Accepted

## Context
Phase 5 integrates the two initial models (Qwen 2.5 Coder 7B, Qwen 2.5
NLP/Instruct 7B) behind the Phase 4 abstraction, with a hard
requirement: Qwen-specific code must never leak into the chat service,
API routes, the frontend, or database models. Configuration must be
externalized (no hardcoded machine-specific paths), streaming must
flow through the provider abstraction, and a defined set of failure
modes must be handled with safe user-facing errors while full
diagnostic detail is logged internally.

## Decisions

### 1. Everything Qwen-specific lives in `src/model_layer/providers/qwen/`
`config.py` (env-var-driven `QwenProviderConfig`) and `provider.py`
(`QwenProvider`, an HTTP client for an OpenAI-compatible inference
server) are the only files that know Qwen-specific request/response
shapes, HTTP error codes, or SSE parsing. `src/model_layer/bootstrap.py`
is the only other file that imports `QwenProvider` — it registers
instances into a `ModelRegistry` and is the sole integration point
`src/main.py` (the composition root) touches. Nothing in
`src/services/`, `src/api/`, `src/models/` (the SQLAlchemy layer), or
`frontend/` imports anything from `providers/qwen/` — verified by
inspection and by `ChatService`/router tests exercising only
`ModelRequest`/`ModelResponse`/`StreamingChunk`.

### 2. QwenProvider talks HTTP, not weights
Rather than loading model weights in-process, `QwenProvider` is an
HTTP client for an already-running, OpenAI-compatible inference server
(the kind vLLM/TGI expose). This satisfies "not to download models,
just add placeholder if required" while still being a fully working,
testable implementation — not a stub. `model_path` is forwarded as the
request's `model` field and used for descriptive metadata; it is never
read from disk by this application.

### 3. Configuration is entirely environment-variable driven, per model
`QwenProviderConfig` covers every axis Phase 5 requires: model path,
endpoint, context length, max output tokens, temperature, streaming,
and hardware/runtime configuration (device/dtype/GPU memory fraction).
`load_qwen_config(prefix=...)` reads `{PREFIX}*` environment variables
independently for the coder and NLP models (`QWEN_CODER_*` /
`QWEN_NLP_*`), so the two can point at different endpoints/hardware
without any code change. No default value is a machine-specific
filesystem path — `MODEL_PATH` has no default at all; `ENDPOINT_URL`
defaults to a generic loopback address, which is a convention, not a
path tied to a particular machine or user. This configuration
deliberately lives in `providers/qwen/`, not `src/core/config.py` —
keeping Qwen-specific *configuration concerns* isolated matters just
as much as isolating the provider code itself.

### 4. Registration is opt-in, not automatic
Each model is only registered if `QWEN_CODER_ENABLED` /
`QWEN_NLP_ENABLED` is set (default: disabled). A default `.env` lets
the application start without any inference server running — Phase 5
integrates the *capability* to use these models, not a requirement
that they be running. `src/main.py`'s lifespan calls
`register_default_providers`/`close_providers` unconditionally; those
functions internally decide whether there's anything to do.

### 5. Streaming uses the same `StreamingChunk` contract as any provider
`QwenProvider.stream` parses the backend's Server-Sent Events into the
same `StreamingChunk` objects `MockProvider` produces — the frontend
(once wired, in a later phase) will "eventually receive a common
streaming format regardless of model implementation" because that
format is fixed at the `ModelProvider` interface, not per-provider.

### 6. A provider-agnostic error hierarchy (`src/model_layer/errors.py`)
`QwenProvider` maps every failure mode Phase 5 lists — unavailable,
timeout, invalid request, loading failure, runtime failure, streaming
interruption — onto one of six generic exceptions
(`ModelUnavailableProviderError`, `ModelTimeoutError`,
`InvalidModelRequestError`, `ModelLoadingError`, `ModelRuntimeError`,
`ModelStreamInterruptedError`), each carrying a generic `safe_message`
with no internal detail. `ChatService` (`src/services/chat_service.py`)
catches only this generic hierarchy (plus a defensive catch-all for
anything else), logs full diagnostic detail
(`exc_info=True`, model_key, exception type — never response bodies or
secrets) via the structured logger, and re-raises as
`ChatServiceError(exc.safe_message)`. A future Qwen version, or an
entirely different provider, can change what it raises internally
without `ChatService` changing at all — it only ever sees the six
generic types.

### 7. Streaming-interruption contract
Documented in `src/model_layer/errors.py` and enforced by both
`QwenProvider` and `ChatService`: a provider may raise before yielding
any chunk, but once it has yielded at least one, it must yield a
terminal `StreamingChunk(is_final=True, finish_reason="error")`
instead of raising — so a consumer never receives a raw exception
mid-stream, only a well-formed terminus. `ChatService.stream` also
defensively catches any exception a misbehaving provider might raise
mid-iteration and converts it to the same terminal chunk shape, so the
guarantee holds even for a provider that doesn't follow the contract
perfectly.

### 8. `models` table seed data is separate from runtime registration
A data-only Alembic migration
(`alembic/versions/..._seed_initial_qwen_models.py`) inserts
descriptive rows for both models into the `models` table (so the
Owner/Developer APIs from Phase 3 show them), independent of whether
`register_default_providers` actually registers a live provider at
runtime. `model_key` values in that migration
(`qwen2.5-coder-7b`, `qwen2.5-nlp-instruct-7b`) must stay in sync with
`QWEN_CODER_MODEL_KEY`/`QWEN_NLP_MODEL_KEY` in
`src/model_layer/bootstrap.py` — this is the same registry/DB-table
separation established in ADR 0007, now populated on both sides.

## Consequences
- A future Qwen version (or a different backend entirely) can replace
  `QwenProvider` by editing only `providers/qwen/` (or adding a new
  provider package) and the one `bootstrap.py` registration call — no
  change to `ModelRouter`, `ChatService`, any API route, or any
  database model. Verified in
  `tests/unit/test_qwen_bootstrap.py::test_both_models_selectable_via_router_and_chat_service`.
- All Qwen-specific failure handling is unit-tested offline via
  `httpx.MockTransport` (`tests/unit/test_qwen_provider.py`) — no real
  inference server is required to verify timeout/connection/4xx/5xx/
  malformed-response/streaming-interruption behavior.
- No real inference server is deployed or required by this phase; the
  application's default configuration has both Qwen models disabled.
