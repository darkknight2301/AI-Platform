"""
`ILAAgentAdapter`: wraps the real ILA module behind `AgentAdapter`.

ILA's authoritative, fixed public interface (`backend/src/ila/`):

    class ILA:
        def __init__(self, **kwargs):
            self.chunck_path
            self.vector_db_path
            self.artifacts_dir
            self.workspace_dir

        def generate(self, query, mode, function_name, step,
                      test_case_desc, overwrite_step, output_file) -> str

Not touched, not reimplemented, not assumed beyond this. Two
consequences:

1. Imported directly (`from src.ila import ILA`), not dynamically —
   ILA is a fixed, first-party module at a known location, not a
   pluggable external one (unlike the previous version of this file).
2. `.generate()` is synchronous/blocking, same as the previously
   assumed `.main()` was — still run via `asyncio.to_thread` with a
   timeout, for the same reason: a blocking call of unknown duration
   must never run on the event loop.

`generate()`'s return value (`generated_code: str`) is returned as-is
as `AgentResult.output` — this platform does NOT duplicate ILA's own
`output_file` write; ILA already performs that update itself per its
documented behavior. See `AgentRequest.ila_params` for where each
positional argument comes from.
"""
from __future__ import annotations

import asyncio
import logging

from src.agent_layer.agent_interface import AgentAdapter
from src.agent_layer.config import ILAAgentConfig
from src.agent_layer.errors import AgentConfigurationError, AgentExecutionError, AgentTimeoutError
from src.agent_layer.schemas import AgentRequest, AgentResult
from src.model_layer.router import ModelRouter
from src.model_layer.schemas import TokenUsage

logger = logging.getLogger(__name__)


def _import_ila_class():
    try:
        from src.ila import ILA
    except ImportError as exc:
        raise AgentConfigurationError(
            "Could not import ILA from src.ila — the ILA module is not present "
            "under backend/src/ila/ in this deployment."
        ) from exc
    return ILA


class ILAAgentAdapter(AgentAdapter):
    def __init__(self, *, config: ILAAgentConfig, model_router: ModelRouter) -> None:
        self._config = config
        self._model_router = model_router
        ila_class = _import_ila_class()
        kwargs = dict(config.constructor_kwargs)
        # Same reuse point the previous version of this adapter had —
        # unrelated to the fixed generate() signature above, and NOT
        # part of ILA's documented constructor deps (chunk/vector-db/
        # artifacts/workspace); left as a best-effort forward, kept
        # only if ILA's constructor actually accepts it (see except
        # below rather than assuming it does).
        if config.default_model_key:
            kwargs.setdefault("default_model_key", config.default_model_key)
        kwargs.setdefault("model_router", model_router)
        try:
            self._ila = ila_class(**kwargs)
        except TypeError as exc:
            raise AgentConfigurationError(
                f"ILA(**kwargs) rejected the configured constructor arguments: {exc}. "
                "Check ILA_CHUNK_PATH/ILA_VECTOR_DB_PATH/ILA_ARTIFACTS_DIR/"
                "ILA_WORKSPACE_DIR and ILA_CONSTRUCTOR_KWARGS against ILA's actual "
                "__init__ signature."
            ) from exc

    @property
    def agent_key(self) -> str:
        return self._config.agent_key

    async def run(self, request: AgentRequest) -> AgentResult:
        params = request.ila_params
        if params is None:
            raise AgentExecutionError(
                "ILA requires mode/function_name/step/output_file — none were provided."
            )

        try:
            generated_code = await asyncio.wait_for(
                asyncio.to_thread(
                    self._ila.generate,
                    request.query,
                    params.mode,
                    params.function_name,
                    params.step,
                    params.test_case_desc,
                    params.overwrite_step,
                    params.output_file,
                ),
                timeout=self._config.timeout_seconds,
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
            output=generated_code,
            # ILA's usage reporting, if any, isn't part of the
            # confirmed interface — left at zero rather than guessed,
            # same as the previous version of this file.
            usage=TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0),
        )
