"""
Phase 9 — Administrative Interfaces integration tests.

These deliberately don't re-test what Phase 3/7's suites already cover
(basic Manager-approves-own-group, Owner-sees-everything, etc — see
test_auth_rbac.py and test_quota.py). This file covers the endpoints
added specifically for the role dashboards, and the negative cases
that make "each role sees only its authorized functionality" true at
the API layer rather than just in the UI:

  - GET /users/me/activity is self-scoped for a Manager
  - GET /users/groups/{group_id} enforces the same own-group-only rule
    as GET /users/groups/{group_id}/usage
  - A Manager cannot use either endpoint against a group they don't run
  - A User (no elevated role) is rejected by both
  - A Developer can reach /system/* (their own dashboard) but not
    /admin/* or the Manager-only group endpoints
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.db.base import Base
from src.db.session import get_db
from src.main import app
from src.models.enums import GroupStatus, Role, UserStatus
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


async def _make_group(session: AsyncSession, name: str) -> Group:
    group = Group(name=name, status=GroupStatus.ACTIVE)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


async def _make_user(
    session: AsyncSession,
    *,
    username: str,
    role: Role = Role.USER,
    status_: UserStatus = UserStatus.ACTIVE,
    group: Group | None = None,
    password: str = "correct-horse-1",
) -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password(password),
        status=status_,
        role=role,
        group_id=group.id if group else None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _login(client: AsyncClient, username: str, password: str = "correct-horse-1") -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Manager: "Authorized activity" panel -----------------------------------

@pytest.mark.asyncio
async def test_manager_activity_only_shows_their_own_actions(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "activity-group")
    await _make_user(pg_session, username="mgr_x", role=Role.MANAGER, group=group)
    await _make_user(pg_session, username="mgr_y", role=Role.MANAGER, group=group)
    pending1 = await _make_user(
        pg_session, username="pending_x", status_=UserStatus.PENDING, group=group
    )
    pending2 = await _make_user(
        pg_session, username="pending_y", status_=UserStatus.PENDING, group=group
    )

    mgr_x_token = await _login(client, "mgr_x")
    mgr_y_token = await _login(client, "mgr_y")

    resp = await client.post(
        f"/api/v1/users/{pending1.id}/approve", headers=_auth_headers(mgr_x_token)
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/users/{pending2.id}/reject", headers=_auth_headers(mgr_y_token)
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/users/me/activity", headers=_auth_headers(mgr_x_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    actions = [e["action"] for e in body["entries"]]
    assert actions == ["APPROVE_USER"]
    assert all(e["target_id"] == str(pending1.id) for e in body["entries"])


@pytest.mark.asyncio
async def test_user_cannot_view_activity(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="plain_user")
    token = await _login(client, "plain_user")
    resp = await client.get("/api/v1/users/me/activity", headers=_auth_headers(token))
    assert resp.status_code == 403


# --- Manager: group summary (own group only) --------------------------------

@pytest.mark.asyncio
async def test_manager_can_view_own_group(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "own-group")
    await _make_user(pg_session, username="mgr_own", role=Role.MANAGER, group=group)
    token = await _login(client, "mgr_own")

    resp = await client.get(f"/api/v1/users/groups/{group.id}", headers=_auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "own-group"


@pytest.mark.asyncio
async def test_manager_cannot_view_other_group_critical_security(
    client: AsyncClient, pg_session
):
    own_group = await _make_group(pg_session, "mgr-b-own")
    other_group = await _make_group(pg_session, "mgr-b-other")
    await _make_user(pg_session, username="mgr_b", role=Role.MANAGER, group=own_group)
    token = await _login(client, "mgr_b")

    resp = await client.get(
        f"/api/v1/users/groups/{other_group.id}", headers=_auth_headers(token)
    )
    assert resp.status_code == 403

    resp = await client.get(
        f"/api/v1/users/groups/{other_group.id}/usage", headers=_auth_headers(token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_view_any_group(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "owner-viewed-group")
    await _make_user(pg_session, username="owner_gv", role=Role.OWNER)
    token = await _login(client, "owner_gv")

    resp = await client.get(f"/api/v1/users/groups/{group.id}", headers=_auth_headers(token))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_plain_user_cannot_view_group(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "irrelevant-group")
    await _make_user(pg_session, username="plain_user2")
    token = await _login(client, "plain_user2")

    resp = await client.get(f"/api/v1/users/groups/{group.id}", headers=_auth_headers(token))
    assert resp.status_code == 403


# --- Developer dashboard reach ------------------------------------------

@pytest.mark.asyncio
async def test_developer_can_reach_system_dashboard_but_not_admin_or_group_endpoints(
    client: AsyncClient, pg_session
):
    group = await _make_group(pg_session, "dev-blocked-group")
    await _make_user(pg_session, username="dev_dash", role=Role.DEVELOPER)
    token = await _login(client, "dev_dash")

    for path in ("/system/logs", "/system/models", "/system/diagnostics", "/system/performance"):
        resp = await client.get(f"/api/v1{path}", headers=_auth_headers(token))
        assert resp.status_code == 200, f"{path}: {resp.text}"

    # Application/backend health is unauthenticated and shared by every role.
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200

    resp = await client.get("/api/v1/admin/audit-logs", headers=_auth_headers(token))
    assert resp.status_code == 403

    resp = await client.get(
        f"/api/v1/users/groups/{group.id}", headers=_auth_headers(token)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_dashboard_reaches_every_admin_surface(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="owner_dash", role=Role.OWNER)
    token = await _login(client, "owner_dash")

    for path in (
        "/admin/groups",
        "/admin/audit-logs",
        "/admin/usage",
        "/admin/config",
        "/admin/models",
        "/system/logs",
        "/system/models",
        "/system/diagnostics",
        "/system/performance",
    ):
        resp = await client.get(f"/api/v1{path}", headers=_auth_headers(token))
        assert resp.status_code == 200, f"{path}: {resp.text}"
