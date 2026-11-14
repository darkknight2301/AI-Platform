"""Shared test helpers: fake Redmine, fake LLM, config factory and a temp-dir TestCase."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from rmsum.cache import Cache
from rmsum.config import Config
from rmsum.httpjson import HttpError

FIXTURES = Path(__file__).parent / "fixtures"
REDMINE = "https://redmine.example.com"
OLLAMA = "http://localhost:11434"


def load_sample() -> dict:
    """Fresh copy of the sample Redmine data."""
    return json.loads((FIXTURES / "sample_issues.json").read_text("utf-8"))


class FakeRedmine:
    """Stands in for ``request_json``: serves the sample data and records requested URLs."""

    def __init__(self, data: dict | None = None):
        self.data = data or load_sample()
        self.calls: list[str] = []

    def __call__(self, url: str, **_):
        self.calls.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/issue_statuses.json":
            return {"issue_statuses": self.data["statuses"]}
        if u.path == "/enumerations/issue_priorities.json":
            return {"issue_priorities": self.data["priorities"]}
        if m := re.fullmatch(r"/issues/(\d+)\.json", u.path):
            if m[1] not in self.data["issues"]:
                raise HttpError(404, "Not Found")
            return {"issue": self.data["issues"][m[1]]}
        if u.path == "/issues.json":
            items = list(self.data["issues"].values())
            if "issue_id" in q:
                items = [i for i in items if str(i["id"]) == q["issue_id"]]
            if "subject" in q:
                items = [i for i in items if q["subject"].lstrip("~").lower() in i["subject"].lower()]
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 100))
            return {"issues": items[off:off + lim], "total_count": len(items), "offset": off, "limit": lim}
        raise HttpError(404, "Not Found")


class FakeLLM:
    """Backend returning canned, mostly valid output (plus deliberately invalid claims)."""
    model_id = "fake-model"

    def __init__(self, num_ctx: int = 16384):
        self.num_ctx, self.max_output = num_ctx, 3000
        self.prompts: list[str] = []

    def generate(self, system: str, prompt: str, schema: dict | None = None) -> str:
        self.prompts.append(prompt)
        if schema is None:
            return ("The login bug on Safari is being fixed. A fix exists in !45. "
                    "Ticket #999 is unrelated. Work continues on the blocker.")
        claim = lambda t, b, s: {"text": t, "basis": b, "sources": s}  # noqa: E731
        sections = {
            "background": [claim("Login fails on Safari", "confirmed", ["#100"])],
            "decisions": [claim("Use SameSite=None; Secure", "confirmed", ["[#100 J3]"])],
            "blockers": [claim("Waiting for #102 to be merged", "confirmed", ["#100 J2"]),
                         claim("Depends on #999", "confirmed", ["#100"]),       # unknown ticket -> dropped
                         claim("Vendor release pending", "confirmed", ["#100 J77"])],  # bad source -> unverified
            "requirement_changes": [claim("iOS 15 must also be supported", "assumption", ["#100 J3"])],
            "implementation": [claim("Fix in !45 and commit a1b2c3d", "confirmed", ["#100 J2"])],
        }
        return json.dumps(sections)


class Base(unittest.TestCase):
    """TestCase with a temporary directory and helpers to build config/cache."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def cfg(self, **analysis) -> Config:
        """Config pointing at the fake servers, with the cache inside the temp dir."""
        cfg = Config()
        cfg.redmine.url, cfg.redmine.api_key = REDMINE, "key"
        cfg.git.base_url = "https://gitlab.example.com/group/project"
        cfg.cache.path = str(self.tmp / "cache.db")
        cfg.translate.enabled = False
        for k, v in analysis.items():
            setattr(cfg.analysis, k, v)
        return cfg

    def cache(self) -> Cache:
        return Cache(self.tmp / "cache.db")
