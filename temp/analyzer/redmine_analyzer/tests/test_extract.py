import unittest

from helpers import REDMINE
from rmsum.extract import extract_facts
from rmsum.models import Attachment, Journal, Ticket

GIT = "https://gitlab.example.com/group/project"


def facts(text: str, **kw) -> dict[tuple[str, str], object]:
    t = Ticket(id=1, subject="s", description=text, **kw)
    return {(f.kind, f.value): f for f in extract_facts([t], REDMINE, GIT)}


class ExtractTests(unittest.TestCase):
    def test_merge_requests(self):
        f = facts("Fixed in !45, MR 46, merge request #47 and https://gitlab.example.com/g/p/-/merge_requests/48")
        self.assertEqual({v for k, v in f if k == "mr"}, {"!45", "!46", "!47", "!48"})
        self.assertEqual(f["mr", "!45"].url, f"{GIT}/-/merge_requests/45")
        self.assertEqual(f["mr", "!48"].url, "https://gitlab.example.com/g/p/-/merge_requests/48")

    def test_commits_need_digit_and_keyword(self):
        f = facts("commit a1b2c3d4e5 and revision: 0123456789abcdef. Also commit added and commit defaced.")
        self.assertEqual({v for k, v in f if k == "commit"}, {"a1b2c3d", "0123456"})

    def test_branches(self):
        f = facts("branch: feature/x-1, also `bugfix/y`, ブランチ: release/1.0 and branch is merged")
        self.assertEqual({v for k, v in f if k == "branch"}, {"feature/x-1", "bugfix/y", "release/1.0"})

    def test_ticket_refs_ignore_url_fragments(self):
        f = facts(f"See #12, #13 and {REDMINE}/issues/14 but not https://example.com/page#15 or &#39;")
        self.assertEqual({v for k, v in f if k == "ticket"}, {"#12", "#13", "#14"})

    def test_documents_and_urls(self):
        f = facts("Spec https://docs.example.com/a.pdf, [[Auth Spec]], design.xlsx, https://example.com/x")
        self.assertEqual({v for k, v in f if k == "doc"},
                         {"https://docs.example.com/a.pdf", "wiki:Auth Spec", "design.xlsx"})
        self.assertIn(("url", "https://example.com/x"), f)

    def test_sources_and_dedup(self):
        t = Ticket(id=7, subject="s", description="See !5",
                   journals=[Journal(3, "a", "2024", "Again !5")],
                   attachments=[Attachment("log.txt", "https://r/x")], commits=[("abcdef1234567", "msg #9")])
        found = {(f.kind, f.value): f for f in extract_facts([t], REDMINE, GIT)}
        self.assertEqual(found["mr", "!5"].sources, ["#7", "#7 J3"])
        self.assertEqual(found["attachment", "log.txt"].url, "https://r/x")
        self.assertIn(("commit", "abcdef1"), found)
        self.assertIn(("ticket", "#9"), found)

    def test_no_git_url_means_no_link(self):
        t = Ticket(id=1, subject="s", description="!5")
        self.assertIsNone(extract_facts([t], REDMINE)[0].url)


if __name__ == "__main__":
    unittest.main()
