"""Maps conversation-service exceptions to HTTP responses.

Kept in one place so every chat/message route handles failures
identically, rather than each endpoint re-deciding status codes.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from src.services.conversation_errors import (
    ChatAccessDeniedError,
    ChatLimitExceededError,
    ChatNotFoundError,
    InvalidMessageOperationError,
    MessageNotFoundError,
    ModelNotConfiguredError,
    TokenQuotaExceededError,
)
from src.services.errors import ChatServiceError

CONVERSATION_EXCEPTIONS = (
    ChatNotFoundError,
    ChatAccessDeniedError,
    MessageNotFoundError,
    InvalidMessageOperationError,
    ModelNotConfiguredError,
    ChatLimitExceededError,
    TokenQuotaExceededError,
    ChatServiceError,
)


def to_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, ChatNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found.")
    if isinstance(exc, ChatAccessDeniedError):
        return HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have permission to access this chat."
        )
    if isinstance(exc, MessageNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    if isinstance(exc, InvalidMessageOperationError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, ModelNotConfiguredError):
        return HTTPException(
            status.HTTP_400_BAD_REQUEST, "The requested model is not configured or not enabled."
        )
    if isinstance(exc, ChatLimitExceededError):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
    if isinstance(exc, TokenQuotaExceededError):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))
    if isinstance(exc, ChatServiceError):
        # Already a safe, generic message (see src/services/errors.py) —
        # 502 because the failure is in the upstream model backend, not
        # this API itself.
        return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    raise exc  # not one of ours — let it propagate
