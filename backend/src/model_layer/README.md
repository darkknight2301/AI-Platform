# Model Layer

The model-independence abstraction described in ARCHITECTURE.md:

```text
Model Registry -> Model Router -> Model Provider Interface -> {Coder Provider, NLP Provider} -> Qwen
```

**Status (Phase 4):** the abstraction itself is implemented —
`ModelRequest`/`ModelResponse`/`StreamingChunk`/`ModelCapabilities`
(`schemas.py`), the `ModelProvider` interface
(`provider_interface.py`), `ModelRegistry` (`registry.py`),
`ModelRouter` (`router.py`), and a fully working `MockProvider`
(`providers/mock_provider.py`) used to prove the seam end-to-end (see
`tests/unit/test_model_layer.py` and
`tests/unit/test_chat_service.py`). `src/services/chat_service.py`
consumes only `ModelRouter` — it has no dependency on any concrete
provider.

**No real (Qwen) provider is implemented yet** — per Phase 4 scope
("not to download models, just add placeholder if required"). Adding
one later means:

1. A new file in `providers/` implementing `ModelProvider`
   (`generate`, `stream`, `capabilities`, `health_check`).
2. One `registry.register(...)` call wiring `model_key -> provider
   instance` — typically done once at process startup.

No changes to `ModelRouter`, `ChatService`, or any router/schema in
this package are required — that's the whole point of the interface.
See ADR 0007 for the full design rationale.
