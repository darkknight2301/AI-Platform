"""
Short-lived, workspace-scoped tickets — the browser-auth path for
`proxy.py`'s GET/WebSocket routes.

Why not the platform's normal Bearer JWT (`get_current_user`) for
these two routes: a plain browser navigation (`<iframe src=...>`,
`window.open(...)`, or a WebSocket handshake) cannot set an
`Authorization` header — only whatever the browser sends
automatically, i.e. cookies. `connect_workspace` (still
Bearer-authenticated, called via `fetch()` from the SPA) mints one of
these and sets it as an `HttpOnly` cookie scoped to that one
workspace's proxy path; every subsequent same-origin request the
browser makes under that path (the editor's asset requests, the
WebSocket handshake) carries it automatically, no frontend wiring
needed beyond navigating to `connect_url` after `connect()` resolves.

Stateless (a signed JWT, verified without a DB lookup) — deliberately
not tracked in `SessionRegistry` or any other in-memory store, so
unlike that registry this doesn't inherit its multi-worker-process
staleness problem (see `session_registry.py`'s docstring): any backend
worker can verify a ticket minted by any other worker.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import InvalidTokenError

from src.core.config import get_settings

_PURPOSE = "workspace_ticket"


def issue_ticket(*, user_id: uuid.UUID, workspace_id: uuid.UUID, ttl_seconds: float) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "workspace_id": str(workspace_id),
        "purpose": _PURPOSE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_ticket(ticket: str, *, workspace_id: uuid.UUID) -> uuid.UUID | None:
    """Returns the ticket's user_id if valid, not expired, and scoped
    to `workspace_id` — None otherwise (never raises)."""
    settings = get_settings()
    try:
        payload = jwt.decode(ticket, settings.secret_key, algorithms=[settings.algorithm])
    except InvalidTokenError:
        return None

    if payload.get("purpose") != _PURPOSE:
        return None
    if payload.get("workspace_id") != str(workspace_id):
        return None
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None
