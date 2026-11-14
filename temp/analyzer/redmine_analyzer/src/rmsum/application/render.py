"""Turns tickets into prompt text and splits long conversations into chronological chunks."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..domain.budget import clip, estimate_tokens
from ..domain.language import has_japanese, japanese_paragraphs
from ..domain.models import Ticket


def neutralise(text: str) -> str:
    """Defuse the data-block delimiters inside ticket text so it cannot "close" the block and inject instructions."""
    return text.replace("<<<", "‹‹‹").replace(">>>", "›››")


def translation_key(ticket_id: int, part: str) -> str:
    """Key of a translatable text: ``part`` is ``subject``, ``description`` or ``J<journal id>``."""
    return f"{ticket_id}:{part}"


def japanese_texts(tickets: Iterable[Ticket]) -> dict[str, str]:
    """Every text of the tickets that contains Japanese, keyed for :func:`translation_key`."""
    found: dict[str, str] = {}
    for t in tickets:
        parts = [("subject", t.subject), ("description", t.description)]
        parts += [(f"J{j.id}", j.notes) for j in t.journals]
        for part, text in parts:
            if text and has_japanese(text):
                found[translation_key(t.id, part)] = text
    return found


@dataclass(frozen=True)
class RenderLimits:
    """How ticket text is shaped for the prompt."""

    max_text_chars: int
    include_original: bool


@dataclass(frozen=True)
class RenderedTicket:
    """A ticket as prompt text: full header, one-line title, and one block per journal."""

    ticket_id: int
    header: str
    title: str
    journal_blocks: tuple[str, ...]
    warnings: tuple[str, ...]

    def text(self) -> str:
        """Complete ticket text (header and every comment, oldest first)."""
        return "\n".join([self.header, *self.journal_blocks])


def _body(text: str, english: str | None, include_original: bool) -> str:
    """Prompt form of a text: translation (plus the Japanese paragraphs) or an untranslated marker."""
    if not text:
        return ""
    if english:
        out = f"[translated from Japanese] {english}"
        return f"{out}\n[original Japanese] {japanese_paragraphs(text)}" if include_original else out
    return f"[UNTRANSLATED JAPANESE] {text}" if has_japanese(text) else text


def render_ticket(ticket: Ticket, translations: Mapping[str, str], limits: RenderLimits) -> RenderedTicket:
    """Render a ticket. A single over-long text is clipped (and reported); nothing else is ever dropped."""
    warnings: list[str] = []

    def text(raw: str, part: str, tag: str) -> str:
        full = neutralise(_body(raw, translations.get(translation_key(ticket.id, part)), limits.include_original))
        if len(full) > limits.max_text_chars:
            warnings.append(f"{tag}: text longer than {limits.max_text_chars} characters was clipped")
        return clip(full, limits.max_text_chars)

    english_subject = translations.get(translation_key(ticket.id, "subject"))
    title = f"=== TICKET #{ticket.id} [{ticket.tracker}] {neutralise(english_subject or ticket.subject)} ==="
    lines = [title]
    if english_subject and limits.include_original:
        lines.append(f"(original subject: {neutralise(ticket.subject)})")
    state = {True: " (closed)", False: "", None: ""}[ticket.closed]
    lines.append(
        f"[#{ticket.id}] Status: {ticket.status}{state} | Priority: {ticket.priority} | "
        f"Assignee: {ticket.assignee or '-'} | Author: {ticket.author} | "
        f"Created: {ticket.created_on} | Updated: {ticket.updated_on}"
    )
    links = [f"child of #{ticket.parent_id}"] if ticket.parent_id else []
    links += [f"parent of #{c}" for c in ticket.children] + [f"{r.label} #{r.other_id}" for r in ticket.relations]
    if links:
        lines.append("Links: " + "; ".join(links))
    if ticket.custom_fields:
        lines.append("Custom fields: " + neutralise("; ".join(f"{k}={v}" for k, v in ticket.custom_fields.items())))
    if ticket.attachments:
        names = ", ".join(a.filename for a in ticket.attachments)
        lines.append(f"Attachments (names only, content not read): {neutralise(names)}")
    if ticket.commits:
        lines.append("Repository commits: " + neutralise("; ".join(f"{r[:10]} {m}" for r, m in ticket.commits)))
    description = text(ticket.description, "description", f"#{ticket.id} description") or "(empty)"
    lines.append(f"DESCRIPTION [#{ticket.id}]:\n{description}")
    lines.append("COMMENTS (oldest first):" if ticket.journals else "COMMENTS: none")

    blocks = []
    for j in ticket.journals:
        tag = f"#{ticket.id} J{j.id}"
        block = f"[{tag}] {j.created_on} {j.author}:"
        if j.changes:
            block += "\n  changes: " + neutralise("; ".join(j.changes))
        if j.notes:
            block += "\n" + text(j.notes, f"J{j.id}", tag)
        blocks.append(block)
    return RenderedTicket(ticket.id, "\n".join(lines), title, tuple(blocks), tuple(warnings))


def split_ticket(rendered: RenderedTicket, budget: int) -> list[str]:
    """Split a ticket into chronological chunks of at most ``budget`` tokens (full header only on the first).

    Later chunks start with a one-line title so the model knows which ticket it is reading.
    """
    chunks: list[list[str]] = [[]]
    used = estimate_tokens(rendered.header)
    for block in rendered.journal_blocks:
        block = clip(block, budget)  # characters >= tokens, so a clipped block always fits the budget
        size = estimate_tokens(block)
        if chunks[-1] and used + size > budget:
            chunks.append([])
            used = estimate_tokens(rendered.title)
        chunks[-1].append(block)
        used += size
    return [
        "\n".join([rendered.header if i == 0 else f"{rendered.title} (continued)", *chunk])
        for i, chunk in enumerate(chunks)
    ]
