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
  (see "Model Independence" below). No model provider is implemented
  yet as of Phase 1.

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
code that consumes the model layer. As of Phase 1, this layer exists
only as a documented placeholder (`src/model_layer/README.md`) — no
provider is implemented yet, per Phase 1 scope control.

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

## Security Boundaries

See `SECURITY.md` for the full security model. In summary: all
authorization is enforced in the Python backend; the frontend and
Nginx are never trusted to make authorization decisions; secrets are
never hardcoded or logged.
