"""
Chat CRUD + conversation endpoints.

Every route resolves ownership via `ConversationService`, which
enforces strict self-ownership only (see `src/services/conversation_service.py`
and ADR 0009) — there is no Owner/Manager bypass for reading or acting
on another user's chats, consistent with Phase 3's stance on private
chat content.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_chat_service, get_conversation_service, get_session_factory
from src.api.error_mapping import CONVERSATION_EXCEPTIONS, to_http_exception
from src.auth.dependencies import get_current_user
from src.db.session import get_db
from src.models.enums import ChatStatus
from src.models.user import User
from src.repositories import model_repository
from src.schemas.chat import ChatCreateRequest, ChatListResponse, ChatSummary, ChatUpdateRequest
from src.schemas.message import (
    ChatHistoryResponse,
    MessageExchangeResponse,
    SendMessageRequest,
)
from src.services.chat_service import ChatService
from src.services.conversation_service import ConversationService, stream_generation

router = APIRouter(prefix="/chats", tags=["chats"])


async def _to_chat_summary(session: AsyncSession, chat) -> ChatSummary:
    model = await model_repository.get_by_id(session, chat.model_id)
    return ChatSummary(
        id=chat.id,
        title=chat.title,
        status=chat.status,
        model_id=chat.model_id,
        model_key=model.model_key if model else "",
        revision=chat.revision,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _sse_line(payload) -> str:
    return f"data: {json.dumps(payload.model_dump(mode='json'))}\n\n"


@router.post("", response_model=ChatSummary, status_code=201)
async def create_chat(
    payload: ChatCreateRequest,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
    session: AsyncSession = Depends(get_db),
):
    try:
        chat = await conversation.create_chat(
            user=current_user, model_key=payload.model_key, title=payload.title
        )
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc
    return await _to_chat_summary(session, chat)


@router.get("", response_model=ChatListResponse)
async def list_chats(
    status_filter: ChatStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
    session: AsyncSession = Depends(get_db),
):
    chats = await conversation.list_chats(
        user=current_user, status=status_filter, limit=limit, offset=offset
    )
    summaries = [await _to_chat_summary(session, c) for c in chats]
    return ChatListResponse(chats=summaries, total=len(summaries))


@router.get("/{chat_id}", response_model=ChatSummary)
async def get_chat(
    chat_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
    session: AsyncSession = Depends(get_db),
):
    try:
        chat = await conversation.get_chat(user=current_user, chat_id=chat_id)
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc
    return await _to_chat_summary(session, chat)


@router.patch("/{chat_id}", response_model=ChatSummary)
async def update_chat(
    chat_id: uuid.UUID,
    payload: ChatUpdateRequest,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
    session: AsyncSession = Depends(get_db),
):
    try:
        chat = await conversation.update_chat(
            user=current_user,
            chat_id=chat_id,
            title=payload.title,
            status=payload.status,
            model_key=payload.model_key,
        )
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc
    return await _to_chat_summary(session, chat)


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
):
    request_id = getattr(request.state, "request_id", None)
    try:
        await conversation.delete_chat(user=current_user, chat_id=chat_id, request_id=request_id)
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc


@router.get("/{chat_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    chat_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
):
    try:
        messages = await conversation.get_history(
            user=current_user, chat_id=chat_id, limit=limit, offset=offset
        )
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc
    out = [await conversation.to_message_out(m) for m in messages]
    return ChatHistoryResponse(chat_id=chat_id, messages=out)


@router.post("/{chat_id}/messages", response_model=None, status_code=201)
async def send_message(
    chat_id: uuid.UUID,
    payload: SendMessageRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
    chat_service: ChatService = Depends(get_chat_service),
    session_factory=Depends(get_session_factory),
):
    """Send a prompt. Non-streaming by default; set `stream: true` for a
    Server-Sent-Events response using the common streaming format
    (`StreamEventOut`) regardless of which model provider handles it.
    """
    request_id = getattr(request.state, "request_id", None)

    if payload.stream:
        try:
            pending = await conversation.prepare_send_stream(
                user=current_user, chat_id=chat_id, content=payload.content, request_id=request_id
            )
        except CONVERSATION_EXCEPTIONS as exc:
            raise to_http_exception(exc) from exc

        async def event_source():
            async for event in stream_generation(chat_service, pending, session_factory):
                yield _sse_line(event)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    try:
        user_message, assistant_message = await conversation.send_message(
            user=current_user, chat_id=chat_id, content=payload.content, request_id=request_id
        )
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc

    assistant_out = await conversation.to_message_out(assistant_message)
    request.state.model_key = assistant_out.model_key

    return MessageExchangeResponse(
        user_message=await conversation.to_message_out(user_message),
        assistant_message=assistant_out,
    )
