# Model Layer

This package is reserved for the model-independence abstraction
described in ARCHITECTURE.md:

```text
Model Registry -> Model Router -> Model Provider Interface -> {Coder Provider, NLP Provider} -> Qwen
```

**Status:** structural placeholder only. Per Phase 1 scope control, no
model-specific (Qwen) implementation or chat functionality is
introduced yet. This directory exists so the eventual provider
abstraction has a clear home and later phases don't need to restructure
the codebase.

Planned contents (future phases):

- `registry.py` — maps logical model names to providers.
- `router.py` — selects a provider/model for a given request.
- `provider_interface.py` — abstract base class all providers implement.
- `providers/` — concrete providers (e.g. Qwen Coder, Qwen NLP), fully
  isolated behind the interface so the application never depends on a
  specific model implementation.
