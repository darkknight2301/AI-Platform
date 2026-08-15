"""
Integration tests for the Phase 2 data model.

These tests run against a real PostgreSQL database (not SQLite) because
several of the guarantees under test — CHECK constraints, FK ON DELETE
behavior — are exactly the kind of thing that can silently differ
between backends. The target database is controlled via
TEST_DATABASE_URL (falls back to a local default suitable for CI
containers that provision Postgres alongside the test run).

If no PostgreSQL instance is reachable, these tests are skipped rather
than failed, so the unit/sqlite-backed suite still runs standalone.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.base import Base
from src.models import AIModel, Chat, Group, Message, User
from src.models.enums import ChatStatus, GroupStatus, MessageRole, ModelCategory, Role, UserStatus

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app_user:app_password@localhost:5432/app_db",
)


def _pg_available() -> bool:
    return os.environ.get("SKIP_PG_TESTS") != "1"


pytestmark = pytest.mark.skipif(
    not _pg_available(), reason="PostgreSQL integration tests disabled (SKIP_PG_TESTS=1)"
)


@pytest_asyncio.fixture
async def pg_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL not reachable: {exc}")

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def _make_group(session: AsyncSession, name: str = "engineering") -> Group:
    group = Group(name=name, status=GroupStatus.ACTIVE)
    session.add(group)
    await session.flush()
    return group


async def _make_user(session: AsyncSession, group: Group, username: str = "alice") -> User:
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash="hashed",
        status=UserStatus.ACTIVE,
        role=Role.USER,
        group=group,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_model(session: AsyncSession, key: str = "qwen-coder-2.5") -> AIModel:
    model = AIModel(
        model_key=key,
        display_name="Qwen Coder 2.5",
        category=ModelCategory.CODER,
        provider="qwen",
        version="2.5",
        is_enabled=True,
        capabilities=["streaming"],
        config_metadata={"context_window": 32768},
    )
    session.add(model)
    await session.flush()
    return model


@pytest.mark.asyncio
async def test_can_create_full_relational_graph(pg_session: AsyncSession):
    group = await _make_group(pg_session)
    user = await _make_user(pg_session, group)
    model = await _make_model(pg_session)

    chat = Chat(user=user, model=model, title="Test chat", status=ChatStatus.ACTIVE)
    pg_session.add(chat)
    await pg_session.flush()

    message = Message(
        chat=chat,
        role=MessageRole.USER,
        content="Hello",
        input_tokens=10,
        output_tokens=0,
        total_tokens=10,
    )
    pg_session.add(message)
    await pg_session.commit()

    fetched = await pg_session.scalar(select(Chat).where(Chat.id == chat.id))
    assert fetched is not None
    assert fetched.user_id == user.id
    assert fetched.model_id == model.id


@pytest.mark.asyncio
async def test_duplicate_username_rejected(pg_session: AsyncSession):
    group = await _make_group(pg_session)
    await _make_user(pg_session, group, username="bob")
    await pg_session.commit()

    pg_session.add(
        User(
            username="bob",
            email="different@example.com",
            password_hash="hashed",
            status=UserStatus.ACTIVE,
            role=Role.USER,
        )
    )
    with pytest.raises(IntegrityError):
        await pg_session.commit()


@pytest.mark.asyncio
async def test_duplicate_email_rejected(pg_session: AsyncSession):
    group = await _make_group(pg_session)
    await _make_user(pg_session, group, username="carol")
    await pg_session.commit()

    pg_session.add(
        User(
            username="carol2",
            email="carol@example.com",
            password_hash="hashed",
            status=UserStatus.ACTIVE,
            role=Role.USER,
        )
    )
    with pytest.raises(IntegrityError):
        await pg_session.commit()


@pytest.mark.asyncio
async def test_invalid_role_value_rejected(pg_session: AsyncSession):
    from sqlalchemy import text

    with pytest.raises(Exception):  # noqa: B017 - DBAPI-level enum/CHECK violation
        await pg_session.execute(
            text(
                "INSERT INTO users (id, username, email, password_hash, status, role, "
                "created_at, updated_at) VALUES (:id, 'x', 'x@example.com', 'h', 'ACTIVE', "
                "'NOT_A_ROLE', now(), now())"
            ),
            {"id": uuid.uuid4()},
        )
        await pg_session.commit()


@pytest.mark.asyncio
async def test_message_token_sum_mismatch_rejected(pg_session: AsyncSession):
    group = await _make_group(pg_session)
    user = await _make_user(pg_session, group)
    model = await _make_model(pg_session)
    chat = Chat(user=user, model=model, title="t", status=ChatStatus.ACTIVE)
    pg_session.add(chat)
    await pg_session.flush()

    pg_session.add(
        Message(
            chat=chat,
            role=MessageRole.ASSISTANT,
            content="hi",
            input_tokens=5,
            output_tokens=5,
            total_tokens=999,  # deliberately wrong
        )
    )
    with pytest.raises(IntegrityError):
        await pg_session.commit()


@pytest.mark.asyncio
async def test_negative_token_count_rejected(pg_session: AsyncSession):
    group = await _make_group(pg_session)
    user = await _make_user(pg_session, group)
    model = await _make_model(pg_session)
    chat = Chat(user=user, model=model, title="t", status=ChatStatus.ACTIVE)
    pg_session.add(chat)
    await pg_session.flush()

    pg_session.add(
        Message(
            chat=chat,
            role=MessageRole.ASSISTANT,
            content="hi",
            input_tokens=-1,
            output_tokens=0,
            total_tokens=-1,
        )
    )
    with pytest.raises(IntegrityError):
        await pg_session.commit()


@pytest.mark.asyncio
async def test_deleting_user_cascades_to_chats_and_messages(pg_session: AsyncSession):
    group = await _make_group(pg_session)
    user = await _make_user(pg_session, group)
    model = await _make_model(pg_session)
    chat = Chat(user=user, model=model, title="t", status=ChatStatus.ACTIVE)
    pg_session.add(chat)
    await pg_session.flush()
    message = Message(
        chat=chat, role=MessageRole.USER, content="hi",
        input_tokens=1, output_tokens=0, total_tokens=1,
    )
    pg_session.add(message)
    await pg_session.commit()

    chat_id, message_id = chat.id, message.id

    await pg_session.delete(user)
    await pg_session.commit()

    assert await pg_session.scalar(select(Chat).where(Chat.id == chat_id)) is None
    assert await pg_session.scalar(select(Message).where(Message.id == message_id)) is None


@pytest.mark.asyncio
async def test_deleting_group_sets_user_group_null(pg_session: AsyncSession):
    group = await _make_group(pg_session, name="temp-group")
    user = await _make_user(pg_session, group, username="dave")
    await pg_session.commit()

    await pg_session.delete(group)
    await pg_session.commit()

    refreshed = await pg_session.scalar(select(User).where(User.id == user.id))
    assert refreshed is not None
    assert refreshed.group_id is None


@pytest.mark.asyncio
async def test_cannot_delete_model_in_use(pg_session: AsyncSession):
    group = await _make_group(pg_session)
    user = await _make_user(pg_session, group)
    model = await _make_model(pg_session)
    chat = Chat(user=user, model=model, title="t", status=ChatStatus.ACTIVE)
    pg_session.add(chat)
    await pg_session.commit()

    await pg_session.delete(model)
    with pytest.raises(IntegrityError):
        await pg_session.commit()
