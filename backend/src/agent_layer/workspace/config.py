"""
Configuration for the workspace/Web IDE subsystem — off by default
(`WORKSPACE_ENABLED=false`), same reversibility convention as
`ILA_ENABLED`. Credentials are deliberately NOT modeled as per-user or
per-workspace secrets — see ADR 0012, "Resolved: credentials are
shared/backend-held, not per-user": one backend-held SSH key, and the
real access boundary is which target folder a workspace is scoped to.
"""
from __future__ import annotations

import os

from pydantic import BaseModel


class WorkspaceConfig(BaseModel):
    enabled: bool = False

    # Backend-held SSH identity — a filesystem path, never the key
    # material itself in an env var/DB row. Same posture as
    # SECRET_KEY/ILA's own credential handling.
    ssh_key_path: str = ""
    default_ssh_username: str = "workspace"
    default_ssh_port: int = 22
    # Single default host for this initial cut — every workspace uses
    # it unless/until a more sophisticated per-user/per-fleet
    # allocation is needed. Extending to multiple hosts later is
    # additive (a lookup instead of a constant), not a redesign.
    default_host: str = ""

    # Where code-server is launched from on the remote host, and the
    # root a new workspace's target_path is created under if the
    # caller doesn't specify one more precisely — the backend
    # "suggests" the folder, per the request.
    workspace_root: str = "/srv/workspaces"
    code_server_bin: str = "code-server"
    code_server_port_range_start: int = 9000
    code_server_port_range_end: int = 9100

    # Torn down after this many seconds with no proxied traffic — see
    # session_registry.py.
    idle_timeout_seconds: float = 1800.0

    # Terminal is disabled per explicit product decision (ADR 0012) —
    # enforced in proxy.py by refusing the terminal WebSocket route,
    # not by this flag alone; kept here mainly so it's visible in one
    # place and trivially reversible if that decision ever changes.
    terminal_enabled: bool = False


def _is_enabled(env_var: str) -> bool:
    return os.environ.get(env_var, "false").strip().lower() in ("1", "true", "yes", "on")


def load_workspace_config() -> WorkspaceConfig:
    enabled = _is_enabled("WORKSPACE_ENABLED")
    return WorkspaceConfig(
        enabled=enabled,
        ssh_key_path=os.environ.get("WORKSPACE_SSH_KEY_PATH", "").strip(),
        default_ssh_username=os.environ.get("WORKSPACE_SSH_USERNAME", "workspace").strip(),
        default_ssh_port=int(os.environ.get("WORKSPACE_SSH_PORT", "22")),
        default_host=os.environ.get("WORKSPACE_DEFAULT_HOST", "").strip(),
        workspace_root=os.environ.get("WORKSPACE_ROOT", "/srv/workspaces").strip(),
        code_server_bin=os.environ.get("WORKSPACE_CODE_SERVER_BIN", "code-server").strip(),
        code_server_port_range_start=int(os.environ.get("WORKSPACE_PORT_RANGE_START", "9000")),
        code_server_port_range_end=int(os.environ.get("WORKSPACE_PORT_RANGE_END", "9100")),
        idle_timeout_seconds=float(os.environ.get("WORKSPACE_IDLE_TIMEOUT_SECONDS", "1800")),
        terminal_enabled=_is_enabled("WORKSPACE_TERMINAL_ENABLED"),
    )
