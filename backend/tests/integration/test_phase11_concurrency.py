"""Phase 11 — concurrent API request handling.

Distinct from test_quota.py's concurrency tests, which target one
specific race (can a limit be bypassed by firing requests
simultaneously). This file asks a different question: does the stack
behave correctly — no crashes, no cross-user data leakage, no
deadlocks — when many *different* users hit *different* endpoints at
the same time. Uses the mock provider (fast, deterministic) so this
stays a correctness test, not a model-latency benchmark; see
`backend/perf/locustfile.py` for actual load/perf testing.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.db.base import Base
from src.db.session import get_db
from src.main import app
from src.models.enums import Role, UserStatus
from src.models.user import User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app_user:app_password@localhost:5432/app_test_db",
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PostgreSQL integration tests disabled (SKIP_PG_TESTS=1)",
)


@pytest_asyncio.fixture
async def pg_engine():
    engine = create_async_engine(TEST_DATABASE_URL, pool_size=20, max_overflow=20)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncSession:
    session_factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(pg_engine):
    session_factory = async_sessionmaker(bind=pg_engine, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


async def _make_user(session: AsyncSession, *, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("correct-horse-1"),
        status=UserStatus.ACTIVE,
        role=Role.USER,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _login_headers(client: AsyncClient, username: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": username, "password": "correct-horse-1"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_concurrent_users_creating_chats_stay_isolated(client: AsyncClient, pg_session):
    """20 different users, each creating + listing their own chat at the
    same time. Every user must see exactly their own chat, never
    another's — the concurrency itself shouldn't cause cross-talk."""
    n_users = 20
    for i in range(n_users):
        await _make_user(pg_session, username=f"concurrent_user_{i}")

    headers_list = await asyncio.gather(
        *[_login_headers(client, f"concurrent_user_{i}") for i in range(n_users)]
    )

    resp = await client.get("/api/v1/models", headers=headers_list[0])
    models = resp.json()
    model_key = models[0]["model_key"] if isinstance(models, list) else models["models"][0]["model_key"]

    async def _create_and_verify(i: int, headers: dict):
        resp = await client.post(
            "/api/v1/chats",
            json={"model_key": model_key, "title": f"chat-{i}"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        chat_id = resp.json()["id"]

        resp = await client.get("/api/v1/chats", headers=headers)
        assert resp.status_code == 200
        chats = resp.json()["chats"]
        assert len(chats) == 1
        assert chats[0]["id"] == chat_id
        assert chats[0]["title"] == f"chat-{i}"

    await asyncio.gather(*[_create_and_verify(i, headers_list[i]) for i in range(n_users)])


@pytest.mark.asyncio
async def test_concurrent_sends_across_different_chats_do_not_interfere(
    client: AsyncClient, pg_session
):
    """Multiple simultaneous chats (per Phase 11's checklist item), each
    getting a message sent at the same time, must each get their own
    correct reply — no cross-chat content bleed."""
    user = await _make_user(pg_session, username="multi_chat_user")
    headers = await _login_headers(client, "multi_chat_user")

    resp = await client.get("/api/v1/models", headers=headers)
    models = resp.json()
    model_key = models[0]["model_key"] if isinstance(models, list) else models["models"][0]["model_key"]

    n_chats = 8
    chat_ids = []
    for i in range(n_chats):
        resp = await client.post(
            "/api/v1/chats", json={"model_key": model_key, "title": f"c{i}"}, headers=headers
        )
        assert resp.status_code == 201
        chat_ids.append(resp.json()["id"])

    async def _send(chat_id: str, text: str):
        resp = await client.post(
            f"/api/v1/chats/{chat_id}/messages", json={"content": text}, headers=headers
        )
        assert resp.status_code in (200, 201), resp.text
        return resp.json()

    results = await asyncio.gather(*[_send(cid, f"hello from {cid}") for cid in chat_ids])
    for chat_id, result in zip(chat_ids, results):
        assert result["user_message"]["content"] == f"hello from {chat_id}"
        assert result["user_message"]["chat_id"] == chat_id
        assert result["assistant_message"]["chat_id"] == chat_id


@pytest.mark.asyncio
async def test_high_concurrency_does_not_error_or_deadlock(client: AsyncClient, pg_session):
    """A burst of unrelated requests (different users, different
    endpoints) at once shouldn't 500 or hang. Not a perf assertion —
    just "the stack doesn't fall over under concurrent load"."""
    n_users = 15
    for i in range(n_users):
        await _make_user(pg_session, username=f"burst_user_{i}")
    headers_list = await asyncio.gather(
        *[_login_headers(client, f"burst_user_{i}") for i in range(n_users)]
    )

    async def _touch(headers: dict):
        r1 = await client.get("/api/v1/users/me", headers=headers)
        r2 = await client.get("/api/v1/models", headers=headers)
        r3 = await client.get("/api/v1/chats", headers=headers)
        return r1.status_code, r2.status_code, r3.status_code

    results = await asyncio.wait_for(
        asyncio.gather(*[_touch(h) for h in headers_list]), timeout=15
    )
    for statuses in results:
        assert all(s == 200 for s in statuses)
