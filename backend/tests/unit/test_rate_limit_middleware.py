"""Unit tests for RateLimitMiddleware's client-key resolution and
pluggable storage backend.

Regression coverage for a review finding: the middleware used to key
exclusively on the raw ASGI transport address, which — behind the
nginx topology `docker-compose.prod.yml` describes (backend is
`expose`-only, reachable only via nginx) — collapses every distinct
client to nginx's own upstream address, turning a per-client limit
into one shared across all clients. `resolve_client_key()` and the
`trust_proxy_headers` flag fix this; these tests exercise both the
vulnerable-if-misconfigured behavior (flag off) and the fixed behavior
(flag on), plus the `RateLimitStore` abstraction that makes a
Redis-backed, cross-replica store a drop-in swap for the in-memory one.
"""
from __future__ import annotations

import importlib.util

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.core.middleware import InMemoryRateLimitStore, RateLimitMiddleware, resolve_client_key


def _build_app(**middleware_kwargs) -> Starlette:
    async def _ok(request: Request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/ping", _ok)])
    app.add_middleware(RateLimitMiddleware, requests_per_minute=2, **middleware_kwargs)
    return app


# --- resolve_client_key ---------------------------------------------------


def test_resolve_client_key_ignores_forwarded_headers_by_default():
    """Without trust_proxy_headers, X-Forwarded-For must never be trusted
    (it's attacker-controlled whenever the app is reachable directly)."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.5, 10.0.0.1")],
        "client": ("172.18.0.3", 12345),
    }
    request = Request(scope)
    assert resolve_client_key(request, trust_proxy_headers=False) == "172.18.0.3"


def test_resolve_client_key_uses_leftmost_forwarded_for_when_trusted():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.5, 10.0.0.1")],
        "client": ("172.18.0.3", 12345),
    }
    request = Request(scope)
    assert resolve_client_key(request, trust_proxy_headers=True) == "203.0.113.5"


def test_resolve_client_key_falls_back_to_real_ip_header():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-real-ip", b"198.51.100.7")],
        "client": ("172.18.0.3", 12345),
    }
    request = Request(scope)
    assert resolve_client_key(request, trust_proxy_headers=True) == "198.51.100.7"


def test_resolve_client_key_falls_back_to_transport_address_when_no_headers_present():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("172.18.0.3", 12345),
    }
    request = Request(scope)
    assert resolve_client_key(request, trust_proxy_headers=True) == "172.18.0.3"


# --- End-to-end middleware behavior ---------------------------------------


def test_distinct_clients_share_one_bucket_when_proxy_headers_not_trusted():
    """This is the pre-fix failure mode, asserted explicitly: with
    trust_proxy_headers left at its (safe) default of False, two
    different X-Forwarded-For values sharing the same transport address
    (e.g. both proxied through the same nginx container) are correctly
    treated as ONE caller for rate-limiting purposes -- proving the app
    doesn't accidentally trust a header that could be forged when it
    IS reachable directly."""
    app = _build_app()  # trust_proxy_headers defaults to False
    with TestClient(app) as client:
        r1 = client.get("/ping", headers={"X-Forwarded-For": "203.0.113.5"})
        r2 = client.get("/ping", headers={"X-Forwarded-For": "203.0.113.9"})
        r3 = client.get("/ping", headers={"X-Forwarded-For": "203.0.113.9"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        # Limit is 2/min; all three requests share the TestClient's single
        # transport address as their key regardless of the spoofed header,
        # so the third request is correctly throttled.
        assert r3.status_code == 429
        assert r3.headers["Retry-After"] == "60"


def test_distinct_clients_get_independent_buckets_when_proxy_headers_trusted():
    app = _build_app(trust_proxy_headers=True)
    with TestClient(app) as client:
        for _ in range(2):
            resp = client.get("/ping", headers={"X-Forwarded-For": "203.0.113.5"})
            assert resp.status_code == 200
        # Client A is now at its limit...
        assert client.get("/ping", headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 429
        # ...but a distinct client (different X-Forwarded-For) is unaffected.
        resp_b = client.get("/ping", headers={"X-Forwarded-For": "203.0.113.9"})
        assert resp_b.status_code == 200


def test_health_check_path_is_exempt_from_rate_limiting():
    async def _health(request: Request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/api/v1/health", _health)])
    app.add_middleware(RateLimitMiddleware, requests_per_minute=1)
    with TestClient(app) as client:
        for _ in range(5):
            assert client.get("/api/v1/health").status_code == 200


# --- Pluggable store --------------------------------------------------------


class _AlwaysAllowStore:
    """Minimal fake satisfying the RateLimitStore protocol."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, float]] = []

    async def hit(self, key: str, *, limit: int, window_seconds: float) -> bool:
        self.calls.append((key, limit, window_seconds))
        return True


class _AlwaysDenyStore:
    async def hit(self, key: str, *, limit: int, window_seconds: float) -> bool:
        return False


def test_middleware_uses_injected_store_instead_of_building_its_own():
    fake_store = _AlwaysAllowStore()
    app = _build_app(store=fake_store)
    with TestClient(app) as client:
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert fake_store.calls, "expected the injected store's hit() to be called"


def test_middleware_returns_429_when_store_denies():
    app = _build_app(store=_AlwaysDenyStore())
    with TestClient(app) as client:
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert resp.json() == {"detail": "Too many requests. Please slow down."}


async def test_in_memory_store_enforces_sliding_window_limit():
    store = InMemoryRateLimitStore()
    assert await store.hit("k", limit=2, window_seconds=60.0) is True
    assert await store.hit("k", limit=2, window_seconds=60.0) is True
    assert await store.hit("k", limit=2, window_seconds=60.0) is False
    # A different key has its own independent budget.
    assert await store.hit("other", limit=2, window_seconds=60.0) is True


@pytest.mark.skipif(
    importlib.util.find_spec("redis") is None,
    reason="redis package not installed in this environment",
)
async def test_redis_store_hit_fails_open_when_redis_unavailable():
    """RedisRateLimitStore must fail OPEN (allow the request) rather than
    raise or block traffic if Redis itself is unreachable -- rate
    limiting is defense-in-depth here, not the primary access control."""
    from src.core.middleware import RedisRateLimitStore

    class _BrokenPipeline:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def zremrangebyscore(self, *a, **kw):
            return self

        def zadd(self, *a, **kw):
            return self

        def zcard(self, *a, **kw):
            return self

        def expire(self, *a, **kw):
            return self

        async def execute(self):
            raise ConnectionError("simulated redis outage")

    class _BrokenRedisClient:
        def pipeline(self, transaction: bool = True):
            return _BrokenPipeline()

    store = RedisRateLimitStore.__new__(RedisRateLimitStore)
    store._redis = _BrokenRedisClient()
    allowed = await store.hit("some-key", limit=1, window_seconds=60.0)
    assert allowed is True
