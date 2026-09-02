"""
`AgentAdapter`: the contract every concrete agent (ILA, or a future
second agent) implements. Deliberately not `ModelProvider` — see
`src/agent_layer/__init__.py` and ADR 0012 for why.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.agent_layer.schemas import AgentRequest, AgentResult


class AgentAdapter(ABC):
    """Abstract base class for all agents.

    Only one method today — `run`. No `stream`/`capabilities`/
    `health_check` trio like `ModelProvider` has: those were shaped
    around "a model always streams and always has a fixed capability
    set." An agent's shape varies enough (ILA's `.main()` is a single
    blocking call with a final result, not a stream) that inventing a
    uniform streaming contract now — before a second agent exists to
    validate it against — would be guessing. Add it when an agent
    actually needs it.
    """

    @property
    @abstractmethod
    def agent_key(self) -> str: ...

    @abstractmethod
    async def run(self, request: AgentRequest) -> AgentResult:
        """Produce a complete result for `request`."""
