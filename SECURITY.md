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

As of Phase 3:

- Authentication and role-based authorization are implemented (see
  ARCHITECTURE.md's "Authentication and Authorization" section).
  Passwords are hashed with bcrypt (`src/core/security.py`) — never
  stored or logged in plaintext. Access tokens are JWTs backed by a
  revocable `auth_sessions` table, so logout and account suspension
  take effect immediately rather than waiting for token expiry.
- Every authentication and authorization-relevant action (register,
  login success/failure/denial, logout, approve/reject, admin
  changes) writes an `AuditLog` entry — this table is no longer just
  schema, it's actively written to.
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
- No model backend is integrated yet, so there is no model-facing
  attack surface yet.

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
