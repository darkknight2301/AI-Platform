"""Self-contained HTML report. No JavaScript: expandable sections use <details>."""

import re
from html import escape

from .models import Analysis, Claim, TicketRef
from .prompts import RISK_SECTIONS, SECTIONS

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1f2933;--mut:#6b7785;--line:#dde1e6;--acc:#1d4ed8;
--ok:#15803d;--warn:#b45309;--bad:#b91c1c}
@media(prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1b2129;--fg:#e5e9ee;--mut:#94a0ad;--line:#2d3641;--acc:#7aa2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}a{color:var(--acc)}
h1{font-size:1.5rem;margin:.2rem 0}h2{font-size:1.15rem;margin:1.8rem 0 .6rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 18px;margin:10px 0}
.meta{width:100%;border-collapse:collapse}.meta td{padding:3px 12px 3px 0;vertical-align:top}.meta td:first-child{color:var(--mut);white-space:nowrap}
.scroll{overflow-x:auto}table.t{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}
.t th,.t td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:.92rem}
.t th{background:var(--bg);color:var(--mut);font-weight:600}
.st,.b,.pr,.chip{display:inline-block;padding:0 8px;border-radius:10px;font-size:.78rem;font-weight:600;border:1px solid}
.st.open{color:var(--acc);border-color:var(--acc)}.st.closed{color:var(--ok);border-color:var(--ok)}
.pr{color:var(--mut);border-color:var(--line)}.pr.hi{color:var(--bad);border-color:var(--bad)}
.b.confirmed{color:var(--ok);border-color:var(--ok)}.b.assumption{color:var(--warn);border-color:var(--warn)}
.b.unverified{color:var(--mut);border-color:var(--mut)}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:8px 0;padding:0 16px}
details.risk{border-left:4px solid var(--bad)}summary{cursor:pointer;padding:10px 0;font-weight:600}
summary .n{color:var(--mut);font-weight:400;margin-left:6px}details ul{margin:0 0 12px;padding-left:20px}details li{margin:6px 0}
.src{font-size:.8rem;color:var(--mut)}.na{color:var(--mut);font-style:italic}
.alert{border-left:4px solid var(--warn)}.chip{color:var(--bad);border-color:var(--bad);text-decoration:none;margin-right:6px}
.dev{font-size:.8rem}footer{margin-top:32px;color:var(--mut);font-size:.8rem}
"""


def _link(url: str | None, label: str) -> str:
    """Escaped ``label``, wrapped in an anchor when ``url`` is known."""
    if not url:
        return escape(label)
    return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(label)}</a>'


def _rich(a: Analysis, text: str) -> str:
    """Escape ``text`` and turn #ticket and !MR references into links."""
    mrs = {f.value: f.url for f in a.facts if f.kind == "mr"}

    def sub(m: re.Match) -> str:
        if m[1]:
            return _link(f"{a.meta['redmine_url']}/issues/{m[1]}", m[0])
        return _link(mrs.get(m[0]), m[0])

    return re.sub(r"(?<![\w&/])(?:#(\d+)|!\d+)\b", sub, escape(text))


def _sources(a: Analysis, tags: list[str]) -> str:
    return ", ".join(_link(a.tag_url(s), s) for s in tags)


def _claims(a: Analysis, claims: list[Claim]) -> str:
    """Bullet list of claims with basis badge and source links."""
    if not claims:
        return '<p class="na">Not available in ticket data.</p>'
    items = "".join(
        f'<li><span class="b {c.basis}">{c.basis}</span> {_rich(a, c.text)} '
        f'<span class="src">{_sources(a, c.sources) or "no source"}</span></li>' for c in claims)
    return f"<ul>{items}</ul>"


def _status(t: TicketRef) -> str:
    return f'<span class="st {"closed" if t.closed else "open"}">{escape(t.status or "?")}</span>'


def _priority(t: TicketRef) -> str:
    high = t.priority.lower() in {"high", "urgent", "immediate", "critical", "高", "緊急", "至急"}
    return f'<span class="pr{" hi" if high else ""}">{escape(t.priority or "-")}</span>'


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Table from pre-escaped cell HTML."""
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="t"><tr>{head}</tr>{body}</table></div>'


def _fact_table(a: Analysis, labels: dict[str, str], hint: str = "") -> str:
    """Table of facts of the given kinds, with where each was found."""
    rows = []
    for f in a.facts:
        if f.kind in labels:
            ref = _link(f.url, f.value) + ("" if f.url or not hint else f' <span class="na dev">({hint})</span>')
            rows.append([labels[f.kind], ref, _sources(a, f.sources)])
    return _table(["Type", "Reference", "Found in"], rows) if rows else '<p class="na">None found in ticket data.</p>'


def render_html(a: Analysis) -> str:
    """Render the complete report for one analysis."""
    root = a.tickets[0]
    risks = [(k, len(a.sections.get(k, []))) for k in RISK_SECTIONS if a.sections.get(k)]
    chips = "".join(f'<a class="chip" href="#sec-{k}">{escape(SECTIONS[k][0])}: {n}</a>' for k, n in risks)
    meta = [("Tracker", escape(root.tracker)), ("Status", _status(root)), ("Priority", _priority(root)),
            ("Assignee", escape(root.assignee or "-")), ("Author", escape(root.author)),
            ("Project", escape(root.project)), ("Created", escape(root.created_on)),
            ("Updated", escape(root.updated_on))]
    meta += [(escape(k), escape(v)) for k, v in root.custom_fields.items()]

    sections = "".join(
        f'<details id="sec-{k}"{" open" if a.sections.get(k) else ""}'
        f'{" class=risk" if k in RISK_SECTIONS and a.sections.get(k) else ""}>'
        f'<summary>{escape(title)}<span class="n">{len(a.sections.get(k, []))}</span></summary>'
        f'{_claims(a, a.sections.get(k, []))}</details>' for k, (title, _) in SECTIONS.items())

    tickets = _table(
        ["ID", "Subject", "Tracker", "Status", "Priority", "Assignee", "Updated", "Found via"],
        [[_link(t.url, f"#{t.id}"), escape(t.title), escape(t.tracker), _status(t), _priority(t),
          escape(t.assignee or "-"), escape(t.updated_on[:10]), _rich(a, t.via)] for t in a.tickets])
    skipped = ("<h3>Not analysed</h3><ul>" + "".join(f"<li>{_rich(a, s)}</li>" for s in a.skipped) + "</ul>") if a.skipped else ""
    warnings = ('<div class="card alert"><strong>Warnings</strong><ul>'
                + "".join(f"<li>{escape(w)}</li>" for w in a.warnings) + "</ul></div>") if a.warnings else ""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>#{root.id} {escape(root.title)}</title><style>{CSS}</style></head><body><main>
<h1>{_link(root.url, f"#{root.id}")} {escape(root.title)}</h1>
{f'<div class="src">Original subject: {escape(root.subject)}</div>' if root.subject_en else ""}
<div class="card"><table class="meta">{"".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in meta)}</table></div>
<h2>Short summary</h2><div class="card">{_rich(a, a.short_summary)}</div>
<div class="card">{chips or '<span class="na">No blockers, unresolved questions, contradictions or requirement changes were reported.</span>'}</div>
{warnings}
<h2>Detailed analysis</h2>{sections}
<h2>Related tickets ({len(a.tickets) - 1})</h2>{tickets}{skipped}
<h2>Development references</h2>{_fact_table(a, {"mr": "Merge request", "commit": "Commit", "branch": "Branch"}, "set git.base_url to link")}
<h2>Documents, links and attachments</h2>{_fact_table(a, {"doc": "Document", "url": "URL", "attachment": "Attachment (name only)", "ticket": "Ticket mention"})}
<footer>Generated {escape(a.meta["generated_at"])} with {escape(a.meta["model"])} (prompt v{escape(a.meta["prompt_version"])}, {escape(a.meta["mode"])}).
Facts and identifiers are extracted by code; statements marked "assumption" or "unverified" are not confirmed by the tickets.</footer>
</main></body></html>"""
