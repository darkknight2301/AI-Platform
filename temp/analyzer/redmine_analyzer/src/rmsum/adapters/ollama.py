"""Ollama backend implementing the ``LanguageModel`` port."""

import logging
import re
from collections.abc import Mapping
from typing import Any, Optional

from ..config import LlmCfg
from ..errors import ContextOverflowError, LLMError, TransportError
from ..ports import Completion, LanguageModel, Transport

log = logging.getLogger(__name__)

# Ollama silently truncates over-long prompts to the context size, so a prompt that "just fits" is suspicious.
OVERFLOW_MARGIN_TOKENS = 16


class OllamaModel:
    """Ollama ``/api/chat`` with deterministic sampling and an explicit context window."""

    def __init__(self, cfg: LlmCfg, transport: Transport, endpoint: Optional[str] = None) -> None:
        self._cfg = cfg
        self._transport = transport
        self._endpoint = (endpoint or cfg.endpoint).rstrip("/")
        self.model_id = cfg.model
        self.context_tokens = cfg.num_ctx
        self.max_output_tokens = cfg.max_output_tokens

    def check_ready(self) -> None:
        """Fail fast if the server is unreachable or the configured model has not been pulled.

        Raises:
            LLMError: server unreachable, or the model is not installed there.
        """
        try:
            reply = self._transport.request_json(f"{self._endpoint}/api/tags", timeout=30.0)
        except TransportError as exc:
            raise LLMError(f"cannot reach Ollama at {self._endpoint}: {exc}") from exc
        models = reply.get("models") if isinstance(reply, dict) else None
        if not isinstance(models, list):
            log.warning("unexpected /api/tags response; skipping model availability check")
            return
        names = {m.get("name", "") for m in models if isinstance(m, dict)}
        wanted = self._cfg.model
        if wanted not in names and (":" in wanted or f"{wanted}:latest" not in names):
            raise LLMError(f"model '{wanted}' is not installed on the Ollama server (installed: {sorted(names)})")

    def generate(self, system: str, prompt: str, schema: Optional[Mapping[str, Any]] = None) -> Completion:
        """Run one chat completion (temperature 0, fixed seed) and return text plus usage."""
        cfg = self._cfg
        body: dict[str, Any] = {
            "model": cfg.model,
            "stream": False,
            "keep_alive": cfg.keep_alive,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            # Ollama's default context is small and truncates silently, so num_ctx is always set explicitly.
            "options": {
                "temperature": 0,
                "top_p": 1,
                "seed": cfg.seed,
                "num_ctx": cfg.num_ctx,
                "num_predict": cfg.max_output_tokens,
            },
        }
        if schema:
            body["format"] = schema
        if cfg.think is not None:
            body["think"] = cfg.think
        try:
            reply = self._transport.request_json(f"{self._endpoint}/api/chat", body=body, timeout=cfg.timeout)
            text = reply["message"]["content"]
        except TransportError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        except (KeyError, TypeError) as exc:
            raise LLMError("unexpected response from Ollama (no message content)") from exc

        prompt_tokens, output_tokens = reply.get("prompt_eval_count"), reply.get("eval_count")
        if isinstance(prompt_tokens, int) and prompt_tokens >= cfg.num_ctx - OVERFLOW_MARGIN_TOKENS:
            raise ContextOverflowError(f"prompt used {prompt_tokens} of {cfg.num_ctx} context tokens")
        return Completion(
            text=re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip(),
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            truncated=reply.get("done_reason") == "length",
        )


BACKENDS = {"ollama": OllamaModel}


def create_model(cfg: LlmCfg, transport: Transport, endpoint: Optional[str] = None) -> LanguageModel:
    """Create the backend named by ``cfg.backend``. Register new backends in ``BACKENDS``."""
    try:
        return BACKENDS[cfg.backend](cfg, transport, endpoint)
    except KeyError:
        raise LLMError(f"unknown llm.backend '{cfg.backend}' (available: {', '.join(BACKENDS)})") from None
