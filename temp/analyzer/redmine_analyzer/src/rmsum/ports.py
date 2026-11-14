"""Interfaces (ports) the application depends on. Adapters implement them; tests fake them."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .domain.models import Ticket


class Transport(Protocol):
    """JSON over HTTP. Implementations: plain urllib, SSH-tunnelled, and a retrying decorator."""

    def request_json(
        self, url: str, *, headers: Optional[Mapping[str, str]] = None, body: Any = None, timeout: float = 30.0
    ) -> Any:
        """GET, or POST when ``body`` is given. Raises TransportError on any failure."""
        ...

    def close(self) -> None:
        """Release connections. Safe to call more than once."""
        ...


class IssueSource(Protocol):
    """Read access to a ticket system."""

    def get_issue(self, issue_id: int) -> Ticket:
        """Fetch one ticket with conversation, relations, children and attachment names."""
        ...

    def search(self, query: str, project: Optional[str], status: str, limit: int) -> list[Ticket]:
        """Find tickets by numeric id or subject text (without conversations)."""
        ...


@dataclass(frozen=True)
class Completion:
    """One model reply plus what the backend reported about it."""

    text: str
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    truncated: bool = False  # the reply hit the output-token limit and is incomplete


class LanguageModel(Protocol):
    """A text-generation backend."""

    model_id: str
    context_tokens: int
    max_output_tokens: int

    def check_ready(self) -> None:
        """Fail fast if the backend is unreachable or the configured model is unavailable. Raises LLMError."""
        ...

    def generate(self, system: str, prompt: str, schema: Optional[Mapping[str, Any]] = None) -> Completion:
        """Generate a reply; with ``schema`` the reply must be a JSON object matching it.

        Raises:
            ContextOverflowError: the prompt filled the context window.
            LLMError: any other backend failure.
        """
        ...


class TextTranslator(Protocol):
    """Japanese to English translation of many texts at once."""

    def translate(self, texts: Mapping[str, str]) -> dict[str, str]:
        """Translate ``{key: text}``. Keys that could not be translated are simply absent from the result."""
        ...
