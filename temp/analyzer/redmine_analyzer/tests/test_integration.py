"""End to end: CLI -> Redmine (fake) -> OllamaBackend (fake HTTP) -> HTML/XLSX/JSON files."""

import contextlib
import io
import json
import sys
import types
import unittest

from openpyxl import load_workbook

from helpers import OLLAMA, REDMINE, Base, FakeLLM, FakeRedmine
from rmsum.cli import main
from rmsum.config import LlmCfg
from rmsum.llm import LLMError, OllamaBackend
from rmsum.httpjson import HttpError


class FakeServers:
    """Routes requests to the fake Redmine or a fake Ollama and records Ollama request bodies."""

    def __init__(self):
        self.redmine, self.llm, self.bodies = FakeRedmine(), FakeLLM(), []

    def __call__(self, url, **kw):
        if url.startswith(OLLAMA):
            self.bodies.append(kw["body"])
            msgs = kw["body"]["messages"]
            reply = self.llm.generate(msgs[0]["content"], msgs[1]["content"], kw["body"].get("format"))
            return {"message": {"role": "assistant", "content": "<think>hmm</think>" + reply}}
        return self.redmine(url, **kw)


class IntegrationTests(Base):
    def config_file(self) -> str:
        p = self.tmp / "config.yml"
        p.write_text(f"""
redmine: {{url: "{REDMINE}", api_key: testkey}}
git: {{base_url: "https://gitlab.example.com/group/project"}}
llm: {{endpoint: "{OLLAMA}", model: qwen3:27b, seed: 7, num_ctx: 8192}}
translate: {{enabled: true, module: fake_api_cli}}
cache: {{path: "{self.tmp}/cache.db"}}
output: {{dir: "{self.tmp}/reports"}}
logging: {{file: ""}}
""", "utf-8")
        return str(p)

    def run_cli(self, servers, *argv) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(["-c", self.config_file(), *argv], fetch=servers)
        return code, buf.getvalue()

    def setUp(self):
        super().setUp()
        self.translated = []
        mod = types.ModuleType("fake_api_cli")
        mod.translate = lambda s: self.translated.append(s) or f"EN:{s}"
        sys.modules["fake_api_cli"] = mod
        self.addCleanup(sys.modules.pop, "fake_api_cli")

    def test_search_then_analyze_all_formats(self):
        servers = FakeServers()
        code, out = self.run_cli(servers, "search", "cookie", "--status", "all")
        self.assertEqual(code, 0)
        self.assertIn("#102", out)
        self.assertIn("Upgrade cookie library", out)

        code, out = self.run_cli(servers, "analyze", "100", "-f", "html", "xlsx", "json")
        self.assertEqual(code, 0, out)
        reports = self.tmp / "reports"
        self.assertIn("login bug on Safari", out)
        self.assertGreater((reports / "redmine_100.html").stat().st_size, 2000)
        self.assertIn("Safari", load_workbook(reports / "redmine_100.xlsx")["Short Summary"]["B3"].value)  # subject row
        data = json.loads((reports / "redmine_100.json").read_text("utf-8"))
        self.assertEqual(data["root_id"], 100)
        self.assertEqual(len(data["tickets"]), 6)
        self.assertTrue(self.translated, "Japanese text must go through api.translate")

        # deterministic request shape sent to Ollama
        body = servers.bodies[0]
        self.assertEqual({k: body["options"][k] for k in ("temperature", "top_p", "seed", "num_ctx")},
                         {"temperature": 0, "top_p": 1, "seed": 7, "num_ctx": 8192})
        self.assertIn("properties", body["format"])
        self.assertNotIn("think", body)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])

        # second run: cache (no LLM calls); --regenerate: calls again
        before = len(servers.bodies)
        self.run_cli(servers, "analyze", "100", "-f", "json")
        self.assertEqual(len(servers.bodies), before)
        self.run_cli(servers, "analyze", "100", "-f", "json", "--regenerate")
        self.assertGreater(len(servers.bodies), before)

    def test_one_failing_ticket_does_not_stop_others(self):
        code, out = self.run_cli(FakeServers(), "analyze", "4040", "105", "-f", "json", "--max-depth", "1")
        self.assertEqual(code, 1)
        self.assertTrue((self.tmp / "reports" / "redmine_105.json").exists())

    def test_config_error_is_reported(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["-c", str(self.tmp / "nope.yml"), "search", "x"]), 1)
        self.assertIn("config file not found", err.getvalue())

    def test_ollama_backend_errors(self):
        def down(url, **kw):
            raise HttpError(0, "connection refused")
        with self.assertRaisesRegex(LLMError, "connection refused"):
            OllamaBackend(LlmCfg(), down).generate("s", "p")
        with self.assertRaises(LLMError):
            OllamaBackend(LlmCfg(), lambda url, **kw: {"unexpected": 1}).generate("s", "p")

    def test_think_option_sent_only_when_configured(self):
        seen = []
        OllamaBackend(LlmCfg(think=False), lambda url, **kw: seen.append(kw["body"]) or {"message": {"content": "ok"}}).generate("s", "p")
        self.assertIs(seen[0]["think"], False)


if __name__ == "__main__":
    unittest.main()
