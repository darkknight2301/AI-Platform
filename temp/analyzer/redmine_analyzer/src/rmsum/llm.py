"""LLM backends. Add another local LLM by implementing :class:`LLMBackend` and registering it."""

import re
from typing import Protocol

from .config import LlmCfg
from .httpjson import Fetch, HttpError, request_json


class LLMError(Exception):
    """The model backend failed or returned unusable output."""


class LLMBackend(Protocol):
    """Interface every model backend implements."""
    model_id: str
    num_ctx: int
    max_output: int

    def generate(self, system: str, prompt: str, schema: dict | None = None) -> str:
        """Return the model's reply; if ``schema`` is given the reply must be JSON matching it."""
        ...


class OllamaBackend:
    """Ollama ``/api/chat`` with deterministic sampling and an explicit context window."""

    def __init__(self, cfg: LlmCfg, fetch: Fetch = request_json):
        self._cfg = cfg
        self._fetch = fetch
        self.model_id = cfg.model
        self.num_ctx = cfg.num_ctx
        self.max_output = cfg.max_output_tokens

    def generate(self, system: str, prompt: str, schema: dict | None = None) -> str:
        """Run one chat completion (temperature 0, fixed seed) and return the text."""
        c = self._cfg
        body = {
            "model": c.model, "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            # Ollama's default context is small and silently truncates, so num_ctx is always set.
            "options": {"temperature": 0, "top_p": 1, "seed": c.seed, "num_ctx": c.num_ctx,
                        "num_predict": c.max_output_tokens},
        }
        if schema:
            body["format"] = schema
        if c.think is not None:
            body["think"] = c.think
        try:
            reply = self._fetch(f"{c.endpoint.rstrip('/')}/api/chat", body=body, timeout=c.timeout)
            text = reply["message"]["content"]
        except (HttpError, KeyError, TypeError) as e:
            raise LLMError(f"Ollama request failed: {e}") from e
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


BACKENDS = {"ollama": OllamaBackend}


def make_backend(cfg: LlmCfg, fetch: Fetch = request_json) -> LLMBackend:
    """Create the backend named by ``cfg.backend``."""
    try:
        return BACKENDS[cfg.backend](cfg, fetch)
    except KeyError:
        raise LLMError(f"unknown llm.backend '{cfg.backend}' (available: {', '.join(BACKENDS)})") from None
