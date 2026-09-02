"""
Wires the ILA agent into an `AgentRegistry`, iff `ILA_ENABLED=true` —
same on/off convention as `model_layer/bootstrap.py`'s
`QWEN_*_ENABLED`. With the default (`false`), `register_default_agents`
registers nothing, so every code path in
`src/services/conversation_service.py` that checks `chat.agent_key`
never finds one to route to for a *new* chat (existing chats with an
`agent_key` already set would still fail cleanly via
`AgentNotFoundError` -> a normal `ChatServiceError`, not a crash) —
this is the concrete mechanism behind "disabling ILA restores existing
behavior without code changes."

`main.py` calls `register_default_agents` the same way it already
calls `model_layer.bootstrap.register_default_providers` — same
pattern, new line, not a new startup mechanism.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent_layer.adapters.ila_adapter import ILAAgentAdapter
from src.agent_layer.config import ILAAgentConfig, load_ila_config
from src.agent_layer.registry import AgentRegistry
from src.model_layer.router import ModelRouter
from src.models.ai_model import AIModel

logger = logging.getLogger(__name__)

ILA_AGENT_KEY = ILAAgentConfig.model_fields["agent_key"].default


def _is_enabled(env_var: str) -> bool:
    return os.environ.get(env_var, "false").strip().lower() in ("1", "true", "yes", "on")


def register_default_agents(registry: AgentRegistry, *, model_router: ModelRouter) -> None:
    """Register ILA if `ILA_ENABLED=true`. Safe to call with it unset —
    the registry simply ends up empty, matching an application with no
    agents at all."""
    if not _is_enabled("ILA_ENABLED"):
        logger.info("ila_agent_not_registered")
        return

    try:
        config = load_ila_config()
        adapter = ILAAgentAdapter(config=config, model_router=model_router)
    except Exception:
        # A misconfigured ILA module must not prevent the rest of the
        # application (including the existing Qwen-only flow) from
        # starting — logged loudly, but not fatal. Matches the
        # reversibility requirement: a broken/absent ILA module is
        # equivalent to ILA_ENABLED=false from every other chat's
        # point of view.
        logger.error("ila_agent_registration_failed", exc_info=True)
        return

    registry.register(agent_key=adapter.agent_key, metadata={"display_name": config.display_name}, adapter=adapter)
    logger.info("ila_agent_registered", extra={"agent_key": adapter.agent_key})


async def sync_agent_model_visibility(session: AsyncSession) -> None:
    """Keep the `ila-agent` placeholder `AIModel` row's `is_enabled`
    in sync with `ILA_ENABLED` at startup.

    Without this, the row (seeded with `is_enabled=False` — see the
    migration) would only ever be toggled by hand through the admin
    model-management endpoint, meaning `ILA_ENABLED=false` would stop
    ILA from actually running but NOT stop it from appearing as a
    selectable option in `GET /models` (which filters on this exact
    column) — the option would be visible but broken, which is worse
    than not reversible at all. This call is what makes "disabling
    ILA_ENABLED restores existing behavior" true for the frontend's
    model list, not just for the backend's routing.
    """
    enabled = _is_enabled("ILA_ENABLED")
    await session.execute(update(AIModel).where(AIModel.model_key == ILA_AGENT_KEY).values(is_enabled=enabled))
    await session.commit()
