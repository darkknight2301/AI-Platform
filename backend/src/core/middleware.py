"""
Lightweight ASGI middleware: request-ID propagation and in-process
performance metrics for the Developer diagnostics endpoints.

Metrics are process-local (reset on restart, not shared across
instances) — sufficient for the foundation this phase establishes.
A real deployment would export these to a metrics backend instead;
that's out of scope here.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from typing import Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


def resolve_client_key(request: Request, *, trust_proxy_headers: bool) -> str:
    """Determine the identifier RateLimitMiddleware buckets a request by.

    When `trust_proxy_headers` is False (the safe default), this is
    always the raw ASGI transport address -- correct when the app is
    reachable directly (dev, tests) since nothing upstream could have
    set proxy headers legitimately.

    When True, the caller is asserting the app sits behind a proxy that
    (a) is the *only* way to reach it and (b) itself sets/overwrites
    `X-Forwarded-For`/`X-Real-IP` rather than passing a client-supplied
    value through unchanged (nginx's `proxy_add_x_forwarded_for` does
    this correctly -- see nginx/nginx.conf.template). Under that
    assumption the left-most `X-Forwarded-For` entry is the original
    client. If both assumptions don't hold (app reachable directly, or a
    proxy that blindly forwards client headers), enabling this setting
    lets any caller forge their bucket key and defeats the limiter --
    it must not be enabled outside that specific topology.
    """
    if trust_proxy_headers:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            candidate = forwarded_for.split(",")[0].strip()
            if candidate:
                return candidate
        real_ip = request.headers.get("X-Real-IP")
        if real_ip and real_ip.strip():
            return real_ip.strip()
    return request.client.host if request.client else "unknown"


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class PerformanceMetrics:
    """Simple in-memory counters, exposed via /api/v1/system/performance."""

    def __init__(self) -> None:
        self.start_time = time.monotonic()
        self.total_requests = 0
        self.total_duration_ms = 0.0
        self.status_class_counts: dict[str, int] = defaultdict(int)

    def record(self, status_code: int, duration_ms: float) -> None:
        self.total_requests += 1
        self.total_duration_ms += duration_ms
        status_class = f"{status_code // 100}xx"
        self.status_class_counts[status_class] += 1

    @property
    def average_response_time_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_duration_ms / self.total_requests

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.start_time


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured per-request log line: timestamp (auto), request_id,
    user_id, endpoint, model, duration, status, error_type. Never logs
    request/response bodies — prompts/replies are deliberately excluded.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        try:
            response: Response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error(
                "http_request",
                extra={
                    "request_id": getattr(request.state, "request_id", None),
                    "user_id": getattr(request.state, "current_user_id", None),
                    "endpoint": f"{request.method} {request.url.path}",
                    "model": getattr(request.state, "model_key", None),
                    "duration_ms": round(duration_ms, 2),
                    "status": 500,
                    "error_type": type(exc).__name__,
                },
            )
            raise
        duration_ms = (time.monotonic() - start) * 1000
        error_type = getattr(request.state, "error_type", None)
        level = logger.error if response.status_code >= 500 else (
            logger.warning if response.status_code >= 400 else logger.info
        )
        level(
            "http_request",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "user_id": getattr(request.state, "current_user_id", None),
                "endpoint": f"{request.method} {request.url.path}",
                "model": getattr(request.state, "model_key", None),
                "duration_ms": round(duration_ms, 2),
                "status": response.status_code,
                "error_type": error_type,
            },
        )
        return response


class RateLimitStore(Protocol):
    """Where RateLimitMiddleware records and checks hits.

    `hit()` records one request for `key` and returns whether it should
    be allowed (i.e. the count for `key` within `window_seconds`,
    including this request, is still <= `limit`). Kept intentionally
    small so alternate backends (see `RedisRateLimitStore`) are a
    drop-in swap for `InMemoryRateLimitStore` — RateLimitMiddleware
    never branches on which one it has.
    """

    async def hit(self, key: str, *, limit: int, window_seconds: float) -> bool: ...


class InMemoryRateLimitStore:
    """Sliding-window counter kept in process memory.

    Correct for a single instance. Process-local: each backend replica
    gets its own independent budget, so the *effective* limit under N
    replicas is N times the configured value — see PERFORMANCE.md.
    This is the default store; use `RedisRateLimitStore` (selected via
    `Settings.rate_limit_redis_url`) once running more than one replica.
    """

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def hit(self, key: str, *, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        window_start = now - window_seconds
        hits = self._hits[key]
        while hits and hits[0] < window_start:
            hits.pop(0)
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


class RedisRateLimitStore:
    """Sliding-window counter backed by a Redis sorted set, shared across
    every backend replica — fixes the process-local under-enforcement
    `InMemoryRateLimitStore` has once more than one instance is running
    (see PERFORMANCE.md's "Scalability bottlenecks").

    Fails OPEN on any Redis error (logs a warning, allows the request).
    Rate limiting here is defense-in-depth, not the primary access
    control — auth/RBAC own that (see auth/dependencies.py) — so an
    unreachable Redis should degrade this specific protection rather
    than take the whole API down.
    """

    def __init__(self, redis_url: str) -> None:
        try:
            import redis.asyncio as redis_asyncio
        except ImportError as exc:  # pragma: no cover - exercised only when misconfigured
            raise RuntimeError(
                "rate_limit_redis_url is configured but the 'redis' package "
                "is not installed. Add `redis` to backend/requirements.txt, "
                "or unset RATE_LIMIT_REDIS_URL to use the in-memory limiter."
            ) from exc
        self._redis = redis_asyncio.from_url(redis_url, decode_responses=True)

    async def hit(self, key: str, *, limit: int, window_seconds: float) -> bool:
        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"
        member = f"{now:.6f}:{uuid.uuid4().hex}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, 0, window_start)
                pipe.zadd(redis_key, {member: now})
                pipe.zcard(redis_key)
                pipe.expire(redis_key, int(window_seconds) + 1)
                _, _, count, _ = await pipe.execute()
            return count <= limit
        except Exception:
            logger.warning(
                "rate_limit_redis_unavailable",
                extra={"redis_key": redis_key},
                exc_info=True,
            )
            return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter, keyed by caller identity.

    The identity key comes from `resolve_client_key()` — by default the
    raw ASGI transport address, or `X-Forwarded-For`/`X-Real-IP` when
    `trust_proxy_headers=True` and the app is reachable only through a
    proxy that sets those headers itself (see that function's docstring
    for why the default is False). The storage backend is pluggable
    (`RateLimitStore`) so this class behaves identically whether counts
    are process-local (`InMemoryRateLimitStore`) or shared across
    replicas via Redis (`RedisRateLimitStore`).

    Health checks are exempt so load balancers aren't throttled.
    """

    _EXEMPT_PATHS = {"/api/v1/health"}

    def __init__(
        self,
        app,
        requests_per_minute: int,
        *,
        trust_proxy_headers: bool = False,
        redis_url: str | None = None,
        store: RateLimitStore | None = None,
    ) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._window_seconds = 60.0
        self._trust_proxy_headers = trust_proxy_headers
        if store is not None:
            self._store: RateLimitStore = store
        elif redis_url:
            self._store = RedisRateLimitStore(redis_url)
        else:
            self._store = InMemoryRateLimitStore()

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)

        client_key = resolve_client_key(request, trust_proxy_headers=self._trust_proxy_headers)
        allowed = await self._store.hit(
            client_key, limit=self._limit, window_seconds=self._window_seconds
        )

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "request_id": getattr(request.state, "request_id", None),
                    "endpoint": f"{request.method} {request.url.path}",
                    "client": client_key,
                },
            )
            return Response(
                content='{"detail":"Too many requests. Please slow down."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        return await call_next(request)


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response: Response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        metrics.record(response.status_code, duration_ms)
        return response
