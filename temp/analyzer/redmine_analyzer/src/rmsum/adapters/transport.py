"""HTTP transports: plain urllib and a retrying decorator."""

import json
import logging
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from ..errors import TransportError
from ..ports import Transport

log = logging.getLogger(__name__)

MAX_RETRY_DELAY = 60.0  # never sleep longer than this, even if the server asks for it


class UrllibTransport:
    """JSON over HTTP(S) using only the standard library."""

    def __init__(self, verify_ssl: bool = True) -> None:
        self._context: ssl.SSLContext | None = None
        if not verify_ssl:
            self._context = ssl.create_default_context()
            self._context.check_hostname = False
            self._context.verify_mode = ssl.CERT_NONE

    def request_json(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 30.0
    ) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        all_headers = {"Accept": "application/json", **({"Content-Type": "application/json"} if data else {})}
        all_headers.update(headers or {})
        request = urllib.request.Request(url, data=data, headers=all_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=self._context) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(200).decode("utf-8", "replace").strip()
            raise TransportError(f"{exc.reason} {detail}".strip(), exc.code, _retry_after(exc)) from exc
        except (OSError, ValueError) as exc:  # URLError and timeouts are OSError; bad JSON is ValueError
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc

    def close(self) -> None:
        """Nothing to release: every request opens its own connection."""


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    """Seconds from a numeric ``Retry-After`` header (HTTP-date form is ignored)."""
    value = exc.headers.get("Retry-After") if exc.headers else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class RetryingTransport:
    """Retries transient failures with exponential backoff, honouring ``Retry-After``.

    Client errors (4xx except 429) and SSH authentication failures are never retried.
    Backoff has no jitter on purpose: a single client gains nothing from it and runs stay reproducible.
    """

    def __init__(
        self,
        inner: Transport,
        attempts: int,
        base_delay: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._attempts = attempts
        self._base_delay = base_delay
        self._sleep = sleep

    def request_json(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 30.0
    ) -> Any:
        for attempt in range(1, self._attempts + 1):
            try:
                return self._inner.request_json(url, headers=headers, body=body, timeout=timeout)
            except TransportError as exc:
                if not exc.retryable or attempt == self._attempts:
                    raise
                delay = exc.retry_after if exc.retry_after is not None else self._base_delay * 2 ** (attempt - 1)
                delay = min(delay, MAX_RETRY_DELAY)
                log.warning("request failed (%s); retry %d/%d in %.1fs", exc, attempt, self._attempts - 1, delay)
                self._sleep(delay)
        raise AssertionError("unreachable")  # loop always returns or raises

    def close(self) -> None:
        self._inner.close()
