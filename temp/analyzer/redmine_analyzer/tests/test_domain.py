import unittest

from helpers import GIT, REDMINE
from rmsum.domain.budget import clip, estimate_tokens
from rmsum.domain.extraction import extract_facts
from rmsum.domain.language import has_japanese, japanese_paragraphs
from rmsum.domain.models import Attachment, Basis, FactKind, Journal, Ticket
from rmsum.domain.validation import ClaimValidator, KnownReferences


def facts(text: str, **kw) -> dict[tuple[str, str], object]:
    ticket = Ticket(id=1, subject="s", description=text, **kw)
    return {(f.kind, f.value): f for f in extract_facts([ticket], REDMINE, GIT)}


class ExtractionTests(unittest.TestCase):
    def values(self, found, kind):
        return {v for k, v in found if k == kind}

    def test_merge_requests(self):
        f = facts("Fixed in !45, MR 46, merge request #47 and https://gitlab.example.com/g/p/-/merge_requests/48")
        self.assertEqual(self.values(f, FactKind.MR), {"!45", "!46", "!47", "!48"})
        self.assertEqual(f[FactKind.MR, "!45"].url, f"{GIT}/-/merge_requests/45")
        self.assertEqual(f[FactKind.MR, "!48"].url, "https://gitlab.example.com/g/p/-/merge_requests/48")

    def test_commits_need_a_digit_and_a_keyword(self):
        f = facts("commit a1b2c3d4e5 and revision: 0123456789abcdef. Also commit added and commit defaced.")
        self.assertEqual(self.values(f, FactKind.COMMIT), {"a1b2c3d", "0123456"})

    def test_branches(self):
        f = facts("branch: feature/x-1, also `bugfix/y`, ブランチ: release/1.0 and branch is merged")
        self.assertEqual(self.values(f, FactKind.BRANCH), {"feature/x-1", "bugfix/y", "release/1.0"})

    def test_ticket_refs_ignore_url_fragments(self):
        f = facts(f"See #12, #13 and {REDMINE}/issues/14 but not https://example.com/page#15 or &#39;")
        self.assertEqual(self.values(f, FactKind.TICKET), {"#12", "#13", "#14"})

    def test_documents_and_urls(self):
        f = facts("Spec https://docs.example.com/a.pdf, [[Auth Spec]], design.xlsx, https://example.com/x")
        self.assertEqual(
            self.values(f, FactKind.DOC), {"https://docs.example.com/a.pdf", "wiki:Auth Spec", "design.xlsx"}
        )
        self.assertIn((FactKind.URL, "https://example.com/x"), f)

    def test_sources_dedup_attachments_and_commits(self):
        t = Ticket(
            id=7,
            subject="s",
            description="See !5",
            journals=(Journal(3, "a", "2024", "Again !5"),),
            attachments=(Attachment("log.txt", "https://r/x"),),
            commits=(("abcdef1234567", "msg #9"),),
        )
        found = {(f.kind, f.value): f for f in extract_facts([t], REDMINE, GIT)}
        self.assertEqual(found[FactKind.MR, "!5"].sources, ("#7", "#7 J3"))
        self.assertEqual(found[FactKind.ATTACHMENT, "log.txt"].url, "https://r/x")
        self.assertIn((FactKind.COMMIT, "abcdef1"), found)
        self.assertIn((FactKind.TICKET, "#9"), found)

    def test_without_git_url_there_is_no_link(self):
        ticket = Ticket(id=1, subject="s", description="!5")
        self.assertIsNone(extract_facts([ticket], REDMINE)[0].url)


class ValidationTests(unittest.TestCase):
    def validator(self) -> ClaimValidator:
        return ClaimValidator(
            KnownReferences(
                ticket_ids=frozenset({100, 102}),
                merge_requests=frozenset({"!45"}),
                commits=frozenset({"a1b2c3d"}),
                tags=frozenset({"#100", "#100 J2", "#102"}),
            )
        )

    def test_check_text(self):
        v = self.validator()
        self.assertIsNone(v.check_text("Blocked by #102 until !45 (commit a1b2c3d4) lands"))
        self.assertEqual(v.check_text("See #999"), "unknown ticket #999")
        self.assertEqual(v.check_text("Fixed in !7"), "unknown merge request !7")
        self.assertEqual(v.check_text("commit deadbee1 did it"), "unknown commit deadbee")
        self.assertIsNone(v.check_text("The 1000000 users saw it"))  # plain numbers are not commits

    def test_validate_normalises_downgrades_and_records_rejections(self):
        raw = {
            "blockers": [
                {"text": "ok", "basis": "confirmed", "sources": ["[#100 J2]", "#100 J99", "nonsense"]},
                {"text": "no source", "basis": "confirmed", "sources": []},
                {"text": "guess", "basis": "assumption"},
                {"text": "no basis at all"},
                {"text": "bad id #5", "basis": "confirmed", "sources": ["#100"]},
                {"text": "OK", "basis": "assumption", "sources": []},  # duplicate (case-insensitive)
                {"text": "weird basis", "basis": "certain", "sources": ["#102"]},
                "plain string statement",
                42,
            ],
            "background": "not a list",
        }
        report = self.validator().validate(raw)
        claims = {c.text: c for c in report.sections[next(s for s in report.sections if s.value == "blockers")]}
        self.assertEqual(claims["ok"].sources, ("#100 J2",))
        self.assertEqual(claims["ok"].basis, Basis.CONFIRMED)
        self.assertEqual(claims["no source"].basis, Basis.UNVERIFIED)
        self.assertEqual(claims["guess"].basis, Basis.ASSUMPTION)  # an honest assumption needs no source
        self.assertEqual(claims["no basis at all"].basis, Basis.UNVERIFIED)  # a missing basis is never trusted
        self.assertEqual(claims["weird basis"].basis, Basis.UNVERIFIED)
        self.assertIn("plain string statement", claims)
        self.assertEqual(len(claims), 6)
        self.assertEqual(sorted(d.reason for d in report.dropped), ["not a statement object", "unknown ticket #5"])


class TextTests(unittest.TestCase):
    def test_japanese_detection(self):
        self.assertTrue(all(map(has_japanese, ["ログイン", "漢字", "ｶﾀｶﾅ", "mixed ひらがな text"])))
        self.assertFalse(any(map(has_japanese, ["", "plain English", "a → b", "#123 !45"])))
        self.assertEqual(japanese_paragraphs("English\n\n日本語\n\nMore English"), "日本語")

    def test_estimate_and_clip(self):
        self.assertLess(estimate_tokens("a" * 320), estimate_tokens("あ" * 320))
        self.assertEqual(estimate_tokens(""), 0)
        clipped = clip("x" * 1000, 200)
        self.assertLessEqual(len(clipped), 200)
        self.assertIn("characters omitted", clipped)
        self.assertEqual(clip("short", 200), "short")


if __name__ == "__main__":
    unittest.main()
