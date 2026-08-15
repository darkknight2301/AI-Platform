"""Aggregates all v1 routers under a single APIRouter."""
from __future__ import annotations

from fastapi import APIRouter

from src.api.v1.routers import health

api_router = APIRouter()
api_router.include_router(health.router)
