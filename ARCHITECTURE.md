# Architecture

## Overview

The application is a Python-backed AI platform intended to support
500+ registered users, multiple groups, concurrent requests, and
multiple interchangeable model backends. This document describes the
foundation established in Phase 1 and the architecture that later
phases will build on.

## Conceptual Architecture

```text
                    Internet
                       |
                     Nginx
                       |
              +--------+--------+
              |                 |
          Frontend           Python API
                                |
                     +----------+----------+
                     |          |          |
                  Database    Workers    Model Layer
                                           |
                              +------------+------------+
                              |                         |
                         Qwen Coder                 Qwen NLP
```

- **Nginx** terminates TLS (where applicable), serves the built
  frontend, and reverse-proxies API traffic to the Python backend,
  including streaming (SSE) and WebSocket connections where required.
- **Frontend** is a lightweight Vite + TypeScript application. It
  holds no business logic or secrets — all authorization is enforced
  server-side.
- **Python API** (FastAPI) is the sole source of truth for business
  logic, authentication/authorization, and data access.
- **Database** is PostgreSQL in staging/production, accessed via
  SQLAlchemy's async engine through Alembic-managed migrations.
- **Workers** handle background/asynchronous processing so long-running
  work (e.g. model inference) doesn't block request/response cycles.
- **Model Layer** abstracts away any specific model implementation
  (see "Model Independence" below). As of Phase 5 the abstraction is
  implemented and integrated with two real Qwen models.

## Technology Choices

| Concern              | Choice                | Rationale |
|-----------------------|------------------------|-----------|
| Backend language      | Python                 | Single backend language across the whole system, per project policy. |
| Web framework         | FastAPI                | Async-native, strong typing via Pydantic, good OpenAPI support. |
| ORM                   | SQLAlchemy 2.0 (async) | Mature, explicit, works with both PostgreSQL (prod) and SQLite (fast local/test runs) without code changes. |
| Migrations             | Alembic                | Standard companion to SQLAlchemy; migration env reads settings directly so it always targets the correct database. |
| Validation/schemas     | Pydantic v2             | Already a FastAPI dependency; used for both settings and request/response schemas. |
| Database (prod)        | PostgreSQL              | Reliable, supports the concurrency and constraint needs of a 500+ user system. |
| Reverse proxy          | Nginx                   | TLS termination, static asset serving, streaming/WebSocket proxying, per project policy. |
| Frontend                | Vite + TypeScript       | Minimal, fast, framework-agnostic starting point; no framework has been prescribed by requirements yet, so the lightest viable option was chosen. Can be extended with a UI framework in a later phase if warranted. |
| Testing                 | pytest, pytest-asyncio, httpx | Standard async-capable Python test stack; `httpx.AsyncClient` drives the FastAPI app in-process for integration tests. |

## Component Responsibilities

- **`src/api/`** — HTTP route definitions only. Routes call into
  `services/`; they do not contain business logic or direct database
  queries.
- **`src/services/`** — business logic, orchestration between
  repositories and (later) the model layer.
- **`src/repositories/`** — data access; the only layer that issues
  SQLAlchemy queries.
- **`src/models/`** — SQLAlchemy ORM model definitions.
- **`src/schemas/`** — Pydantic request/response models exposed over
  the API. Kept separate from ORM models so the API contract can evolve
  independently of the storage schema.
- **`src/auth/`** — authentication (identity/session/token handling)
  and authorization (permission/role checks), enforced entirely
  server-side. Structural placeholder as of Phase 1.
- **`src/core/`** — cross-cutting concerns: configuration (`config.py`)
  and structured logging (`logging.py`).
- **`src/db/`** — SQLAlchemy async engine/session factory
  (`session.py`) and the declarative base (`base.py`).
- **`src/model_layer/`** — the model-independence abstraction (see
  below). Structural placeholder as of Phase 1.
- **`src/workers/`** — background/async job processing, separate from
  the request/response path. Empty as of Phase 1.

## Data Flow (request lifecycle, current foundation)

```text
Client
  -> Nginx (TLS termination, routing)
  -> FastAPI app (src/main.py)
      -> CORS middleware
      -> API router (src/api/v1/router.py)
          -> endpoint handler (e.g. src/api/v1/routers/health.py)
              -> (future) service layer
                  -> (future) repository layer
                      -> SQLAlchemy async session -> PostgreSQL
  <- JSON response
```

Once business functionality is added in later phases, handlers will
delegate to `services/`, which will use `repositories/` for data
access and the `model_layer/` for any model-backed functionality —
keeping routing, business logic, data access, and model orchestration
in separate, independently testable layers.

## Model Independence

The application must not depend directly on any specific model
implementation (e.g. Qwen). The intended abstraction:

```text
Model Registry
      |
Model Router
      |
Model Provider Interface
      |
+-----+------+
|            |
Coder       NLP
Provider   Provider
|            |
Qwen        Qwen
```

- **Model Registry** — maps logical model names/capabilities to
  available providers.
- **Model Router** — selects the appropriate provider for a given
  request (e.g. by capability, load, or explicit request).
- **Model Provider Interface** — an abstract interface that every
  concrete provider implements (e.g. `generate()`, `stream()`).
  Application code depends only on this interface.
- **Concrete providers** (e.g. Qwen Coder, Qwen NLP) implement the
  interface and encapsulate all model-specific request/response
  translation.

This means adding a new model or swapping a provider requires writing
a new provider implementation, not rewriting the chat system or any
code that consumes the model layer. As of Phase 5, this abstraction is
implemented in full (`src/model_layer/`), with a working mock provider
proving the seam end-to-end and two real Qwen models integrated behind
it — see the "Model Abstraction Layer" section below and ADR 0007/0008
for the concrete design.

## Scalability Considerations (500+ users)

The web/API layer and the model-inference layer are deliberately
decoupled:

- **Web/API scalability**: FastAPI is async and stateless, so multiple
  backend instances can run behind Nginx. Database access uses a
  connection pool (`DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW`) sized
  independently of any single model backend's capacity.
- **Model-inference scalability**: model backends are assumed to have
  materially lower concurrency limits than the web tier. Future phases
  will introduce request queuing at the model layer (not at the web
  tier) so a burst of concurrent users does not translate 1:1 into
  concurrent model invocations.
- **Background processing**: long-running or bursty work (e.g. model
  inference) is intended to run through `src/workers/`, keeping HTTP
  request/response latency predictable.

None of the above assumes the model infrastructure can process 500
simultaneous generations; that capacity is a separate, later-phase
concern from web/API scalability.

## Deployment Concept

```text
                 ┌─────────────┐
 Internet  ───►  │    Nginx    │  (TLS termination, static assets, reverse proxy)
                 └──────┬──────┘
                        │
          ┌─────────────┼───────────────┐
          ▼                             ▼
   Frontend (static build)      Python API (one or more instances)
                                        │
                         ┌──────────────┼───────────────┐
                         ▼                              ▼
                    PostgreSQL                     Background Workers
                                                          │
                                                     Model Layer
                                                          │
                                              (future) Qwen providers
```

Configuration (`ENVIRONMENT`, database URL, secrets, etc.) is supplied
via environment variables per deployment target
(development/staging/production); nothing environment-specific is
hardcoded in application code.

## Data Model

Established in Phase 2. All tables live under `src/models/`, one
module per entity, registered on the shared `Base` declarative base
(`src/db/base.py`) and versioned through Alembic migrations
(`alembic/versions/`).

### Entity-Relationship Overview

```text
Group  1───N  User  1───N  Chat  N───1  AIModel
                       │           │
                       │           └──1───N Chat (a model can back many chats)
                       │
                       └──N  AuditLog (actor, nullable — system actions have no actor)
                       │
                       └──N  Usage
                                │
Chat  1───N  Message  1───(0/1)─ Usage (a usage record may reference the message that produced it)
Chat  1───N  Usage
AIModel  1───N  Usage
```

- **Group → User**: one-to-many. `users.group_id` is nullable
  (`ON DELETE SET NULL`) — a user can exist without a group, and
  deleting a group does not delete its members.
- **User → Chat**: one-to-many, `ON DELETE CASCADE` — deleting a user
  removes their chats (and, transitively, their messages).
- **AIModel → Chat**: one-to-many, `ON DELETE RESTRICT` — a model that
  is in use by any chat cannot be deleted (disable it via
  `is_enabled` instead).
- **Chat → Message**: one-to-many, `ON DELETE CASCADE`.
- **Usage**: references `user`, `model` (both required), and
  optionally `chat`/`message` (`ON DELETE SET NULL`) — usage records
  are accounting data and are kept even if the chat/message they
  originated from is later removed.
- **AuditLog**: references `actor_user_id` only, as a nullable,
  `ON DELETE SET NULL` foreign key — audit entries must outlive the
  user account they're about, and some actions are system-initiated
  with no human actor at all. `target_type`/`target_id` are plain
  strings (not foreign keys) for the same reason: the audited target
  may no longer exist.

### Roles

`Role` (`USER`, `MANAGER`, `DEVELOPER`, `OWNER`) is stored as a single
column on `users`, not a separate permissions table. It's deliberately
just an ordered set of values (`ROLE_RANK` in `src/models/enums.py`
gives each a numeric rank) so that a future, single, central
authorization utility can compare rank (`ROLE_RANK[user.role] >=
ROLE_RANK[Role.MANAGER]`) instead of every endpoint hardcoding
`if role == "..."` checks. No such utility is implemented yet — Phase
2 only establishes the data shape it will sit on top of.

### Enum Storage Strategy

All enum-like columns (`role`, `status` fields, `category`, etc.) are
stored as `VARCHAR` with a database-level `CHECK` constraint
(`native_enum=False, create_constraint=True` in SQLAlchemy), rather
than native PostgreSQL `ENUM` types. This means:

- The exact same schema works against SQLite, which has no enum type —
  useful for fast local/unit test runs.
- Adding a new value later is a normal migration, not PostgreSQL's
  transaction-restricted `ALTER TYPE ... ADD VALUE`.
- Invalid values are still rejected at the database layer, not just
  in application code.

### Token Accounting

Both `messages` and `usage_records` store `input_tokens`,
`output_tokens`, and `total_tokens`, each with `CHECK` constraints
enforcing non-negative values and `total_tokens = input_tokens +
output_tokens`. `usage_records` is intentionally denormalized (it
duplicates `user_id`/`chat_id` rather than requiring a join through
`messages`) because usage/quota reporting is expected to be a frequent
query pattern at 500+ users and should not require joining through
every message.

### Indexing for Expected Query Patterns (500+ users)

| Pattern | Index |
|---|---|
| "My recent chats" | `chats(user_id, updated_at)` |
| "My active/archived chats" | `chats(user_id, status)` |
| "Messages in a chat, in order" | `messages(chat_id, created_at)` |
| "My usage over time" / quota checks | `usage_records(user_id, timestamp)` |
| "Usage by model" (capacity planning) | `usage_records(model_id, timestamp)` |
| "Usage for a specific chat" | `usage_records(chat_id, timestamp)` |
| "Audit trail for a user" | `audit_logs(actor_user_id, timestamp)` |
| "Audit trail for a specific target" | `audit_logs(target_type, target_id)` |
| Login/lookup by identifier | unique indexes on `users.username`, `users.email` |

### Primary Keys

All tables use UUID surrogate primary keys (`sqlalchemy.Uuid`,
generated client-side via `uuid.uuid4()`), so IDs are safe to expose
in API responses/URLs without leaking sequential volume information
(e.g. total user or message count), and can be generated before an
insert if a future feature needs that (e.g. optimistic client-side
creation).

### Not Yet Implemented

No authentication or authorization *logic* exists yet — only the
supporting columns (`password_hash`, `status`, `role`) and the `Role`
enum. No model provider is wired to the `models` table's rows yet
(that's `src/model_layer/`, still a placeholder per ADR 0002). See
`docs/adr/0005-data-model-design.md` for the detailed rationale behind
these choices.

## Authentication and Authorization

Established in Phase 3. Implemented in `src/core/security.py` (hashing
+ JWT), `src/models/auth_session.py` (revocable sessions),
`src/auth/dependencies.py` (the single request-level enforcement
point), `src/services/auth_service.py` /
`src/services/user_service.py` (business logic), and the
`auth`/`users`/`system`/`admin` routers.

### Registration → Approval Flow

```text
Register (POST /api/v1/auth/register)
   -> status=PENDING, role=USER (always — see ADR 0006)
   ↓
Manager approval (POST /api/v1/users/{id}/approve, own group only)
  or Owner approval (any group)
   ↓
Active (can now log in)
```

Rejection (`POST /api/v1/users/{id}/reject`) sets `status=INACTIVE`
instead. Every step writes an `AuditLog` entry. See ADR 0006 for the
full group-assignment policy — in short: `role` is never
client-settable at registration (there is no `role` field on the
request schema at all), and requesting a `group_id` only routes the
pending account to that group's Manager, it grants no privilege.

### Login / Session Handling

Access tokens are JWTs (`HS256`, `SECRET_KEY`), but a JWT's signature
alone can't be revoked before it expires. Every issued token carries a
`jti` claim that must match a non-revoked row in `auth_sessions`
(Phase 3's addition to the schema). `POST /api/v1/auth/logout` revokes
that row immediately — the same token is rejected on the very next
request, not just after its natural expiry.

`get_current_user` (the sole authentication dependency; every
protected route depends on it, directly or via `require_min_role`)
re-validates on **every request**, not just at login:

```text
token present -> signature/expiry valid -> session not revoked
  -> user still exists -> account status == ACTIVE
```

That last check is why suspending an account takes effect immediately:
an already-issued, still-unexpired, non-revoked token is rejected the
moment `user.status` stops being `ACTIVE`.

### Roles

`Role` (`USER < MANAGER < DEVELOPER < OWNER`, see ADR 0005) is enforced
through exactly two dependency factories in
`src/auth/dependencies.py`, so no router hardcodes role-name
comparisons:

- **`require_min_role(role)`** — rank-based threshold, via
  `ROLE_RANK`. Used where privilege is naturally hierarchical (e.g.
  approving users requires Manager-or-above; admin endpoints require
  Owner, which is top-ranked so `require_min_role(Role.OWNER)` also
  correctly excludes everyone else).
- **`require_roles(*roles)`** — exact-set membership, for
  non-hierarchical grants. Not currently used by any route (Developer
  access is expressed as `require_min_role(Role.DEVELOPER)`, which
  also — correctly — admits Owner), but kept available for a future
  case where privilege isn't a simple ordered scale.

Group-scoped checks (Manager-of-own-group) are inherently
resource-specific and live in `can_manage_group`
(`src/auth/dependencies.py`), called from `user_service.py` — not
duplicated per-endpoint.

| Role | Can | Enforced by |
|---|---|---|
| User | View/manage own profile, own usage | `is_self_or_owner` |
| Manager | View users in own group; approve/reject pending users in own group; view own-group usage | `can_manage_group` |
| Developer | View application logs, model status, diagnostics, performance — **not** other users' data | `require_min_role(Role.DEVELOPER)` on `/system/*`; `/users` list and `/users/{id}` still enforce self-or-Owner-or-Manager-of-group, so Developer gets 403 there |
| Owner | Manage users (role/status/group), groups, models, global (non-secret) config, audit logs, global usage | `require_min_role(Role.OWNER)` on `/admin/*` |

### Endpoint Map

```text
POST   /api/v1/auth/register        public
POST   /api/v1/auth/login           public
POST   /api/v1/auth/logout          authenticated
GET    /api/v1/auth/me              authenticated

GET    /api/v1/users/me             authenticated (self)
GET    /api/v1/users/me/usage       authenticated (self)
GET    /api/v1/users                Manager (own group) | Owner (all)
GET    /api/v1/users/groups/{id}/usage   Manager (own group) | Owner (any)
GET    /api/v1/users/{id}           self | Manager (same group) | Owner
POST   /api/v1/users/{id}/approve   Manager (own group) | Owner
POST   /api/v1/users/{id}/reject    Manager (own group) | Owner

GET    /api/v1/system/logs          Developer+
GET    /api/v1/system/models        Developer+
GET    /api/v1/system/diagnostics   Developer+
GET    /api/v1/system/performance   Developer+

GET/POST   /api/v1/admin/groups           Owner
PATCH      /api/v1/admin/users/{id}       Owner
GET/POST   /api/v1/admin/models           Owner
PATCH      /api/v1/admin/models/{id}      Owner
GET        /api/v1/admin/audit-logs       Owner
GET        /api/v1/admin/usage            Owner
GET        /api/v1/admin/config           Owner (non-secret fields only)
```

### Request Tracing

`RequestIDMiddleware` (`src/core/middleware.py`) assigns (or
propagates, via `X-Request-ID`) a request ID to every request, echoed
back in the response header and threaded through to `AuditLog.request_id`
and application logs — so a single request's audit trail and log
lines can be correlated.

## Model Abstraction Layer

Established in Phase 4 (the abstraction) and integrated with real
models in Phase 5 (Qwen 2.5 Coder 7B, Qwen 2.5 NLP/Instruct 7B) — see
ADR 0007 and ADR 0008.

```text
ChatService -> ModelRouter -> ModelRegistry -> ModelProvider -> QwenProvider (or MockProvider)
```

- **`ChatService`** (`src/services/chat_service.py`) — the chat
  system's only entry point into the model layer. Depends solely on
  `ModelRouter`; has no knowledge of `ModelRegistry` or any concrete
  provider. Translates every provider/router failure into
  `ChatServiceError` (a safe, generic message) while logging full
  diagnostic detail internally — provider-agnostic, so this works
  identically whether the underlying provider is `MockProvider` or
  `QwenProvider`.
- **`ModelRouter`** (`src/model_layer/router.py`) — resolves a
  `model_key` (or a `ModelCategory`, for "any enabled CODER model"
  -style requests) to a live `ModelProvider`, raising a typed error
  (`ModelNotFoundError`, `ModelUnavailableError`,
  `NoProviderForCategoryError`) if it can't.
- **`ModelRegistry`** (`src/model_layer/registry.py`) — in-memory,
  process-local index of `model_key -> ModelRegistration`
  (register/enable/disable/get/list/check_availability/get_capabilities).
  **Not** the same thing as the `models` database table (`AIModel`,
  Phase 2/3): the table is the durable, Owner-editable record of which
  models are configured to exist (seeded with both Qwen models in
  Phase 5 — see the seed migration); the registry is the runtime index
  mapping each one's key to a live provider instance, built at process
  startup by `src/main.py`'s lifespan calling
  `model_layer.bootstrap.register_default_providers`. See ADR 0007/0008.
- **`ModelProvider`** (`src/model_layer/provider_interface.py`) — the
  interface every concrete provider implements: `generate`, `stream`,
  `capabilities`, `health_check`. Nothing above this interface may
  import a concrete provider class directly.
- **Domain schemas** (`src/model_layer/schemas.py`) — `ModelRequest`,
  `ModelResponse`, `StreamingChunk`, `ModelCapabilities` are the only
  objects that cross any boundary in this stack; provider-specific
  tuning goes in `ModelRequest.options` (an open dict), not new schema
  fields.
- **Error hierarchy** (`src/model_layer/errors.py`) —
  `ModelUnavailableProviderError`, `ModelTimeoutError`,
  `InvalidModelRequestError`, `ModelLoadingError`, `ModelRuntimeError`,
  `ModelStreamInterruptedError`. Every provider maps its own failures
  onto these before they cross the interface boundary; `ChatService`
  catches only these (plus a defensive catch-all), never a
  provider-specific exception.
- **`MockProvider`** (`src/model_layer/providers/mock_provider.py`) —
  a complete, dependency-free `ModelProvider` implementation used to
  prove the whole stack end-to-end.
- **`QwenProvider`** (`src/model_layer/providers/qwen/provider.py`,
  Phase 5) — an HTTP client for an already-running, OpenAI-compatible
  inference server (vLLM/TGI-style) hosting a Qwen model. Does not
  load or download weights itself. Configuration
  (`src/model_layer/providers/qwen/config.py`) is entirely
  environment-variable driven, independently per model
  (`QWEN_CODER_*` / `QWEN_NLP_*` — see `.env.example`): model path,
  endpoint, context length, max output tokens, temperature, streaming,
  device/dtype/GPU memory fraction. No machine-specific path is
  hardcoded anywhere. Registration is opt-in
  (`QWEN_CODER_ENABLED`/`QWEN_NLP_ENABLED`, default disabled), so the
  app starts fine with no inference server running.

Adding a new/future provider (a new Qwen version or a different
backend entirely) is a new file in `providers/` implementing
`ModelProvider`, plus one `registry.register(...)` call in
`bootstrap.py` — no changes to `ModelRouter`, `ChatService`, any
schema, or any file outside `src/model_layer/`.

## Chat Backend

Established in Phase 6 — see ADR 0009 for full design rationale.

```text
API routers (chats.py, messages.py)
  -> ConversationService (persistence + orchestration)
      -> repositories (chat/message/model)          [DB]
      -> ChatService (Phase 5, model-orchestration)  -> ModelRouter -> ... -> QwenProvider/MockProvider
```

### Endpoints

```text
POST   /api/v1/chats                    create (model_key required, title optional)
GET    /api/v1/chats                    list own chats (status filter, pagination)
GET    /api/v1/chats/{id}               get one
PATCH  /api/v1/chats/{id}               update title/status/model
DELETE /api/v1/chats/{id}               soft delete (status=DELETED)
GET    /api/v1/chats/{id}/history       active conversation thread

POST   /api/v1/chats/{id}/messages      send a prompt (stream: bool)
POST   /api/v1/messages/{id}/edit       edit a prompt -> new revision (+ cascades one reply)
POST   /api/v1/messages/{id}/regenerate regenerate a reply -> new revision
GET    /api/v1/messages/{id}/revisions  all revisions of a message's slot
POST   /api/v1/messages/{id}/activate   make a revision active (server-persisted undo/redo)
```

### Revision model

A "slot" is a logical position in a conversation (one prompt, or the
one reply that follows it). Editing/regenerating never overwrites or
deletes — it inserts a new row in the same slot
(`root_message_id` + `sequence_number` + `revision`, see the
docstring in `src/models/message.py`) and flips `is_active`. History
is never destroyed; `GET /messages/{id}/revisions` can always retrieve
every prior version, and `POST /messages/{id}/activate` can always
restore one.

### Ownership

Every operation resolves through `ConversationService`'s
`_get_owned_chat`/`_get_owned_message`, which require exact
`chat.user_id == requester.id` — no Owner/Manager bypass (chats are
private content; see ADR 0009 point 4).

### Streaming

`POST .../messages` (and edit/regenerate) with `"stream": true` return
Server-Sent Events. Every `data:` line is a `StreamEventOut` — the
same shape regardless of which model provider produced it (Mock or
Qwen); the terminal event always carries `is_final`, `finish_reason`,
the persisted `message_id`, and token counts, even on failure
(`finish_reason="error"`). Persistence of the completed message
happens in a dedicated `AsyncSessionLocal`-backed session
(`src.services.conversation_service.stream_generation`), not the
request-scoped one, since a streaming response's body is consumed
after the route handler returns.

## Quotas and Limits

Established in Phase 7 — see ADR 0010 for full design rationale.

Two independently-configurable limits, both resolved as **user
override > group override > global default**:

```text
Chat limit:   max active (status=ACTIVE) chats per user
Token quota:  max input+output tokens per user within the renewal window
```

Overrides live on `Group`/`User` (nullable `Integer` columns), managed
via `PATCH /api/v1/admin/groups/{id}` / `PATCH /api/v1/admin/users/{id}`
(Owner only). Global defaults and the renewal policy are
environment-configurable (`Settings.default_max_active_chats`,
`default_token_quota`, `token_quota_renewal_policy`).

### Renewal policy

Configurable: `ROLLING_24H` (default — trailing 24h from "now",
continuously sliding) or `DAILY_RESET_UTC` (fixed UTC-midnight reset).
Both are always computed as `SUM(usage_records.total_tokens)` over the
window — never a separately-mutable counter.

### Concurrency safety

- **Chat limit**: `pg_advisory_xact_lock` held across the whole
  count-then-insert (cheap — no external call involved).
- **Token quota**: the lock is held only for a brief check-and-insert
  of a `QuotaReservation` row (a conservative token estimate,
  `Settings.quota_reservation_estimated_output_tokens`), released
  immediately — never held across the (potentially many-second) model
  call. Concurrent requests see each other's open reservations in
  their own quota check, closing the race a bare usage-sum check would
  leave open.

### Charging policy

A failed model request (`ChatServiceError`, from Phase 5/6) is never
charged: the reservation is released, no `Usage` row is created —
consistent with Phase 6's existing "a failed generation persists no
message" policy (ADR 0009).

### API

`GET /api/v1/users/me/quota` (self) and `GET /api/v1/users/{id}/quota`
(self, Owner, or Manager-of-same-group) return `used_tokens`,
`quota_tokens`, `percent_used`, `renewal_policy`, `renews_at`,
`active_chats`, `max_active_chats` — everything a frontend needs to
show "62%", "62,000 / 100,000", and a renewal time.

## Security Boundaries

See `SECURITY.md` for the full security model. In summary: all
authorization is enforced in the Python backend; the frontend and
Nginx are never trusted to make authorization decisions; secrets are
never hardcoded or logged.
