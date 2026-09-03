"""
`SessionRegistry`: tracks active SSH tunnels (one per open workspace
connection), and closes them after `idle_timeout_seconds` of no
proxied traffic (ADR 0012, "Session lifecycle / timeouts").

**Deliberately in-memory, process-local — a known, documented
limitation, not an oversight.** This repeats the exact shape of a
mistake already made and fixed once in this codebase
(`RateLimitMiddleware`'s original process-local rate limiting, before
`RedisRateLimitStore` — see `docs/architecture/final-review.md`'s
remediation note): if the backend ever runs `WEB_CONCURRENCY > 1`,
each worker process has its own registry, so a session opened against
worker A is invisible to worker B. Unlike the rate limiter, this
isn't fixed with the same Redis-backed-counter trick, because what's
being tracked here is a live SSH connection object, not a count — a
real fix needs either sticky routing (the same worker always serving
a given workspace's proxied requests) or moving tunnel ownership out
of the Gunicorn worker pool entirely (a dedicated workspace-proxy
process, similar in spirit to how vLLM/model-serving already runs
outside the worker pool — see `docs/model-serving.md`). Flagged here
explicitly rather than silently shipped as if it were multi-worker
safe; not solved in this pass.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)


class SessionRegistry:
    def __init__(self, *, idle_timeout_seconds: float) -> None:
        self._idle_timeout_seconds = idle_timeout_seconds
        self._sessions: dict[uuid.UUID, tuple[object, object, float]] = {}
        self._lock = asyncio.Lock()

    async def put(self, workspace_id: uuid.UUID, ssh_conn: object, channel: object) -> None:
        async with self._lock:
            await self._close_existing(workspace_id)
            self._sessions[workspace_id] = (ssh_conn, channel, time.monotonic())

    async def get(self, workspace_id: uuid.UUID) -> object | None:
        async with self._lock:
            entry = self._sessions.get(workspace_id)
            if entry is None:
                return None
            ssh_conn, channel, _ = entry
            self._sessions[workspace_id] = (ssh_conn, channel, time.monotonic())
            return channel

    async def touch(self, workspace_id: uuid.UUID) -> None:
        async with self._lock:
            entry = self._sessions.get(workspace_id)
            if entry is not None:
                ssh_conn, channel, _ = entry
                self._sessions[workspace_id] = (ssh_conn, channel, time.monotonic())

    async def close(self, workspace_id: uuid.UUID) -> None:
        async with self._lock:
            await self._close_existing(workspace_id)

    async def _close_existing(self, workspace_id: uuid.UUID) -> None:
        entry = self._sessions.pop(workspace_id, None)
        if entry is None:
            return
        ssh_conn, _channel, _ = entry
        close = getattr(ssh_conn, "close", None)
        if close is not None:
            close()

    async def sweep_idle(self) -> None:
        """Close any session idle longer than `idle_timeout_seconds`.
        Intended to be called periodically by a background task (see
        `proxy.py`'s router startup) — not automatic on its own."""
        now = time.monotonic()
        async with self._lock:
            stale = [
                workspace_id
                for workspace_id, (_conn, _chan, last_active) in self._sessions.items()
                if now - last_active > self._idle_timeout_seconds
            ]
        for workspace_id in stale:
            logger.info("workspace_session_idle_timeout", extra={"workspace_id": str(workspace_id)})
            await self.close(workspace_id)
