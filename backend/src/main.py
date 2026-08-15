"""
Application entrypoint.

Wires together configuration, logging, middleware, and API routers.
Business functionality (chat, model orchestration, etc.) is deliberately
NOT included yet — Phase 1 establishes foundation only.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.v1.router import api_router
from src.core.config import get_settings
from src.core.logging import configure_logging
from src.core.middleware import PerformanceMiddleware, RequestIDMiddleware

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "application_startup",
        extra={"environment": settings.environment.value, "app_name": settings.app_name},
    )
    yield
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
app.add_middleware(PerformanceMiddleware)
app.add_middleware(RequestIDMiddleware)

app.include_router(api_router, prefix=settings.api_v1_prefix)
