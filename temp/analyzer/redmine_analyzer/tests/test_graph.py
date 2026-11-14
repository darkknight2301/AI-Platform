import unittest

from helpers import REDMINE, FakeRedmine
from rmsum.config import RedmineCfg
from rmsum.graph import build_graph
from rmsum.redmine import RedmineClient, RedmineError


def client(fake=None):
    fake = fake or FakeRedmine()
    return RedmineClient(RedmineCfg(url=REDMINE, api_key="k"), fake), fake


class GraphTests(unittest.TestCase):
    def test_full_traversal_without_loops_or_duplicates(self):
        c, fake = client()
        g = build_graph(c, 100, max_depth=2, max_tickets=25)
        self.assertEqual(list(g.tickets), [100, 90, 101, 102, 103, 105])
        self.assertEqual(g.via[105], "#90 parent of #105")
        for tid in g.tickets:
            self.assertEqual(sum(u.endswith(f"/issues/{tid}.json?include=journals%2Crelations%2Cchildren%2Cattachments%2Cchangesets")
                                 for u in fake.calls), 1, f"#{tid} fetched more than once")
        pairs = [frozenset((a, b)) for a, _, b in g.edges]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_depth_limit_is_reported(self):
        g = build_graph(client()[0], 100, max_depth=1)
        self.assertNotIn(105, g.tickets)
        self.assertTrue(any(s.startswith("#105: beyond max depth 1") for s in g.skipped))

    def test_ticket_limit_is_reported(self):
        g = build_graph(client()[0], 100, max_tickets=3)
        self.assertEqual(len(g.tickets), 3)
        self.assertTrue(all("limit" in s or "depth" in s for s in g.skipped) and g.skipped)

    def test_text_refs_followed_only_when_enabled_and_failures_recorded(self):
        off = build_graph(client()[0], 100, redmine_url=REDMINE)
        on = build_graph(client()[0], 100, follow_text_refs=True, redmine_url=REDMINE)
        self.assertFalse(any("#404" in s for s in off.skipped))
        self.assertTrue(any(s.startswith("#404: fetch failed") for s in on.skipped))

    def test_relation_labels_follow_ticket_perspective(self):
        t = client()[0].get_issue(100)
        self.assertIn((102, "blocked by"), t.relations)
        self.assertIn((103, "relates to"), t.relations)

    def test_missing_root_raises(self):
        with self.assertRaises(RedmineError):
            build_graph(client()[0], 4040)


class ClientTests(unittest.TestCase):
    def test_parse_details(self):
        t = client()[0].get_issue(100)
        self.assertEqual([j.id for j in t.journals], [1, 2, 3])  # chronological
        self.assertEqual(t.journals[0].changes, ["status_id: New → In Progress"])
        self.assertEqual(t.journals[2].changes, ["Component: web → auth"])
        self.assertEqual(t.custom_fields, {"Customer": "ACME", "Component": "auth"})
        self.assertEqual((t.parent_id, t.children, t.assignee), (90, [101], "Bob Smith"))
        self.assertEqual(t.attachments[0].filename, "safari_error.png")
        self.assertTrue(client()[0].get_issue(101).closed)

    def test_search_by_id_and_subject_with_pagination(self):
        c, fake = client()
        c._cfg.page_size = 2
        self.assertEqual([t.id for t in c.search("100")], [100])
        found = c.search("cookie", status="all")
        self.assertEqual(sorted(t.id for t in found), [102, 103])
        self.assertEqual(len(c.search("", status="all", limit=5)), 5)
        self.assertTrue(any("offset=2" in u for u in fake.calls))

    def test_retries_5xx_then_fails_but_not_4xx(self):
        from unittest.mock import patch
        from rmsum.httpjson import HttpError
        calls = []

        def flaky(url, **_):
            calls.append(url)
            raise HttpError(503, "busy")

        with patch("rmsum.redmine.time.sleep"), self.assertRaises(RedmineError):
            RedmineClient(RedmineCfg(url=REDMINE, api_key="k"), flaky).get_issue(1)
        self.assertEqual(len(calls), 3)
        with self.assertRaises(RedmineError):
            client()[0].get_issue(4040)


if __name__ == "__main__":
    unittest.main()
