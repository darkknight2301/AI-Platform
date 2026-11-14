import os
import unittest
from unittest.mock import patch

from helpers import Base
from rmsum.config import ConfigError, load_config


class ConfigTests(Base):
    def write(self, text: str):
        p = self.tmp / "c.yml"
        p.write_text(text, "utf-8")
        return p

    def test_load_with_env_expansion_and_defaults(self):
        p = self.write("redmine:\n  url: https://r.example.com/\n  api_key: ${RM_KEY}\nllm:\n  model: qwen3:27b\n  think: false\n")
        with patch.dict(os.environ, {"RM_KEY": "secret"}):
            cfg = load_config(p)
        self.assertEqual((cfg.redmine.url, cfg.redmine.api_key), ("https://r.example.com", "secret"))
        self.assertEqual((cfg.llm.num_ctx, cfg.llm.think, cfg.analysis.max_depth), (16384, False, 2))

    def test_errors(self):
        with self.assertRaisesRegex(ConfigError, "not found"):
            load_config(self.tmp / "missing.yml")
        with self.assertRaisesRegex(ConfigError, "unknown key"):
            load_config(self.write("redmine: {url: u, api_key: k, urll: x}"))
        with self.assertRaisesRegex(ConfigError, "unknown section"):
            load_config(self.write("redmin: {}"))
        with self.assertRaisesRegex(ConfigError, "required"):
            load_config(self.write("llm: {model: x}"))
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ConfigError, "unset environment"):
            load_config(self.write("redmine: {url: u, api_key: '${NOPE_KEY}'}"))
        with self.assertRaisesRegex(ConfigError, "invalid YAML"):
            load_config(self.write("a: [unclosed"))


if __name__ == "__main__":
    unittest.main()
