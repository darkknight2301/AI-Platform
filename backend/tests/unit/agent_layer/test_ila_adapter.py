"""Unit tests for `ILAAgentAdapter` against ILA's confirmed interface
(`ILA(**kwargs).generate(query, mode, function_name, step,
test_case_desc, overwrite_step, output_file) -> str`) — a fake
`src.ila.ILA` is installed into `sys.modules` for each test so these
don't depend on the real module actually being present under
backend/src/ila/.
"""
from __future__ import annotations

import sys
import types

import pytest

from src.agent_layer.adapters.ila_adapter import ILAAgentAdapter
from src.agent_layer.config import ILAAgentConfig
from src.agent_layer.errors import AgentConfigurationError, AgentExecutionError, AgentTimeoutError
from src.agent_layer.schemas import AgentRequest, ILAGenerateParams


def _install_fake_ila_module(ila_class: type) -> None:
    module = types.ModuleType("src.ila")
    module.ILA = ila_class
    sys.modules["src.ila"] = module


@pytest.fixture(autouse=True)
def _cleanup_fake_module():
    yield
    sys.modules.pop("src.ila", None)


def _params(**overrides) -> ILAGenerateParams:
    defaults = dict(
        mode="generate", function_name="do_thing", step="implement", output_file="out.py"
    )
    defaults.update(overrides)
    return ILAGenerateParams(**defaults)


def test_missing_module_raises_configuration_error():
    sys.modules.pop("src.ila", None)
    config = ILAAgentConfig()
    with pytest.raises(AgentConfigurationError):
        ILAAgentAdapter(config=config, model_router=None)


def test_constructor_kwargs_forwarded_and_type_error_wrapped():
    class StrictILA:
        def __init__(self, **kwargs):
            raise TypeError("unexpected keyword argument 'bogus'")

    _install_fake_ila_module(StrictILA)
    config = ILAAgentConfig(constructor_kwargs={"bogus": "x"})
    with pytest.raises(AgentConfigurationError):
        ILAAgentAdapter(config=config, model_router=None)


@pytest.mark.asyncio
async def test_run_calls_generate_with_positional_args_in_order():
    captured = {}

    class FakeILA:
        def __init__(self, **kwargs):
            captured["init_kwargs"] = kwargs

        def generate(self, query, mode, function_name, step, test_case_desc, overwrite_step, output_file):
            captured["args"] = (query, mode, function_name, step, test_case_desc, overwrite_step, output_file)
            return "def do_thing(): ..."

    _install_fake_ila_module(FakeILA)
    config = ILAAgentConfig(constructor_kwargs={"chunk_path": "/data/chunks"})
    adapter = ILAAgentAdapter(config=config, model_router="router-sentinel")

    request = AgentRequest(
        agent_key="ila-agent",
        query="implement the thing",
        ila_params=_params(test_case_desc="covers edge case", overwrite_step=True, output_file="src/thing.py"),
    )
    result = await adapter.run(request)

    assert result.output == "def do_thing(): ..."
    assert result.usage.total_tokens == 0
    assert captured["args"] == (
        "implement the thing",
        "generate",
        "do_thing",
        "implement",
        "covers edge case",
        True,
        "src/thing.py",
    )
    assert captured["init_kwargs"]["chunk_path"] == "/data/chunks"
    assert captured["init_kwargs"]["model_router"] == "router-sentinel"


@pytest.mark.asyncio
async def test_run_without_ila_params_raises_execution_error():
    class FakeILA:
        def __init__(self, **kwargs):
            pass

        def generate(self, *args):
            raise AssertionError("should not be called")

    _install_fake_ila_module(FakeILA)
    adapter = ILAAgentAdapter(config=ILAAgentConfig(), model_router=None)

    with pytest.raises(AgentExecutionError):
        await adapter.run(AgentRequest(agent_key="ila-agent", query="x", ila_params=None))


@pytest.mark.asyncio
async def test_run_wraps_generate_exception_as_execution_error():
    class FakeILA:
        def __init__(self, **kwargs):
            pass

        def generate(self, *args):
            raise RuntimeError("boom")

    _install_fake_ila_module(FakeILA)
    adapter = ILAAgentAdapter(config=ILAAgentConfig(), model_router=None)

    with pytest.raises(AgentExecutionError):
        await adapter.run(AgentRequest(agent_key="ila-agent", query="x", ila_params=_params()))


@pytest.mark.asyncio
async def test_run_raises_timeout_error_when_exceeding_configured_timeout():
    import time

    class SlowILA:
        def __init__(self, **kwargs):
            pass

        def generate(self, *args):
            time.sleep(0.2)
            return "too slow"

    _install_fake_ila_module(SlowILA)
    adapter = ILAAgentAdapter(config=ILAAgentConfig(timeout_seconds=0.01), model_router=None)

    with pytest.raises(AgentTimeoutError):
        await adapter.run(AgentRequest(agent_key="ila-agent", query="x", ila_params=_params()))
