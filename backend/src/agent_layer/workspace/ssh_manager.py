"""
`SSHManager`: the only piece of this platform that ever holds/uses an
SSH credential (ADR 0012, §Web IDE — "Backend/Workspace security").
The browser never sees a host, port, or key; it only ever talks to
`proxy.py`, which is the only caller of this class.

Uses `asyncssh` (lazy-imported, same pattern as `RedisRateLimitStore`
in `core/middleware.py` and `vllm` in the model-serving scripts) so
the rest of the app has no hard dependency on it unless
`WORKSPACE_ENABLED=true` actually selects this code path.

**Unverified against a live asyncssh install / real remote host** —
no network access was available while writing this (same constraint
noted throughout this project's docs). The command this runs to
start `code-server` and the exact port-liveness check should be
smoke-tested against your actual `code-server` version before relying
on this in production; the shape (connect, check-or-start, open a
direct-tcpip channel) is correct, the exact shell one-liner may need
adjustment.
"""
from __future__ import annotations

import logging
import shlex

from src.agent_layer.workspace.config import WorkspaceConfig
from src.agent_layer.workspace.errors import WorkspaceProvisioningError
from src.models.workspace import Workspace

logger = logging.getLogger(__name__)


def _import_asyncssh():
    try:
        import asyncssh
    except ImportError as exc:
        raise WorkspaceProvisioningError(
            "The 'asyncssh' package is required for WORKSPACE_ENABLED=true "
            "but is not installed."
        ) from exc
    return asyncssh


class SSHManager:
    def __init__(self, config: WorkspaceConfig) -> None:
        self._config = config

    async def _connect(self, workspace: Workspace):
        asyncssh = _import_asyncssh()
        try:
            return await asyncssh.connect(
                workspace.host,
                port=workspace.ssh_port,
                username=workspace.ssh_username,
                client_keys=[self._config.ssh_key_path],
                known_hosts=None,  # see config.py's module docstring / .env.example
                # for the production recommendation to pin known_hosts
                # once host keys are catalogued, rather than trusting
                # on first connect.
            )
        except Exception as exc:
            logger.error(
                "workspace_ssh_connect_failed",
                extra={"workspace_id": str(workspace.id), "host": workspace.host},
                exc_info=True,
            )
            raise WorkspaceProvisioningError() from exc

    async def ensure_code_server(self, workspace: Workspace) -> int:
        """Confirm `code-server` is running on `workspace.host`, bound
        to `workspace.target_path`, starting it if not. Returns the
        port it's listening on.

        Binds to 127.0.0.1 on the remote host only (never
        0.0.0.0/publicly routable — see ADR 0012's "Network security")
        and disables `code-server`'s own auth (`--auth none`): this
        platform's proxy layer is the actual authentication/
        authorization boundary (the port is unreachable except via the
        SSH tunnel this class itself opens), so a second, redundant
        auth layer at code-server would just be one more credential to
        manage without adding real protection.
        """
        port = workspace.code_server_port or self._config.code_server_port_range_start
        conn = await self._connect(workspace)
        try:
            check = await conn.run(f"curl -sf -o /dev/null http://127.0.0.1:{port}/", check=False)
            if check.exit_status == 0:
                return port

            start_cmd = (
                f"nohup {shlex.quote(self._config.code_server_bin)} "
                f"--bind-addr 127.0.0.1:{port} --auth none "
                f"{shlex.quote(workspace.target_path)} "
                f">/tmp/code-server-{workspace.id}.log 2>&1 & disown"
            )
            await conn.run(f"mkdir -p {shlex.quote(workspace.target_path)}", check=True)
            await conn.run(start_cmd, check=True)
            return port
        except Exception as exc:
            logger.error(
                "workspace_code_server_start_failed",
                extra={"workspace_id": str(workspace.id)},
                exc_info=True,
            )
            raise WorkspaceProvisioningError() from exc
        finally:
            conn.close()

    async def open_channel(self, workspace: Workspace, port: int):
        """Open a direct-tcpip SSH channel to `code-server`'s port on
        the remote host, for `proxy.py` to relay HTTP/WebSocket bytes
        over. Caller owns the returned connection's lifecycle (close
        it when the proxied request/connection ends) — see
        `session_registry.py`, which is what actually tracks these.
        """
        conn = await self._connect(workspace)
        try:
            return conn, await conn.open_connection(host="127.0.0.1", port=port)
        except Exception:
            conn.close()
            raise
