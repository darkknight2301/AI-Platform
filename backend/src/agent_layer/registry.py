"""
`AgentRegistry`: agent_key -> `AgentAdapter`, deliberately structurally
identical to `model_layer.registry.ModelRegistry` (register/get/list,
in-memory, process-local, not a singleton) — so adding a second agent
later is the same shape as adding a model provider today: implement
`AgentAdapter`, register it, nothing else changes. See ADR 0012.

Intentionally smaller than `ModelRegistry`: no `enable`/`disable`/
`check_availability` — an agent isn't "enabled/disabled" at this
layer the way a model is (that's what `ILA_ENABLED` at the
`bootstrap.py` level already controls: unset -> never registered at
all). Add those operations here if/when a second agent's lifecycle
actually needs them, rather than speculatively now.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.agent_layer.agent_interface import AgentAdapter


class AgentNotFoundError(KeyError):
    """Raised when a requested agent_key has never been registered."""


@dataclass(frozen=True)
class AgentRegistration:
    agent_key: str
    adapter: AgentAdapter
    metadata: dict = field(default_factory=dict)


class AgentRegistry:
    def __init__(self) -> None:
        self._registrations: dict[str, AgentRegistration] = {}

    def register(
        self, *, agent_key: str, adapter: AgentAdapter, metadata: dict | None = None
    ) -> AgentRegistration:
        if agent_key in self._registrations:
            raise ValueError(f"Agent '{agent_key}' is already registered.")
        registration = AgentRegistration(agent_key=agent_key, adapter=adapter, metadata=metadata or {})
        self._registrations[agent_key] = registration
        return registration

    def get(self, agent_key: str) -> AgentRegistration:
        try:
            return self._registrations[agent_key]
        except KeyError as exc:
            raise AgentNotFoundError(agent_key) from exc

    def list_agents(self) -> list[AgentRegistration]:
        return list(self._registrations.values())
