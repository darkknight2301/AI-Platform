"""
Generic FastAPI dependencies for accessing app-level singletons set up
in `src/main.py`'s lifespan. No provider-specific code here — routes
depending on `get_model_router` receive a `ModelRouter` and never know
which providers are registered behind it.
"""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.session import AsyncSessionLocal, get_db
from src.model_layer.registry import ModelRegistry
from src.model_layer.router import ModelRouter
from src.services.chat_service import ChatService
from src.services.conversation_service import ConversationService


def get_model_registry(request: Request) -> ModelRegistry:
    return request.app.state.model_registry


def get_model_router(request: Request) -> ModelRouter:
    return request.app.state.model_router


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """The session factory used for work that must outlive the
    request-scoped `get_db` session (e.g. persisting a streamed
    generation after the response has started sending — see
    `src.services.conversation_service.stream_generation` and ADR 0009).
    A distinct, overridable dependency so tests can point it at the
    same test database/engine `get_db` is overridden to use.
    """
    return AsyncSessionLocal


def get_chat_service(router: ModelRouter = Depends(get_model_router)) -> ChatService:
    return ChatService(router)


def get_conversation_service(
    session: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
) -> ConversationService:
    return ConversationService(session, chat_service)
