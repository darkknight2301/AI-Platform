"""Unit tests for `AgentRegistry` (mirrors test_model_layer.py's
coverage of ModelRegistry's register/get/list/not-found shape)."""
from __future__ import annotations

import pytest

from src.agent_layer.adapters.fake_adapter import FakeAgentAdapter
from src.agent_layer.registry import AgentNotFoundError, AgentRegistry


def test_register_and_get_round_trips():
    registry = AgentRegistry()
    adapter = FakeAgentAdapter(agent_key="ila-agent")
    registry.register(agent_key="ila-agent", adapter=adapter, metadata={"display_name": "ILA"})

    registration = registry.get("ila-agent")
    assert registration.agent_key == "ila-agent"
    assert registration.adapter is adapter
    assert registration.metadata == {"display_name": "ILA"}


def test_get_unknown_agent_raises_not_found():
    registry = AgentRegistry()
    with pytest.raises(AgentNotFoundError):
        registry.get("does-not-exist")


def test_register_duplicate_key_raises():
    registry = AgentRegistry()
    registry.register(agent_key="ila-agent", adapter=FakeAgentAdapter())
    with pytest.raises(ValueError):
        registry.register(agent_key="ila-agent", adapter=FakeAgentAdapter())


def test_list_agents_returns_all_registrations():
    registry = AgentRegistry()
    registry.register(agent_key="a", adapter=FakeAgentAdapter(agent_key="a"))
    registry.register(agent_key="b", adapter=FakeAgentAdapter(agent_key="b"))
    keys = {r.agent_key for r in registry.list_agents()}
    assert keys == {"a", "b"}


def test_empty_registry_lists_nothing():
    """The ILA_ENABLED=false default state — see bootstrap.py."""
    assert AgentRegistry().list_agents() == []


@pytest.mark.asyncio
async def test_fake_agent_adapter_run_echoes_query():
    from src.agent_layer.schemas import AgentRequest

    adapter = FakeAgentAdapter(agent_key="fake-agent")
    result = await adapter.run(AgentRequest(agent_key="fake-agent", query="hello"))
    assert "hello" in result.output
    assert result.usage.total_tokens > 0
