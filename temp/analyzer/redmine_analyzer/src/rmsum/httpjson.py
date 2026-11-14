"""Minimal JSON-over-HTTP helper built on urllib (no third-party HTTP client)."""

import json
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

type Fetch = Callable[..., Any]
"""Signature of :func:`request_json`; clients accept any compatible callable (used by tests)."""


class HttpError(Exception):
    """HTTP or network failure. ``status`` is 0 for network-level errors."""

    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


def request_json(url: str, *, headers: dict[str, str] | None = None, body: Any = None,
                 timeout: float = 30.0, verify_ssl: bool = True) -> Any:
    """GET (or POST when ``body`` is given) and return the decoded JSON response.

    Raises:
        HttpError: on HTTP error status, network failure or invalid JSON.
    """
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Accept": "application/json", **({"Content-Type": "application/json"} if data else {}),
            **(headers or {})}
    ctx = None
    if not verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdrs),
                                    timeout=timeout, context=ctx) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, str(e.reason)) from e
    except (OSError, json.JSONDecodeError) as e:  # URLError and timeouts are OSError
        raise HttpError(0, f"{type(e).__name__}: {e}") from e
