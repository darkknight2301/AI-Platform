"""
`WorkspaceService`: ownership enforcement + get-or-create for a chat's
`Workspace` row, and the orchestration of "connect" (provision
code-server, open/reuse a tunnel, hand back a proxy URL) — the layer
`proxy.py`'s HTTP routes call into. `SSHManager`/`SessionRegistry` do
the actual work; this class is the policy/ownership layer above them,
same division of responsibility `ConversationService` has over
`ModelRouter`/`AgentRegistry`.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.agent_layer.workspace.config import WorkspaceConfig
from src.agent_layer.workspace.errors import (
    WorkspaceForbiddenRouteError,
    WorkspaceNotConfiguredError,
    WorkspaceNotFoundError,
)
from src.agent_layer.workspace.session_registry import SessionRegistry
from src.agent_layer.workspace.ssh_manager import SSHManager
from src.models.chat import Chat
from src.models.enums import WorkspaceStatus
from src.models.user import User
from src.models.workspace import Workspace
from src.repositories import workspace_repository

# Best-effort match for code-server's terminal WebSocket route — see
# ssh_manager.py's module docstring and ADR 0012's "Resolved: terminal
# is disabled": VERIFY this against the actual code-server version
# deployed (its exact terminal endpoint path is version-dependent and
# wasn't confirmed against a live install here). Defense in depth: also
# disable/hide the terminal panel via code-server's own product
# configuration if it supports one, rather than relying on this
# pattern match alone.
_TERMINAL_ROUTE_MARKERS = ("/terminal", "pty")


def is_forbidden_route(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in _TERMINAL_ROUTE_MARKERS)


class WorkspaceService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        config: WorkspaceConfig,
        ssh_manager: SSHManager,
        session_registry: SessionRegistry,
    ) -> None:
        self._session = session
        self._config = config
        self._ssh_manager = ssh_manager
        self._session_registry = session_registry

    async def _get_owned_chat(self, user: User, chat_id: uuid.UUID) -> Chat:
        chat = await self._session.get(Chat, chat_id)
        if chat is None or chat.user_id != user.id:
            # Same "don't distinguish not-found from not-owned"
            # posture ConversationService already uses (ADR — see the
            # prior code review's "403-vs-404" finding, an accepted
            # trade-off, not something this subsystem should diverge
            # from).
            raise WorkspaceNotFoundError()
        if chat.agent_key is None:
            raise WorkspaceNotConfiguredError("This chat is not agent-backed.")
        return chat

    async def get_or_create_for_chat(self, *, user: User, chat_id: uuid.UUID) -> Workspace:
        if not self._config.enabled:
            raise WorkspaceNotConfiguredError()
        if not self._config.default_host or not self._config.ssh_key_path:
            raise WorkspaceNotConfiguredError(
                "WORKSPACE_DEFAULT_HOST/WORKSPACE_SSH_KEY_PATH are not set."
            )
        chat = await self._get_owned_chat(user, chat_id)

        existing = await workspace_repository.get_by_chat_id(self._session, chat.id)
        if existing is not None:
            return existing

        # Backend suggests the folder — one per (user, chat), never a
        # path the caller supplies. See ADR 0012.
        target_path = f"{self._config.workspace_root.rstrip('/')}/{user.id}/{chat.id}"
        workspace = Workspace(
            chat_id=chat.id,
            user_id=user.id,
            host=self._config.default_host,
            ssh_port=self._config.default_ssh_port,
            ssh_username=self._config.default_ssh_username,
            target_path=target_path,
            status=WorkspaceStatus.PENDING,
        )
        self._session.add(workspace)
        await self._session.commit()
        await self._session.refresh(workspace)
        return workspace

    async def connect(self, *, user: User, chat_id: uuid.UUID) -> Workspace:
        """Ensure code-server is running for this chat's workspace and
        return the (possibly newly-created) `Workspace` row with
        `code_server_port` populated. Does not itself open the
        SSH tunnel proxy.py relays over — see `open_persistent_channel`/
        `open_ephemeral_channel`."""
        workspace = await self.get_or_create_for_chat(user=user, chat_id=chat_id)
        port = await self._ssh_manager.ensure_code_server(workspace)
        workspace.code_server_port = port
        workspace.status = WorkspaceStatus.ACTIVE
        await self._session.commit()
        await self._session.refresh(workspace)
        return workspace

    async def open_persistent_channel(self, *, user_id: uuid.UUID, workspace_id: uuid.UUID, path: str) -> object:
        """For WebSocket use only (`proxy_websocket`) — the channel is
        long-lived for the connection's duration, cached in
        `SessionRegistry` so a reconnect within its idle window can
        find it again, and swept on idle timeout. NOT for HTTP: see
        `open_ephemeral_channel` and its docstring for why reusing a
        one-shot `Connection: close` HTTP channel here was a real bug,
        not just a design choice — fixed in this pass, not shipped
        this way originally.
        """
        if is_forbidden_route(path):
            raise WorkspaceForbiddenRouteError()

        workspace = await self._get_owned_workspace(user_id, workspace_id)

        channel = await self._session_registry.get(workspace.id)
        if channel is not None:
            return channel

        ssh_conn, channel = await self._ssh_manager.open_channel(workspace, workspace.code_server_port)
        await self._session_registry.put(workspace.id, ssh_conn, channel)
        return channel

    async def open_ephemeral_channel(self, *, user_id: uuid.UUID, workspace_id: uuid.UUID, path: str):
        """For one-shot HTTP requests (`proxy_http`) — a fresh SSH
        connection + channel per call, never stored in
        `SessionRegistry`, never reused across calls.

        This is a fix, not a stylistic choice: `proxy_http` sends
        `Connection: close` and reads until EOF, which is fine for one
        request but leaves the channel dead afterward. The original
        version of this method shared `open_persistent_channel`'s
        registry-backed reuse logic, meaning a second HTTP request
        (e.g. the browser loading a JS/CSS asset while the WS
        connection was also active) could be handed back that
        already-EOF'd channel and hang. Callers of THIS method own the
        returned `(ssh_conn, channel)` and must close `ssh_conn` when
        done — `proxy_http` does so in a `finally` block.
        """
        if is_forbidden_route(path):
            raise WorkspaceForbiddenRouteError()

        workspace = await self._get_owned_workspace(user_id, workspace_id)
        return await self._ssh_manager.open_channel(workspace, workspace.code_server_port)

    async def _get_owned_workspace(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
        workspace = await workspace_repository.get_by_id(self._session, workspace_id)
        if workspace is None or workspace.user_id != user_id:
            raise WorkspaceNotFoundError()
        if workspace.code_server_port is None or workspace.status != WorkspaceStatus.ACTIVE:
            raise WorkspaceNotConfiguredError("Call connect() before proxying.")
        return workspace
