"""Deterministic extraction of references: tickets, MRs, branches, commits, documents, URLs.

Everything here is regex/API driven, so the LLM never has to guess identifiers.
"""

import re
from collections.abc import Iterable
from urllib.parse import unquote

from .models import Fact, Ticket

URL = re.compile(r"https?://[^\s<>\"'`]+")
TICKET = re.compile(r"(?<![\w&/])#(\d{1,7})\b")
MR = re.compile(r"(?<![\w&])!(\d{1,7})\b|(?:merge[ _]requests?|\bMR)\s*[#:!]?\s*(\d{1,7})\b", re.I)
COMMIT = re.compile(r"(?:\b(?:commit|rev(?:ision)?|sha1?)\b|コミット)[\s:：#`]*([0-9a-f]{7,40})\b", re.I)
BRANCH = re.compile(
    r"(?<![\w/.-])((?:feature|feat|bugfix|hotfix|release|topic)/[\w.\-/]+)"
    r"|(?:\bbranch(?:es)?|ブランチ)\s*(?:[:：=]\s*[`'\"]?|[`'\"])([\w][\w.\-/]*)", re.I)
DOC_FILE = re.compile(r"[\w\-./\\]+\.(?:pdf|docx?|xlsx?|pptx?|md)\b", re.I)
DOC_URL = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|md)(?:[?#]|$)|/wiki/|/documents/|confluence|sharepoint|docs\.google", re.I)
WIKI = re.compile(r"\[\[([^\]|\n]+)(?:\|[^\]\n]*)?\]\]")
SHA = re.compile(r"[0-9a-f]{7,40}")


def extract_facts(tickets: Iterable[Ticket], redmine_url: str, git_url: str = "") -> list[Fact]:
    """Collect de-duplicated references from all text of the given tickets.

    Each Fact lists its sources as tags: ``#12`` (subject, description, fields, commits,
    attachments) or ``#12 J5`` (journal 5 of ticket 12). Commits are keyed by their first
    7 characters so short and long SHAs merge. Links to MRs/commits/branches need ``git_url``
    unless the text contains the full URL.
    """
    found: dict[tuple[str, str], Fact] = {}

    def add(kind: str, value: str, tag: str, url: str | None = None) -> None:
        f = found.setdefault((kind, value), Fact(kind, value, url, []))
        f.url = f.url or url
        if tag not in f.sources:
            f.sources.append(tag)

    def git(path: str) -> str | None:
        return f"{git_url}/-/{path}" if git_url else None

    def scan(text: str, tag: str) -> None:
        for m in URL.finditer(text):
            url = m.group().rstrip(".,;:)]}>")
            if url.startswith(redmine_url) and (i := re.search(r"/issues/(\d+)", url)):
                add("ticket", f"#{i[1]}", tag, url)
            elif i := re.search(r"/(?:merge_requests|pull)/(\d+)", url):
                add("mr", f"!{i[1]}", tag, url)
            elif i := re.search(r"/commits?/([0-9a-f]{7,40})\b", url):
                add("commit", i[1][:7], tag, url)
            elif i := re.search(r"/tree/([^\s?#]+)", url):
                add("branch", unquote(i[1]), tag, url)
            else:
                add("doc" if DOC_URL.search(url) else "url", url, tag, url)
        text = URL.sub(" ", text)  # do not re-match fragments of URLs below
        for n in TICKET.findall(text):
            if int(n):
                add("ticket", f"#{int(n)}", tag, f"{redmine_url}/issues/{int(n)}")
        for m in MR.finditer(text):
            n = int(m[1] or m[2])
            add("mr", f"!{n}", tag, git(f"merge_requests/{n}"))
        for m in COMMIT.finditer(text):
            if any(c.isdigit() for c in m[1]):
                add("commit", m[1][:7].lower(), tag, git(f"commit/{m[1].lower()}"))
        for m in BRANCH.finditer(text):
            if name := (m[1] or m[2]).rstrip(".,-/"):
                add("branch", name, tag, git(f"tree/{name}"))
        for m in DOC_FILE.finditer(text):
            add("doc", m[0], tag)
        for m in WIKI.finditer(text):
            add("doc", f"wiki:{m[1].strip()}", tag)

    for t in tickets:
        base = f"#{t.id}"
        scan(t.subject, base)
        scan(t.description, base)
        for value in t.custom_fields.values():
            scan(value, base)
        for j in t.journals:
            scan(j.notes + "\n" + "; ".join(j.changes), f"{base} J{j.id}")
        for rev, msg in t.commits:
            is_sha = bool(SHA.fullmatch(rev))
            add("commit", rev[:7] if is_sha else rev, base, git(f"commit/{rev}") if is_sha else None)
            scan(msg, base)
        for a in t.attachments:
            add("attachment", a.filename, base, a.url or None)
    return list(found.values())
