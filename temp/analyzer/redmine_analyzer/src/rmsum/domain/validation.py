"""Validation of model output against the facts extracted by code.

The model may only cite tickets, journals, merge requests and commits that exist in the ticket
data. Anything else is dropped (and recorded), because a plausible-looking invented identifier
is worse than a missing statement. Validation cannot detect false prose that cites real IDs.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .extraction import MR, TICKET
from .models import Basis, Claim, DroppedClaim, Section

_TAG = re.compile(r"#(\d+)(?:\s*[-:,]?\s*J(\d+))?")
_HEX = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)


@dataclass(frozen=True)
class KnownReferences:
    """Every identifier that legitimately exists in the analysed ticket data."""

    ticket_ids: frozenset[int]
    merge_requests: frozenset[str]  # "!45"
    commits: frozenset[str]  # first 7 characters
    tags: frozenset[str]  # "#12" and "#12 J5"


@dataclass(frozen=True)
class ValidationReport:
    """Validated claims per section plus everything that was rejected."""

    sections: dict[Section, tuple[Claim, ...]]
    dropped: tuple[DroppedClaim, ...]


class ClaimValidator:
    """Checks model statements against :class:`KnownReferences`."""

    def __init__(self, known: KnownReferences) -> None:
        self._known = known

    def check_text(self, text: str) -> str | None:
        """Return why ``text`` must be rejected (it names an unknown identifier), or None if it is acceptable."""
        for number in TICKET.findall(text):
            if int(number) not in self._known.ticket_ids:
                return f"unknown ticket #{int(number)}"
        for match in MR.finditer(text):
            if f"!{int(match[1] or match[2])}" not in self._known.merge_requests:
                return f"unknown merge request !{int(match[1] or match[2])}"
        for word in _HEX.findall(text):
            looks_like_sha = any(c.isdigit() for c in word) and any(c.isalpha() for c in word)
            if looks_like_sha and word[:7].lower() not in self._known.commits:
                return f"unknown commit {word[:7]}"
        return None

    def normalise_tag(self, raw: str) -> str | None:
        """Canonical ``#N`` / ``#N Jm`` form of a model-written source tag, or None if it does not exist."""
        match = _TAG.search(raw)
        if not match:
            return None
        tag = f"#{match[1]} J{match[2]}" if match[2] else f"#{match[1]}"
        return tag if tag in self._known.tags else None

    def _claim(self, item: Any) -> tuple[Claim | None, str]:
        """Validate one raw claim; returns ``(claim, "")`` or ``(None, reason)``."""
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            return None, "not a statement object"
        text = str(item.get("text", "")).strip()
        if not text:
            return None, "empty statement"
        if reason := self.check_text(text):
            return None, reason
        raw_sources = item.get("sources")
        sources: list[str] = []
        for raw in raw_sources if isinstance(raw_sources, list) else []:
            tag = self.normalise_tag(str(raw))
            if tag and tag not in sources:
                sources.append(tag)
        try:
            basis = Basis(item.get("basis"))
        except ValueError:
            basis = Basis.UNVERIFIED
        # "confirmed" without a verifiable source is exactly the failure mode we guard against.
        if basis is Basis.CONFIRMED and not sources:
            basis = Basis.UNVERIFIED
        return Claim(text, basis, tuple(sources)), ""

    def validate(self, raw: Mapping[str, Any]) -> ValidationReport:
        """Validate and de-duplicate every section of a model reply."""
        sections: dict[Section, tuple[Claim, ...]] = {}
        dropped: list[DroppedClaim] = []
        for section in Section:
            items = raw.get(section.value)
            kept: list[Claim] = []
            seen: set[str] = set()
            for item in items if isinstance(items, list) else []:
                claim, reason = self._claim(item)
                if claim is None:
                    text = item.get("text", "") if isinstance(item, dict) else str(item)
                    dropped.append(DroppedClaim(section.value, str(text)[:300], reason))
                elif claim.text.lower() not in seen:
                    seen.add(claim.text.lower())
                    kept.append(claim)
            sections[section] = tuple(kept)
        return ValidationReport(sections, tuple(dropped))
