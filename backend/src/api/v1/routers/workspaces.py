"""
Workspace/Web IDE routes — the only thing the browser ever talks to
for a workspace (ADR 0012, §Web IDE). No host/port/SSH credential
ever appears in a request or response here; everything past this
router is `WorkspaceService`/`SSHManager`'s problem.

`connect_workspace` is Bearer-authenticated (normal `get_current_user`,
called via `fetch()` from the SPA) and mints a short-lived,
workspace-scoped ticket (`tickets.py`) as an `HttpOnly` cookie scoped
to that workspace's proxy path. `proxy_http`/`proxy_websocket` are
authenticated from that cookie instead — see `tickets.py`'s docstring
for why a plain browser navigation/WebSocket handshake needs this
instead of the platform's normal Authorization-header auth.
"""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request, Response, WebSocket
from fastapi.responses import Response as HTTPResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect, WebSocketState

from src.agent_layer.workspace import tickets
from src.agent_layer.workspace.errors import WorkspaceError, WorkspaceNotFoundError
from src.agent_layer.workspace.schemas import WorkspaceInfo
from src.agent_layer.workspace.workspace_service import WorkspaceService
from src.api.deps import get_workspace_service
from src.auth.dependencies import get_current_user
from src.core.config import get_settings
from src.db.session import get_db
from src.models.enums import AuditResult
from src.models.user import User
from src.repositories import audit_log_repository

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

_COOKIE_NAME_PREFIX = "ws_ticket_"


def _to_error_response(exc: WorkspaceError) -> HTTPResponse:
    status_code = 404 if "not exist" in exc.safe_message.lower() else 400
    return HTTPResponse(content=exc.safe_message, status_code=status_code)


def _cookie_name(workspace_id: uuid.UUID) -> str:
    return f"{_COOKIE_NAME_PREFIX}{workspace_id}"


@router.post("/{chat_id}/connect", response_model=WorkspaceInfo)
async def connect_workspace(
    chat_id: uuid.UUID,
    response: Response,
    current_user: User = Depends(get_current_user),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
    session: AsyncSession = Depends(get_db),
):
    try:
        workspace = await workspace_service.connect(user=current_user, chat_id=chat_id)
    except WorkspaceError as exc:
        return _to_error_response(exc)

    idle_timeout = workspace_service._config.idle_timeout_seconds  # noqa: SLF001 - internal, same module family
    ticket = tickets.issue_ticket(
        user_id=current_user.id, workspace_id=workspace.id, ttl_seconds=idle_timeout
    )
    response.set_cookie(
        key=_cookie_name(workspace.id),
        value=ticket,
        httponly=True,
        secure=get_settings().is_production,
        samesite="lax",
        max_age=int(idle_timeout),
        path=f"/api/v1/workspaces/{workspace.id}/",
    )

    # Session-level metadata only (who, which workspace, when) — never
    # file contents or terminal output, same posture SECURITY.md
    # already establishes elsewhere. Uses the SAME session instance
    # `workspace_service` holds (FastAPI caches `Depends(get_db)`
    # within one request), so this commits alongside `connect()`'s own
    # writes, not as a separate transaction.
    await audit_log_repository.create(
        session,
        actor_user_id=current_user.id,
        action="WORKSPACE_CONNECT",
        result=AuditResult.SUCCESS,
        target_type="workspace",
        target_id=str(workspace.id),
    )
    await session.commit()

    return WorkspaceInfo(
        id=workspace.id,
        chat_id=workspace.chat_id,
        status=workspace.status,
        target_path=workspace.target_path,
        connect_url=f"/api/v1/workspaces/{workspace.id}/proxy/",
        terminal_enabled=workspace_service._config.terminal_enabled,  # noqa: SLF001
    )


async def _user_id_from_cookie(request: Request, workspace_id: uuid.UUID) -> uuid.UUID:
    ticket = request.cookies.get(_cookie_name(workspace_id))
    if not ticket:
        raise WorkspaceNotFoundError()  # same non-distinguishing posture as elsewhere in this app
    user_id = tickets.verify_ticket(ticket, workspace_id=workspace_id)
    if user_id is None:
        raise WorkspaceNotFoundError()
    return user_id


@router.api_route(
    "/{workspace_id}/proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
)
async def proxy_http(
    workspace_id: uuid.UUID,
    path: str,
    request: Request,
    workspace_service: WorkspaceService = Depends(get_workspace_service),
):
    """Relays one HTTP request to code-server over the SSH channel.

    NOTE: a real reverse proxy needs to stream the body both ways and
    forward the full header set (minus hop-by-hop headers); this
    passes the essentials (method, path, body) through
    `asyncssh`'s stream pair. Verify against your actual `code-server`
    version's asset-loading behavior (it may issue range requests for
    large files) before relying on this for anything beyond the editor
    UI shell — flagged as unverified, same as `ssh_manager.py`.
    """
    try:
        user_id = await _user_id_from_cookie(request, workspace_id)
        ssh_conn, channel = await workspace_service.open_ephemeral_channel(
            user_id=user_id, workspace_id=workspace_id, path=path
        )
    except WorkspaceError as exc:
        return _to_error_response(exc)

    try:
        writer, reader = channel
        body = await request.body()
        request_line = f"{request.method} /{path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
        for key, value in request.headers.items():
            if key.lower() in ("host", "connection", "content-length", "cookie"):
                continue  # never forward our own auth cookie to code-server
            request_line += f"{key}: {value}\r\n"
        request_line += f"Content-Length: {len(body)}\r\n\r\n"
        writer.write(request_line.encode() + body)

        raw = await reader.read()
        head, _, response_body = raw.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n", 1)[0]
        status_code = int(status_line.split(b" ")[1]) if b" " in status_line else 502
        return HTTPResponse(content=response_body, status_code=status_code)
    finally:
        # This connection is one-shot (see open_ephemeral_channel's
        # docstring) — always close it here, never leave it for
        # SessionRegistry to track or a future request to reuse.
        ssh_conn.close()


@router.websocket("/{workspace_id}/proxy-ws/{path:path}")
async def proxy_websocket(
    websocket: WebSocket,
    workspace_id: uuid.UUID,
    path: str,
    workspace_service: WorkspaceService = Depends(get_workspace_service),
):
    """WebSocket relay for code-server's editor/file-watcher traffic.

    Authenticated the same way as `proxy_http` — via the cookie the
    browser's WebSocket handshake sends automatically for a
    same-origin connection under this path, not a header (WebSocket
    clients can't set arbitrary headers from browser JS either).
    Terminal routes are refused at `open_persistent_channel`/
    `open_ephemeral_channel` ->
    `is_forbidden_route` — the actual enforcement point for "terminal
    is disabled" (ADR 0012), independent of the code-server UI.
    """
    ticket = websocket.cookies.get(_cookie_name(workspace_id))
    user_id = tickets.verify_ticket(ticket, workspace_id=workspace_id) if ticket else None
    if user_id is None:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    try:
        _ssh_conn, channel = await workspace_service.open_persistent_channel(
            user_id=user_id, workspace_id=workspace_id, path=path
        )
    except WorkspaceError as exc:
        await websocket.close(code=4403, reason=exc.safe_message)
        return

    await websocket.accept()
    writer, reader = channel

    async def _relay_remote_to_browser() -> None:
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                await websocket.send_bytes(chunk)
        except Exception:
            pass
        finally:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()

    relay_task = asyncio.create_task(_relay_remote_to_browser())
    try:
        while True:
            data = await websocket.receive_bytes()
            writer.write(data)
    except WebSocketDisconnect:
        pass
    finally:
        relay_task.cancel()
        writer.close()
