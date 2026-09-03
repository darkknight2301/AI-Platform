"""
`src/agent_layer/workspace/`: the Web IDE subsystem (ADR 0012, §Web
IDE). Deliberately separate from the rest of `agent_layer/` — an
agent (ILA) may or may not use a workspace; a workspace's own
provisioning/proxy logic has nothing to do with how an agent runs.

```text
ChatView "Open VS Code" -> proxy.py (FastAPI routes)
                                  |
                          workspace_service.py (ownership,
                          resolves/creates the Workspace row)
                                  |
                          ssh_manager.py (backend-held SSH key,
                          ensures code-server is running on the
                          remote host, opens a tunnel)
                                  |
                          session_registry.py (tracks the open
                          tunnel, idle-timeout teardown)
```

Off by default (`WORKSPACE_ENABLED=false`) — see `config.py`. Nothing
here is imported by `src/agent_layer/adapters/ila_adapter.py` or vice
versa; an `AgentResult.workspace_id` is the only coupling point.
"""
