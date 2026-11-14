"""Shared test doubles: fake Redmine transport, fake model, fake translator, config and temp-dir TestCase."""

import json
import re
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from rmsum.config import Config, GitCfg, RedmineCfg
from rmsum.errors import TransportError
from rmsum.ports import Completion

FIXTURES = Path(__file__).parent / "fixtures"
REDMINE = "https://redmine.example.com"
OLLAMA = "http://localhost:11434"
GIT = "https://gitlab.example.com/group/project"


def load_sample() -> dict:
    """Fresh copy of the sample Redmine data."""
    return json.loads((FIXTURES / "sample_issues.json").read_text("utf-8"))


class FakeRedmine:
    """Transport that serves the sample data and records the URLs requested."""

    def __init__(self, data: dict | None = None) -> None:
        self.data = data or load_sample()
        self.calls: list[str] = []

    def close(self) -> None:
        pass

    def request_json(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 30.0
    ):
        self.calls.append(url)
        parsed = urlparse(url)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if parsed.path == "/issue_statuses.json":
            return {"issue_statuses": self.data["statuses"]}
        if parsed.path == "/enumerations/issue_priorities.json":
            return {"issue_priorities": self.data["priorities"]}
        if match := re.fullmatch(r"/issues/(\d+)\.json", parsed.path):
            if match[1] not in self.data["issues"]:
                raise TransportError("Not Found", 404)
            return {"issue": self.data["issues"][match[1]]}
        if parsed.path == "/issues.json":
            items = list(self.data["issues"].values())
            if "issue_id" in query:
                items = [i for i in items if str(i["id"]) == query["issue_id"]]
            if "subject" in query:
                items = [i for i in items if query["subject"].lstrip("~").lower() in i["subject"].lower()]
            offset, limit = int(query.get("offset", 0)), int(query.get("limit", 100))
            return {"issues": items[offset : offset + limit], "total_count": len(items)}
        raise TransportError("Not Found", 404)


class FakeModel:
    """Language model returning canned output, including deliberately invalid claims to exercise validation."""

    model_id = "fake-model"

    def __init__(self, context_tokens: int = 16384, max_output_tokens: int = 3000) -> None:
        self.context_tokens = context_tokens
        self.max_output_tokens = max_output_tokens
        self.prompts: list[str] = []

    def check_ready(self) -> None:
        pass

    def reply(self, prompt: str, schema: Mapping[str, Any] | None) -> Completion:
        """Override in subclasses to script behaviour."""
        if schema is None:
            return Completion(
                "The login bug on Safari is being fixed. A fix exists in !45. "
                "Ticket #999 is unrelated. Work continues on the blocker.",
                100,
                20,
            )

        def claim(text: str, basis: str, sources: list[str]) -> dict:
            return {"text": text, "basis": basis, "sources": sources}

        sections = {
            "background": [claim("Login fails on Safari", "confirmed", ["#100"])],
            "decisions": [claim("Use SameSite=None; Secure", "confirmed", ["[#100 J3]"])],
            "blockers": [
                claim("Waiting for #102 to be merged", "confirmed", ["#100 J2"]),
                claim("Depends on #999", "confirmed", ["#100"]),  # unknown ticket -> rejected
                claim("Vendor release pending", "confirmed", ["#100 J77"]),  # bad source -> unverified
            ],
            "requirement_changes": [claim("iOS 15 must also be supported", "assumption", ["#100 J3"])],
            "implementation": [claim("Fix in !45 and commit a1b2c3d", "confirmed", ["#100 J2"])],
        }
        return Completion(json.dumps(sections), 500, 200)

    def generate(self, system: str, prompt: str, schema: Mapping[str, Any] | None = None) -> Completion:
        self.prompts.append(prompt)
        return self.reply(prompt, schema)


class FakeTranslator:
    """Translator that prefixes texts; records what it was asked to translate."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []

    def translate(self, texts: Mapping[str, str]) -> dict[str, str]:
        self.requests.append(dict(texts))
        return {key: f"EN({text[:30]})" for key, text in texts.items()}


class Base(unittest.TestCase):
    """TestCase with a temporary directory and a config pointing at the fakes."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)  # TestCase.enterContext needs Python 3.11
        self.tmp = Path(directory.name)

    def config(self, **analysis: Any) -> Config:
        cfg = Config(redmine=RedmineCfg(url=REDMINE, api_key="key"), git=GitCfg(base_url=GIT))
        return replace(cfg, analysis=replace(cfg.analysis, **analysis))


def ollama_reply(model: "FakeModel", path: str, body: Any = None) -> dict:
    """What a real Ollama would answer for ``/api/tags`` and ``/api/chat``, backed by a FakeModel."""
    if path == "/api/tags":
        return {"models": [{"name": "qwen3:27b"}]}
    completion = model.generate(body["messages"][0]["content"], body["messages"][1]["content"], body.get("format"))
    return {
        "message": {"role": "assistant", "content": completion.text},
        "prompt_eval_count": completion.prompt_tokens,
        "eval_count": completion.output_tokens,
        "done_reason": "length" if completion.truncated else "stop",
    }


class FakeOllamaTransport:
    """In-process stand-in for the HTTP path to Ollama."""

    def __init__(self, model: "FakeModel") -> None:
        self.model = model
        self.chat_calls = 0

    def request_json(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 30.0
    ):
        path = urlparse(url).path
        self.chat_calls += path == "/api/chat"
        return ollama_reply(self.model, path, body)

    def close(self) -> None:
        pass


def serve_fake_ollama(model: "FakeModel") -> HTTPServer:
    """Start a real local HTTP server that behaves like Ollama (used behind the fake SSH channel)."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._send(ollama_reply(model, self.path))

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send(ollama_reply(model, self.path, body))

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class FakeSshTransport:
    """Pretends to be a paramiko transport: channels are plain sockets to a local HTTP server."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.targets: list[tuple[str, int]] = []

    def is_active(self) -> bool:
        return True

    def open_channel(
        self, kind: str, destination: tuple[str, int], source: tuple[str, int], timeout: float | None = None
    ):
        assert kind == "direct-tcpip"
        self.targets.append(destination)
        return socket.create_connection(("127.0.0.1", self.port))


class FakeSshClient:
    def __init__(self, transport: FakeSshTransport) -> None:
        self.transport = transport
        self.closed = False

    def get_transport(self) -> FakeSshTransport:
        return self.transport

    def close(self) -> None:
        self.closed = True
