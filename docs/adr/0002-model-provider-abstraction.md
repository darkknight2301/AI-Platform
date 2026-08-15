# 0002 — Isolate model backends behind a provider abstraction

## Status
Accepted (interface design only — no implementation yet)

## Context
The application must support multiple model backends and must not
depend directly on any specific model implementation (e.g. Qwen).
Coupling the chat/business logic directly to a specific model API
would make it expensive to add new models or swap providers later.

## Decision
Introduce a layered abstraction:

```text
Model Registry -> Model Router -> Model Provider Interface -> concrete providers (e.g. Qwen Coder, Qwen NLP)
```

Application code depends only on the Model Provider Interface. Concrete
providers translate between that interface and a specific model
backend's API. The registry maps logical model names/capabilities to
available providers; the router selects a provider for a given
request.

This directory structure is established in Phase 1
(`backend/src/model_layer/`), but no provider implementation is added
yet — that is explicitly out of scope until a later phase, per the
Phase 1 scope control instructions.

## Consequences
- Adding a new model backend requires writing a new provider, not
  modifying the chat system or any code that consumes the model layer.
- The application can be tested against a fake/mock provider without
  any real model backend being available.
- Slightly more indirection than calling a model API directly; judged
  worthwhile given the explicit "must not depend on Qwen-specific
  implementation" requirement.
