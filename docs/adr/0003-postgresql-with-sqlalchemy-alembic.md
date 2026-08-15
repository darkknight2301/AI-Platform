# 0003 — Use PostgreSQL with SQLAlchemy (async) and Alembic

## Status
Accepted

## Context
The application must support 500+ registered users, multiple groups,
and concurrent requests, with database-enforced constraints for data
integrity. It needs a migration story that scales past ad-hoc schema
changes.

## Decision
Use PostgreSQL as the production/staging database, accessed through
SQLAlchemy's async ORM (2.0-style), with schema migrations managed by
Alembic. Alembic's `env.py` reads the connection string from the
application's own `Settings` object rather than a separately
maintained config value, so migrations always target the same database
the app would use for the active environment.

For fast local test runs, the same SQLAlchemy engine can point at
SQLite (`sqlite+aiosqlite:///:memory:`) instead of PostgreSQL, since no
application code branches on database vendor for the functionality
implemented so far. This keeps the test suite fast and independent of
a running PostgreSQL instance without introducing a second data-access
code path.

## Consequences
- Production and staging always run PostgreSQL, satisfying the
  concurrency/constraint requirements of a 500+ user system.
- Local/CI test runs are fast and don't require provisioning a
  database server for the foundation-phase test suite.
- If future functionality relies on PostgreSQL-specific features (e.g.
  JSONB operators, specific constraint types), integration tests for
  that functionality should run against real PostgreSQL rather than
  SQLite — this should be revisited per-feature as the schema grows.
