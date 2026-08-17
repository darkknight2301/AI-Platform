# Security

This document describes the security boundaries established across
Phases 1-3. It will be extended as model-facing functionality is
implemented in later phases.

## Core Principles

- **All authorization is enforced server-side**, in the Python
  backend. The frontend is never trusted to make or enforce
  authorization decisions — it is treated as untrusted client code.
- **No secrets are hardcoded.** All credentials, API keys, and
  environment-specific values are supplied via environment variables
  (see `backend/.env.example`). `.env` files are excluded from version
  control.
- **No secrets are logged.** The structured logger
  (`backend/src/core/logging.py`) logs application events, not request
  bodies or credential material; call sites are responsible for never
  passing secrets into log calls, including authentication tokens.
- **Passwords are never stored in plaintext.** Registration hashes
  every password with bcrypt (`src/core/security.py`) before it
  touches the database; `verify_password` never compares plaintext to
  plaintext.
- **Internal model endpoints are never exposed directly.** All access
  to model backends will go through the Python API and the model
  layer abstraction — never proxied directly to end users or the
  frontend.

## Trust Boundaries

```text
[Untrusted]                         [Trusted]
Browser / Frontend  ──HTTP──►  Nginx  ──HTTP──►  Python API  ──►  Database
                                                       │
                                                       ▼
                                                 Model Layer (internal only)
```

- Anything originating from the browser (including any client-supplied
  role/permission claims) is untrusted input and must be re-validated
  server-side.
- Nginx performs TLS termination and routing only — it does not make
  authorization decisions and contains no business logic.
- The model layer and any underlying model backends are internal-only;
  they are never directly reachable from the internet or the frontend.

## Configuration & Secrets Management

- `backend/.env.example` and `frontend/.env.example` enumerate every
  configuration variable an operator must supply. Neither file
  contains real values.
- `SECRET_KEY` (used to sign access tokens, see
  `src/core/security.py`) must be a long, random value, unique per
  environment, and must never be committed. The `.env.example` file
  documents how to generate one locally.
- Database credentials are supplied via `DATABASE_URL` and are never
  embedded in application code.

## CORS

CORS origins are environment-driven (`CORS_ALLOW_ORIGINS`), defaulting
to the local frontend dev server only. Production deployments must set
this explicitly to the real frontend origin(s) — a wildcard origin
combined with credentialed requests must not be used in production.

## Current Scope

As of Phase 7:

- Chat and token usage are now bounded: every chat creation and model
  call is gated by `src/services/quota_service.py`'s concurrency-safe
  limit checks (`pg_advisory_xact_lock` — see ADR 0010), preventing a
  single user (or a burst of concurrent requests from one user) from
  unbounded resource consumption. A failed model call is never
  charged against quota.

- Authentication and role-based authorization are implemented (see
  ARCHITECTURE.md's "Authentication and Authorization" section).
  Passwords are hashed with bcrypt (`src/core/security.py`) — never
  stored or logged in plaintext. Access tokens are JWTs backed by a
  revocable `auth_sessions` table, so logout and account suspension
  take effect immediately rather than waiting for token expiry.
- Every authentication and authorization-relevant action (register,
  login success/failure/denial, logout, approve/reject, admin
  changes) writes an `AuditLog` entry — this table is no longer just
  schema, it's actively written to. Chat/message CRUD deliberately
  does NOT write to this table (see ADR 0009, point 9) — it remains
  reserved for account/security/administrative actions.
- Role is never client-settable at registration — there is no `role`
  field on the registration request schema at all (see ADR 0006). The
  only way to change a user's role or group after registration is the
  Owner-only `PATCH /api/v1/admin/users/{id}` endpoint.
- `GET /api/v1/admin/config` exposes only non-secret configuration
  (`app_name`, `environment`, rate limit, token expiry) — `secret_key`
  and any credential/connection-string value are never included, and
  this is enforced by the response schema (`GlobalConfigOut`) only
  declaring those specific fields, not by filtering a larger object.
- Developer-role endpoints (`/api/v1/system/*`) expose operational
  data (logs, model status, diagnostics, performance) only — they do
  not expose other users' chats, profiles, or PII. `Role.DEVELOPER`
  does not grant access to `/api/v1/users` or `/api/v1/users/{id}` for
  another user; those still enforce self/Owner/Manager-of-same-group.
- Two real model providers (Qwen 2.5 Coder 7B, Qwen 2.5 NLP/Instruct
  7B) are integrated behind the model abstraction (see ARCHITECTURE.md's
  "Model Abstraction Layer" and ADR 0008). `QwenProvider`'s API key
  (`QWEN_*_API_KEY`), if configured, is only ever sent as an outbound
  `Authorization` header to the configured backend — never logged (see
  `QwenProvider._log_error`, which logs only error kind/type/model_key,
  never headers, request bodies, or response bodies).
- Every Qwen-backend failure (unavailable, timeout, invalid request,
  loading, runtime error, streaming interruption) is mapped to a
  generic, safe-to-display error before it reaches `ChatService`'s
  caller; internal diagnostic detail (exception type, status code) is
  logged via the structured logger, never the raw response body (which
  could echo request content back).
- The chat/message HTTP API (Phase 6) is now the model-facing attack
  surface: every chat/message operation requires authentication and
  enforces strict per-user ownership (`ConversationService`,
  `chat.user_id == requester.id`, no Owner/Manager bypass — see
  ARCHITECTURE.md's "Chat Backend" section and ADR 0009, point 4). A
  failed model call never destroys existing conversation state (ADR
  0009, point 5), and streaming responses always terminate with a
  well-formed event even on failure, never a raw exception (ADR 0009,
  point 7) — the same safe-error-handling guarantee established in
  Phase 5 now reaches all the way to the HTTP client.

## Planned (Later Phases)

- Rate limiting, enforced server-side (`RATE_LIMIT_REQUESTS_PER_MINUTE`
  is defined in configuration now but not yet enforced).
- Request queuing/backpressure at the model layer so the model
  infrastructure's concurrency limits are never exceeded regardless of
  web-tier load.
- Password reset / account recovery flow.
- Dependency and container vulnerability scanning as part of CI, once
  a CI pipeline is introduced.

## Reporting

This is an internal foundation document, not a public disclosure
policy. Update this section with an internal reporting process once
one is established.
