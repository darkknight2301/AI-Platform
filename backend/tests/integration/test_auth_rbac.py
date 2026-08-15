"""
Phase 3 — Authentication and RBAC integration tests.

Runs against a real PostgreSQL database, with the app's `get_db`
dependency overridden to use that same database.

Covers the "Critical Security Tests":
  - User A cannot access User B
  - Manager A cannot manage Group B
  - User cannot call Owner APIs
  - Developer cannot call Owner APIs
  - Unauthenticated users cannot call protected APIs
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


# --- Registration -------------------------------------------------------------

@pytest.mark.asyncio
async def test_registration_creates_pending_user_with_forced_role_user(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "newperson",
            "email": "newperson@example.com",
            "password": "hunter2fish",
            "role": "OWNER",  # deliberate privilege-escalation attempt via extra field
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["role"] == "USER"


@pytest.mark.asyncio
async def test_registration_rejects_duplicate_username(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="dup_user")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "dup_user", "email": "other@example.com", "password": "abc12345xy"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_password_is_hashed_not_stored_plaintext(client: AsyncClient, pg_session):
    plaintext = "supersecret1"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"username": "hashcheck", "email": "hashcheck@example.com", "password": plaintext},
    )
    assert resp.status_code == 201
    from sqlalchemy import select

    user = await pg_session.scalar(select(User).where(User.username == "hashcheck"))
    assert user.password_hash != plaintext
    assert user.password_hash.startswith("$2b$")


# --- Login / logout / account status ------------------------------------------

@pytest.mark.asyncio
async def test_login_rejected_for_pending_account(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="pending_guy", status_=UserStatus.PENDING)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "pending_guy", "password": "correct-horse-1"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_login_rejected_for_suspended_account(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="suspended_guy", status_=UserStatus.SUSPENDED)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "suspended_guy", "password": "correct-horse-1"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_login_rejected_for_wrong_password(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="wrongpw_guy")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "wrongpw_guy", "password": "not-the-password"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_rejected_for_unknown_user(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "does-not-exist", "password": "whatever123"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_success_returns_working_token(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="gooduser")
    token = await _login(client, "gooduser")
    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["username"] == "gooduser"


@pytest.mark.asyncio
async def test_logout_immediately_invalidates_token(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="logoutuser")
    token = await _login(client, "logoutuser")

    resp = await client.post("/api/v1/auth/logout", headers=_auth_headers(token))
    assert resp.status_code == 204

    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_suspending_account_invalidates_existing_token_on_next_request(
    client: AsyncClient, pg_session
):
    user = await _make_user(pg_session, username="willbesuspended")
    token = await _login(client, "willbesuspended")

    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert resp.status_code == 200

    user.status = UserStatus.SUSPENDED
    await pg_session.commit()

    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert resp.status_code == 403


# --- Manager approval workflow --------------------------------------------

@pytest.mark.asyncio
async def test_manager_can_approve_pending_user_in_own_group(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "team-a")
    await _make_user(pg_session, username="mgr_a", role=Role.MANAGER, group=group)
    pending = await _make_user(
        pg_session, username="pending_a", status_=UserStatus.PENDING, group=group
    )
    mgr_token = await _login(client, "mgr_a")

    resp = await client.post(
        f"/api/v1/users/{pending.id}/approve", headers=_auth_headers(mgr_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ACTIVE"

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "pending_a", "password": "correct-horse-1"},
    )
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_manager_can_reject_pending_user_in_own_group(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "team-b")
    await _make_user(pg_session, username="mgr_b", role=Role.MANAGER, group=group)
    pending = await _make_user(
        pg_session, username="pending_b", status_=UserStatus.PENDING, group=group
    )
    mgr_token = await _login(client, "mgr_b")

    resp = await client.post(
        f"/api/v1/users/{pending.id}/reject", headers=_auth_headers(mgr_token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "INACTIVE"


@pytest.mark.asyncio
async def test_manager_cannot_manage_group_b_critical_security(client: AsyncClient, pg_session):
    """CRITICAL SECURITY TEST: Manager A cannot manage Group B."""
    group_a = await _make_group(pg_session, "group-a")
    group_b = await _make_group(pg_session, "group-b")
    await _make_user(pg_session, username="mgr_only_a", role=Role.MANAGER, group=group_a)
    pending_b = await _make_user(
        pg_session, username="pending_in_b", status_=UserStatus.PENDING, group=group_b
    )
    mgr_a_token = await _login(client, "mgr_only_a")

    approve_resp = await client.post(
        f"/api/v1/users/{pending_b.id}/approve", headers=_auth_headers(mgr_a_token)
    )
    assert approve_resp.status_code == 403

    reject_resp = await client.post(
        f"/api/v1/users/{pending_b.id}/reject", headers=_auth_headers(mgr_a_token)
    )
    assert reject_resp.status_code == 403

    usage_resp = await client.get(
        f"/api/v1/users/groups/{group_b.id}/usage", headers=_auth_headers(mgr_a_token)
    )
    assert usage_resp.status_code == 403

    list_resp = await client.get("/api/v1/users", headers=_auth_headers(mgr_a_token))
    assert list_resp.status_code == 200
    listed_ids = {u["id"] for u in list_resp.json()["users"]}
    assert str(pending_b.id) not in listed_ids


@pytest.mark.asyncio
async def test_owner_can_approve_user_in_any_group(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "owner-target-group")
    await _make_user(pg_session, username="owner1", role=Role.OWNER)
    pending = await _make_user(
        pg_session, username="pending_owner_target", status_=UserStatus.PENDING, group=group
    )
    owner_token = await _login(client, "owner1")

    resp = await client.post(
        f"/api/v1/users/{pending.id}/approve", headers=_auth_headers(owner_token)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ACTIVE"


# --- Critical security tests: cross-user / cross-role access -----------------

@pytest.mark.asyncio
async def test_user_a_cannot_access_user_b_critical_security(client: AsyncClient, pg_session):
    """CRITICAL SECURITY TEST: User A cannot access User B."""
    user_a = await _make_user(pg_session, username="user_a")
    user_b = await _make_user(pg_session, username="user_b")
    token_a = await _login(client, "user_a")

    resp = await client.get(f"/api/v1/users/{user_b.id}", headers=_auth_headers(token_a))
    assert resp.status_code == 403

    self_resp = await client.get(f"/api/v1/users/{user_a.id}", headers=_auth_headers(token_a))
    assert self_resp.status_code == 200


@pytest.mark.asyncio
async def test_user_cannot_call_owner_apis_critical_security(client: AsyncClient, pg_session):
    """CRITICAL SECURITY TEST: User cannot call Owner APIs."""
    await _make_user(pg_session, username="plain_user")
    token = await _login(client, "plain_user")

    for method, path in [
        ("GET", "/api/v1/admin/groups"),
        ("POST", "/api/v1/admin/groups"),
        ("GET", "/api/v1/admin/audit-logs"),
        ("GET", "/api/v1/admin/usage"),
        ("GET", "/api/v1/admin/config"),
    ]:
        resp = await client.request(method, path, headers=_auth_headers(token), json={})
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"


@pytest.mark.asyncio
async def test_developer_cannot_call_owner_apis_critical_security(client: AsyncClient, pg_session):
    """CRITICAL SECURITY TEST: Developer cannot call Owner APIs."""
    await _make_user(pg_session, username="dev_user", role=Role.DEVELOPER)
    token = await _login(client, "dev_user")

    for method, path in [
        ("GET", "/api/v1/admin/groups"),
        ("GET", "/api/v1/admin/audit-logs"),
        ("GET", "/api/v1/admin/config"),
    ]:
        resp = await client.request(method, path, headers=_auth_headers(token), json={})
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"

    diag_resp = await client.get("/api/v1/system/diagnostics", headers=_auth_headers(token))
    assert diag_resp.status_code == 200


@pytest.mark.asyncio
async def test_developer_does_not_get_unrestricted_user_access(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="dev_user2", role=Role.DEVELOPER)
    other = await _make_user(pg_session, username="someone_else")
    token = await _login(client, "dev_user2")

    resp = await client.get(f"/api/v1/users/{other.id}", headers=_auth_headers(token))
    assert resp.status_code == 403

    list_resp = await client.get("/api/v1/users", headers=_auth_headers(token))
    assert list_resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_users_cannot_call_protected_apis_critical_security(
    client: AsyncClient, pg_session
):
    """CRITICAL SECURITY TEST: Unauthenticated users cannot call protected APIs."""
    user = await _make_user(pg_session, username="target_for_anon")

    protected = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/users/me"),
        ("GET", f"/api/v1/users/{user.id}"),
        ("GET", "/api/v1/users"),
        ("GET", "/api/v1/system/diagnostics"),
        ("GET", "/api/v1/admin/groups"),
        ("POST", "/api/v1/auth/logout"),
    ]
    for method, path in protected:
        resp = await client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"

    health_resp = await client.get("/api/v1/health")
    assert health_resp.status_code == 200


@pytest.mark.asyncio
async def test_invalid_bearer_token_rejected(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


# --- Role capability checks ---------------------------------------------------

@pytest.mark.asyncio
async def test_user_can_access_own_usage_and_profile(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="usage_user")
    token = await _login(client, "usage_user")

    profile_resp = await client.get("/api/v1/users/me", headers=_auth_headers(token))
    assert profile_resp.status_code == 200

    usage_resp = await client.get("/api/v1/users/me/usage", headers=_auth_headers(token))
    assert usage_resp.status_code == 200
    assert usage_resp.json()["total_tokens"] == 0


@pytest.mark.asyncio
async def test_manager_can_view_own_group_users_only(client: AsyncClient, pg_session):
    group_a = await _make_group(pg_session, "view-group-a")
    group_b = await _make_group(pg_session, "view-group-b")
    await _make_user(pg_session, username="mgr_view_a", role=Role.MANAGER, group=group_a)
    await _make_user(pg_session, username="member_a", group=group_a)
    await _make_user(pg_session, username="member_b", group=group_b)

    token = await _login(client, "mgr_view_a")
    resp = await client.get("/api/v1/users", headers=_auth_headers(token))
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()["users"]}
    assert "member_a" in usernames
    assert "mgr_view_a" in usernames
    assert "member_b" not in usernames


@pytest.mark.asyncio
async def test_owner_can_view_all_users_across_groups(client: AsyncClient, pg_session):
    group_a = await _make_group(pg_session, "owner-view-a")
    group_b = await _make_group(pg_session, "owner-view-b")
    await _make_user(pg_session, username="owner_viewer", role=Role.OWNER)
    await _make_user(pg_session, username="oa_member", group=group_a)
    await _make_user(pg_session, username="ob_member", group=group_b)

    token = await _login(client, "owner_viewer")
    resp = await client.get("/api/v1/users", headers=_auth_headers(token))
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()["users"]}
    assert {"oa_member", "ob_member", "owner_viewer"} <= usernames


@pytest.mark.asyncio
async def test_owner_can_manage_groups_and_models(client: AsyncClient, pg_session):
    await _make_user(pg_session, username="owner_admin", role=Role.OWNER)
    token = await _login(client, "owner_admin")

    group_resp = await client.post(
        "/api/v1/admin/groups", json={"name": "new-owner-group"}, headers=_auth_headers(token)
    )
    assert group_resp.status_code == 201

    model_resp = await client.post(
        "/api/v1/admin/models",
        json={
            "model_key": "test-model-1",
            "display_name": "Test Model",
            "category": "CODER",
            "provider": "qwen",
            "version": "1.0",
        },
        headers=_auth_headers(token),
    )
    assert model_resp.status_code == 201

    config_resp = await client.get("/api/v1/admin/config", headers=_auth_headers(token))
    assert config_resp.status_code == 200
    assert "secret_key" not in config_resp.json()

    audit_resp = await client.get("/api/v1/admin/audit-logs", headers=_auth_headers(token))
    assert audit_resp.status_code == 200
    assert audit_resp.json()["total"] > 0


@pytest.mark.asyncio
async def test_manager_cannot_call_admin_endpoints(client: AsyncClient, pg_session):
    group = await _make_group(pg_session, "mgr-no-admin-group")
    await _make_user(pg_session, username="mgr_no_admin", role=Role.MANAGER, group=group)
    token = await _login(client, "mgr_no_admin")

    resp = await client.get("/api/v1/admin/groups", headers=_auth_headers(token))
    assert resp.status_code == 403
