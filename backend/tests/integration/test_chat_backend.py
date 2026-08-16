"""
Phase 6 — Chat backend integration tests.

Runs against a real PostgreSQL database, with `get_db` overridden the
same way as the Phase 3 RBAC tests, and `get_model_router` overridden
to inject a test `ModelRouter` — most tests use `MockProvider`
(Phase 4) for speed/determinism; a dedicated end-to-end test uses the
real `QwenProvider` (Phase 5) wired to an `httpx.MockTransport`, to
concretely satisfy "complete backend chat flow works against the Qwen
model providers" without requiring a live inference server.
"""
from __future__ import annotations

import json
import os
import uuid

import httpx
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
from src.model_layer.providers.qwen.config import QwenProviderConfig
from src.model_layer.providers.qwen.provider import QwenProvider
from src.model_layer.registry import ModelRegistry
from src.model_layer.router import ModelRouter
from src.models.ai_model import AIModel
from src.models.enums import ModelCategory, Role, UserStatus
from src.models.user import User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app_user:app_password@localhost:5432/app_test_db",
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PostgreSQL integration tests disabled (SKIP_PG_TESTS=1)",
)

MOCK_MODEL_KEY = "mock-coder-1"


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

    registry = ModelRegistry()
    registry.register(
        model_key=MOCK_MODEL_KEY,
        provider=MockProvider(category=ModelCategory.CODER),
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


async def _make_active_user(session: AsyncSession, *, username: str, password: str = "correct-horse-1") -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password(password),
        status=UserStatus.ACTIVE,
        role=Role.USER,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _make_model(
    session: AsyncSession, *, model_key: str = MOCK_MODEL_KEY, category: ModelCategory = ModelCategory.CODER
) -> AIModel:
    model = AIModel(
        model_key=model_key,
        display_name=model_key,
        category=category,
        provider="mock",
        version="1.0",
        is_enabled=True,
        capabilities=["streaming"],
        config_metadata={},
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return model


async def _login(client: AsyncClient, username: str, password: str = "correct-horse-1") -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username_or_email": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_chat(client: AsyncClient, token: str, *, model_key: str = MOCK_MODEL_KEY, title: str | None = None):
    resp = await client.post(
        "/api/v1/chats",
        json={"model_key": model_key, "title": title},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data:")
        events.append(json.loads(block[len("data:"):].strip()))
    return events


# --- chat CRUD -----------------------------------------------------------

@pytest.mark.asyncio
async def test_create_chat(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="alice")
    token = await _login(client, "alice")

    chat = await _create_chat(client, token, title="My chat")
    assert chat["title"] == "My chat"
    assert chat["model_key"] == MOCK_MODEL_KEY
    assert chat["status"] == "ACTIVE"
    assert chat["revision"] == 1


@pytest.mark.asyncio
async def test_create_chat_default_title(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="bob")
    token = await _login(client, "bob")

    chat = await _create_chat(client, token, title=None)
    assert chat["title"] == "New chat"


@pytest.mark.asyncio
async def test_create_chat_unknown_model_rejected(client: AsyncClient, pg_session):
    await _make_active_user(pg_session, username="carol")
    token = await _login(client, "carol")

    resp = await client.post(
        "/api/v1/chats", json={"model_key": "does-not-exist"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_chats_only_own(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="dave")
    await _make_active_user(pg_session, username="erin")
    dave_token = await _login(client, "dave")
    erin_token = await _login(client, "erin")

    await _create_chat(client, dave_token, title="Dave's chat")
    await _create_chat(client, erin_token, title="Erin's chat")

    resp = await client.get("/api/v1/chats", headers=_auth_headers(dave_token))
    assert resp.status_code == 200
    titles = {c["title"] for c in resp.json()["chats"]}
    assert titles == {"Dave's chat"}


@pytest.mark.asyncio
async def test_get_update_delete_chat(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="frank")
    token = await _login(client, "frank")
    chat = await _create_chat(client, token)

    get_resp = await client.get(f"/api/v1/chats/{chat['id']}", headers=_auth_headers(token))
    assert get_resp.status_code == 200

    patch_resp = await client.patch(
        f"/api/v1/chats/{chat['id']}", json={"title": "Renamed"}, headers=_auth_headers(token)
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Renamed"
    assert patch_resp.json()["revision"] == 2

    delete_resp = await client.delete(f"/api/v1/chats/{chat['id']}", headers=_auth_headers(token))
    assert delete_resp.status_code == 204

    after_delete = await client.get(f"/api/v1/chats/{chat['id']}", headers=_auth_headers(token))
    assert after_delete.status_code == 200
    assert after_delete.json()["status"] == "DELETED"

    list_resp = await client.get("/api/v1/chats", headers=_auth_headers(token))
    assert chat["id"] not in {c["id"] for c in list_resp.json()["chats"]}


@pytest.mark.asyncio
async def test_get_nonexistent_chat_404(client: AsyncClient, pg_session):
    await _make_active_user(pg_session, username="grace")
    token = await _login(client, "grace")
    resp = await client.get(f"/api/v1/chats/{uuid.uuid4()}", headers=_auth_headers(token))
    assert resp.status_code == 404


# --- ownership -----------------------------------------------------------

@pytest.mark.asyncio
async def test_user_cannot_access_another_users_chat(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="heidi")
    await _make_active_user(pg_session, username="ivan")
    heidi_token = await _login(client, "heidi")
    ivan_token = await _login(client, "ivan")

    chat = await _create_chat(client, heidi_token)

    for method, path in [
        ("GET", f"/api/v1/chats/{chat['id']}"),
        ("PATCH", f"/api/v1/chats/{chat['id']}"),
        ("DELETE", f"/api/v1/chats/{chat['id']}"),
        ("GET", f"/api/v1/chats/{chat['id']}/history"),
        ("POST", f"/api/v1/chats/{chat['id']}/messages"),
    ]:
        resp = await client.request(
            method, path, headers=_auth_headers(ivan_token), json={"content": "hi"}
        )
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"


@pytest.mark.asyncio
async def test_unauthenticated_cannot_call_chat_apis(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="judy")
    token = await _login(client, "judy")
    chat = await _create_chat(client, token)

    for method, path in [
        ("GET", "/api/v1/chats"),
        ("POST", "/api/v1/chats"),
        ("GET", f"/api/v1/chats/{chat['id']}"),
        ("GET", f"/api/v1/chats/{chat['id']}/history"),
    ]:
        resp = await client.request(method, path, json={"model_key": MOCK_MODEL_KEY})
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


# --- send / history --------------------------------------------------------

@pytest.mark.asyncio
async def test_send_message_and_history(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="kevin")
    token = await _login(client, "kevin")
    chat = await _create_chat(client, token)

    content = "```python\nprint('hello')\n```"
    resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages",
        json={"content": content},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_message"]["content"] == content  # verbatim, no mangling
    assert body["user_message"]["role"] == "USER"
    assert body["assistant_message"]["role"] == "ASSISTANT"
    assert content in body["assistant_message"]["content"]  # mock echoes it
    assert body["assistant_message"]["total_tokens"] > 0
    assert body["assistant_message"]["response_time_ms"] is not None
    assert body["assistant_message"]["model_key"] == MOCK_MODEL_KEY

    history_resp = await client.get(
        f"/api/v1/chats/{chat['id']}/history", headers=_auth_headers(token)
    )
    assert history_resp.status_code == 200
    messages = history_resp.json()["messages"]
    assert [m["role"] for m in messages] == ["USER", "ASSISTANT"]
    assert [m["sequence_number"] for m in messages] == [0, 1]


@pytest.mark.asyncio
async def test_multi_turn_conversation_context_grows(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="laura")
    token = await _login(client, "laura")
    chat = await _create_chat(client, token)

    await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "first"}, headers=_auth_headers(token)
    )
    await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "second"}, headers=_auth_headers(token)
    )

    history = (
        await client.get(f"/api/v1/chats/{chat['id']}/history", headers=_auth_headers(token))
    ).json()["messages"]
    assert len(history) == 4
    assert [m["sequence_number"] for m in history] == [0, 1, 2, 3]


# --- edit / regenerate / revisions -----------------------------------------

@pytest.mark.asyncio
async def test_edit_creates_new_revision_and_regenerates_reply(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="mallory")
    token = await _login(client, "mallory")
    chat = await _create_chat(client, token)

    send_resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "v1"}, headers=_auth_headers(token)
    )
    user_msg = send_resp.json()["user_message"]
    original_assistant_id = send_resp.json()["assistant_message"]["id"]

    edit_resp = await client.post(
        f"/api/v1/messages/{user_msg['id']}/edit",
        json={"content": "v2"},
        headers=_auth_headers(token),
    )
    assert edit_resp.status_code == 200, edit_resp.text
    edited = edit_resp.json()
    assert edited["user_message"]["content"] == "v2"
    assert edited["user_message"]["revision"] == 2
    assert edited["user_message"]["sequence_number"] == user_msg["sequence_number"]
    assert edited["assistant_message"]["id"] != original_assistant_id
    assert edited["assistant_message"]["revision"] == 2

    # History shows only the ACTIVE (latest) revisions.
    history = (
        await client.get(f"/api/v1/chats/{chat['id']}/history", headers=_auth_headers(token))
    ).json()["messages"]
    assert len(history) == 2
    assert history[0]["content"] == "v2"

    # But the original v1 is NOT deleted — it's queryable via revisions.
    revisions_resp = await client.get(
        f"/api/v1/messages/{user_msg['id']}/revisions", headers=_auth_headers(token)
    )
    assert revisions_resp.status_code == 200
    revisions = revisions_resp.json()["revisions"]
    contents = {r["content"] for r in revisions}
    assert contents == {"v1", "v2"}
    active_ids = [r["id"] for r in revisions if r["is_active"]]
    assert len(active_ids) == 1


@pytest.mark.asyncio
async def test_regenerate_preserves_old_reply_as_inactive(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="nathan")
    token = await _login(client, "nathan")
    chat = await _create_chat(client, token)

    send_resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "hello"}, headers=_auth_headers(token)
    )
    original_assistant = send_resp.json()["assistant_message"]

    regen_resp = await client.post(
        f"/api/v1/messages/{original_assistant['id']}/regenerate",
        json={},
        headers=_auth_headers(token),
    )
    assert regen_resp.status_code == 200, regen_resp.text
    regenerated = regen_resp.json()["assistant_message"]
    assert regenerated["id"] != original_assistant["id"]
    assert regenerated["revision"] == 2
    assert regenerated["sequence_number"] == original_assistant["sequence_number"]

    revisions_resp = await client.get(
        f"/api/v1/messages/{original_assistant['id']}/revisions", headers=_auth_headers(token)
    )
    revisions = revisions_resp.json()["revisions"]
    assert len(revisions) == 2
    inactive = [r for r in revisions if not r["is_active"]]
    assert len(inactive) == 1
    assert inactive[0]["id"] == original_assistant["id"]

    # Prompt (the turn before it) is untouched.
    history = (
        await client.get(f"/api/v1/chats/{chat['id']}/history", headers=_auth_headers(token))
    ).json()["messages"]
    assert history[0]["content"] == "hello"


@pytest.mark.asyncio
async def test_activate_revision_is_server_persisted_undo_redo(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="olivia")
    token = await _login(client, "olivia")
    chat = await _create_chat(client, token)

    send_resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "v1"}, headers=_auth_headers(token)
    )
    v1_id = send_resp.json()["user_message"]["id"]

    await client.post(
        f"/api/v1/messages/{v1_id}/edit", json={"content": "v2"}, headers=_auth_headers(token)
    )

    # Undo: reactivate v1.
    activate_resp = await client.post(
        f"/api/v1/messages/{v1_id}/activate", headers=_auth_headers(token)
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["content"] == "v1"
    assert activate_resp.json()["is_active"] is True

    history = (
        await client.get(f"/api/v1/chats/{chat['id']}/history", headers=_auth_headers(token))
    ).json()["messages"]
    assert history[0]["content"] == "v1"


@pytest.mark.asyncio
async def test_cannot_edit_inactive_revision(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="peter")
    token = await _login(client, "peter")
    chat = await _create_chat(client, token)

    send_resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "v1"}, headers=_auth_headers(token)
    )
    v1_id = send_resp.json()["user_message"]["id"]
    await client.post(
        f"/api/v1/messages/{v1_id}/edit", json={"content": "v2"}, headers=_auth_headers(token)
    )

    # v1 is now inactive — editing it again should be rejected.
    resp = await client.post(
        f"/api/v1/messages/{v1_id}/edit", json={"content": "v3"}, headers=_auth_headers(token)
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cannot_regenerate_user_message(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="quinn")
    token = await _login(client, "quinn")
    chat = await _create_chat(client, token)

    send_resp = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"content": "hi"}, headers=_auth_headers(token)
    )
    user_msg_id = send_resp.json()["user_message"]["id"]

    resp = await client.post(
        f"/api/v1/messages/{user_msg_id}/regenerate", json={}, headers=_auth_headers(token)
    )
    assert resp.status_code == 409


# --- streaming ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_message_streaming(client: AsyncClient, pg_session):
    await _make_model(pg_session)
    await _make_active_user(pg_session, username="rachel")
    token = await _login(client, "rachel")
    chat = await _create_chat(client, token)

    async with client.stream(
        "POST",
        f"/api/v1/chats/{chat['id']}/messages",
        json={"content": "stream me", "stream": True},
        headers=_auth_headers(token),
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = ""
        async for chunk in resp.aiter_text():
            body += chunk

    events = _parse_sse(body)
    assert len(events) >= 2
    assert all(not e["is_final"] for e in events[:-1])
    final = events[-1]
    assert final["is_final"] is True
    assert final["finish_reason"] == "stop"
    assert final["message_id"] is not None
    assert final["total_tokens"] > 0

    # The streamed reply was actually persisted.
    history = (
        await client.get(f"/api/v1/chats/{chat['id']}/history", headers=_auth_headers(token))
    ).json()["messages"]
    assert len(history) == 2
    assert history[1]["id"] == final["message_id"]
    reconstructed = "".join(e["delta"] for e in events)
    assert history[1]["content"] == reconstructed


# --- end-to-end against the real QwenProvider (Phase 5) ----------------------

@pytest.mark.asyncio
async def test_full_chat_flow_against_qwen_provider(client: AsyncClient, pg_session):
    """The concrete proof of 'complete backend chat flow works against
    the Qwen model providers': every chat/message endpoint exercised
    through the API, with the model layer backed by the real
    `QwenProvider` (talking to an `httpx.MockTransport`-simulated
    backend — no live inference server needed, same as Phase 5's own
    provider tests)."""
    model_key = "qwen2.5-coder-7b"
    await _make_model(pg_session, model_key=model_key, category=ModelCategory.CODER)
    await _make_active_user(pg_session, username="sam")
    token = await _login(client, "sam")

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": []})
        call_count["n"] += 1
        body = json.loads(request.content)
        last_user = next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": f"qwen-reply: {last_user}"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    qwen_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://qwen-backend/v1")
    qwen_config = QwenProviderConfig(
        model_key=model_key,
        display_name="Qwen 2.5 Coder 7B",
        endpoint_url="http://qwen-backend/v1",
        context_length=32768,
        max_output_tokens=4096,
    )
    provider = QwenProvider(
        model_key=model_key, category=ModelCategory.CODER, config=qwen_config, http_client=qwen_client
    )
    registry = ModelRegistry()
    registry.register(model_key=model_key, provider=provider, category=ModelCategory.CODER)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter(registry)

    try:
        chat = await _create_chat(client, token, model_key=model_key, title="Qwen chat")

        send_resp = await client.post(
            f"/api/v1/chats/{chat['id']}/messages",
            json={"content": "write a function"},
            headers=_auth_headers(token),
        )
        assert send_resp.status_code == 201, send_resp.text
        assistant = send_resp.json()["assistant_message"]
        assert assistant["content"] == "qwen-reply: write a function"
        assert assistant["model_key"] == model_key
        assert assistant["total_tokens"] == 7

        user_msg_id = send_resp.json()["user_message"]["id"]
        edit_resp = await client.post(
            f"/api/v1/messages/{user_msg_id}/edit",
            json={"content": "write a better function"},
            headers=_auth_headers(token),
        )
        assert edit_resp.status_code == 200
        assert edit_resp.json()["assistant_message"]["content"] == "qwen-reply: write a better function"

        regen_resp = await client.post(
            f"/api/v1/messages/{edit_resp.json()['assistant_message']['id']}/regenerate",
            json={},
            headers=_auth_headers(token),
        )
        assert regen_resp.status_code == 200
        assert regen_resp.json()["assistant_message"]["content"] == "qwen-reply: write a better function"

        history_resp = await client.get(
            f"/api/v1/chats/{chat['id']}/history", headers=_auth_headers(token)
        )
        assert history_resp.status_code == 200
        messages = history_resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["content"] == "write a better function"
        assert call_count["n"] == 3  # initial send + edit-cascade + regenerate
    finally:
        app.dependency_overrides[get_model_router] = lambda: ModelRouter(ModelRegistry())
        await provider.aclose()
