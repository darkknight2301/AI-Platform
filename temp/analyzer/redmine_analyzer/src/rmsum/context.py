"""Token budgeting and rendering of tickets into prompt text."""

import math
import re
from dataclasses import dataclass, field

from .models import Ticket
from .translate import has_japanese


def estimate_tokens(text: str) -> int:
    """Conservative token estimate without a tokenizer: ~3.2 ASCII chars, or 1 non-ASCII char, per token."""
    ascii_chars = len(text.encode("ascii", "ignore"))
    return math.ceil(ascii_chars / 3.2 + (len(text) - ascii_chars))


def clip(text: str, limit: int) -> str:
    """Shorten ``text`` to about ``limit`` chars, keeping head and tail and marking the cut."""
    if len(text) <= limit:
        return text
    keep = max(limit - 60, 0) // 2
    if not keep:
        return text[:limit]
    return f"{text[:keep]}\n[... {len(text) - 2 * keep} characters omitted ...]\n{text[-keep:]}"


def _body(text: str, en: str | None, include_original: bool) -> str:
    """Prompt form of a text: translation (plus optional original) or an untranslated marker."""
    if not text:
        return ""
    if en:
        out = f"[translated from Japanese] {en}"
        if not include_original:
            return out
        japanese = "\n\n".join(p for p in re.split(r"\n\s*\n", text) if has_japanese(p))
        return f"{out}\n[original Japanese] {japanese}"
    return f"[UNTRANSLATED JAPANESE] {text}" if has_japanese(text) else text


@dataclass(slots=True)
class Rendered:
    """A ticket as prompt text: full header, short title line, and one block per journal."""
    header: str
    title: str
    journals: list[str]
    warnings: list[str] = field(default_factory=list)

    def text(self) -> str:
        """Complete ticket text (header and every comment, oldest first)."""
        return "\n".join([self.header, *self.journals])


def render_ticket(t: Ticket, max_chars: int, include_original: bool) -> Rendered:
    """Render a ticket. Over-long single texts are clipped (and reported); nothing else is dropped."""
    warnings: list[str] = []

    def text(raw: str, en: str | None, tag: str) -> str:
        full = _body(raw, en, include_original)
        if len(full) > max_chars:
            warnings.append(f"{tag}: text longer than {max_chars} characters was clipped")
        return clip(full, max_chars)

    subject = t.subject_en or t.subject
    title = f"=== TICKET #{t.id} [{t.tracker}] {subject} ==="
    lines = [title]
    if t.subject_en and include_original:
        lines.append(f"(original subject: {t.subject})")
    lines.append(f"[#{t.id}] Status: {t.status}{' (closed)' if t.closed else ''} | Priority: {t.priority} | "
                 f"Assignee: {t.assignee or '-'} | Author: {t.author} | Created: {t.created_on} | Updated: {t.updated_on}")
    links = [f"child of #{t.parent_id}"] if t.parent_id else []
    links += [f"parent of #{c}" for c in t.children] + [f"{label} #{o}" for o, label in t.relations]
    if links:
        lines.append("Links: " + "; ".join(links))
    if t.custom_fields:
        lines.append("Custom fields: " + "; ".join(f"{k}={v}" for k, v in t.custom_fields.items()))
    if t.attachments:
        lines.append("Attachments (names only, content not read): " + ", ".join(a.filename for a in t.attachments))
    if t.commits:
        lines.append("Repository commits: " + "; ".join(f"{r[:10]} {m}" for r, m in t.commits))
    lines.append(f"DESCRIPTION [#{t.id}]:\n{text(t.description, t.description_en, f'#{t.id} description') or '(empty)'}")
    lines.append("COMMENTS (oldest first):" if t.journals else "COMMENTS: none")

    journals = []
    for j in t.journals:
        tag = f"#{t.id} J{j.id}"
        block = f"[{tag}] {j.created_on} {j.author}:"
        if j.changes:
            block += "\n  changes: " + "; ".join(j.changes)
        if j.notes:
            block += "\n" + text(j.notes, j.notes_en, tag)
        journals.append(block)
    return Rendered("\n".join(lines), title, journals, warnings)


def split_ticket(r: Rendered, budget: int) -> list[str]:
    """Split a ticket into chronological chunks of at most ``budget`` tokens (header on the first).

    Later chunks start with a one-line title so the model knows which ticket it is reading.
    """
    chunks: list[list[str]] = [[]]
    used = estimate_tokens(r.header)
    for line in r.journals:
        line = clip(line, budget)  # chars >= tokens, so a clipped line always fits
        n = estimate_tokens(line)
        if chunks[-1] and used + n > budget:
            chunks.append([])
            used = estimate_tokens(r.title)
        chunks[-1].append(line)
        used += n
    return [("\n".join([r.header if i == 0 else r.title + " (continued)", *c])) for i, c in enumerate(chunks)]
