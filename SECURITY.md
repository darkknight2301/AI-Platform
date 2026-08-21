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

As of Phase 8:

- The chat frontend (React SPA, `frontend/`) stores the JWT access
  token in `localStorage` and sends it as a standard `Authorization:
  Bearer` header on every API call — never as a cookie, so it isn't
  automatically attached to requests to other origins. The frontend
  performs no server-side rendering and holds no secrets of its own
  (no API keys, no database credentials); its only sensitive artifact
  is the user's own access token, scoped to that user's own session
  (revocable via logout — Phase 3).
- No attachment/file-upload/image-upload code path exists anywhere in
  the frontend (explicitly excluded, Phase 8) — there is no
  multipart-upload attack surface to consider.
- Markdown rendering (`react-markdown`) does not execute raw HTML from
  message content by default; message content is always treated as
  data, never as trusted markup.

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

## Phase 10 — Observability, Audit, Security

- **Structured logging**: `RequestLoggingMiddleware`
  (`src/core/middleware.py`) emits one JSON log line per request —
  timestamp, request_id, user_id, endpoint, model (when applicable),
  duration_ms, status, error_type. It never logs request/response
  bodies, so prompts and replies are excluded by construction, not by
  a filter that could be bypassed. `error_type` for handled
  `HTTPException`s is captured via a dedicated exception handler in
  `main.py`; unhandled exceptions are caught, logged, and re-raised so
  Starlette's own 500 handling is unchanged.
- **Rate limiting / brute-force protection**: `RateLimitMiddleware`
  enforces `RATE_LIMIT_REQUESTS_PER_MINUTE` per caller. The caller's
  identity comes from `resolve_client_key()` (`src/core/middleware.py`):
  by default the raw connection address (correct when the app is
  reachable directly, e.g. local dev/tests), or `X-Forwarded-For`/
  `X-Real-IP` when `TRUST_PROXY_HEADERS=true` — which must only be set
  when the backend is reachable *exclusively* through a proxy that sets
  those headers itself (nginx does; see `nginx/nginx.conf.template`).
  `docker-compose.prod.yml` sets `TRUST_PROXY_HEADERS=true` because the
  backend there is `expose`-only, never published on the host — the
  precondition the setting requires. Earlier revisions of this
  middleware keyed on the raw connection address unconditionally, which
  behind that same nginx topology collapsed every request to nginx's
  upstream address rather than the real client; this has been fixed.
  Storage is pluggable: in-memory (`InMemoryRateLimitStore`,
  process-local, the default) or Redis (`RedisRateLimitStore`, shared
  across replicas, selected by setting `RATE_LIMIT_REDIS_URL`) —
  `docker-compose.prod.yml` runs a `redis` service and wires this by
  default, since that compose file defaults to `BACKEND_REPLICAS=2`.
  The Redis path fails open (allows the request, logs a warning) on any
  Redis error, since this is defense-in-depth, not the primary access
  control. Separately, `auth_service.authenticate` locks out an
  identifier (username/email) for 15 minutes after 5 recent `LOGIN`
  `FAILURE` audit entries — this check is driven by the audit log
  itself, not a separate in-memory counter, so it survives process
  restarts and is consistent across instances regardless of the
  rate-limiter configuration above.
- **CSRF**: not implemented, deliberately. The API is Bearer-token
  authenticated (`Authorization` header from `localStorage`), never
  cookie-based — see "Current Scope" above. CSRF relies on the
  browser automatically attaching credentials (cookies) to
  cross-origin requests; there's nothing here for a forged
  cross-origin form submission to attach. Revisit if a cookie-based
  session is ever introduced.
- **Security headers**: `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy` are set both at the nginx layer
  (`nginx/nginx.conf.template`) and, for defense-in-depth, directly by
  the FastAPI app (`main.py`) — the API is reachable directly in dev
  and tests where nginx isn't in front of it.
- **Audit coverage extended**: `DELETE_CHAT` and `PROMPT_EDIT` are now
  audit-logged (`src/services/conversation_service.py`), alongside the
  registration/login/logout/approval/role/model/quota events already
  covered since earlier phases. Chat/message *content* is still never
  written to the audit log — only that the action occurred, by whom,
  and against which chat/message id.
- **IDOR / RBAC bypass / group isolation**: exercised directly by
  `backend/tests/integration/test_admin_dashboards.py` (Phase 9) and
  `test_phase10_security.py` (Phase 10) — a User can't reach another
  user's chats, a Manager can't reach another group, a Developer can't
  reach `/admin/*`, and a plain user gets 403 on every elevated
  endpoint tested.
- **Input validation / SQL injection**: every DB access goes through
  SQLAlchemy's async ORM/Core with bound parameters — no endpoint
  builds a query by string-formatting user input (verified by
  inspection: the only raw `text()` calls in the codebase are a static
  `SELECT 1` health check and a parameterized advisory-lock call).
  Every request body is a Pydantic schema with explicit
  length/pattern constraints (see `schemas/auth.py`,
  `schemas/message.py`).
- **XSS**: chat content is rendered via `react-markdown`
  (`frontend/src/components/Markdown.tsx`), which treats message
  content as data and does not execute raw HTML by default; no
  `dangerouslySetInnerHTML`/`innerHTML` usage exists anywhere in the
  frontend (verified by inspection).
- **Sensitive data exposure**: `GET /api/v1/admin/config` continues to
  expose only the fields declared on `GlobalConfigOut` — `secret_key`
  and `database_url` are structurally absent from that schema, not
  filtered out of a larger object. Covered by
  `test_config_endpoint_never_exposes_secret_key`.

## Planned (Later Phases)

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
