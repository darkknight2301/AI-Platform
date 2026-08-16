"""Service-layer error types shared by chat-related services."""
from __future__ import annotations


class ChatServiceError(Exception):
    """A safe-to-display error raised by `ChatService`.

    `str(exc)` IS the user-facing message — callers (a future chat
    API route) can show it directly. Diagnostic detail never lives on
    this exception; it's logged internally at the point of failure
    (see `src/services/chat_service.py`) and discarded before
    translation into this type.
    """
