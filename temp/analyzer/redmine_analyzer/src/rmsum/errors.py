"""Exception hierarchy.

Every failure the tool anticipates derives from :class:`RmsumError`, so the CLI can report it in one
line and continue with the next ticket instead of showing a traceback.
"""

from typing import Optional


class RmsumError(Exception):
    """Base class for expected, user-reportable failures."""


class ConfigError(RmsumError):
    """Configuration file missing, malformed or invalid."""


class TransportError(RmsumError):
    """HTTP or network failure. ``status`` is 0 for failures below HTTP (DNS, timeout, SSH)."""

    def __init__(self, message: str, status: int = 0, retry_after: Optional[float] = None) -> None:
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """True for transient failures: network errors, rate limiting (429) and server errors (5xx)."""
        return self.status in (0, 429) or self.status >= 500


class SshAuthError(TransportError):
    """SSH authentication was rejected. Never retried automatically; the user must re-enter credentials."""

    @property
    def retryable(self) -> bool:
        return False


class SourceError(RmsumError):
    """The ticket source (Redmine) failed or returned data we cannot interpret."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class LLMError(RmsumError):
    """The language model backend failed."""


class ContextOverflowError(LLMError):
    """The prompt filled the model's context window, so the model may have silently dropped input."""


class InvalidModelOutputError(LLMError):
    """The model kept returning output that is not the requested JSON."""
