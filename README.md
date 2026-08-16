# AI Platform

Production application foundation for a multi-model AI platform serving
500+ users. This repository is being built in phases; **Phase 1
(Foundation and Architecture)** is complete. No chat/model business
logic has been implemented yet — see `ARCHITECTURE.md` for the planned
model-independence design and `docs/adr/` for key decisions.

## Repository Layout

```text
.
├── backend/            Python/FastAPI application
│   ├── src/
│   │   ├── api/         Route definitions (versioned under v1/)
│   │   ├── api/
│   │   │   └── v1/routers/  auth.py, users.py, system.py, admin.py, health.py
│   │   ├── services/     business logic (auth_service, user_service)
│   │   ├── repositories/ data access (user, group, auth_session, audit_log, model, usage)
│   │   ├── models/       SQLAlchemy ORM models (users, groups, chats, messages, models, usage, audit logs, auth_sessions)
│   │   ├── schemas/      Pydantic request/response schemas
│   │   ├── auth/         dependencies.py — authentication + RBAC enforcement
│   │   ├── core/         Config, logging
│   │   ├── db/           Engine/session, declarative base
│   │   ├── model_layer/  ModelRegistry, ModelRouter, ModelProvider interface, errors, mock + Qwen providers
│   │   ├── workers/       Background workers (empty — later phase)
│   │   └── main.py        FastAPI application entrypoint
│   ├── alembic/           Database migrations
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── .env.example
├── frontend/            Minimal Vite + TypeScript frontend
│   ├── src/
│   └── .env.example
├── nginx/
│   └── nginx.conf.template
├── docs/
│   └── adr/              Architecture Decision Records
├── ARCHITECTURE.md
├── SECURITY.md
└── README.md
```

## Prerequisites

- Python 3.11+
- Node.js 20+ (for the frontend)
- PostgreSQL 14+ (production/staging; local dev may use SQLite — see below)
- Nginx (production reverse proxy)

## Backend — Local Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# Edit .env: set SECRET_KEY and DATABASE_URL for your local Postgres instance.

# Create the database (once) and apply migrations
createdb app_db   # or: psql -c "CREATE DATABASE app_db;"
alembic upgrade head

# Start the API
PYTHONPATH=. uvicorn src.main:app --reload
```

The API is served at `http://localhost:8000`. Interactive docs are
available at `/docs` and `/redoc` in non-production environments.

### Database & Migrations

The schema (users, groups, chats, messages, models, usage records,
audit logs — see `ARCHITECTURE.md` for the full entity-relationship
description) is managed entirely through Alembic. `alembic/env.py`
reads the connection string from application settings, so migrations
always target whichever `DATABASE_URL` is active.

```bash
cd backend
alembic upgrade head          # apply all migrations
alembic downgrade base        # roll back to an empty schema
alembic revision --autogenerate -m "describe your change"  # after editing src/models/
```

### Running Tests

```bash
cd backend
PYTHONPATH=. pytest -v
```

Most tests (health check, config, model-metadata checks) run against
an in-memory SQLite database by default (configured in
`tests/conftest.py`) so they don't require a live PostgreSQL instance.

The relational/constraint and authentication/RBAC test suites
(`tests/integration/test_data_model.py`,
`tests/integration/test_auth_rbac.py`) exercise the schema and API
against a **real PostgreSQL database**, since CHECK constraints, FK
`ON DELETE` behavior, and end-to-end auth flows are exactly the kind
of thing that can silently differ between database backends or break
between unit-level mocks and real HTTP dependency injection. Point
them at a disposable database via `TEST_DATABASE_URL` (defaults to
`postgresql+asyncpg://app_user:app_password@localhost:5432/app_test_db`
— **a separate database from the one migrations manage**, since these
tests drop/recreate the schema on every run); if that database isn't
reachable, set `SKIP_PG_TESTS=1` to skip those tests rather than fail
the run. Production and staging always use PostgreSQL — SQLite is a
test/local-dev convenience only.

### Model Layer (Qwen)

Both Qwen models are **disabled by default** — the app starts fine
without any inference server running. To enable one or both, point
them at an already-running OpenAI-compatible inference server (e.g.
vLLM, TGI) via environment variables (see `backend/.env.example` for
the full list per model: `QWEN_CODER_*` / `QWEN_NLP_*`):

```bash
QWEN_CODER_ENABLED=true
QWEN_CODER_ENDPOINT_URL=http://localhost:8001/v1
QWEN_NLP_ENABLED=true
QWEN_NLP_ENDPOINT_URL=http://localhost:8002/v1
```

This application does not download or serve model weights itself —
`QwenProvider` is an HTTP client only. See `ARCHITECTURE.md`'s "Model
Abstraction Layer" section and ADR 0008 for the full design.



```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

The dev server proxies API calls to `VITE_API_BASE_URL` (defaults to
`/api/v1`, intended to be routed through Nginx in deployed
environments).

## Nginx

`nginx/nginx.conf.template` is a starting point for the production
reverse proxy. It routes `/api/*` to the Python backend (with SSE/
WebSocket support and generous streaming timeouts) and serves the
built frontend for everything else. Replace `__SERVER_NAME__` and the
TLS certificate placeholders before deploying — no real domains or
certificates are included.

## Environment Configuration

All configuration is environment-variable driven (`backend/.env.example`,
`frontend/.env.example`). The backend supports four environments:
`development`, `staging`, `production`, `test`. Never commit a `.env`
file with real values.

## Further Reading

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — component responsibilities, data flow, model-independence design.
- [`SECURITY.md`](./SECURITY.md) — security boundaries and practices.
- [`docs/adr/`](./docs/adr/) — architecture decision records.

## Project Status

**Phase 1 — Foundation and Architecture: complete.**
**Phase 2 — Database and Data Model: complete.**
**Phase 3 — Authentication and RBAC: complete.**
**Phase 4 — Model Abstraction and Registry: complete.**
**Phase 5 — Qwen Model Integration: complete.**

Implemented: project structure, environment-driven configuration,
database engine/session setup, structured logging, health check
endpoint, Nginx template, minimal frontend, documentation, the full
relational data model with Alembic migrations, registration with
manager-approval workflow, login/logout with revocable JWT sessions,
role-based authorization, the full model abstraction layer
(`ModelRegistry`, `ModelRouter`, `ModelProvider` interface), and — as
of Phase 5 — two real model providers (Qwen 2.5 Coder 7B, Qwen 2.5
NLP/Instruct 7B) integrated behind that abstraction via
`QwenProvider`, with environment-driven per-model configuration and a
provider-agnostic failure-handling hierarchy. See `ARCHITECTURE.md`'s
"Model Abstraction Layer" section and ADR 0007/0008.

Not yet implemented (by design — later phases): chat/message
business-logic endpoints (the schema and model-layer plumbing exist;
no create-chat/send-message HTTP API yet), background workers, rate
limiting enforcement, password reset flow.
