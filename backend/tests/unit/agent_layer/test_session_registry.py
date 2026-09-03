from __future__ import annotations

import uuid

import pytest

from src.agent_layer.workspace.session_registry import SessionRegistry


class _FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_sweep_idle_closes_sessions_past_timeout():
    registry = SessionRegistry(idle_timeout_seconds=0)
    workspace_id = uuid.uuid4()
    conn = _FakeConn()
    await registry.put(workspace_id, conn, object())

    await registry.sweep_idle()

    assert conn.closed
    assert await registry.get(workspace_id) is None


@pytest.mark.asyncio
async def test_sweep_idle_leaves_active_sessions_alone():
    registry = SessionRegistry(idle_timeout_seconds=3600)
    workspace_id = uuid.uuid4()
    conn = _FakeConn()
    await registry.put(workspace_id, conn, object())

    await registry.sweep_idle()

    assert not conn.closed
    assert await registry.get(workspace_id) is not None


@pytest.mark.asyncio
async def test_put_closes_previous_session_for_same_workspace():
    registry = SessionRegistry(idle_timeout_seconds=3600)
    workspace_id = uuid.uuid4()
    first, second = _FakeConn(), _FakeConn()
    await registry.put(workspace_id, first, object())
    await registry.put(workspace_id, second, object())

    assert first.closed
    assert not second.closed
