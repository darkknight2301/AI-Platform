"""
Generic FastAPI dependencies for accessing app-level singletons set up
in `src/main.py`'s lifespan. No provider-specific code here — routes
depending on `get_model_router` receive a `ModelRouter` and never know
which providers are registered behind it.
"""
from __future__ import annotations

from fastapi import Request

from src.model_layer.registry import ModelRegistry
from src.model_layer.router import ModelRouter


def get_model_registry(request: Request) -> ModelRegistry:
    return request.app.state.model_registry


def get_model_router(request: Request) -> ModelRouter:
    return request.app.state.model_router
