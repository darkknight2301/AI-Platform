"""
Phase 7 — Token quotas and chat limits integration tests.

Runs against real PostgreSQL (quota concurrency safety relies on
`pg_advisory_xact_lock`, which SQLite doesn't have — see ADR 0010),
with the same dependency-override pattern as
`tests/integration/test_chat_backend.py`.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.deps import get_model_router, get_session_factory
from src.core.security import hash_password
from src.db.base import Base
from src.db.session import get_db
from src.main import app
from src.model_layer.providers.mock_provider import MockProvider
from src.model_layer.registry import ModelRegistry
from src.model_layer.router import ModelRouter
from src.models.ai_model import AIModel
from src.models.enums import GroupStatus, ModelCategory, Role, UserStatus
from src.models.group import Group
from src.models.user import User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app_user:app_password@localhost:5432/app_test_db",
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PostgreSQL integration tests disabled (SKIP_PG_TESTS=1)",
)

MODEL_KEY = "mock-coder-1"


@pytest_asyncio.fixture
async def pg_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable: {exc}")
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(pg_engine):
    return async_sessionmaker(bind=pg_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def pg_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(session_factory):
    async def _override_get_db():
        async with session_factory() as session:
            yield session

    registry = ModelRegistry()
    registry.register(
        model_key=MODEL_KEY,
        provider=MockProvider(category=ModelCategory.CODER, canned_response="ok"),
        category=ModelCategory.CODER,
    )
    router = ModelRouter(registry)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_model_router] = lambda: router
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_model_router, None)
    app.dependency_overrides.pop(get_session_factory, None)


async def _make_model(session: AsyncSession, model_key: str = MODEL_KEY) -> AIModel:
    model = AIModel(
        model_key=model_key,
        display_name=model_key,
        category=ModelCategory.CODER,
        provider="mock",
        version="1.0",
        is_enabled=True,
        capabilities=[],
        config_metadata={},
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return model


async def _make_group(session: AsyncSession, name: str, **overrides) -> Group:
    group = Group(name=name, status=GroupStatus.ACTIVE, **overrides)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


async def _make_user(
    session: AsyncSession,
    *,
    username: str,
    group: Group | None = None,
    password: str = "correct-horse-1",
    role: Role = Role.USER,
    **overrides,
) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password(password),
        status=UserStatus.ACTIVE,
        role=role,
        group_id=group.id if group else None,
        **overrides,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _login(client: AsyncClient, username: str, password: str = "correct-horse-1") -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username_or_email": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- chat limit -----------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_limit_global_default_enforced(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_user(pg_session, username="alice", max_active_chats_override=2)
    token = await _login(client, "alice")

    for _ in range(2):
        resp = await client.post(
            "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
        )
        assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
    )
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_chat_limit_does_not_delete_existing_chats(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_user(pg_session, username="bob", max_active_chats_override=1)
    token = await _login(client, "bob")

    first = await client.post(
        "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
    )
    assert first.status_code == 201

    rejected = await client.post(
        "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
    )
    assert rejected.status_code == 429

    list_resp = await client.get("/api/v1/chats", headers=_auth_headers(token))
    assert list_resp.status_code == 200
    assert len(list_resp.json()["chats"]) == 1
    assert list_resp.json()["chats"][0]["id"] == first.json()["id"]


@pytest.mark.asyncio
async def test_chat_limit_user_override_beats_group_override(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "team-x", max_active_chats_override=1)
    await _make_model(pg_session)
    await _make_user(pg_session, username="carol", group=group, max_active_chats_override=3)
    token = await _login(client, "carol")

    for _ in range(3):
        resp = await client.post(
            "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
        )
        assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
    )
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_chat_limit_group_override_beats_global_default(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "team-y", max_active_chats_override=1)
    await _make_model(pg_session)
    await _make_user(pg_session, username="dave", group=group)
    token = await _login(client, "dave")

    resp = await client.post(
        "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
    )
    assert resp.status_code == 201

    resp = await client.post(
        "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
    )
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_chat_limit_concurrent_creation_cannot_bypass(client: AsyncClient, pg_session):
    """CRITICAL: multiple simultaneous chat-creation requests must not
    push the active-chat count past the limit."""
    await _make_model(pg_session)
    await _make_user(pg_session, username="erin", max_active_chats_override=5)
    token = await _login(client, "erin")

    async def _create():
        return await client.post(
            "/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token)
        )

    results = await asyncio.gather(*[_create() for _ in range(10)])
    accepted = [r for r in results if r.status_code == 201]
    rejected = [r for r in results if r.status_code == 429]
    assert len(accepted) == 5
    assert len(rejected) == 5

    list_resp = await client.get("/api/v1/chats", headers=_auth_headers(token))
    assert len(list_resp.json()["chats"]) == 5


# --- token quota -----------------------------------------------------------

@pytest.mark.asyncio
async def test_token_quota_exceeded_blocks_send(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    # Tiny quota, smaller than the reservation estimate — first send fails.
    await _make_user(pg_session, username="frank", token_quota_override=1)
    token = await _login(client, "frank")

    chat = (
        await client.post("/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token))
    ).json()

    resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "hi"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_token_quota_usage_reflected_after_send(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    # Must exceed the reservation estimate (default 2048) or the
    # reservation itself is rejected before generation even starts;
    # small enough that percent_used is still meaningfully nonzero.
    await _make_user(pg_session, username="grace", token_quota_override=3000)
    token = await _login(client, "grace")

    chat = (
        await client.post("/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token))
    ).json()
    send_resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "hello"}, headers=_auth_headers(token)
    )
    assert send_resp.status_code == 201
    charged_tokens = send_resp.json()["assistant_message"]["total_tokens"]
    assert charged_tokens > 0

    quota_resp = await client.get("/api/v1/users/me/quota", headers=_auth_headers(token))
    assert quota_resp.status_code == 200
    body = quota_resp.json()
    assert body["token_quota"]["quota_tokens"] == 3000
    assert body["token_quota"]["used_tokens"] >= charged_tokens
    assert 0 < body["token_quota"]["percent_used"] < 100
    assert "renews_at" in body["token_quota"]


@pytest.mark.asyncio
async def test_failed_generation_not_charged(client: AsyncClient, pg_session):
    """Documented charging policy: a failed model request is not charged —
    the reservation is released, no Usage row is created."""
    await _make_model(pg_session, model_key="failing-model")
    await _make_user(pg_session, username="heidi", token_quota_override=100_000)
    token = await _login(client, "heidi")

    from src.model_layer.registry import ModelRegistry as _Registry
    from src.model_layer.router import ModelRouter as _Router
    from src.services.errors import ChatServiceError

    class _AlwaysFails(MockProvider):
        async def generate(self, request):
            raise ChatServiceError("simulated failure")

    failing_registry = _Registry()
    failing_registry.register(
        model_key="failing-model",
        provider=_AlwaysFails(category=ModelCategory.CODER),
        category=ModelCategory.CODER,
    )
    app.dependency_overrides[get_model_router] = lambda: _Router(failing_registry)

    chat = (
        await client.post(
            "/api/v1/chats", json={"model_key": "failing-model"}, headers=_auth_headers(token)
        )
    ).json()
    resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "hi"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 502

    quota_resp = await client.get("/api/v1/users/me/quota", headers=_auth_headers(token))
    assert quota_resp.json()["token_quota"]["used_tokens"] == 0


@pytest.mark.asyncio
async def test_token_quota_concurrent_requests_cannot_bypass(client: AsyncClient, pg_session):
    """CRITICAL: N concurrent sends against a quota that only has room
    for a handful of reservations must not all succeed.

    Uses a MockProvider with artificial latency so the concurrent
    requests' reserve-then-generate windows genuinely overlap in time —
    without that, an instant provider lets each request fully complete
    (reserve, generate, release) before the next one even starts,
    defeating the point of the test (nothing would ever actually
    contend for the same reservation window)."""
    await _make_model(pg_session)
    from src.core.config import get_settings

    settings = get_settings()
    estimate = settings.quota_reservation_estimated_output_tokens
    await _make_user(pg_session, username="ivan", token_quota_override=estimate * 3)
    token = await _login(client, "ivan")

    slow_registry = ModelRegistry()
    slow_registry.register(
        model_key=MODEL_KEY,
        provider=MockProvider(
            category=ModelCategory.CODER, canned_response="ok", simulated_latency_seconds=0.3
        ),
        category=ModelCategory.CODER,
    )
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(slow_registry)

    chat = (
        await client.post("/api/v1/chats", json={"model_key": MODEL_KEY}, headers=_auth_headers(token))
    ).json()

    async def _send():
        return await client.post(
            f"/api/v1/chats/{chat['id']}/messages",
            json={"content": "hi"},
            headers=_auth_headers(token),
        )

    results = await asyncio.gather(*[_send() for _ in range(8)])
    accepted = [r for r in results if r.status_code == 201]
    rejected = [r for r in results if r.status_code == 429]
    assert len(accepted) == 3
    assert len(rejected) == 5

    quota_resp = await client.get("/api/v1/users/me/quota", headers=_auth_headers(token))
    used = quota_resp.json()["token_quota"]["used_tokens"]
    quota = quota_resp.json()["token_quota"]["quota_tokens"]
    assert used <= quota  # actual usage (tiny "ok" replies) never exceeds quota


# --- usage visibility --------------------------------------------------------

@pytest.mark.asyncio
async def test_user_can_see_own_quota(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="judy")
    token = await _login(client, "judy")
    resp = await client.get("/api/v1/users/me/quota", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert "token_quota" in body and "chat_limit" in body


@pytest.mark.asyncio
async def test_manager_can_see_authorized_group_quota(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "team-z")
    await _make_user(pg_session, username="mgr_z", role=Role.MANAGER, group=group)
    member = await _make_user(pg_session, username="member_z", group=group)
    mgr_token = await _login(client, "mgr_z")

    resp = await client.get(f"/api/v1/users/{member.id}/quota", headers=_auth_headers(mgr_token))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_manager_cannot_see_other_group_quota(client: AsyncClient, pg_session):
    group_a = await _make_group(pg_session, "group-a-quota")
    group_b = await _make_group(pg_session, "group-b-quota")
    await _make_user(pg_session, username="mgr_a_quota", role=Role.MANAGER, group=group_a)
    member_b = await _make_user(pg_session, username="member_b_quota", group=group_b)
    mgr_token = await _login(client, "mgr_a_quota")

    resp = await client.get(f"/api/v1/users/{member_b.id}/quota", headers=_auth_headers(mgr_token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_see_other_users_quota(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="kevin_q")
    user_b = await _make_user(pg_session, username="laura_q")
    token_a = await _login(client, "kevin_q")

    resp = await client.get(f"/api/v1/users/{user_b.id}/quota", headers=_auth_headers(token_a))
    assert resp.status_code == 403


# --- admin override management ------------------------------------------------

@pytest.mark.asyncio
async def test_owner_can_set_group_and_user_overrides(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="owner_q", role=Role.OWNER)
    owner_token = await _login(client, "owner_q")

    group_resp = await client.post(
        "/api/v1/admin/groups", json={"name": "quota-group"}, headers=_auth_headers(owner_token)
    )
    assert group_resp.status_code == 201
    group_id = group_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/admin/groups/{group_id}",
        json={"max_active_chats_override": 7, "token_quota_override": 5000},
        headers=_auth_headers(owner_token),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["max_active_chats_override"] == 7
    assert patch_resp.json()["token_quota_override"] == 5000

    member = await _make_user(pg_session, username="quota_member")
    user_patch = await client.patch(
        f"/api/v1/admin/users/{member.id}",
        json={"token_quota_override": 12345},
        headers=_auth_headers(owner_token),
    )
    assert user_patch.status_code == 200
    assert user_patch.json()["id"] == str(member.id)

    quota_resp = await client.get(
        f"/api/v1/users/{member.id}/quota", headers=_auth_headers(owner_token)
    )
    assert quota_resp.json()["token_quota"]["quota_tokens"] == 12345


@pytest.mark.asyncio
async def test_owner_can_clear_override_with_explicit_null(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="owner_q2", role=Role.OWNER)
    owner_token = await _login(client, "owner_q2")
    member = await _make_user(pg_session, username="quota_member2", token_quota_override=999)

    resp = await client.patch(
        f"/api/v1/admin/users/{member.id}",
        json={"token_quota_override": None},
        headers=_auth_headers(owner_token),
    )
    assert resp.status_code == 200

    quota_resp = await client.get(
        f"/api/v1/users/{member.id}/quota", headers=_auth_headers(owner_token)
    )
    from src.core.config import get_settings

    assert quota_resp.json()["token_quota"]["quota_tokens"] == get_settings().default_token_quota


@pytest.mark.asyncio
async def test_global_config_exposes_quota_defaults(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="owner_q3", role=Role.OWNER)
    token = await _login(client, "owner_q3")
    resp = await client.get("/api/v1/admin/config", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert "default_max_active_chats" in body
    assert "default_token_quota" in body
    assert "token_quota_renewal_policy" in body
