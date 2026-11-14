import sys
import types
import unittest

from helpers import Base
from rmsum.models import Journal, Ticket
from rmsum.translate import Translator, has_japanese, load_translator, translate_ticket
from rmsum.config import TranslateCfg


class TranslateTests(Base):
    def test_detection(self):
        self.assertTrue(all(map(has_japanese, ["ログイン", "漢字", "ｶﾀｶﾅ", "mixed ひらがな text"])))
        self.assertFalse(any(map(has_japanese, ["", "plain English", "a → b", "#123 !45"])))

    def test_only_japanese_paragraphs_translated_and_cached(self):
        calls = []
        tr = Translator(lambda s: calls.append(s) or f"EN({s})", self.cache())
        text = "English intro\n\nログインできない\n\n```\ncode\n```"
        self.assertEqual(tr.to_english(text), "English intro\n\nEN(ログインできない)\n\n```\ncode\n```")
        tr.to_english("ログインできない")
        self.assertEqual(calls, ["ログインできない"])  # second call served from cache
        self.assertIsNone(tr.to_english("no japanese here"))

    def test_failure_keeps_original(self):
        def boom(_):
            raise RuntimeError("api down")
        self.assertIsNone(Translator(boom, self.cache()).to_english("ログイン"))
        self.assertIsNone(Translator(lambda s: "  ", self.cache()).to_english("ログイン"))

    def test_translate_ticket_fills_en_fields(self):
        t = Ticket(id=1, subject="件名", description="説明", journals=[Journal(1, "a", "d", "コメント"), Journal(2, "a", "d", "plain")])
        translate_ticket(t, Translator(lambda s: "T:" + s, self.cache()))
        self.assertEqual((t.subject_en, t.description_en, t.journals[0].notes_en, t.journals[1].notes_en),
                         ("T:件名", "T:説明", "T:コメント", None))
        self.assertEqual(t.subject, "件名")  # original preserved

    def test_loader(self):
        self.assertIsNone(load_translator(TranslateCfg(enabled=False), self.cache()))
        self.assertIsNone(load_translator(TranslateCfg(module="no_such_module_xyz"), self.cache()))
        self.assertIsNone(load_translator(TranslateCfg(module="json"), self.cache()))  # no translate()
        fake = types.ModuleType("fake_api_mod")
        fake.translate = lambda s: "EN"
        sys.modules["fake_api_mod"] = fake
        self.addCleanup(sys.modules.pop, "fake_api_mod")
        self.assertEqual(load_translator(TranslateCfg(module="fake_api_mod"), self.cache()).to_english("日本語"), "EN")


if __name__ == "__main__":
    unittest.main()
