"""
`FakeAgentAdapter`: a fully working `AgentAdapter` with no external
dependency — no ILA module, no subprocess, no network. Same role
`MockProvider` plays for the model layer (see `model_layer/providers/
mock_provider.py`): proves `AgentRegistry`/`ConversationService`'s
ILA branch end-to-end without needing the real ILA module installed,
and is the template a second real agent's tests can copy.
"""
from __future__ import annotations

from src.agent_layer.agent_interface import AgentAdapter
from src.agent_layer.schemas import AgentRequest, AgentResult
from src.model_layer.schemas import TokenUsage


class FakeAgentAdapter(AgentAdapter):
    def __init__(self, *, agent_key: str = "fake-agent") -> None:
        self._agent_key = agent_key

    @property
    def agent_key(self) -> str:
        return self._agent_key

    async def run(self, request: AgentRequest) -> AgentResult:
        output = f"[fake-agent echo] {request.query}"
        return AgentResult(
            agent_key=self._agent_key,
            output=output,
            usage=TokenUsage(
                input_tokens=len(request.query.split()),
                output_tokens=len(output.split()),
                total_tokens=len(request.query.split()) + len(output.split()),
            ),
        )
