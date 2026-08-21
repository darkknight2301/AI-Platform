"""
Application entrypoint.

Wires together configuration, logging, middleware, API routers, and
(as of Phase 5) the model layer's registry/router. This is the
composition root: the only place besides `src/model_layer/bootstrap.py`
itself that touches Qwen-provider wiring, and even here only via the
generic `register_default_providers`/`close_providers` functions —
never `QwenProvider` directly. No chat/business-logic endpoints are
wired yet.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware

from src.api.v1.router import api_router
from src.core.config import get_settings
from src.core.logging import configure_logging
from src.core.middleware import (
    PerformanceMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
)
from src.model_layer.bootstrap import close_providers, register_default_providers
from src.model_layer.registry import ModelRegistry
from src.model_layer.router import ModelRouter

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "application_startup",
        extra={"environment": settings.environment.value, "app_name": settings.app_name},
    )

    model_registry = ModelRegistry()
    register_default_providers(model_registry)
    app.state.model_registry = model_registry
    app.state.model_router = ModelRouter(model_registry)
    logger.info(
        "model_registry_initialized",
        extra={"registered_models": [m.model_key for m in model_registry.list_models()]},
    )

    yield

    await close_providers(model_registry)
    logger.info("application_shutdown")


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_headers(request, call_next):
    """Defense-in-depth: nginx (see nginx/nginx.conf.template) sets these
    in front of the app, but the API is also reachable directly in dev/
    tests, so set them here too rather than depending solely on the proxy."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


app.add_middleware(PerformanceMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.rate_limit_requests_per_minute,
    trust_proxy_headers=settings.trust_proxy_headers,
    redis_url=settings.rate_limit_redis_url,
)
app.add_middleware(RequestIDMiddleware)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request, exc: HTTPException):
    # Stash the exception type so RequestLoggingMiddleware can include
    # it in the structured log line without changing the response body.
    request.state.error_type = type(exc).__name__
    return await http_exception_handler(request, exc)


app.include_router(api_router, prefix=settings.api_v1_prefix)
