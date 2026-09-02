"""
`ILAAgentAdapter`: wraps the real ILA module behind `AgentAdapter`.

ILA's actual interface, as specified by its author: a plain Python
class, `ILA(**kwargs)`, used per-request as `ILA(**kwargs).main(query="...")`
— synchronous, not async, and (as far as this adapter assumes) returns
a single final result rather than streaming. Two consequences of that:

1. The ILA class is imported dynamically (`importlib`), by
   `ILAAgentConfig.module_path`/`class_name`, rather than a hardcoded
   `from <package> import ILA` — this file has no compile-time
   dependency on the ILA module actually being installed unless
   `ILA_ENABLED=true` selects it.
2. `.main()` is run via `asyncio.to_thread` (with a timeout), not
   awaited directly — a blocking call of unknown duration must never
   run on the event loop, or it would stall every other in-flight
   request on the same worker process for as long as ILA takes.

`kwargs` for the constructor are NOT guessed at here — see
`config.py`'s `constructor_kwargs`/module docstring for why.
"""
from __future__ import annotations

import asyncio
import importlib
import logging

from src.agent_layer.agent_interface import AgentAdapter
from src.agent_layer.config import ILAAgentConfig
from src.agent_layer.errors import AgentConfigurationError, AgentExecutionError, AgentTimeoutError
from src.agent_layer.schemas import AgentRequest, AgentResult
from src.model_layer.router import ModelRouter
from src.model_layer.schemas import TokenUsage

logger = logging.getLogger(__name__)


def _resolve_ila_class(module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise AgentConfigurationError(
            f"Could not import ILA_MODULE_PATH={module_path!r}: {exc}"
        ) from exc
    try:
        return getattr(module, class_name)
    except AttributeError as exc:
        raise AgentConfigurationError(
            f"Module {module_path!r} has no class {class_name!r} (ILA_CLASS_NAME)."
        ) from exc


def _coerce_output(raw_result: object) -> str:
    """`.main()`'s return type isn't specified beyond "the desired
    engineering output" — accept a plain string as-is, or fall back to
    str() for anything else, rather than assuming a specific object
    shape (e.g. `.content`/`.text`) ILA may not actually have."""
    if isinstance(raw_result, str):
        return raw_result
    return str(raw_result)


class ILAAgentAdapter(AgentAdapter):
    def __init__(self, *, config: ILAAgentConfig, model_router: ModelRouter) -> None:
        self._config = config
        self._model_router = model_router
        self._ila_class = _resolve_ila_class(config.module_path, config.class_name)

    @property
    def agent_key(self) -> str:
        return self._config.agent_key

    async def run(self, request: AgentRequest) -> AgentResult:
        try:
            raw_result = await asyncio.wait_for(
                asyncio.to_thread(self._run_sync, request), timeout=self._config.timeout_seconds
            )
        except TimeoutError as exc:
            logger.error(
                "ila_agent_timeout",
                extra={"agent_key": self.agent_key, "timeout_seconds": self._config.timeout_seconds},
            )
            raise AgentTimeoutError() from exc
        except Exception as exc:  # ILA's own code failing is not this adapter's fault to predict
            logger.error(
                "ila_agent_execution_failed",
                extra={"agent_key": self.agent_key, "error_type": type(exc).__name__},
                exc_info=exc,
            )
            raise AgentExecutionError(str(exc)) from exc

        return AgentResult(
            agent_key=self.agent_key,
            output=_coerce_output(raw_result),
            # ILA's own usage reporting, if any, isn't part of the
            # confirmed interface (`.main(query=...) -> output`) — left
            # at zero here rather than guessed. If/when ILA reports
            # token usage from its internal model calls, wire it
            # through here instead of leaving this at zero.
            usage=TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0),
            raw_output=raw_result if not isinstance(raw_result, str) else None,
        )

    def _run_sync(self, request: AgentRequest) -> object:
        kwargs = dict(self._config.constructor_kwargs)
        # Give ILA a way to reach the platform's existing models
        # through the same ModelRouter every Qwen call already uses —
        # concrete reuse of existing infra (ADR 0012), not a second
        # HTTP client. `model_router` is the assumed kwarg name ILA's
        # constructor looks for; if ILA's real signature differs, only
        # this one line needs to change.
        kwargs.setdefault("model_router", self._model_router)
        if self._config.default_model_key:
            kwargs.setdefault("default_model_key", self._config.default_model_key)
        instance = self._ila_class(**kwargs)
        return instance.main(query=request.query)
