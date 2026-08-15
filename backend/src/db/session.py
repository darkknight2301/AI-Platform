"""
Async SQLAlchemy engine and session management.

Production uses PostgreSQL (asyncpg driver). The engine is built purely
from configuration so alternate drivers (e.g. sqlite+aiosqlite for fast
local/test runs) work without code changes.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings

settings = get_settings()

_engine_kwargs = {"echo": settings.database_echo, "pool_pre_ping": True}

# SQLite (used for lightweight test runs) does not support pool sizing
# parameters that asyncpg/psycopg understand, so only pass them for
# server-backed databases.
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs["pool_size"] = settings.database_pool_size
    _engine_kwargs["max_overflow"] = settings.database_max_overflow

engine = create_async_engine(settings.database_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a request-scoped DB session."""
    async with AsyncSessionLocal() as session:
        yield session
