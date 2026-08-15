# 0007 — Model abstraction layer: registry, router, provider interface

## Status
Accepted

## Context
Phase 4 requires a model-agnostic architecture in place *before* any
real model backend (Qwen) is integrated, satisfying the Common
Instructions' "Model Independence" requirement: the application must
not depend directly on Qwen-specific implementation, and adding a new
model must not require rewriting the chat system.

## Decision

### Layering
```text
ChatService -> ModelRouter -> ModelRegistry -> ModelProvider -> concrete provider
```

Each layer depends only on the interface directly below it:

- **`ChatService`** (`src/services/chat_service.py`) depends only on
  `ModelRouter`. It has no import of `ModelRegistry` or any concrete
  provider class.
- **`ModelRouter`** (`src/model_layer/router.py`) depends only on
  `ModelRegistry`. Its job is purely resolution — given a `model_key`
  (or a `ModelCategory`), return a `ModelProvider` instance, or raise a
  typed error (`ModelNotFoundError`, `ModelUnavailableError`,
  `NoProviderForCategoryError`) if it can't.
- **`ModelRegistry`** (`src/model_layer/registry.py`) is a plain
  in-memory index (`model_key -> ModelRegistration`), with
  register/enable/disable/get/list/check_availability/get_capabilities
  operations. It holds no routing policy and no provider-specific
  logic — it's pure bookkeeping.
- **`ModelProvider`** (`src/model_layer/provider_interface.py`) is an
  ABC every concrete provider implements: `generate`, `stream`,
  `capabilities`, `health_check`.

### Domain schemas, not provider-specific shapes
`ModelRequest`, `ModelResponse`, `StreamingChunk`, `ModelCapabilities`
(`src/model_layer/schemas.py`) are the only objects that cross any
layer boundary in this stack. They carry no provider-specific fields;
provider-specific tuning goes in `ModelRequest.options` (an open
`dict`), which a provider may interpret however it needs without the
schema itself growing a field per provider.

### Registry vs. the `models` database table
`ModelRegistry` (Phase 4, in-memory, process-local) is deliberately
**not** the same thing as `AIModel` / the `models` table (Phase 2,
persistent, admin-editable via the Owner API from Phase 3). The
database table is the durable record of which models an Owner has
configured to exist; the registry is the runtime index mapping each
configured model's key to a *live provider instance*. Keeping them
separate means:
- The persistence layer (`src/models/`) has zero dependency on any
  provider SDK or runtime.
- A provider can be hot-swapped (e.g. for blue/green deploys) by
  changing what's registered, without a database migration.
- Wiring the two together (reading `AIModel` rows at startup and
  calling `registry.register(...)` for each enabled one) is
  straightforward future work, deferred to whichever phase adds a real
  provider — Phase 4 doesn't need it to satisfy its own acceptance
  criteria, so it isn't built prematurely.

### Mock provider as the concrete proof
`MockProvider` (`src/model_layer/providers/mock_provider.py`) is a
complete, working `ModelProvider` — no network calls, no model
download, entirely deterministic — used to prove the whole stack
end-to-end (`tests/unit/test_chat_service.py`). It also doubles as the
template for a real provider: a Qwen provider is a new file in
`providers/` implementing the same interface, plus one
`registry.register(...)` call. No changes to `ModelRouter`,
`ChatService`, or the schemas are needed — this is the concrete,
testable meaning of "adding a new provider should require localized
changes."

### Categories
`ModelCategory` (`CODER`, `NLP`) is reused from `src.models.enums`
(Phase 2) rather than redefined in the model layer, avoiding two
sources of truth for the same concept. `ModelRegistry.list_models` and
`ModelRouter.route_by_category` both take a `ModelCategory`, so adding
a future category is an enum value addition (plus, per ADR 0005's
enum-storage strategy, a plain migration for the database CHECK
constraint) — no redesign of the registry, router, or chat service.

## Consequences
- `ChatService` can be fully unit-tested against `MockProvider` with
  no database, no HTTP layer, and no real model backend — verified in
  `tests/unit/test_chat_service.py` and
  `tests/unit/test_model_layer.py`.
- No real provider exists yet (by design — Phase 4 explicitly scopes
  out downloading or integrating an actual model). The application
  does not yet automatically register any provider at startup;
  wiring that up is deferred to the phase that adds a real provider.
- Streaming is represented uniformly (`ModelProvider.stream` is always
  implemented, even by providers with no true incremental streaming),
  so callers never need to branch on provider capability to get a
  response — they only consult `capabilities.streaming` if they care
  whether the stream is "real."
