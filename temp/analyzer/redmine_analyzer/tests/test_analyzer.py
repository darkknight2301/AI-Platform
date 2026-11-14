import unittest

from helpers import REDMINE, Base, FakeLLM, FakeRedmine
from rmsum.analyzer import analyze, facts_text
from rmsum.config import RedmineCfg
from rmsum.llm import LLMError
from rmsum.redmine import RedmineClient
from rmsum.translate import Translator


class AnalyzerTests(Base):
    def run_analysis(self, llm=None, redmine=None, cfg=None, translator=None, **kw):
        cfg = cfg or self.cfg()
        redmine = redmine or FakeRedmine()
        llm = llm or FakeLLM()
        client = RedmineClient(RedmineCfg(url=REDMINE, api_key="k"), redmine)
        return analyze(100, cfg=cfg, client=client, backend=llm, cache=self.cache(), translator=translator, **kw), llm

    def test_direct_mode_validates_claims(self):
        a, llm = self.run_analysis()
        self.assertEqual(a.meta["mode"], "direct")
        self.assertEqual(len(llm.prompts), 2)  # consolidation + summary
        blockers = {c.text: c for c in a.sections["blockers"]}
        self.assertNotIn("Depends on #999", blockers)                      # unknown ticket dropped
        self.assertEqual(blockers["Vendor release pending"].basis, "unverified")  # bad source tag removed
        self.assertEqual(blockers["Vendor release pending"].sources, [])
        self.assertEqual(blockers["Waiting for #102 to be merged"].basis, "confirmed")
        self.assertEqual(a.sections["decisions"][0].sources, ["#100 J3"])  # "[#100 J3]" normalised
        self.assertEqual(a.sections["implementation"][0].basis, "confirmed")  # !45 and a1b2c3d are real facts
        self.assertTrue(any("dropped" in w for w in a.warnings))

    def test_summary_sentences_with_unknown_ids_removed(self):
        a, _ = self.run_analysis()
        self.assertNotIn("#999", a.short_summary)
        self.assertIn("!45", a.short_summary)
        self.assertTrue(any("summary sentence" in w for w in a.warnings))

    def test_prompt_contains_facts_and_chronological_history(self):
        _, llm = self.run_analysis()
        p = llm.prompts[0]
        self.assertIn("!45 (found in: #100 J2)", p)
        self.assertIn("https://docs.example.com/specs/auth-v2.pdf", p)
        self.assertIn("safari_error.png", p)
        self.assertIn("#100 blocked by #102", p)  # relation from the root's point of view
        self.assertLess(p.index("[#100 J1]"), p.index("[#100 J2]"))
        self.assertLess(p.index("[#100 J2]"), p.index("[#100 J3]"))
        self.assertIn("TICKETS FETCHED", p)
        self.assertIn("TICKET REFERENCES IN TEXT (not fetched):\n- #404", p)  # only unknown tickets listed
        self.assertNotIn("- #101 (found in", p)

    def test_map_reduce_for_small_context(self):
        a, llm = self.run_analysis(llm=FakeLLM(num_ctx=1200))
        self.assertEqual(a.meta["mode"], "map-reduce")
        self.assertGreater(len(llm.prompts), 8)  # one per ticket chunk + consolidation + summary
        self.assertTrue(a.sections["background"])

    def test_cache_hit_regenerate_and_staleness(self):
        redmine = FakeRedmine()
        _, llm = self.run_analysis(redmine=redmine)
        n = len(llm.prompts)
        a, llm2 = self.run_analysis(redmine=redmine)
        self.assertEqual(len(llm2.prompts), 0, "unchanged tickets must be served from cache")
        self.assertEqual(a.root_id, 100)
        _, llm3 = self.run_analysis(redmine=redmine, regenerate=True)
        self.assertEqual(len(llm3.prompts), n)
        redmine.data["issues"]["102"]["updated_on"] = "2024-06-01T00:00:00Z"  # a related ticket changed
        _, llm4 = self.run_analysis(redmine=redmine)
        self.assertEqual(len(llm4.prompts), n, "a changed related ticket must invalidate the cache")

    def test_translation_reaches_prompt_and_original_preserved(self):
        tr = Translator(lambda s: "TRANSLATED", self.cache())
        _, llm = self.run_analysis(translator=tr)
        p = llm.prompts[0]
        self.assertIn("[translated from Japanese]", p)
        self.assertIn("調査を開始しました", p)  # original kept

    def test_untranslated_japanese_is_flagged(self):
        a, llm = self.run_analysis()
        self.assertIn("[UNTRANSLATED JAPANESE]", llm.prompts[0])
        self.assertTrue(any("could not be translated" in w for w in a.warnings))

    def test_invalid_json_retried_once_then_error(self):
        class BadLLM(FakeLLM):
            def generate(self, system, prompt, schema=None):
                self.prompts.append(prompt)
                return "not json" if schema else "x"

        class FixesItself(FakeLLM):
            def generate(self, system, prompt, schema=None):
                if schema and "not valid JSON" not in prompt:
                    self.prompts.append(prompt)
                    return "```json\n{broken"
                return super().generate(system, prompt, schema)

        with self.assertRaises(LLMError):
            self.run_analysis(llm=BadLLM())
        a, _ = self.run_analysis(llm=FixesItself())
        self.assertTrue(a.sections["background"])

    def test_missing_info_is_explicit(self):
        a, llm = self.run_analysis()
        self.assertIn("BRANCHES:", llm.prompts[0])
        self.assertEqual(len(a.sections["dependencies"]), 0)

    def test_facts_text_per_ticket_is_filtered(self):
        from rmsum.extract import extract_facts
        from rmsum.graph import build_graph
        c = RedmineClient(RedmineCfg(url=REDMINE, api_key="k"), FakeRedmine())
        g = build_graph(c, 100)
        facts = extract_facts(g.tickets.values(), REDMINE, "https://g/p")
        only = facts_text(g, facts, only=101)
        self.assertIn("!47", only)
        self.assertNotIn("!45", only)
        self.assertNotIn("TICKETS FETCHED", only)


if __name__ == "__main__":
    unittest.main()
