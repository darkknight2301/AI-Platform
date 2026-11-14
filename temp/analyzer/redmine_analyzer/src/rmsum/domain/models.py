"""Immutable domain models shared by every layer.

Tickets and analysis results are frozen dataclasses with tuple collections, so no layer can
change another layer's data by accident (translation, for instance, never edits a Ticket).
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

from .compat import StrEnum

SCHEMA_VERSION = 2  # bump when the JSON layout of Analysis changes


class Basis(StrEnum):
    """How well a statement is supported."""

    CONFIRMED = "confirmed"  # stated explicitly in a cited ticket text
    ASSUMPTION = "assumption"  # inferred by the model
    UNVERIFIED = "unverified"  # claimed as confirmed, but no valid source could be matched


class FactKind(StrEnum):
    """Kinds of references extracted by code."""

    TICKET = "ticket"
    MR = "mr"
    BRANCH = "branch"
    COMMIT = "commit"
    DOC = "doc"
    URL = "url"
    ATTACHMENT = "attachment"


class Section(StrEnum):
    """Sections of the detailed analysis, in report order."""

    BACKGROUND = "background"
    REQUIREMENTS = "requirements"
    DISCUSSION_HISTORY = "discussion_history"
    TECHNICAL_APPROACH = "technical_approach"
    DECISIONS = "decisions"
    IMPLEMENTATION = "implementation"
    DEPENDENCIES = "dependencies"
    BLOCKERS = "blockers"
    UNRESOLVED_QUESTIONS = "unresolved_questions"
    CONTRADICTIONS = "contradictions"
    REQUIREMENT_CHANGES = "requirement_changes"
    CURRENT_STATUS = "current_status"


@dataclass(frozen=True)
class Journal:
    """One comment/update on a ticket (``changes`` are human-readable field changes)."""

    id: int
    author: str
    created_on: str
    notes: str = ""
    changes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Attachment:
    """Attachment reference. The file itself is never downloaded or read."""

    filename: str
    url: str = ""


@dataclass(frozen=True)
class Relation:
    """A link to another ticket; ``label`` reads from the owning ticket's view, e.g. ``blocked by``."""

    other_id: int
    label: str


@dataclass(frozen=True)
class Ticket:
    """A Redmine issue with everything needed for analysis."""

    id: int
    subject: str
    description: str = ""
    tracker: str = ""
    status: str = ""
    closed: Optional[bool] = None  # None = unknown (status lookup unavailable)
    priority: str = ""
    author: str = ""
    assignee: str = ""
    project: str = ""
    created_on: str = ""
    updated_on: str = ""
    url: str = ""
    custom_fields: Mapping[str, str] = field(default_factory=dict)
    journals: tuple[Journal, ...] = ()
    parent_id: Optional[int] = None
    children: tuple[int, ...] = ()
    relations: tuple[Relation, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    commits: tuple[tuple[str, str], ...] = ()  # (revision, message)


@dataclass(frozen=True)
class Claim:
    """One statement of the analysis with its basis and source tags (``#12`` or ``#12 J5``)."""

    text: str
    basis: Basis
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class DroppedClaim:
    """A model statement rejected by validation, kept for auditability."""

    where: str  # section key, or "summary"
    text: str
    reason: str


@dataclass(frozen=True)
class Fact:
    """A reference found by code (never by the LLM) and the places it was found."""

    kind: FactKind
    value: str
    url: Optional[str]
    sources: tuple[str, ...]


@dataclass(frozen=True)
class SkippedTicket:
    """A related ticket that was seen but not analysed (limit reached or fetch failed)."""

    ticket_id: int
    reason: str
    via: str


@dataclass(frozen=True)
class TicketRef:
    """Compact ticket description stored in the analysis (no conversation text)."""

    id: int
    subject: str
    subject_en: Optional[str]
    tracker: str
    status: str
    closed: Optional[bool]
    priority: str
    assignee: str
    author: str
    project: str
    created_on: str
    updated_on: str
    url: str
    via: str
    custom_fields: Mapping[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str:
        """English subject when translated, otherwise the original."""
        return self.subject_en or self.subject


@dataclass(frozen=True)
class RunStats:
    """Timings and LLM usage of the run that produced an analysis."""

    fetch_seconds: float = 0.0
    translate_seconds: float = 0.0
    llm_seconds: float = 0.0
    total_seconds: float = 0.0
    llm_calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class AnalysisMeta:
    """Provenance of an analysis."""

    model: str
    prompt_version: str
    mode: str  # "direct" or "map-reduce"
    generated_at: str
    redmine_url: str
    fingerprint: str
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class Analysis:
    """Final result for one root ticket; serialisable to JSON and consumed by all report writers."""

    root_id: int
    short_summary: str
    sections: Mapping[Section, tuple[Claim, ...]]
    tickets: tuple[TicketRef, ...]  # root first, then related tickets in discovery order
    facts: tuple[Fact, ...]
    skipped: tuple[SkippedTicket, ...]
    warnings: tuple[str, ...]
    dropped: tuple[DroppedClaim, ...]
    meta: AnalysisMeta
    stats: RunStats

    @property
    def root(self) -> TicketRef:
        return self.tickets[0]

    def claims(self, section: Section) -> tuple[Claim, ...]:
        """Claims of a section (empty tuple when the model reported nothing)."""
        return self.sections.get(section, ())

    def facts_of(self, *kinds: FactKind) -> list[Fact]:
        """Facts of the given kinds, in extraction order."""
        return [f for f in self.facts if f.kind in kinds]

    def tag_url(self, tag: str) -> Optional[str]:
        """Redmine URL for a source tag such as ``#12`` or ``#12 J5`` (None if ``tag`` is not a tag)."""
        match = re.fullmatch(r"#(\d+)(?: J(\d+))?", tag)
        if not match:
            return None
        url = f"{self.meta.redmine_url}/issues/{match[1]}"
        return f"{url}#change-{match[2]}" if match[2] else url

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict form for JSON output."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Analysis":
        """Rebuild an Analysis from :meth:`to_dict` output.

        Raises:
            KeyError, TypeError, ValueError: the data is not a current-schema analysis.
        """
        if data["meta"]["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {data['meta']['schema_version']}")

        def ref(t: Mapping[str, Any]) -> TicketRef:
            return TicketRef(**t)

        return cls(
            root_id=data["root_id"],
            short_summary=data["short_summary"],
            sections={
                Section(k): tuple(Claim(c["text"], Basis(c["basis"]), tuple(c["sources"])) for c in v)
                for k, v in data["sections"].items()
            },
            tickets=tuple(ref(t) for t in data["tickets"]),
            facts=tuple(Fact(FactKind(f["kind"]), f["value"], f["url"], tuple(f["sources"])) for f in data["facts"]),
            skipped=tuple(SkippedTicket(**s) for s in data["skipped"]),
            warnings=tuple(data["warnings"]),
            dropped=tuple(DroppedClaim(**d) for d in data["dropped"]),
            meta=AnalysisMeta(**data["meta"]),
            stats=RunStats(**data["stats"]),
        )
