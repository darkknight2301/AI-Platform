import unittest

from rmsum.context import clip, estimate_tokens, render_ticket, split_ticket
from rmsum.models import Journal, Ticket


def big_ticket(n=40) -> Ticket:
    return Ticket(id=5, subject="Big", description="desc", status="New", journals=[
        Journal(i, "u", f"2024-01-{i:02d}", f"comment number {i} " + "word " * 60) for i in range(1, n + 1)])


class ContextTests(unittest.TestCase):
    def test_estimate_counts_japanese_heavier(self):
        self.assertLess(estimate_tokens("a" * 320), estimate_tokens("あ" * 320))
        self.assertEqual(estimate_tokens(""), 0)

    def test_clip_marks_omission(self):
        out = clip("x" * 1000, 200)
        self.assertLessEqual(len(out), 200)
        self.assertIn("characters omitted", out)
        self.assertEqual(clip("short", 200), "short")

    def test_render_marks_japanese_states(self):
        t = Ticket(id=1, subject="s", description="説明", journals=[Journal(1, "a", "d", "コメント")])
        t.description_en = "Explanation"
        r = render_ticket(t, 1000, include_original=True)
        self.assertIn("[translated from Japanese] Explanation", r.header)
        self.assertIn("[original Japanese] 説明", r.header)
        self.assertIn("[UNTRANSLATED JAPANESE] コメント", r.journals[0])
        self.assertNotIn("[original Japanese]", render_ticket(t, 1000, include_original=False).header)

    def test_original_block_contains_only_japanese_paragraphs(self):
        t = Ticket(id=1, subject="s", description="日本語です。\n\nEnglish paragraph stays once.")
        t.description_en = "It is Japanese.\n\nEnglish paragraph stays once."
        header = render_ticket(t, 1000, include_original=True).header
        self.assertEqual(header.count("English paragraph stays once."), 1)
        self.assertIn("[original Japanese] 日本語です。", header)

    def test_long_text_is_clipped_with_warning(self):
        t = Ticket(id=1, subject="s", description="x" * 500)
        self.assertEqual(len(render_ticket(t, 100, True).warnings), 1)

    def test_split_keeps_every_comment_in_order_within_budget(self):
        r = render_ticket(big_ticket(), 6000, True)
        chunks = split_ticket(r, 600)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(estimate_tokens(c) <= 600 for c in chunks))
        self.assertTrue(chunks[0].startswith("=== TICKET #5"))
        self.assertIn("(continued)", chunks[1])
        tags = [f"[#5 J{i}]" for i in range(1, 41)]
        joined = "\n".join(chunks)
        self.assertTrue(all(t in joined for t in tags))
        self.assertEqual(sorted(tags, key=joined.index), tags)

    def test_small_ticket_is_one_chunk(self):
        self.assertEqual(len(split_ticket(render_ticket(big_ticket(2), 6000, True), 5000)), 1)


if __name__ == "__main__":
    unittest.main()
