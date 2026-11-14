import json
import unittest

from openpyxl import load_workbook

from helpers import REDMINE, Base, FakeLLM, FakeRedmine
from rmsum.analyzer import analyze
from rmsum.config import RedmineCfg
from rmsum.export_html import render_html
from rmsum.export_xlsx import write_xlsx
from rmsum.models import Analysis, Claim
from rmsum.redmine import RedmineClient


class ExportTests(Base):
    def setUp(self):
        super().setUp()
        client = RedmineClient(RedmineCfg(url=REDMINE, api_key="k"), FakeRedmine())
        self.a = analyze(100, cfg=self.cfg(), client=client, backend=FakeLLM(), cache=self.cache())

    def test_html_report(self):
        html = render_html(self.a)
        self.assertIn("<details", html)
        self.assertIn(f'href="{REDMINE}/issues/102"', html)                       # ticket link
        self.assertIn(f'href="{REDMINE}/issues/100#change-2"', html)              # journal source link
        self.assertIn('href="https://gitlab.example.com/group/project/-/merge_requests/45"', html)
        self.assertIn("safari_error.png", html)
        self.assertIn("auth-v2.pdf", html)
        self.assertIn('class="b unverified"', html)
        self.assertIn("Not available in ticket data", html)                        # empty sections stated
        self.assertNotIn("<script", html)

    def test_html_escapes_content(self):
        self.a.sections["background"].append(Claim("<script>alert(1)</script> #100", "confirmed", ["#100"]))
        self.a.warnings.append("<b>x</b>")
        html = render_html(self.a)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<b>x</b>", html)

    def test_xlsx_sheets_and_links(self):
        path = self.tmp / "r.xlsx"
        write_xlsx(self.a, path)
        wb = load_workbook(path)
        self.assertEqual(wb.sheetnames, ["Short Summary", "Detailed Analysis", "Related Tickets",
                                         "MR References", "Open Issues", "Other References"])
        related = wb["Related Tickets"]
        self.assertEqual(related.max_row, 1 + 6 + 0)
        self.assertEqual(related["A2"].hyperlink.target, f"{REDMINE}/issues/100")
        mr = {r[1].value: r[1].hyperlink.target if r[1].hyperlink else None for r in wb["MR References"].iter_rows(min_row=2)}
        self.assertEqual(mr["!46"], "https://gitlab.example.com/group/project/-/merge_requests/46")
        self.assertTrue(any(r[0].value == "Blockers" for r in wb["Open Issues"].iter_rows(min_row=2)))
        self.assertEqual(wb["Short Summary"]["A1"].value, "Field")

    def test_xlsx_formula_injection_is_neutralised(self):
        self.a.sections["background"].append(Claim("=HYPERLINK(\"http://evil\")", "assumption", []))
        write_xlsx(self.a, self.tmp / "r.xlsx")
        ws = load_workbook(self.tmp / "r.xlsx")["Detailed Analysis"]
        cell = next(c for row in ws.iter_rows() for c in row if str(c.value).startswith("=HYPERLINK"))
        self.assertEqual(cell.data_type, "s")

    def test_empty_sheet_says_so(self):
        self.a.facts = [f for f in self.a.facts if f.kind not in ("mr", "commit", "branch")]
        write_xlsx(self.a, self.tmp / "r.xlsx")
        self.assertEqual(load_workbook(self.tmp / "r.xlsx")["MR References"]["A2"].value, "None found in ticket data")

    def test_json_roundtrip(self):
        again = Analysis.from_dict(json.loads(json.dumps(self.a.to_dict())))
        self.assertEqual(again, self.a)


if __name__ == "__main__":
    unittest.main()
