"""Unit tests for `ILAAgentAdapter` — proves the dynamic-import,
thread-offload, timeout, and error-mapping behavior without needing
the real ILA module: a fake `ILA(**kwargs).main(query=...)` class is
injected into `sys.modules` for each test.
"""
from __future__ import annotations

import sys
import types

import pytest

from src.agent_layer.adapters.ila_adapter import ILAAgentAdapter
from src.agent_layer.config import ILAAgentConfig
from src.agent_layer.errors import AgentConfigurationError, AgentExecutionError, AgentTimeoutError
from src.agent_layer.schemas import AgentRequest


def _install_fake_module(module_name: str, ila_class: type) -> None:
    module = types.ModuleType(module_name)
    module.ILA = ila_class
    sys.modules[module_name] = module


@pytest.fixture(autouse=True)
def _cleanup_fake_modules():
    yield
    for name in list(sys.modules):
        if name.startswith("_fake_ila_"):
            del sys.modules[name]


def test_unresolvable_module_raises_configuration_error():
    config = ILAAgentConfig(module_path="_fake_ila_does_not_exist", class_name="ILA")
    with pytest.raises(AgentConfigurationError):
        ILAAgentAdapter(config=config, model_router=None)


def test_unresolvable_class_raises_configuration_error():
    _install_fake_module("_fake_ila_mod_a", ila_class=object)
    config = ILAAgentConfig(module_path="_fake_ila_mod_a", class_name="NotThere")
    with pytest.raises(AgentConfigurationError):
        ILAAgentAdapter(config=config, model_router=None)


@pytest.mark.asyncio
async def test_run_calls_main_and_wraps_string_output():
    captured_kwargs = {}

    class FakeILA:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        def main(self, query: str) -> str:
            return f"engineered: {query}"

    _install_fake_module("_fake_ila_mod_b", FakeILA)
    config = ILAAgentConfig(
        module_path="_fake_ila_mod_b", class_name="ILA", constructor_kwargs={"tools": ["search"]}
    )
    adapter = ILAAgentAdapter(config=config, model_router="router-sentinel")

    result = await adapter.run(AgentRequest(agent_key="ila-agent", query="build a widget"))

    assert result.output == "engineered: build a widget"
    assert result.usage.total_tokens == 0
    assert captured_kwargs["tools"] == ["search"]
    assert captured_kwargs["model_router"] == "router-sentinel"


@pytest.mark.asyncio
async def test_run_coerces_non_string_output():
    class FakeILA:
        def __init__(self, **kwargs):
            pass

        def main(self, query: str):
            return {"summary": "done"}

    _install_fake_module("_fake_ila_mod_c", FakeILA)
    config = ILAAgentConfig(module_path="_fake_ila_mod_c", class_name="ILA")
    adapter = ILAAgentAdapter(config=config, model_router=None)

    result = await adapter.run(AgentRequest(agent_key="ila-agent", query="x"))
    assert result.output == str({"summary": "done"})
    assert result.raw_output == {"summary": "done"}


@pytest.mark.asyncio
async def test_run_wraps_exception_as_execution_error():
    class FakeILA:
        def __init__(self, **kwargs):
            pass

        def main(self, query: str):
            raise RuntimeError("boom")

    _install_fake_module("_fake_ila_mod_d", FakeILA)
    config = ILAAgentConfig(module_path="_fake_ila_mod_d", class_name="ILA")
    adapter = ILAAgentAdapter(config=config, model_router=None)

    with pytest.raises(AgentExecutionError):
        await adapter.run(AgentRequest(agent_key="ila-agent", query="x"))


@pytest.mark.asyncio
async def test_run_raises_timeout_error_when_exceeding_configured_timeout():
    import time

    class SlowILA:
        def __init__(self, **kwargs):
            pass

        def main(self, query: str):
            time.sleep(0.2)
            return "too slow"

    _install_fake_module("_fake_ila_mod_e", SlowILA)
    config = ILAAgentConfig(module_path="_fake_ila_mod_e", class_name="ILA", timeout_seconds=0.01)
    adapter = ILAAgentAdapter(config=config, model_router=None)

    with pytest.raises(AgentTimeoutError):
        await adapter.run(AgentRequest(agent_key="ila-agent", query="x"))
