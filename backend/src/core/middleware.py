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

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory fixed-window rate limiter, keyed by client IP.

    Process-local — same documented limitation as `PerformanceMetrics`
    above (a real multi-instance deployment needs a shared store, e.g.
    Redis). Sufficient as the foundation this phase establishes.
    Health checks are exempt so load balancers aren't throttled.
    """

    _EXEMPT_PATHS = {"/api/v1/health"}

    def __init__(self, app, requests_per_minute: int) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._window_seconds = 60.0
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)

        client_key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - self._window_seconds
        hits = self._hits[client_key]
        while hits and hits[0] < window_start:
            hits.pop(0)

        if len(hits) >= self._limit:
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

        hits.append(now)
        return await call_next(request)


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response: Response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        metrics.record(response.status_code, duration_ms)
        return response
