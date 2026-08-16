# Model Layer

The model-independence abstraction described in ARCHITECTURE.md:

```text
Model Registry -> Model Router -> Model Provider Interface -> {Coder Provider, NLP Provider} -> Qwen
```

**Status (Phase 5):** the abstraction is implemented in full —
`ModelRequest`/`ModelResponse`/`StreamingChunk`/`ModelCapabilities`
(`schemas.py`), the `ModelProvider` interface
(`provider_interface.py`), a provider-agnostic error hierarchy
(`errors.py`), `ModelRegistry` (`registry.py`), `ModelRouter`
(`router.py`), a working `MockProvider`
(`providers/mock_provider.py`), and — as of Phase 5 — a working
`QwenProvider` (`providers/qwen/provider.py`) integrating **Qwen 2.5
Coder 7B** and **Qwen 2.5 NLP/Instruct 7B** behind the same interface.
`src/services/chat_service.py` consumes only `ModelRouter` — it has no
dependency on any concrete provider, Qwen included.

`QwenProvider` is an HTTP client for an already-running,
OpenAI-compatible inference server (vLLM/TGI-style) — it does not load
or download model weights itself. All configuration is
environment-variable driven per model (`QWEN_CODER_*` / `QWEN_NLP_*`
— see `.env.example`), and registration is opt-in
(`QWEN_CODER_ENABLED`/`QWEN_NLP_ENABLED`, default disabled), so the
app starts fine with no inference server running.

`src/main.py`'s lifespan calls
`model_layer.bootstrap.register_default_providers`/`close_providers`
— the only integration point outside `providers/qwen/` itself that
touches `QwenProvider`.

Adding a future provider (a new Qwen version, or an entirely different
backend) means:

1. A new file in `providers/` implementing `ModelProvider`
   (`generate`, `stream`, `capabilities`, `health_check`), mapping its
   own failures onto `src/model_layer/errors.py`'s generic hierarchy.
2. One `registry.register(...)` call in `bootstrap.py`.

No changes to `ModelRouter`, `ChatService`, or any router/schema in
this package are required. See ADR 0007 and ADR 0008 for the full
design rationale.
