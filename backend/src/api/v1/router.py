"""Aggregates all v1 routers under a single APIRouter."""
from __future__ import annotations

from fastapi import APIRouter

from src.api.v1.routers import admin, auth, chats, health, messages, models, system, users, workspaces

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(chats.router)
api_router.include_router(messages.router)
api_router.include_router(models.router)
api_router.include_router(system.router)
api_router.include_router(admin.router)
api_router.include_router(workspaces.router)
