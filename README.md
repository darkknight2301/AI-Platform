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
│   │   ├── services/     Business logic (empty — Phase 2+)
│   │   ├── repositories/ Data access layer (empty — Phase 2+)
│   │   ├── models/       SQLAlchemy ORM models (empty — Phase 2+)
│   │   ├── schemas/      Pydantic request/response schemas
│   │   ├── auth/         Authentication/authorization (placeholder — Phase 2+)
│   │   ├── core/         Config, logging
│   │   ├── db/           Engine/session, declarative base
│   │   ├── model_layer/  Model provider abstraction (placeholder — later phase)
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

# Run database migrations (once models exist, from Phase 2 onward)
alembic upgrade head

# Start the API
PYTHONPATH=. uvicorn src.main:app --reload
```

The API is served at `http://localhost:8000`. Interactive docs are
available at `/docs` and `/redoc` in non-production environments.

### Running Tests

```bash
cd backend
PYTHONPATH=. pytest -v
```

Tests run against an in-memory SQLite database by default (configured
in `tests/conftest.py`) so they don't require a live PostgreSQL
instance. Production and staging always use PostgreSQL.

## Frontend — Local Setup

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

Implemented: project structure, environment-driven configuration,
database engine/session setup, Alembic migrations scaffold, structured
logging, health check endpoint with automated test, Nginx template,
minimal frontend, documentation.

Not yet implemented (by design — later phases): authentication/
authorization logic, database models/business tables, model provider
implementations, chat functionality, background workers, rate
limiting enforcement.
