# Architecture Decision Records

This directory records significant architecture decisions and their
rationale, so future contributors understand why the system looks the
way it does, not just what it looks like.

| ADR | Title |
|-----|-------|
| [0001](./0001-python-fastapi-backend.md) | Use Python/FastAPI as the sole backend language and framework |
| [0002](./0002-model-provider-abstraction.md) | Isolate model backends behind a provider abstraction |
| [0003](./0003-postgresql-with-sqlalchemy-alembic.md) | Use PostgreSQL with SQLAlchemy (async) and Alembic |
| [0004](./0004-vite-typescript-frontend.md) | Use a minimal Vite/TypeScript frontend for the foundation phase |
| [0005](./0005-data-model-design.md) | Data model design: UUID keys, portable enums, denormalized usage accounting |
