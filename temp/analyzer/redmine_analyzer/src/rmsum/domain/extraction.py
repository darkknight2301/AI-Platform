"""Deterministic extraction of references: tickets, MRs, branches, commits, documents, URLs.

Everything here is regex/API driven, so the LLM never has to guess identifiers.
"""

import re
from collections.abc import Iterable
from urllib.parse import unquote
from typing import Optional

from .models import Fact, FactKind, Ticket

URL = re.compile(r"https?://[^\s<>\"'`]+")
TICKET = re.compile(r"(?<![\w&/])#(\d{1,7})\b")
MR = re.compile(r"(?<![\w&])!(\d{1,7})\b|(?:merge[ _]requests?|\bMR)\s*[#:!]?\s*(\d{1,7})\b", re.I)
COMMIT = re.compile(r"(?:\b(?:commit|rev(?:ision)?|sha1?)\b|コミット)[\s:：#`]*([0-9a-f]{7,40})\b", re.I)
BRANCH = re.compile(
    r"(?<![\w/.-])((?:feature|feat|bugfix|hotfix|release|topic)/[\w.\-/]+)"
    r"|(?:\bbranch(?:es)?|ブランチ)\s*(?:[:：=]\s*[`'\"]?|[`'\"])([\w][\w.\-/]*)",
    re.I,
)
DOC_FILE = re.compile(r"[\w\-./\\]+\.(?:pdf|docx?|xlsx?|pptx?|md)\b", re.I)
DOC_URL = re.compile(
    r"\.(?:pdf|docx?|xlsx?|pptx?|md)(?:[?#]|$)|/wiki/|/documents/|confluence|sharepoint|docs\.google", re.I
)
WIKI = re.compile(r"\[\[([^\]|\n]+)(?:\|[^\]\n]*)?\]\]")
SHA = re.compile(r"[0-9a-f]{7,40}")


class _FactCollector:
    """Accumulates facts keyed by (kind, value), merging sources and keeping the first known URL."""

    def __init__(self, redmine_url: str, git_url: str) -> None:
        self._redmine_url = redmine_url
        self._git_url = git_url
        self._found: dict[tuple[FactKind, str], tuple[Optional[str], list[str]]] = {}

    def add(self, kind: FactKind, value: str, tag: str, url: Optional[str] = None) -> None:
        known_url, sources = self._found.setdefault((kind, value), (url, []))
        if url and not known_url:
            self._found[(kind, value)] = (url, sources)
        if tag not in sources:
            sources.append(tag)

    def git(self, path: str) -> Optional[str]:
        """Link into the configured GitLab project, or None when no project URL is configured."""
        return f"{self._git_url}/-/{path}" if self._git_url else None

    def scan(self, text: str, tag: str) -> None:
        """Extract every kind of reference from one text; ``tag`` identifies where the text came from."""
        for match in URL.finditer(text):
            self._classify_url(match.group().rstrip(".,;:)]}>"), tag)
        text = URL.sub(" ", text)  # URLs are handled; do not re-match their fragments below
        for number in TICKET.findall(text):
            if int(number):
                self.add(FactKind.TICKET, f"#{int(number)}", tag, f"{self._redmine_url}/issues/{int(number)}")
        for match in MR.finditer(text):
            number = int(match[1] or match[2])
            self.add(FactKind.MR, f"!{number}", tag, self.git(f"merge_requests/{number}"))
        for match in COMMIT.finditer(text):
            if any(c.isdigit() for c in match[1]):  # filters words like "added"/"defaced"
                self.add(FactKind.COMMIT, match[1][:7].lower(), tag, self.git(f"commit/{match[1].lower()}"))
        for match in BRANCH.finditer(text):
            if name := (match[1] or match[2]).rstrip(".,-/"):
                self.add(FactKind.BRANCH, name, tag, self.git(f"tree/{name}"))
        for match in DOC_FILE.finditer(text):
            self.add(FactKind.DOC, match[0], tag)
        for match in WIKI.finditer(text):
            self.add(FactKind.DOC, f"wiki:{match[1].strip()}", tag)

    def _classify_url(self, url: str, tag: str) -> None:
        if url.startswith(self._redmine_url) and (m := re.search(r"/issues/(\d+)", url)):
            self.add(FactKind.TICKET, f"#{m[1]}", tag, url)
        elif m := re.search(r"/(?:merge_requests|pull)/(\d+)", url):
            self.add(FactKind.MR, f"!{m[1]}", tag, url)
        elif m := re.search(r"/commits?/([0-9a-f]{7,40})\b", url):
            self.add(FactKind.COMMIT, m[1][:7], tag, url)
        elif m := re.search(r"/tree/([^\s?#]+)", url):
            self.add(FactKind.BRANCH, unquote(m[1]), tag, url)
        else:
            self.add(FactKind.DOC if DOC_URL.search(url) else FactKind.URL, url, tag, url)

    def facts(self) -> tuple[Fact, ...]:
        return tuple(Fact(kind, value, url, tuple(src)) for (kind, value), (url, src) in self._found.items())


def extract_facts(tickets: Iterable[Ticket], redmine_url: str, git_url: str = "") -> tuple[Fact, ...]:
    """Collect de-duplicated references from all text of the given tickets.

    Each Fact lists its sources as tags: ``#12`` (subject, description, fields, commits,
    attachments) or ``#12 J5`` (journal 5 of ticket 12). Commits are keyed by their first
    7 characters so short and long SHAs merge. Links to MRs/commits/branches need ``git_url``
    unless the text contains the full URL.
    """
    collector = _FactCollector(redmine_url, git_url)
    for t in tickets:
        base = f"#{t.id}"
        collector.scan(t.subject, base)
        collector.scan(t.description, base)
        for value in t.custom_fields.values():
            collector.scan(value, base)
        for j in t.journals:
            collector.scan(j.notes + "\n" + "; ".join(j.changes), f"{base} J{j.id}")
        for revision, message in t.commits:
            is_sha = bool(SHA.fullmatch(revision))  # Subversion revisions are plain numbers
            collector.add(
                FactKind.COMMIT,
                revision[:7] if is_sha else revision,
                base,
                collector.git(f"commit/{revision}") if is_sha else None,
            )
            collector.scan(message, base)
        for a in t.attachments:
            collector.add(FactKind.ATTACHMENT, a.filename, base, a.url or None)
    return collector.facts()
