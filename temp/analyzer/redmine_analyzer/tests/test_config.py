import dataclasses
import os
import unittest
from unittest.mock import patch

from helpers import Base
from rmsum.config import Config, LlmCfg, RedmineCfg, SshCfg, load_config
from rmsum.errors import ConfigError


class ConfigTests(Base):
    def write(self, text: str):
        path = self.tmp / "c.yml"
        path.write_text(text, "utf-8")
        return path

    def minimal(self, extra: str = "") -> str:
        return f"redmine: {{url: 'https://r.example.com/', api_key: k}}\n{extra}"

    def test_load_with_env_expansion_defaults_and_normalisation(self):
        path = self.write(
            "redmine:\n  url: https://r.example.com/\n  api_key: ${RM_KEY}\n"
            "git: {base_url: 'https://g.example.com/p/'}\nllm:\n  think: false\nssh: {key_file: '~/k'}\n"
        )
        with patch.dict(os.environ, {"RM_KEY": "secret"}):
            cfg = load_config(path)
        self.assertEqual(
            (cfg.redmine.url, cfg.redmine.api_key, cfg.git.base_url),
            ("https://r.example.com", "secret", "https://g.example.com/p"),
        )
        llm = cfg.llm
        self.assertEqual((llm.num_ctx, llm.think, llm.keep_alive, cfg.analysis.max_depth), (16384, False, "30m", 2))
        self.assertNotIn("~", cfg.ssh.key_file)

    def test_config_is_immutable(self):
        cfg = load_config(self.write(self.minimal()))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cfg.llm.model = "other"  # type: ignore[misc]

    def test_secrets_are_not_in_repr(self):
        cfg = load_config(self.write("redmine: {url: 'https://r', api_key: topsecret-key}"))
        self.assertNotIn("topsecret-key", repr(cfg))

    def test_structural_errors(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_config(self.tmp / "missing.yml")
        with self.assertRaisesRegex(ConfigError, "unknown key 'urll'"):
            load_config(self.write("redmine: {url: u, api_key: k, urll: x}"))
        with self.assertRaisesRegex(ConfigError, "unknown section"):
            load_config(self.write("redmin: {}"))
        with self.assertRaisesRegex(ConfigError, "required"):
            load_config(self.write("llm: {model: x}"))
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ConfigError, "unset variable"):
            load_config(self.write("redmine: {url: u, api_key: '${NOPE_KEY}'}"))
        with self.assertRaisesRegex(ConfigError, "invalid YAML"):
            load_config(self.write("a: [unclosed"))
        with self.assertRaisesRegex(ConfigError, "must be a mapping"):
            load_config(self.write(self.minimal("llm: [1, 2]")))

    def test_removed_keys_get_a_helpful_message(self):
        with self.assertRaisesRegex(ConfigError, "no longer uses a database"):
            load_config(self.write(self.minimal("cache: {path: x}")))
        with self.assertRaisesRegex(ConfigError, "asked for at run time"):
            load_config(self.write(self.minimal("ssh: {password: hunter2}")))

    def test_types_and_ranges_are_validated(self):
        for text, message in [
            ("llm: {num_ctx: lots}", "llm.num_ctx must be of type int"),
            ("llm: {num_ctx: true}", "llm.num_ctx must be of type int"),
            ("llm: {think: maybe}", "llm.think must be true, false or null"),
            ("llm: {num_ctx: 100}", "num_ctx must be >= 2048"),
            ("llm: {max_output_tokens: 9000}", "max_output_tokens"),
            ("redmine: {url: u, api_key: k, page_size: 500}", "page_size"),
            ("analysis: {max_tickets: 0}", "max_tickets"),
            ("ssh: {port: 70000}", "ssh.port"),
            ("logging: {level: LOUD}", "logging.level"),
            ("translate: {batch_items: 0}", "batch_items"),
        ]:
            with self.subTest(text), self.assertRaisesRegex(ConfigError, message):
                base = "" if text.startswith("redmine") else "redmine: {url: u, api_key: k}\n"
                load_config(self.write(base + text))

    def test_numbers_are_coerced(self):
        cfg = load_config(self.write(self.minimal("llm: {timeout: 60}\nredmine: {url: u, api_key: 12345}")))
        self.assertEqual((cfg.llm.timeout, cfg.redmine.api_key), (60.0, "12345"))

    def test_defaults_are_valid(self):
        self.assertIsInstance(Config(), Config)
        self.assertEqual((LlmCfg().backend, SshCfg().enabled, RedmineCfg().retries), ("ollama", False, 3))


if __name__ == "__main__":
    unittest.main()
