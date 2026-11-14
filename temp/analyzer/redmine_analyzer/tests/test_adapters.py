import json
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from helpers import REDMINE, Base, FakeRedmine, FakeSshClient, FakeSshTransport
from rmsum.adapters.ollama import OllamaModel, create_model
from rmsum.adapters.redmine import RedmineClient
from rmsum.adapters.ssh import CredentialPrompter, SshCredentials, SshTransport, open_ssh_transport
from rmsum.adapters.transport import RetryingTransport
from rmsum.adapters.translation import BatchTranslator, load_translator
from rmsum.config import LlmCfg, RedmineCfg, SshCfg, TranslateCfg
from rmsum.errors import ConfigError, ContextOverflowError, LLMError, SourceError, SshAuthError, TransportError


class ScriptedTransport:
    """Transport that raises/returns the scripted outcomes in order."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def request_json(self, url, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self):
        self.closed = True


class RetryTests(unittest.TestCase):
    def retrying(self, *outcomes, attempts=3):
        sleeps = []
        inner = ScriptedTransport(*outcomes)
        return RetryingTransport(inner, attempts, base_delay=1.0, sleep=sleeps.append), inner, sleeps

    def test_retries_transient_failures_with_backoff(self):
        transport, inner, sleeps = self.retrying(TransportError("down"), TransportError("busy", 503), {"ok": 1})
        self.assertEqual(transport.request_json("u"), {"ok": 1})
        self.assertEqual((inner.calls, sleeps), (3, [1.0, 2.0]))

    def test_honours_retry_after_and_caps_it(self):
        transport, _, sleeps = self.retrying(TransportError("slow", 429, 5.0), TransportError("slow", 429, 9999), {})
        transport.request_json("u")
        self.assertEqual(sleeps, [5.0, 60.0])

    def test_does_not_retry_client_errors_or_auth_failures(self):
        for error in (TransportError("nope", 404), SshAuthError("bad password")):
            transport, inner, sleeps = self.retrying(error, {})
            with self.assertRaises(TransportError):
                transport.request_json("u")
            self.assertEqual((inner.calls, sleeps), (1, []))

    def test_gives_up_after_the_last_attempt(self):
        transport, inner, _ = self.retrying(*[TransportError("x", 500)] * 3)
        with self.assertRaises(TransportError):
            transport.request_json("u")
        self.assertEqual(inner.calls, 3)


class RedmineTests(unittest.TestCase):
    def client(self, fake=None, page_size=100):
        return RedmineClient(RedmineCfg(url=REDMINE, api_key="k", page_size=page_size), fake or FakeRedmine())

    def test_parses_conversation_relations_and_names(self):
        ticket = self.client().get_issue(100)
        self.assertEqual([j.id for j in ticket.journals], [1, 2, 3])  # chronological, not API order
        self.assertEqual(ticket.journals[0].changes, ("status_id: New → In Progress",))
        self.assertEqual(ticket.journals[2].changes, ("Component: web → auth",))
        self.assertEqual(dict(ticket.custom_fields), {"Customer": "ACME", "Component": "auth"})
        self.assertEqual((ticket.parent_id, ticket.children, ticket.assignee), (90, (101,), "Bob Smith"))
        labels = {(r.other_id, r.label) for r in ticket.relations}
        self.assertEqual(labels, {(102, "blocked by"), (103, "relates to")})
        self.assertEqual(ticket.attachments[0].filename, "safari_error.png")
        self.assertIs(self.client().get_issue(101).closed, True)

    def test_search_paginates(self):
        fake = FakeRedmine()
        client = self.client(fake, page_size=2)
        self.assertEqual([t.id for t in client.search("100", None, "all", 20)], [100])
        self.assertEqual(sorted(t.id for t in client.search("cookie", None, "all", 20)), [102, 103])
        self.assertEqual(len(client.search("", None, "all", 5)), 5)
        self.assertTrue(any("offset=2" in url for url in fake.calls))

    def test_errors_are_source_errors(self):
        with self.assertRaises(SourceError):
            self.client().get_issue(4040)

    def test_closed_is_unknown_and_lookup_retried_when_status_list_fails_transiently(self):
        class Flaky(FakeRedmine):
            fail = True

            def request_json(self, url, **kwargs):
                if "issue_statuses" in url and self.fail:
                    raise TransportError("busy", 503)
                return super().request_json(url, **kwargs)

        fake = Flaky()
        client = self.client(fake)
        self.assertIsNone(client.get_issue(101).closed)  # unknown, not silently "open"
        fake.fail = False
        self.assertIs(client.get_issue(101).closed, True)  # the failure was not cached

    def test_permanent_lookup_failure_is_remembered(self):
        class Forbidden(FakeRedmine):
            def request_json(self, url, **kwargs):
                if "issue_statuses" in url:
                    self.calls.append(url)
                    raise TransportError("Forbidden", 403)
                return super().request_json(url, **kwargs)

        fake = Forbidden()
        client = self.client(fake)
        client.get_issue(101)
        client.get_issue(102)
        self.assertEqual(sum("issue_statuses" in u for u in fake.calls), 1)


class OllamaTests(unittest.TestCase):
    def reply(self, **extra):
        return {"message": {"content": "<think>x</think>hello"}, "prompt_eval_count": 100, "eval_count": 7, **extra}

    def test_request_shape_is_deterministic_and_response_parsed(self):
        transport = ScriptedTransport(self.reply(done_reason="stop"))
        seen = {}
        transport.request_json = lambda url, **kw: seen.update(url=url, **kw) or self.reply(done_reason="stop")
        model = OllamaModel(LlmCfg(seed=7, num_ctx=8192, max_output_tokens=500), transport)
        completion = model.generate("sys", "prompt", {"type": "object"})
        body = seen["body"]
        self.assertEqual(seen["url"], "http://localhost:11434/api/chat")
        self.assertEqual(
            body["options"], {"temperature": 0, "top_p": 1, "seed": 7, "num_ctx": 8192, "num_predict": 500}
        )
        self.assertEqual((body["keep_alive"], body["format"], body["stream"]), ("30m", {"type": "object"}, False))
        self.assertNotIn("think", body)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertEqual((completion.text, completion.prompt_tokens, completion.output_tokens), ("hello", 100, 7))
        self.assertFalse(completion.truncated)

    def test_truncation_overflow_and_errors(self):
        small = LlmCfg(num_ctx=4096, max_output_tokens=500)
        model = OllamaModel(small, ScriptedTransport(self.reply(done_reason="length")))
        self.assertTrue(model.generate("s", "p").truncated)
        model = OllamaModel(small, ScriptedTransport(self.reply(prompt_eval_count=4090)))
        with self.assertRaises(ContextOverflowError):
            model.generate("s", "p")
        with self.assertRaisesRegex(LLMError, "request failed"):
            OllamaModel(LlmCfg(), ScriptedTransport(TransportError("refused"))).generate("s", "p")
        with self.assertRaisesRegex(LLMError, "unexpected response"):
            OllamaModel(LlmCfg(), ScriptedTransport({"nope": 1})).generate("s", "p")

    def test_think_only_sent_when_configured(self):
        seen = {}
        transport = ScriptedTransport()
        transport.request_json = lambda url, **kw: seen.update(kw) or self.reply()
        OllamaModel(LlmCfg(think=False), transport).generate("s", "p")
        self.assertIs(seen["body"]["think"], False)

    def test_check_ready(self):
        tags = {"models": [{"name": "qwen3:27b"}, {"name": "other:latest"}]}
        OllamaModel(LlmCfg(model="qwen3:27b"), ScriptedTransport(tags)).check_ready()
        OllamaModel(LlmCfg(model="other"), ScriptedTransport(tags)).check_ready()  # implicit :latest
        with self.assertRaisesRegex(LLMError, "not installed"):
            OllamaModel(LlmCfg(model="missing:1b"), ScriptedTransport(tags)).check_ready()
        with self.assertRaisesRegex(LLMError, "cannot reach"):
            OllamaModel(LlmCfg(), ScriptedTransport(TransportError("refused"))).check_ready()

    def test_unknown_backend(self):
        with self.assertRaisesRegex(LLMError, "unknown llm.backend"):
            create_model(LlmCfg(backend="nope"), ScriptedTransport())


class TranslationTests(unittest.TestCase):
    def test_batches_many_texts_into_one_call(self):
        calls = []

        def api(text):
            calls.append(text)
            return text.replace("日本語", "Japanese")

        translator = BatchTranslator(api, max_chars=4000, max_items=20)
        result = translator.translate({"a": "日本語1", "b": "日本語2", "c": "日本語1"})
        self.assertEqual(len(calls), 1)
        # the duplicated text is translated once but fills both keys
        self.assertEqual(result, {"a": "Japanese1", "b": "Japanese2", "c": "Japanese1"})

    def test_batch_limits_split_calls(self):
        calls = []
        translator = BatchTranslator(lambda t: calls.append(t) or t, max_chars=4000, max_items=2)
        translator.translate({str(i): f"テキスト{i}" for i in range(5)})
        self.assertEqual(len(calls), 3)

    def test_mangled_markers_fall_back_to_one_by_one(self):
        calls = []

        def api(text):
            calls.append(text)
            return "no markers survived" if "@@SEG" in text else f"EN:{text}"

        result = BatchTranslator(api, 4000, 20).translate({"a": "一", "b": "二"})
        self.assertEqual(result, {"a": "EN:一", "b": "EN:二"})
        self.assertEqual(len(calls), 3)

    def test_failures_leave_keys_out(self):
        def broken(text):
            raise RuntimeError("api down")

        self.assertEqual(BatchTranslator(broken, 4000, 20).translate({"a": "一", "b": "二"}), {})
        self.assertEqual(BatchTranslator(lambda t: "  ", 4000, 20).translate({"a": "一"}), {})

    def test_loader(self):
        self.assertIsNone(load_translator(TranslateCfg(enabled=False)))
        self.assertIsNone(load_translator(TranslateCfg(module="no_such_module_xyz")))
        self.assertIsNone(load_translator(TranslateCfg(module="json")))  # module without translate()
        module = types.ModuleType("fake_translate_api")
        module.translate = lambda text: "EN"
        sys.modules["fake_translate_api"] = module
        self.addCleanup(sys.modules.pop, "fake_translate_api")
        translator = load_translator(TranslateCfg(module="fake_translate_api"))
        self.assertEqual(translator.translate({"k": "日本語"}), {"k": "EN"})


class EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body["model"] == "boom":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"gpu on fire")
            return
        out = json.dumps({"message": {"content": "reply to " + body["messages"][1]["content"]}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        out = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


class SshTests(Base):
    def setUp(self):
        super().setUp()
        self.server = HTTPServer(("127.0.0.1", 0), EchoHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.channel_transport = FakeSshTransport(self.server.server_address[1])
        self.connects: list[SshCredentials] = []

    def connector(self, cfg, creds):
        self.connects.append(creds)
        return FakeSshClient(self.channel_transport)

    def test_ollama_over_ssh(self):
        ssh = SshTransport(SshCfg(enabled=True), SshCredentials("gpu-box", "bob", "pw"), self.connector)
        ssh.connect()
        model = OllamaModel(LlmCfg(), ssh, "http://127.0.0.1:11434")
        self.assertEqual(model.generate("sys", "hello").text, "reply to hello")
        self.assertEqual(model.generate("sys", "again").text, "reply to again")
        self.assertEqual(len(self.connects), 1, "one SSH connection is reused")
        self.assertEqual(self.channel_transport.targets[0], ("127.0.0.1", 11434))
        self.assertEqual(ssh.request_json("http://127.0.0.1:11434/api/tags"), {"ok": True})

    def test_http_error_and_connection_failure_become_transport_errors(self):
        ssh = SshTransport(SshCfg(), SshCredentials("h", "u", "p"), self.connector)
        with self.assertRaisesRegex(TransportError, "500.*gpu on fire"):
            ssh.request_json("http://127.0.0.1:11434/api/chat", body={"model": "boom", "messages": []})

        def unreachable(cfg, creds):
            raise OSError("no route to host")

        with self.assertRaisesRegex(TransportError, "SSH request via h failed.*no route"):
            SshTransport(SshCfg(), SshCredentials("h", "u", "p"), unreachable).request_json("http://x:1/")

    def test_password_is_not_in_repr(self):
        self.assertNotIn("secret-pw", repr(SshCredentials("h", "u", "secret-pw")))

    def test_interactive_prompt_uses_defaults_and_hides_password(self):
        asked = []
        prompter = CredentialPrompter(
            ask=lambda label: asked.append(label) or ("" if "IP" in label else "alice"),
            ask_secret=lambda label: asked.append(label) or "pw",
            interactive=lambda: True,
        )
        creds = prompter.credentials(SshCfg(host="10.0.0.5"))
        self.assertEqual((creds.host, creds.username, creds.password), ("10.0.0.5", "alice", "pw"))
        self.assertIn("[10.0.0.5]", asked[0])

    def test_non_interactive_uses_environment_or_fails_clearly(self):
        env = {"RMSUM_SSH_HOST": "h", "RMSUM_SSH_USER": "u", "RMSUM_SSH_PASSWORD": "p"}
        creds = CredentialPrompter(environ=env, interactive=lambda: False).credentials(SshCfg())
        self.assertEqual((creds.host, creds.username, creds.password), ("h", "u", "p"))
        with self.assertRaisesRegex(ConfigError, "no terminal"):
            CredentialPrompter(environ={}, interactive=lambda: False).credentials(SshCfg())

    def test_wrong_password_is_asked_again_then_gives_up(self):
        passwords = iter(["wrong1", "wrong2", "right"])
        prompter = CredentialPrompter(
            ask=lambda label: "x", ask_secret=lambda label: next(passwords), interactive=lambda: True
        )
        secrets, attempts = [], []

        def connector(cfg, creds):
            attempts.append(creds.password)
            if creds.password != "right":
                raise SshAuthError("bad password")
            return FakeSshClient(self.channel_transport)

        open_ssh_transport(SshCfg(), prompter, secrets.append, connector)
        self.assertEqual(attempts, ["wrong1", "wrong2", "right"])
        self.assertEqual(secrets, attempts)  # every password was registered for log redaction

        always_wrong = CredentialPrompter(ask=lambda l: "x", ask_secret=lambda l: "nope", interactive=lambda: True)
        def reject(cfg, creds):
            raise SshAuthError("x")

        with self.assertRaises(SshAuthError):
            open_ssh_transport(SshCfg(), always_wrong, lambda secret: None, reject)


if __name__ == "__main__":
    unittest.main()
