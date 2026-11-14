import json
import os
import unittest
from dataclasses import replace
from datetime import datetime
from unittest.mock import patch

from openpyxl import load_workbook

from helpers import GIT, REDMINE, Base, FakeModel, FakeRedmine
from rmsum.adapters.redmine import RedmineClient
from rmsum.application.service import AnalysisService, AnalysisSettings
from rmsum.domain.models import Analysis, Basis, Claim, DroppedClaim, Section
from rmsum.reporting.audit import HEADERS, AuditEntry, AuditLog
from rmsum.reporting.html import render_html
from rmsum.reporting.writer import atomic_write, load_previous, report_path, write_reports
from rmsum.reporting.xlsx import write_xlsx


class ReportBase(Base):
    def setUp(self):
        super().setUp()
        cfg = self.config()
        service = AnalysisService(
            RedmineClient(cfg.redmine, FakeRedmine()), FakeModel(), None, AnalysisSettings.from_config(cfg, False)
        )
        self.analysis = service.analyze(100).analysis

    def with_claim(self, section: Section, text: str, basis: Basis = Basis.CONFIRMED) -> Analysis:
        sections = dict(self.analysis.sections)
        sections[section] = sections[section] + (Claim(text, basis, ("#100",)),)
        return replace(self.analysis, sections=sections)


class HtmlTests(ReportBase):
    def test_report_content_and_links(self):
        html = render_html(self.analysis)
        self.assertIn("<details", html)
        self.assertIn(f'href="{REDMINE}/issues/102"', html)
        self.assertIn(f'href="{REDMINE}/issues/100#change-2"', html)  # journal source link
        self.assertIn(f'href="{GIT}/-/merge_requests/45"', html)
        self.assertIn("safari_error.png", html)
        self.assertIn("auth-v2.pdf", html)
        self.assertIn('class="b unverified"', html)
        self.assertIn("Not available in ticket data", html)  # empty sections say so
        self.assertIn("Statements rejected by validation", html)
        self.assertNotIn("<script", html)

    def test_untrusted_text_is_escaped(self):
        analysis = self.with_claim(Section.BACKGROUND, "<script>alert(1)</script> #100")
        analysis = replace(analysis, warnings=("<b>x</b>",), dropped=(DroppedClaim("background", "<i>bad</i>", "r"),))
        html = render_html(analysis)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<b>x</b>", html)
        self.assertNotIn("<i>bad</i>", html)

    def test_unknown_open_state_is_shown_as_unknown(self):
        tickets = (replace(self.analysis.tickets[0], closed=None),) + self.analysis.tickets[1:]
        self.assertIn('class="st unknown"', render_html(replace(self.analysis, tickets=tickets)))


class XlsxTests(ReportBase):
    def test_sheets_links_and_content(self):
        path = self.tmp / "r.xlsx"
        write_xlsx(self.analysis, path)
        wb = load_workbook(path)
        self.assertEqual(
            wb.sheetnames,
            [
                "Short Summary",
                "Detailed Analysis",
                "Related Tickets",
                "MR References",
                "Open Issues",
                "Other References",
            ],
        )
        related = wb["Related Tickets"]
        self.assertEqual(related.max_row, 1 + 6)
        self.assertEqual(related["A2"].hyperlink.target, f"{REDMINE}/issues/100")
        mr = {r[1].value: r[1].hyperlink.target for r in wb["MR References"].iter_rows(min_row=2) if r[1].hyperlink}
        self.assertEqual(mr["!46"], "https://gitlab.example.com/group/project/-/merge_requests/46")
        self.assertTrue(any(r[0].value == "Blockers" for r in wb["Open Issues"].iter_rows(min_row=2)))

    def test_formula_injection_is_neutralised(self):
        analysis = self.with_claim(Section.BACKGROUND, '=HYPERLINK("http://evil")', Basis.ASSUMPTION)
        write_xlsx(analysis, self.tmp / "r.xlsx")
        sheet = load_workbook(self.tmp / "r.xlsx")["Detailed Analysis"]
        cell = next(c for row in sheet.iter_rows() for c in row if str(c.value).startswith("=HYPERLINK"))
        self.assertEqual(cell.data_type, "s")

    def test_empty_sheet_says_so(self):
        analysis = replace(self.analysis, facts=())
        write_xlsx(analysis, self.tmp / "r.xlsx")
        self.assertEqual(load_workbook(self.tmp / "r.xlsx")["MR References"]["A2"].value, "None found in ticket data")


class WriterTests(ReportBase):
    def test_json_is_always_written_and_roundtrips(self):
        written = write_reports(self.analysis, self.tmp, ["html"])
        self.assertEqual([p.name for p in written], ["redmine_100.html", "redmine_100.json"])
        self.assertEqual(load_previous(report_path(self.tmp, 100, "json")), self.analysis)

    def test_all_formats(self):
        names = [p.name for p in write_reports(self.analysis, self.tmp, ["html", "xlsx", "json"])]
        self.assertEqual(names, ["redmine_100.html", "redmine_100.xlsx", "redmine_100.json"])

    def test_failed_write_keeps_the_old_file_and_leaves_no_temp_file(self):
        target = self.tmp / "report.txt"
        target.write_text("old")

        def explode(path):
            path.write_text("partial")
            raise OSError("disk full")

        with self.assertRaises(OSError):
            atomic_write(target, explode)
        self.assertEqual(target.read_text(), "old")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["report.txt"])

    def test_load_previous_tolerates_garbage_and_old_schemas(self):
        path = self.tmp / "redmine_1.json"
        self.assertIsNone(load_previous(path))
        path.write_text("{not json")
        self.assertIsNone(load_previous(path))
        data = self.analysis.to_dict()
        data["meta"]["schema_version"] = 1
        path.write_text(json.dumps(data))
        self.assertIsNone(load_previous(path))
        path.write_text(json.dumps({"root_id": 1}))
        self.assertIsNone(load_previous(path))


class AuditTests(Base):
    def entry(self, ticket=1, outcome="ANALYSED", **kwargs) -> AuditEntry:
        return AuditEntry(ticket_id=ticket, outcome=outcome, timestamp=datetime(2024, 5, 1, 12, 0), **kwargs)

    def rows(self, path):
        sheet = load_workbook(path)["Audit Log"]
        return [[c.value for c in row] for row in sheet.iter_rows(min_row=2)]

    def test_entries_accumulate_across_calls(self):
        path = self.tmp / "audit.xlsx"
        log = AuditLog(path, user="alice")
        log.record(self.entry(100, subject="Login", llm_calls=2, total_seconds=12.34, ollama_host="ssh:gpu"))
        AuditLog(path, user="alice").record(self.entry(101, "FAILED", error="HTTP 404"))
        header = [c.value for c in load_workbook(path)["Audit Log"][1]]
        self.assertEqual(header, HEADERS)
        rows = self.rows(path)
        summary = [(r[1], r[2], r[4]) for r in rows]
        self.assertEqual(summary, [("alice", "#100", "ANALYSED"), ("alice", "#101", "FAILED")])
        self.assertEqual((rows[0][9], rows[0][17], rows[0][18]), (2, 12.3, "ssh:gpu"))
        self.assertEqual(rows[1][20], "HTTP 404")

    def test_disabled_log_does_nothing(self):
        self.assertIsNone(AuditLog(None).record(self.entry()))

    def test_locked_file_falls_back_to_a_side_file(self):
        path = self.tmp / "audit.xlsx"
        real_replace = os.replace
        calls = []

        def locked_once(src, dst):
            calls.append(dst)
            if len(calls) == 1:
                raise PermissionError("file is open in Excel")
            return real_replace(src, dst)

        with patch("rmsum.reporting.audit.os.replace", locked_once):
            written = AuditLog(path, user="u").record(self.entry())
        self.assertNotEqual(written, path)
        self.assertTrue(written.exists())
        self.assertFalse(any(p.name.startswith(".") for p in self.tmp.iterdir()))

    def test_corrupt_file_is_set_aside_not_overwritten(self):
        path = self.tmp / "audit.xlsx"
        path.write_bytes(b"this is not a zip file")
        AuditLog(path, user="u").record(self.entry())
        self.assertEqual(len(self.rows(path)), 1)
        self.assertEqual((self.tmp / "audit.corrupt.xlsx").read_bytes(), b"this is not a zip file")

    def test_never_raises(self):
        blocker = self.tmp / "file"
        blocker.write_text("x")
        self.assertIsNone(AuditLog(blocker / "audit.xlsx", user="u").record(self.entry()))  # parent is a file


if __name__ == "__main__":
    unittest.main()
