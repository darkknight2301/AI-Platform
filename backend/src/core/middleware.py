"""
Lightweight ASGI middleware: request-ID propagation and in-process
performance metrics for the Developer diagnostics endpoints.

Metrics are process-local (reset on restart, not shared across
instances) — sufficient for the foundation this phase establishes.
A real deployment would export these to a metrics backend instead;
that's out of scope here.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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


metrics = PerformanceMetrics()


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response: Response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        metrics.record(response.status_code, duration_ms)
        return response
