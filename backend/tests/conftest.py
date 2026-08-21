"""
Shared pytest fixtures.

Tests run against an in-memory SQLite database (via the aiosqlite
driver) rather than requiring a live PostgreSQL server. The engine is
built purely from `DATABASE_URL`, so this is a drop-in swap — no
application code branches on "test mode".
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("LOG_JSON", "false")
# The RateLimitMiddleware (Phase 10) is process-global and shared by
# every test in this session via the single `app` instance — a limit
# tuned for a real deployment would make unrelated tests flake once
# the suite's cumulative request count crosses it within the same
# 60s window. Raise it here rather than disable it, so rate-limiting
# itself still gets exercised deliberately in test_phase10_security.py.
os.environ.setdefault("RATE_LIMIT_REQUESTS_PER_MINUTE", "10000")

from src.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _test_settings():
    settings = get_settings()
    assert settings.environment.value == "test"
    yield settings


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    from src.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
