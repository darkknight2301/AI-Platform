"""Excel export: Short Summary, Detailed Analysis, Related Tickets, MR References, Open Issues, Other References."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .models import Analysis
from .prompts import RISK_SECTIONS, SECTIONS

# A cell is plain text, or (text, url) for a hyperlink.
type Cell = str | int | tuple[str, str | None]


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list[Cell]], widths: list[int]) -> None:
    """Add a formatted sheet (bold header, wrapped text, filter, frozen header row)."""
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows or [["None found in ticket data"] + [""] * (len(headers) - 1)]:
        ws.append([c[0] if isinstance(c, tuple) else c for c in row])
        for cell, src in zip(ws[ws.max_row], row):
            if isinstance(cell.value, str):
                cell.data_type = "s"  # never let text starting with "=" become a formula
            if isinstance(src, tuple) and src[1]:
                cell.hyperlink = src[1]
                cell.style = "Hyperlink"
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _found(a: Analysis, sources: list[str]) -> Cell:
    """Sources as text; the first one is the hyperlink."""
    return (", ".join(sources), a.tag_url(sources[0]) if sources else None)


def write_xlsx(a: Analysis, path: str | Path) -> None:
    """Write the six-sheet workbook for ``a`` to ``path``."""
    root = a.tickets[0]
    wb = Workbook()
    wb.remove(wb.active)

    rows: list[list[Cell]] = [
        ["Ticket", (f"#{root.id}", root.url)], ["Subject", root.title], ["Original subject", root.subject],
        ["Status", root.status], ["Priority", root.priority], ["Assignee", root.assignee], ["Author", root.author],
        ["Updated", root.updated_on], ["Tickets analysed", len(a.tickets)], ["Model", a.meta["model"]],
        ["Generated", a.meta["generated_at"]], ["Short summary", a.short_summary],
    ]
    rows += [[f"Warning {i}", w] for i, w in enumerate(a.warnings, 1)]
    _sheet(wb, "Short Summary", ["Field", "Value"], rows, [22, 110])

    rows = [[title, c.text, c.basis, ", ".join(c.sources), (c.sources[0], a.tag_url(c.sources[0])) if c.sources else ""]
            for key, (title, _) in SECTIONS.items() for c in a.sections.get(key, [])]
    _sheet(wb, "Detailed Analysis", ["Section", "Statement", "Basis", "Sources", "Link"], rows, [26, 90, 13, 24, 14])

    rows = [[(f"#{t.id}", t.url), t.title, t.tracker, t.status, t.priority, t.assignee, t.updated_on[:10], t.via]
            for t in a.tickets]
    for s in a.skipped:
        tid, _, why = s.partition(": ")
        rows.append([tid, "", "", "Not analysed", "", "", "", why])
    _sheet(wb, "Related Tickets", ["ID", "Subject", "Tracker", "Status", "Priority", "Assignee", "Updated", "Found via"],
           rows, [10, 50, 12, 16, 12, 18, 12, 48])

    kinds = {"mr": "Merge request", "commit": "Commit", "branch": "Branch"}
    rows = [[kinds[f.kind], (f.value, f.url), _found(a, f.sources)] for f in a.facts if f.kind in kinds]
    _sheet(wb, "MR References", ["Type", "Reference", "Found in"], rows, [18, 60, 30])

    rows = [[SECTIONS[k][0], c.text, c.basis, ", ".join(c.sources)] for k in RISK_SECTIONS for c in a.sections.get(k, [])]
    _sheet(wb, "Open Issues", ["Type", "Statement", "Basis", "Sources"], rows, [30, 90, 13, 24])

    kinds = {"doc": "Document", "url": "URL", "attachment": "Attachment (name only)", "ticket": "Ticket mention"}
    rows = [[kinds[f.kind], (f.value, f.url), _found(a, f.sources)] for f in a.facts if f.kind in kinds]
    _sheet(wb, "Other References", ["Type", "Reference", "Found in"], rows, [24, 70, 30])
    wb.save(path)
