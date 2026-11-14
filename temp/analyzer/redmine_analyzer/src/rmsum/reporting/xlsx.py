"""Excel report: Short Summary, Detailed Analysis, Related Tickets, MR References, Open Issues, Other References."""

from pathlib import Path
from typing import TypeAlias

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ..domain.models import Analysis, FactKind
from ..domain.sections import RISK_SECTIONS, SECTION_INFO

# A cell is plain text/number, or (text, url) for a hyperlink.
Cell: TypeAlias = str | int | float | tuple[str, str | None]

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
NO_DATA = "None found in ticket data"


def add_sheet(wb: Workbook, title: str, headers: list[str], rows: list[list[Cell]], widths: list[int]) -> None:
    """Add a formatted sheet (bold header, wrapped text, filter, frozen header row)."""
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in rows or [[NO_DATA] + [""] * (len(headers) - 1)]:
        ws.append([c[0] if isinstance(c, tuple) else c for c in row])
        for cell, source in zip(ws[ws.max_row], row):
            if isinstance(cell.value, str):
                cell.data_type = "s"  # text starting with "=" must never become a formula (injection)
            if isinstance(source, tuple) and source[1]:
                cell.hyperlink = source[1]
                cell.style = "Hyperlink"
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for index, width in enumerate(widths):
        ws.column_dimensions[chr(65 + index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _found_in(a: Analysis, sources: tuple[str, ...]) -> Cell:
    """Sources as text; the first one carries the hyperlink."""
    return (", ".join(sources), a.tag_url(sources[0]) if sources else None)


def build_workbook(a: Analysis) -> Workbook:
    """Create the six-sheet workbook for ``a``."""
    root = a.root
    wb = Workbook()
    wb.remove(wb.active)

    rows: list[list[Cell]] = [
        ["Ticket", (f"#{root.id}", root.url)],
        ["Subject", root.title],
        ["Original subject", root.subject],
        ["Status", root.status],
        ["Priority", root.priority],
        ["Assignee", root.assignee],
        ["Author", root.author],
        ["Updated", root.updated_on],
        ["Tickets analysed", len(a.tickets)],
        ["Model", a.meta.model],
        ["Generated", a.meta.generated_at],
        ["Short summary", a.short_summary],
    ]
    rows += [[f"Warning {i}", w] for i, w in enumerate(a.warnings, 1)]
    add_sheet(wb, "Short Summary", ["Field", "Value"], rows, [22, 110])

    rows = [
        [
            info.title,
            c.text,
            c.basis.value,
            ", ".join(c.sources),
            (c.sources[0], a.tag_url(c.sources[0])) if c.sources else "",
        ]
        for section, info in SECTION_INFO.items()
        for c in a.claims(section)
    ]
    add_sheet(wb, "Detailed Analysis", ["Section", "Statement", "Basis", "Sources", "Link"], rows, [26, 90, 13, 24, 14])

    rows = [
        [(f"#{t.id}", t.url), t.title, t.tracker, t.status, t.priority, t.assignee, t.updated_on[:10], t.via]
        for t in a.tickets
    ]
    rows += [[f"#{s.ticket_id}", "", "", "Not analysed", "", "", "", f"{s.reason} ({s.via})"] for s in a.skipped]
    headers = ["ID", "Subject", "Tracker", "Status", "Priority", "Assignee", "Updated", "Found via"]
    add_sheet(wb, "Related Tickets", headers, rows, [10, 50, 12, 16, 12, 18, 12, 48])

    development = {FactKind.MR: "Merge request", FactKind.COMMIT: "Commit", FactKind.BRANCH: "Branch"}
    rows = [[development[f.kind], (f.value, f.url), _found_in(a, f.sources)] for f in a.facts_of(*development)]
    add_sheet(wb, "MR References", ["Type", "Reference", "Found in"], rows, [18, 60, 30])

    rows = [
        [SECTION_INFO[s].title, c.text, c.basis.value, ", ".join(c.sources)] for s in RISK_SECTIONS for c in a.claims(s)
    ]
    add_sheet(wb, "Open Issues", ["Type", "Statement", "Basis", "Sources"], rows, [30, 90, 13, 24])

    other = {
        FactKind.DOC: "Document",
        FactKind.URL: "URL",
        FactKind.ATTACHMENT: "Attachment (name only)",
        FactKind.TICKET: "Ticket mention",
    }
    rows = [[other[f.kind], (f.value, f.url), _found_in(a, f.sources)] for f in a.facts_of(*other)]
    add_sheet(wb, "Other References", ["Type", "Reference", "Found in"], rows, [24, 70, 30])
    return wb


def write_xlsx(a: Analysis, path: Path) -> None:
    """Write the workbook to ``path``."""
    build_workbook(a).save(path)
