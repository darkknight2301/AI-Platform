"""End to end through ``rmsum.cli.main``: fake Redmine, fake Ollama (in-process or behind a fake SSH channel)."""

import contextlib
import unittest
import io
import json
import sys
import types

from openpyxl import load_workbook

from helpers import (
    REDMINE,
    Base,
    FakeModel,
    FakeOllamaTransport,
    FakeRedmine,
    FakeSshClient,
    FakeSshTransport,
    serve_fake_ollama,
)
from rmsum.adapters.ssh import CredentialPrompter
from rmsum.cli import main, read_ticket_ids
from rmsum.errors import ConfigError

PASSWORD = "s3cret-pw-do-not-leak"


class CliBase(Base):
    def setUp(self):
        super().setUp()
        self.out = self.tmp / "reports"
        self.log_file = self.tmp / "rmsum.log"
        self.model = FakeModel()
        self.ollama = FakeOllamaTransport(self.model)
        self.redmine = FakeRedmine()
        self.translated: list[str] = []
        module = types.ModuleType("fake_api_cli")
        module.translate = lambda text: self.translated.append(text) or text.replace("@@SEG", "@@SEG")
        sys.modules["fake_api_cli"] = module
        self.addCleanup(sys.modules.pop, "fake_api_cli")

    def config_file(self, extra: str = "") -> str:
        path = self.tmp / "config.yml"
        path.write_text(
            f"""
redmine: {{url: "{REDMINE}", api_key: testkey}}
git: {{base_url: "https://gitlab.example.com/group/project"}}
llm: {{model: qwen3:27b, seed: 7, num_ctx: 8192}}
translate: {{enabled: true, module: fake_api_cli}}
output: {{dir: "{self.out}"}}
logging: {{file: "{self.log_file}"}}
{extra}
""",
            "utf-8",
        )
        return str(path)

    def run_cli(self, *argv, extra_config: str = "", **injected) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        injected.setdefault("redmine_transport", self.redmine)
        injected.setdefault("llm_transport", self.ollama)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["-c", self.config_file(extra_config), *argv], **injected)
        return code, out.getvalue(), err.getvalue()

    def audit_rows(self) -> list[list]:
        sheet = load_workbook(self.out / "audit_log.xlsx")["Audit Log"]
        return [[c.value for c in row] for row in sheet.iter_rows(min_row=2)]


class CliTests(CliBase):
    def test_search(self):
        code, out, _ = self.run_cli("search", "cookie", "--status", "all")
        self.assertEqual(code, 0)
        self.assertIn("#102", out)
        self.assertIn("Upgrade cookie library", out)

    def test_analyze_writes_reports_audit_log_and_translates_in_batches(self):
        code, out, _ = self.run_cli("analyze", "100", "-f", "html", "xlsx")
        self.assertEqual(code, 0, out)
        self.assertIn("login bug on Safari", out)
        for name in ("redmine_100.html", "redmine_100.xlsx", "redmine_100.json", "audit_log.xlsx"):
            self.assertGreater((self.out / name).stat().st_size, 500, name)
        self.assertEqual(len(self.translated), 1, "all Japanese texts of all tickets in one api.translate call")
        self.assertEqual(json.loads((self.out / "redmine_100.json").read_text("utf-8"))["root_id"], 100)
        (row,) = self.audit_rows()
        ticket, outcome, analysed, mode, model, llm_calls = row[2], row[4], row[5], row[7], row[8], row[9]
        expected = ("#100", "ANALYSED", 6, "direct", "qwen3:27b", 2)
        self.assertEqual((ticket, outcome, analysed, mode, model, llm_calls), expected)
        self.assertIn("redmine_100.html", row[19])

    def test_unchanged_tickets_are_reused_and_regenerate_forces_a_new_run(self):
        self.run_cli("analyze", "100")
        first = self.ollama.chat_calls
        code, out, _ = self.run_cli("analyze", "100")
        self.assertEqual((code, self.ollama.chat_calls), (0, first))
        self.assertIn("reused", out)
        self.run_cli("analyze", "100", "--regenerate")
        self.assertGreater(self.ollama.chat_calls, first)
        self.assertEqual([r[4] for r in self.audit_rows()], ["ANALYSED", "REUSED", "ANALYSED"])

    def test_batch_from_file_continues_after_a_failure(self):
        ids = self.tmp / "ids.txt"
        ids.write_text("# tickets for today\n105\n\n4040  // does not exist\n#101\n105\n")
        code, out, _ = self.run_cli("analyze", "--from-file", str(ids), "-f", "json", "--max-depth", "1")
        self.assertEqual(code, 1)
        self.assertIn("2 of 3 ticket(s) succeeded, 1 failed", out)
        self.assertTrue((self.out / "redmine_105.json").exists())
        self.assertTrue((self.out / "redmine_101.json").exists())
        failed = [r for r in self.audit_rows() if r[4] == "FAILED"]
        self.assertEqual((len(failed), failed[0][2]), (1, "#4040"))
        self.assertIn("404", failed[0][20])

    def test_unexpected_error_in_one_ticket_does_not_abort_the_batch(self):
        class Crashing(FakeModel):
            def reply(self, prompt, schema):
                if "TICKET #105" in prompt:
                    raise ZeroDivisionError("bug")
                return super().reply(prompt, schema)

        self.ollama.model = Crashing()
        code, _, _ = self.run_cli("analyze", "105", "101", "-f", "json", "--max-depth", "0")
        self.assertEqual(code, 1)
        self.assertEqual([r[4] for r in self.audit_rows()], ["FAILED", "ANALYSED"])

    def test_unusable_model_server_fails_fast_before_any_ticket(self):
        class OtherModelsOnly:
            def request_json(self, url, **kwargs):
                return {"models": [{"name": "other:1b"}]}

            def close(self):
                pass

        class Unreachable(OtherModelsOnly):
            def request_json(self, url, **kwargs):
                from rmsum.errors import TransportError

                raise TransportError("connection refused")

        for transport, message in ((OtherModelsOnly(), "not installed"), (Unreachable(), "cannot reach Ollama")):
            with self.subTest(message):
                code, _, err = self.run_cli("analyze", "100", llm_transport=transport)
                self.assertEqual(code, 1)
                self.assertIn(message, err)
                self.assertFalse((self.out / "audit_log.xlsx").exists(), "no ticket was started")

    def test_interrupt_exits_with_130(self):
        class Interrupted(FakeModel):
            def reply(self, prompt, schema):
                raise KeyboardInterrupt

        self.ollama.model = Interrupted()
        self.assertEqual(self.run_cli("analyze", "100")[0], 130)

    def test_configuration_errors_are_reported_without_a_traceback(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main(["-c", str(self.tmp / "nope.yml"), "search", "x"]), 1)
        self.assertIn("config file not found", err.getvalue())
        code, _, err_text = self.run_cli("analyze")
        self.assertEqual(code, 1)
        self.assertIn("no ticket ids", err_text)

    def test_read_ticket_ids_rejects_garbage(self):
        path = self.tmp / "bad.txt"
        path.write_text("12\nhello\n")
        with self.assertRaisesRegex(ConfigError, "bad.txt:2"):
            read_ticket_ids(path)


class SshRuntimePromptTests(CliBase):
    SSH = "ssh: {enabled: true, host: 10.0.0.5, username: llmuser, remote_port: 11434}"

    def setUp(self):
        super().setUp()
        self.server = serve_fake_ollama(self.model)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.channels = FakeSshTransport(self.server.server_address[1])
        self.connections: list = []

    def connector(self, cfg, creds):
        self.connections.append(creds)
        return FakeSshClient(self.channels)

    def prompter(self, answers: list[str]):
        asked: list[str] = []
        prompter = CredentialPrompter(
            ask=lambda label: asked.append(label) or answers.pop(0),
            ask_secret=lambda label: asked.append(label) or PASSWORD,
            interactive=lambda: True,
        )
        return prompter, asked

    def test_credentials_are_asked_once_per_run_and_never_leak(self):
        prompter, asked = self.prompter(["192.168.1.50", "bob"])
        code, out, err = self.run_cli(
            "analyze", "100", "101", "-f", "html", "json",
            extra_config=self.SSH, llm_transport=None, prompter=prompter, ssh_connector=self.connector,
        )
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(asked), 3)  # host, user, password: once, not per ticket
        self.assertIn("[10.0.0.5]", asked[0])  # YAML value offered as default
        used = [(c.host, c.username, c.password) for c in self.connections]
        self.assertEqual(used, [("192.168.1.50", "bob", PASSWORD)])
        self.assertEqual(self.channels.targets[0], ("127.0.0.1", 11434))
        self.assertTrue(self.model.prompts)

        # the password must not appear anywhere the tool writes or prints
        artefacts = [out, err, self.log_file.read_text("utf-8")]
        artefacts += [p.read_text("utf-8") for pattern in ("*.html", "*.json") for p in self.out.glob(pattern)]
        for text in artefacts:
            self.assertNotIn(PASSWORD, text)
        for row in self.audit_rows():
            self.assertNotIn(PASSWORD, " ".join(str(c) for c in row))
            self.assertEqual(row[18], "ssh:192.168.1.50")  # audit records where the model ran, not how we logged in

    def test_the_password_is_never_sent_to_ollama(self):
        prompter, _ = self.prompter(["h", "u"])
        self.run_cli(
            "analyze", "105", "-f", "json", "--max-depth", "0",
            extra_config=self.SSH, llm_transport=None, prompter=prompter, ssh_connector=self.connector,
        )
        self.assertFalse(any(PASSWORD in prompt for prompt in self.model.prompts))

    def test_ssh_flag_overrides_the_config(self):
        prompter, asked = self.prompter(["h", "u"])
        code, *_ = self.run_cli(
            "analyze", "105", "-f", "json", "--max-depth", "0", "--no-ssh",
            extra_config=self.SSH, llm_transport=None, prompter=prompter, ssh_connector=self.connector,
        )
        # --no-ssh means direct HTTP to llm.endpoint, which is not running here: it must fail, and must not prompt
        self.assertEqual((code, asked), (1, []))

    def test_without_a_terminal_the_environment_is_used_or_the_run_fails_clearly(self):
        no_tty = CredentialPrompter(environ={}, interactive=lambda: False)
        code, _, err = self.run_cli(
            "analyze", "100", extra_config="ssh: {enabled: true}", llm_transport=None, prompter=no_tty
        )
        self.assertEqual(code, 1)
        self.assertIn("no terminal", err)
        environ = {"RMSUM_SSH_HOST": "h", "RMSUM_SSH_USER": "u", "RMSUM_SSH_PASSWORD": PASSWORD}
        env = CredentialPrompter(environ=environ, interactive=lambda: False)
        code, *_ = self.run_cli(
            "analyze", "105", "-f", "json", "--max-depth", "0",
            extra_config=self.SSH, llm_transport=None, prompter=env, ssh_connector=self.connector,
        )
        self.assertEqual(code, 0)

    def test_wrong_password_reports_a_clean_error_after_three_tries(self):
        from rmsum.errors import SshAuthError

        def reject(cfg, creds):
            raise SshAuthError("SSH authentication failed for u@h")

        prompter, asked = self.prompter(["h", "u"])
        code, _, err = self.run_cli(
            "analyze", "100", extra_config=self.SSH, llm_transport=None, prompter=prompter, ssh_connector=reject
        )
        self.assertEqual(code, 1)
        self.assertIn("authentication failed", err)
        self.assertEqual(sum("password" in a for a in asked), 3)


if __name__ == "__main__":
    unittest.main()
