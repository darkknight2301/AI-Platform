# Security

This document describes the security boundaries established as part
of the Phase 1 foundation. It will be extended as authentication,
authorization, and model-facing functionality are implemented in later
phases.

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
- **Passwords are never stored in plaintext.** (No password storage
  exists yet as of Phase 1; when authentication is implemented, this
  will use a standard salted hashing algorithm, e.g. bcrypt/argon2.)
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
- `SECRET_KEY` (used for token signing, once authentication is
  implemented) must be a long, random value, unique per environment,
  and must never be committed. The `.env.example` file documents how to
  generate one locally.
- Database credentials are supplied via `DATABASE_URL` and are never
  embedded in application code.

## CORS

CORS origins are environment-driven (`CORS_ALLOW_ORIGINS`), defaulting
to the local frontend dev server only. Production deployments must set
this explicitly to the real frontend origin(s) — a wildcard origin
combined with credentialed requests must not be used in production.

## Current Scope

As of Phase 2:

- No authentication or authorization *logic* is implemented yet
  (`backend/src/auth/` is a structural placeholder). There are
  currently no protected endpoints — only the public health check.
- The database schema now exists (`users`, `groups`, `chats`,
  `messages`, `models`, `usage_records`, `audit_logs`), but nothing
  reads or writes it from the API yet — no business endpoints exist.
- `users.password_hash` is a plain string column; no hashing routine
  is implemented yet. When authentication is added, this column must
  only ever be written via a proper password-hashing function
  (bcrypt/argon2) — never a plaintext or reversibly-encrypted value.
- The `audit_logs` table exists so that, once actions exist to audit,
  entries can be written from day one rather than retrofitted later.
  Its `audit_metadata` JSON field must never be used to store secrets
  or tokens (see "No secrets are logged" above — the same rule applies
  to structured audit data).
- No model backend is integrated yet, so there is no model-facing
  attack surface yet.

## Planned (Later Phases)

- Authentication (session/token-based identity verification).
- Authorization (role/permission/group-based access control),
  enforced via FastAPI dependencies on every protected route.
- Rate limiting, enforced server-side (`RATE_LIMIT_REQUESTS_PER_MINUTE`
  is defined in configuration now but not yet enforced).
- Request queuing/backpressure at the model layer so the model
  infrastructure's concurrency limits are never exceeded regardless of
  web-tier load.
- Dependency and container vulnerability scanning as part of CI, once
  a CI pipeline is introduced.

## Reporting

This is an internal foundation document, not a public disclosure
policy. Update this section with an internal reporting process once
one is established.
