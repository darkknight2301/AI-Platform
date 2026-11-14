"""Plain dataclasses shared by all modules."""

import re
from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class Journal:
    """One comment/update on a ticket. ``notes_en`` is set only when ``notes`` is Japanese."""
    id: int
    author: str
    created_on: str
    notes: str = ""
    changes: list[str] = field(default_factory=list)
    notes_en: str | None = None


@dataclass(slots=True)
class Attachment:
    """Attachment reference. The file itself is never downloaded or read."""
    filename: str
    url: str = ""


@dataclass(slots=True)
class Ticket:
    """A Redmine issue with everything needed for analysis.

    ``relations`` holds ``(other_id, label)`` where the label reads from this ticket's
    point of view, e.g. ``(102, "blocked by")``.
    """
    id: int
    subject: str
    description: str = ""
    tracker: str = ""
    status: str = ""
    closed: bool = False
    priority: str = ""
    author: str = ""
    assignee: str = ""
    project: str = ""
    created_on: str = ""
    updated_on: str = ""
    url: str = ""
    custom_fields: dict[str, str] = field(default_factory=dict)
    journals: list[Journal] = field(default_factory=list)
    parent_id: int | None = None
    children: list[int] = field(default_factory=list)
    relations: list[tuple[int, str]] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    commits: list[tuple[str, str]] = field(default_factory=list)  # (revision, message)
    subject_en: str | None = None
    description_en: str | None = None


@dataclass(slots=True)
class Claim:
    """One statement of the analysis. ``basis`` is confirmed, assumption or unverified."""
    text: str
    basis: str
    sources: list[str] = field(default_factory=list)  # tags like "#12" or "#12 J5"


@dataclass(slots=True)
class Fact:
    """A reference found by code (never by the LLM): ticket, mr, branch, commit, doc, url, attachment."""
    kind: str
    value: str
    url: str | None
    sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TicketRef:
    """Compact ticket description stored in the analysis (no conversation text)."""
    id: int
    subject: str
    subject_en: str | None
    tracker: str
    status: str
    closed: bool
    priority: str
    assignee: str
    author: str
    project: str
    created_on: str
    updated_on: str
    url: str
    via: str
    custom_fields: dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        """English subject when translated, otherwise the original."""
        return self.subject_en or self.subject


@dataclass(slots=True)
class Analysis:
    """Final result for one root ticket; serialisable to JSON and used by all exporters."""
    root_id: int
    short_summary: str
    sections: dict[str, list[Claim]]
    tickets: list[TicketRef]  # root first
    facts: list[Fact]
    skipped: list[str]
    warnings: list[str]
    meta: dict[str, str]

    def to_dict(self) -> dict:
        """Plain-dict form for JSON/cache storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Analysis":
        """Rebuild an Analysis from :meth:`to_dict` output."""
        return cls(
            root_id=d["root_id"], short_summary=d["short_summary"],
            sections={k: [Claim(**c) for c in v] for k, v in d["sections"].items()},
            tickets=[TicketRef(**t) for t in d["tickets"]],
            facts=[Fact(**f) for f in d["facts"]],
            skipped=d["skipped"], warnings=d["warnings"], meta=d["meta"])

    def tag_url(self, tag: str) -> str | None:
        """Redmine URL for a source tag such as ``#12`` or ``#12 J5`` (None if not a tag)."""
        m = re.fullmatch(r"#(\d+)(?: J(\d+))?", tag)
        if not m:
            return None
        url = f"{self.meta['redmine_url']}/issues/{m[1]}"
        return f"{url}#change-{m[2]}" if m[2] else url
