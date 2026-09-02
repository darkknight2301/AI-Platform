"""
`src/agent_layer/`: orchestration/agent abstraction, deliberately
separate from `src/model_layer/` (see ADR 0012).

```text
ConversationService -> AgentRegistry -> AgentAdapter -> concrete agent
```

An agent is NOT a model: it may call zero, one, or many models
internally (reusing `ModelRouter`, the same one `ChatService` already
holds), use tools, and produce output that isn't a single text
completion. `AgentAdapter` (`agent_interface.py`) is intentionally a
different, smaller contract than `ModelProvider` — nothing in this
package implements `ModelProvider`, and nothing outside this package
should ever import a concrete agent class directly (same discipline
as `model_layer/provider_interface.py`'s rule for providers).

Fully additive and reversible: with `ILA_ENABLED=false` (the
default), `bootstrap.register_default_agents` registers nothing, and
every existing Qwen-only code path is exercised exactly as before —
see `src/services/conversation_service.py`'s `chat.agent_key is None`
branches.
"""
