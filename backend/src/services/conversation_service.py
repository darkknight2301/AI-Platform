"""
`ConversationService`: orchestrates chat/message persistence together
with the model layer (`ChatService`, Phase 5). This is the layer that
turns a "send a prompt" HTTP request into: ownership check -> persist
user message -> build model context from the active thread -> call the
model -> persist assistant reply + usage -> bump chat state.

Deliberately separate from `src.services.chat_service.ChatService`
(Phase 5), which stays pure model-orchestration with zero DB
dependency — this service composes that one with the repository layer.

## Failure-ordering rule

Every mutation that depends on a model call succeeding (deactivating
an old revision, inserting the new one) happens strictly AFTER that
call returns successfully. `_call_model` (which can raise
`ChatServiceError`) is always separated from `_persist_assistant_message`
(which cannot fail in the domain sense — it's a pure insert) so a
failed generation never leaves a slot with no active revision, and
never partially commits a deactivation without its replacement. See
ADR 0009.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.session import AsyncSessionLocal
from src.model_layer.schemas import ModelMessage, ModelRequest, ModelResponse
from src.models.ai_model import AIModel
from src.models.chat import Chat
from src.models.enums import ChatStatus, MessageRole
from src.models.message import Message
from src.models.usage import Usage
from src.models.user import User
from src.repositories import chat_repository, message_repository, model_repository
from src.schemas.message import MessageOut, StreamEventOut
from src.services.chat_service import ChatService
from src.services.conversation_errors import (
    ChatAccessDeniedError,
    ChatNotFoundError,
    InvalidMessageOperationError,
    MessageNotFoundError,
    ModelNotConfiguredError,
)
from src.services.errors import ChatServiceError

_DEFAULT_TITLE = "New chat"


class ConversationService:
    def __init__(self, session: AsyncSession, chat_service: ChatService) -> None:
        self._session = session
        self._chat_service = chat_service

    # --- ownership -----------------------------------------------------------

    async def _get_owned_chat(self, user: User, chat_id: uuid.UUID) -> Chat:
        chat = await chat_repository.get_by_id(self._session, chat_id)
        if chat is None:
            raise ChatNotFoundError(str(chat_id))
        if chat.user_id != user.id:
            raise ChatAccessDeniedError(str(chat_id))
        return chat

    async def _get_owned_message(self, user: User, message_id: uuid.UUID) -> tuple[Message, Chat]:
        message = await message_repository.get_by_id(self._session, message_id)
        if message is None:
            raise MessageNotFoundError(str(message_id))
        chat = await self._get_owned_chat(user, message.chat_id)
        return message, chat

    async def _get_model_by_key(self, model_key: str) -> AIModel:
        model = await model_repository.get_by_key(self._session, model_key)
        if model is None or not model.is_enabled:
            raise ModelNotConfiguredError(model_key)
        return model

    # --- chat CRUD -------------------------------------------------------------

    async def create_chat(self, *, user: User, model_key: str, title: str | None) -> Chat:
        model = await self._get_model_by_key(model_key)
        chat = Chat(
            user_id=user.id,
            model_id=model.id,
            title=title or _DEFAULT_TITLE,
            status=ChatStatus.ACTIVE,
        )
        self._session.add(chat)
        await self._session.commit()
        await self._session.refresh(chat)
        return chat

    async def list_chats(
        self, *, user: User, status: ChatStatus | None, limit: int, offset: int
    ) -> list[Chat]:
        return await chat_repository.list_by_user(
            self._session, user.id, status=status, limit=limit, offset=offset
        )

    async def get_chat(self, *, user: User, chat_id: uuid.UUID) -> Chat:
        return await self._get_owned_chat(user, chat_id)

    async def update_chat(
        self,
        *,
        user: User,
        chat_id: uuid.UUID,
        title: str | None,
        status: ChatStatus | None,
        model_key: str | None,
    ) -> Chat:
        chat = await self._get_owned_chat(user, chat_id)
        if title is not None:
            chat.title = title
        if status is not None:
            chat.status = status
        if model_key is not None:
            model = await self._get_model_by_key(model_key)
            chat.model_id = model.id
        chat.revision += 1
        await self._session.commit()
        await self._session.refresh(chat)
        return chat

    async def delete_chat(self, *, user: User, chat_id: uuid.UUID) -> None:
        """Soft delete: sets status=DELETED. Never hard-deletes — history
        (including all message revisions) is preserved."""
        chat = await self._get_owned_chat(user, chat_id)
        chat.status = ChatStatus.DELETED
        chat.revision += 1
        await self._session.commit()

    async def get_history(
        self, *, user: User, chat_id: uuid.UUID, limit: int, offset: int
    ) -> list[Message]:
        await self._get_owned_chat(user, chat_id)
        return await message_repository.list_active_thread(
            self._session, chat_id, limit=limit, offset=offset
        )

    # --- message assembly helpers ------------------------------------------

    async def to_message_out(self, message: Message) -> MessageOut:
        root_id = message_repository.resolve_root_id(message)
        revisions = await message_repository.list_slot_revisions(self._session, root_id)
        model_key = None
        if message.model_id is not None:
            model = await model_repository.get_by_id(self._session, message.model_id)
            model_key = model.model_key if model else None
        return MessageOut(
            id=message.id,
            chat_id=message.chat_id,
            role=message.role,
            content=message.content,
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            total_tokens=message.total_tokens,
            revision=message.revision,
            revision_count=len(revisions),
            root_message_id=message.root_message_id,
            is_active=message.is_active,
            sequence_number=message.sequence_number,
            response_time_ms=message.response_time_ms,
            model_key=model_key,
            created_at=message.created_at,
        )

    @staticmethod
    def _to_model_messages(messages: list[Message]) -> list[ModelMessage]:
        return [
            ModelMessage(role=message_repository.to_model_role(m.role), content=m.content)
            for m in messages
        ]

    async def _call_model(self, model_request: ModelRequest) -> tuple[ModelResponse, int]:
        start = time.monotonic()
        response = await self._chat_service.complete(model_request)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return response, elapsed_ms

    async def _persist_assistant_message(
        self,
        *,
        chat: Chat,
        model: AIModel,
        response: ModelResponse,
        elapsed_ms: int,
        request_id: str | None,
        root_message_id: uuid.UUID | None,
        sequence_number: int,
        revision: int,
    ) -> Message:
        message = Message(
            chat_id=chat.id,
            role=MessageRole.ASSISTANT,
            content=response.content,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.total_tokens,
            request_id=request_id,
            revision=revision,
            root_message_id=root_message_id,
            is_active=True,
            sequence_number=sequence_number,
            response_time_ms=elapsed_ms,
            model_id=model.id,
        )
        self._session.add(message)
        await self._session.flush()

        self._session.add(
            Usage(
                user_id=chat.user_id,
                chat_id=chat.id,
                message_id=message.id,
                model_id=model.id,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.total_tokens,
                timestamp=datetime.now(UTC),
            )
        )
        return message

    # --- send a new prompt ---------------------------------------------------

    async def send_message(
        self, *, user: User, chat_id: uuid.UUID, content: str, request_id: str | None
    ) -> tuple[Message, Message]:
        chat = await self._get_owned_chat(user, chat_id)
        model = await model_repository.get_by_id(self._session, chat.model_id)
        if model is None:
            raise ModelNotConfiguredError(str(chat.model_id))

        user_message = await self._insert_new_slot(
            chat=chat, role=MessageRole.USER, content=content
        )
        await self._session.flush()

        context = await message_repository.list_active_thread(self._session, chat.id, limit=1000)
        model_request = ModelRequest(
            model_key=model.model_key, messages=self._to_model_messages(context)
        )

        try:
            response, elapsed_ms = await self._call_model(model_request)
        except ChatServiceError:
            # Keep the user's prompt even though generation failed.
            await self._session.commit()
            raise

        assistant_message = await self._persist_assistant_message(
            chat=chat,
            model=model,
            response=response,
            elapsed_ms=elapsed_ms,
            request_id=request_id,
            root_message_id=None,
            sequence_number=user_message.sequence_number + 1,
            revision=1,
        )
        chat.revision += 1
        await self._session.commit()
        await self._session.refresh(user_message)
        await self._session.refresh(assistant_message)
        return user_message, assistant_message

    async def _insert_new_slot(self, *, chat: Chat, role: MessageRole, content: str) -> Message:
        sequence_number = await message_repository.get_next_sequence_number(
            self._session, chat.id
        )
        message = Message(
            chat_id=chat.id,
            role=role,
            content=content,
            revision=1,
            root_message_id=None,
            is_active=True,
            sequence_number=sequence_number,
        )
        self._session.add(message)
        return message

    # --- edit a user prompt ---------------------------------------------------

    async def edit_message(
        self, *, user: User, message_id: uuid.UUID, content: str, request_id: str | None
    ) -> tuple[Message, Message | None]:
        target, chat = await self._get_owned_message(user, message_id)
        if target.role != MessageRole.USER:
            raise InvalidMessageOperationError("Only user messages can be edited.")
        if not target.is_active:
            raise InvalidMessageOperationError("Only the active revision can be edited.")

        model = await model_repository.get_by_id(self._session, chat.model_id)
        if model is None:
            raise ModelNotConfiguredError(str(chat.model_id))

        root_id = message_repository.resolve_root_id(target)
        next_revision = await message_repository.get_max_revision_in_slot(self._session, root_id) + 1

        # Editing the prompt text itself has no external call and thus
        # no failure mode — safe to do unconditionally.
        await message_repository.deactivate_slot(self._session, root_id)
        new_user_message = Message(
            chat_id=chat.id,
            role=MessageRole.USER,
            content=content,
            revision=next_revision,
            root_message_id=root_id,
            is_active=True,
            sequence_number=target.sequence_number,
        )
        self._session.add(new_user_message)
        await self._session.flush()

        # If a paired assistant reply already exists at the next slot,
        # regenerate it for the edited prompt.
        following = await message_repository.get_active_at_sequence(
            self._session, chat.id, target.sequence_number + 1
        )
        assistant_message: Message | None = None
        if following is not None and following.role == MessageRole.ASSISTANT:
            context = await message_repository.list_active_thread_before(
                self._session, chat.id, before_sequence_number=following.sequence_number
            )
            model_request = ModelRequest(
                model_key=model.model_key, messages=self._to_model_messages(context)
            )
            following_root = message_repository.resolve_root_id(following)
            following_next_revision = (
                await message_repository.get_max_revision_in_slot(self._session, following_root) + 1
            )

            try:
                response, elapsed_ms = await self._call_model(model_request)
            except ChatServiceError:
                # Keep the edited prompt; the old reply stays active
                # untouched since we haven't deactivated it yet.
                chat.revision += 1
                await self._session.commit()
                raise

            await message_repository.deactivate_slot(self._session, following_root)
            assistant_message = await self._persist_assistant_message(
                chat=chat,
                model=model,
                response=response,
                elapsed_ms=elapsed_ms,
                request_id=request_id,
                root_message_id=following_root,
                sequence_number=following.sequence_number,
                revision=following_next_revision,
            )

        chat.revision += 1
        await self._session.commit()
        await self._session.refresh(new_user_message)
        if assistant_message is not None:
            await self._session.refresh(assistant_message)
        return new_user_message, assistant_message

    # --- regenerate an assistant reply -----------------------------------------

    async def regenerate_message(
        self, *, user: User, message_id: uuid.UUID, request_id: str | None
    ) -> Message:
        target, chat = await self._get_owned_message(user, message_id)
        if target.role != MessageRole.ASSISTANT:
            raise InvalidMessageOperationError("Only assistant messages can be regenerated.")
        if not target.is_active:
            raise InvalidMessageOperationError("Only the active revision can be regenerated.")

        model = await model_repository.get_by_id(self._session, chat.model_id)
        if model is None:
            raise ModelNotConfiguredError(str(chat.model_id))

        root_id = message_repository.resolve_root_id(target)
        next_revision = await message_repository.get_max_revision_in_slot(self._session, root_id) + 1
        context = await message_repository.list_active_thread_before(
            self._session, chat.id, before_sequence_number=target.sequence_number
        )
        model_request = ModelRequest(
            model_key=model.model_key, messages=self._to_model_messages(context)
        )

        response, elapsed_ms = await self._call_model(model_request)
        # Only reached on success — old revision stays active if the
        # call above raised.
        await message_repository.deactivate_slot(self._session, root_id)
        new_message = await self._persist_assistant_message(
            chat=chat,
            model=model,
            response=response,
            elapsed_ms=elapsed_ms,
            request_id=request_id,
            root_message_id=root_id,
            sequence_number=target.sequence_number,
            revision=next_revision,
        )
        chat.revision += 1
        await self._session.commit()
        await self._session.refresh(new_message)
        return new_message

    # --- revisions / undo-redo -------------------------------------------------

    async def list_revisions(self, *, user: User, message_id: uuid.UUID) -> list[Message]:
        target, _ = await self._get_owned_message(user, message_id)
        root_id = message_repository.resolve_root_id(target)
        return await message_repository.list_slot_revisions(self._session, root_id)

    async def activate_revision(self, *, user: User, message_id: uuid.UUID) -> Message:
        """Server-persisted undo/redo: make `message_id` the active revision
        of its slot, deactivating every sibling. Does not regenerate a
        paired reply — see ADR 0009 for this documented limitation."""
        target, chat = await self._get_owned_message(user, message_id)
        root_id = message_repository.resolve_root_id(target)
        await message_repository.deactivate_slot(self._session, root_id)
        target.is_active = True
        chat.revision += 1
        await self._session.commit()
        await self._session.refresh(target)
        return target

    # --- streaming setup -------------------------------------------------------

    async def prepare_send_stream(
        self, *, user: User, chat_id: uuid.UUID, content: str, request_id: str | None
    ) -> PendingGeneration:
        chat = await self._get_owned_chat(user, chat_id)
        model = await model_repository.get_by_id(self._session, chat.model_id)
        if model is None:
            raise ModelNotConfiguredError(str(chat.model_id))

        user_message = await self._insert_new_slot(
            chat=chat, role=MessageRole.USER, content=content
        )
        await self._session.flush()
        context = await message_repository.list_active_thread(self._session, chat.id, limit=1000)
        model_request = ModelRequest(
            model_key=model.model_key, messages=self._to_model_messages(context)
        )
        # Commit now: the prompt must be durable regardless of what
        # happens to the request-scoped session once streaming begins.
        await self._session.commit()

        return PendingGeneration(
            chat_id=chat.id,
            user_id=chat.user_id,
            model_id=model.id,
            deactivate_root_id=None,
            root_message_id=None,
            sequence_number=user_message.sequence_number + 1,
            revision=1,
            request_id=request_id,
            model_request=model_request,
        )

    async def prepare_regenerate_stream(
        self, *, user: User, message_id: uuid.UUID, request_id: str | None
    ) -> PendingGeneration:
        target, chat = await self._get_owned_message(user, message_id)
        if target.role != MessageRole.ASSISTANT:
            raise InvalidMessageOperationError("Only assistant messages can be regenerated.")
        if not target.is_active:
            raise InvalidMessageOperationError("Only the active revision can be regenerated.")

        model = await model_repository.get_by_id(self._session, chat.model_id)
        if model is None:
            raise ModelNotConfiguredError(str(chat.model_id))

        root_id = message_repository.resolve_root_id(target)
        next_revision = await message_repository.get_max_revision_in_slot(self._session, root_id) + 1
        context = await message_repository.list_active_thread_before(
            self._session, chat.id, before_sequence_number=target.sequence_number
        )
        model_request = ModelRequest(
            model_key=model.model_key, messages=self._to_model_messages(context)
        )

        return PendingGeneration(
            chat_id=chat.id,
            user_id=chat.user_id,
            model_id=model.id,
            deactivate_root_id=root_id,
            root_message_id=root_id,
            sequence_number=target.sequence_number,
            revision=next_revision,
            request_id=request_id,
            model_request=model_request,
        )

    async def prepare_edit_stream(
        self, *, user: User, message_id: uuid.UUID, content: str, request_id: str | None
    ) -> PendingGeneration | None:
        """Persist the new prompt revision synchronously (no model call
        needed for that part), then return a `PendingGeneration` for
        streaming the regenerated reply — or None if the edited prompt
        has no paired reply to regenerate."""
        target, chat = await self._get_owned_message(user, message_id)
        if target.role != MessageRole.USER:
            raise InvalidMessageOperationError("Only user messages can be edited.")
        if not target.is_active:
            raise InvalidMessageOperationError("Only the active revision can be edited.")

        model = await model_repository.get_by_id(self._session, chat.model_id)
        if model is None:
            raise ModelNotConfiguredError(str(chat.model_id))

        root_id = message_repository.resolve_root_id(target)
        next_revision = await message_repository.get_max_revision_in_slot(self._session, root_id) + 1

        await message_repository.deactivate_slot(self._session, root_id)
        new_user_message = Message(
            chat_id=chat.id,
            role=MessageRole.USER,
            content=content,
            revision=next_revision,
            root_message_id=root_id,
            is_active=True,
            sequence_number=target.sequence_number,
        )
        self._session.add(new_user_message)
        await self._session.flush()

        following = await message_repository.get_active_at_sequence(
            self._session, chat.id, target.sequence_number + 1
        )
        if following is None or following.role != MessageRole.ASSISTANT:
            chat.revision += 1
            await self._session.commit()
            return None

        context = await message_repository.list_active_thread_before(
            self._session, chat.id, before_sequence_number=following.sequence_number
        )
        model_request = ModelRequest(
            model_key=model.model_key, messages=self._to_model_messages(context)
        )
        following_root = message_repository.resolve_root_id(following)
        following_next_revision = (
            await message_repository.get_max_revision_in_slot(self._session, following_root) + 1
        )

        chat.revision += 1
        # Commit the edited prompt now — durable regardless of what
        # happens to this session once streaming begins.
        await self._session.commit()

        return PendingGeneration(
            chat_id=chat.id,
            user_id=chat.user_id,
            model_id=model.id,
            deactivate_root_id=following_root,
            root_message_id=following_root,
            sequence_number=following.sequence_number,
            revision=following_next_revision,
            request_id=request_id,
            model_request=model_request,
        )


@dataclass
class PendingGeneration:
    """Everything `stream_generation` needs to finish a generation and
    persist it in a fresh DB session, without holding any ORM object
    bound to the (possibly-closed-by-then) request-scoped session."""

    chat_id: uuid.UUID
    user_id: uuid.UUID
    model_id: uuid.UUID
    deactivate_root_id: uuid.UUID | None
    root_message_id: uuid.UUID | None
    sequence_number: int
    revision: int
    request_id: str | None
    model_request: ModelRequest


async def stream_generation(
    chat_service: ChatService,
    pending: PendingGeneration,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
) -> AsyncIterator[StreamEventOut]:
    """Stream a generation and persist it once complete.

    Uses `session_factory` (a fresh session per call, NOT the
    request-scoped session) for the final write, since a
    `StreamingResponse`'s body may be sent well after the route
    handler function itself has returned — see ADR 0009. Defaults to
    the application's real session factory; callers (routers) inject
    it via `src.api.deps.get_session_factory` so tests can override it
    the same way they override `get_db`.
    """
    start = time.monotonic()
    content_parts: list[str] = []
    elapsed_ms = 0
    content = ""
    usage = None
    final_chunk = None

    try:
        async for chunk in chat_service.stream(pending.model_request):
            if not chunk.is_final:
                content_parts.append(chunk.delta)
                yield StreamEventOut(delta=chunk.delta, is_final=False)
                continue

            if chunk.finish_reason == "error":
                # Nothing more will be yielded. Nothing is persisted: the
                # prompt (already committed by the caller) is preserved;
                # the failed reply is not recorded as a message.
                yield StreamEventOut(delta="", is_final=True, finish_reason="error")
                return

            elapsed_ms = int((time.monotonic() - start) * 1000)
            content = "".join(content_parts)
            usage = chunk.usage
            final_chunk = chunk
            break
        else:
            # Generator exhausted without a final chunk — treat like a
            # clean-but-unexpected end rather than crash the response.
            yield StreamEventOut(delta="", is_final=True, finish_reason="stop")
            return
    except ChatServiceError:
        # Once headers are sent for an SSE response, the HTTP status
        # can no longer change — a terminal error event is the only
        # way left to signal failure to the client. Nothing is
        # persisted for a beginning-of-stream failure either.
        yield StreamEventOut(delta="", is_final=True, finish_reason="error")
        return

    async with session_factory() as session:
        if pending.deactivate_root_id is not None:
            await message_repository.deactivate_slot(session, pending.deactivate_root_id)

        message = Message(
            chat_id=pending.chat_id,
            role=MessageRole.ASSISTANT,
            content=content,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            request_id=pending.request_id,
            revision=pending.revision,
            root_message_id=pending.root_message_id,
            is_active=True,
            sequence_number=pending.sequence_number,
            response_time_ms=elapsed_ms,
            model_id=pending.model_id,
        )
        session.add(message)
        await session.flush()

        session.add(
            Usage(
                user_id=pending.user_id,
                chat_id=pending.chat_id,
                message_id=message.id,
                model_id=pending.model_id,
                input_tokens=message.input_tokens,
                output_tokens=message.output_tokens,
                total_tokens=message.total_tokens,
                timestamp=datetime.now(UTC),
            )
        )

        chat = await session.get(Chat, pending.chat_id)
        if chat is not None:
            chat.revision += 1

        await session.commit()
        message_id = message.id

    yield StreamEventOut(
        delta="",
        is_final=True,
        finish_reason=final_chunk.finish_reason if final_chunk else "stop",
        message_id=message_id,
        input_tokens=usage.input_tokens if usage else None,
        output_tokens=usage.output_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
    )
