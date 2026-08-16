"""
Message-scoped endpoints: edit a prompt, regenerate a reply, list a
slot's revisions, and activate a specific revision (server-persisted
undo/redo). See `src/models/message.py` for the revision model and
`src/services/conversation_service.py` for the orchestration.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from src.api.deps import get_chat_service, get_conversation_service, get_session_factory
from src.api.error_mapping import CONVERSATION_EXCEPTIONS, to_http_exception
from src.auth.dependencies import get_current_user
from src.models.user import User
from src.schemas.message import (
    EditMessageRequest,
    MessageExchangeResponse,
    MessageOut,
    MessageRevisionsResponse,
    RegenerateMessageRequest,
)
from src.services.chat_service import ChatService
from src.services.conversation_service import ConversationService, stream_generation

router = APIRouter(prefix="/messages", tags=["messages"])


def _sse_line(payload) -> str:
    return f"data: {json.dumps(payload.model_dump(mode='json'))}\n\n"


@router.post("/{message_id}/edit", response_model=None)
async def edit_message(
    message_id: uuid.UUID,
    payload: EditMessageRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
    chat_service: ChatService = Depends(get_chat_service),
    session_factory=Depends(get_session_factory),
):
    """Edit a user prompt. Never overwrites the previous text — it creates
    a new revision in the same slot (see the module docstring on
    `src/models/message.py`) and, if a reply already followed this
    prompt, regenerates that reply for the edited version."""
    request_id = getattr(request.state, "request_id", None)

    if payload.stream:
        # Streaming edit: create the new prompt revision synchronously
        # (fast, no model call), then stream only the regenerated reply.
        try:
            pending = await conversation.prepare_edit_stream(
                user=current_user, message_id=message_id, content=payload.content, request_id=request_id
            )
        except CONVERSATION_EXCEPTIONS as exc:
            raise to_http_exception(exc) from exc

        if pending is None:
            # Edited prompt had no paired reply to regenerate — nothing to stream.
            return StreamingResponse(iter(()), media_type="text/event-stream")

        async def event_source():
            async for event in stream_generation(chat_service, pending, session_factory):
                yield _sse_line(event)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    try:
        new_user_message, assistant_message = await conversation.edit_message(
            user=current_user, message_id=message_id, content=payload.content, request_id=request_id
        )
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc

    return MessageExchangeResponse(
        user_message=await conversation.to_message_out(new_user_message),
        assistant_message=(
            await conversation.to_message_out(assistant_message)
            if assistant_message is not None
            else None
        ),
    )


@router.post("/{message_id}/regenerate", response_model=None)
async def regenerate_message(
    message_id: uuid.UUID,
    payload: RegenerateMessageRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
    chat_service: ChatService = Depends(get_chat_service),
    session_factory=Depends(get_session_factory),
):
    """Regenerate an assistant reply without touching the prompt that
    produced it, or any other historical state."""
    request_id = getattr(request.state, "request_id", None)

    if payload.stream:
        try:
            pending = await conversation.prepare_regenerate_stream(
                user=current_user, message_id=message_id, request_id=request_id
            )
        except CONVERSATION_EXCEPTIONS as exc:
            raise to_http_exception(exc) from exc

        async def event_source():
            async for event in stream_generation(chat_service, pending, session_factory):
                yield _sse_line(event)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    try:
        new_message = await conversation.regenerate_message(
            user=current_user, message_id=message_id, request_id=request_id
        )
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc

    return MessageExchangeResponse(assistant_message=await conversation.to_message_out(new_message))


@router.get("/{message_id}/revisions", response_model=MessageRevisionsResponse)
async def list_revisions(
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
):
    try:
        revisions = await conversation.list_revisions(user=current_user, message_id=message_id)
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc

    out = [await conversation.to_message_out(m) for m in revisions]
    active = next((m.id for m in revisions if m.is_active), message_id)
    return MessageRevisionsResponse(revisions=out, active_message_id=active)


@router.post("/{message_id}/activate", response_model=MessageOut)
async def activate_revision(
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    conversation: ConversationService = Depends(get_conversation_service),
):
    """Server-persisted undo/redo: make this revision the active one for
    its slot. See ADR 0009 for the documented scope of this operation."""
    try:
        message = await conversation.activate_revision(user=current_user, message_id=message_id)
    except CONVERSATION_EXCEPTIONS as exc:
        raise to_http_exception(exc) from exc
    return await conversation.to_message_out(message)
