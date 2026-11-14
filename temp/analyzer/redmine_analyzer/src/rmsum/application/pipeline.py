"""The LLM passes: per-ticket digests (only for large inputs), consolidation, and the short summary.

Facts come from code; the model only interprets them, and every statement it returns is validated
against those facts (see :mod:`rmsum.domain.validation`).
"""

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias

from ..domain.budget import clip, estimate_tokens
from ..domain.models import Claim, DroppedClaim, Fact, FactKind, Section
from ..domain.sections import SECTION_INFO
from ..domain.validation import ClaimValidator, KnownReferences
from ..errors import ContextOverflowError, InvalidModelOutputError, LLMError
from ..ports import LanguageModel
from .graph import TicketGraph
from .prompts import (
    SECTION_SCHEMA,
    SYSTEM_JSON,
    SYSTEM_TEXT,
    consolidate_prompt,
    repair_prompt,
    summary_prompt,
    ticket_prompt,
)
from .render import RenderedTicket, split_ticket

log = logging.getLogger(__name__)

MIN_BUDGET = 400  # tokens; a floor so tiny context windows still make progress
SAFETY_FACTOR = 0.9  # the token estimate is a heuristic: never plan to use more than 90% of the window
MAX_JSON_ATTEMPTS = 2

_FACT_TITLES = (
    (FactKind.MR, "MERGE REQUESTS"),
    (FactKind.BRANCH, "BRANCHES"),
    (FactKind.COMMIT, "COMMITS"),
    (FactKind.TICKET, "TICKET REFERENCES IN TEXT"),
    (FactKind.DOC, "DOCUMENTS / SPECIFICATIONS"),
    (FactKind.URL, "EXTERNAL URLS"),
    (FactKind.ATTACHMENT, "ATTACHMENT FILENAMES"),
)
# Detail removed first from related (non-root) tickets when their digests do not fit the context.
_DROP_ORDER = (
    Section.DISCUSSION_HISTORY,
    Section.TECHNICAL_APPROACH,
    Section.DEPENDENCIES,
    Section.BACKGROUND,
    Section.IMPLEMENTATION,
    Section.REQUIREMENTS,
)

Digest: TypeAlias = dict[Section, tuple[Claim, ...]]


@dataclass(frozen=True)
class PipelineResult:
    """Output of one pipeline run."""

    sections: Mapping[Section, tuple[Claim, ...]]
    summary: str
    mode: str  # "direct" or "map-reduce"
    warnings: tuple[str, ...]
    dropped: tuple[DroppedClaim, ...]


def facts_text(
    graph: TicketGraph,
    facts: Sequence[Fact],
    only: int | None = None,
    limit: int = 40,
    titles: Mapping[int, str] | None = None,
) -> str:
    """Render the FACTS block of a prompt: all tickets, or only the facts found in ticket ``only``.

    ``titles`` maps ticket ids to display subjects (English when translated).
    """
    titles = titles or {}

    def in_scope(fact: Fact) -> bool:
        return only is None or any(s == f"#{only}" or s.startswith(f"#{only} ") for s in fact.sources)

    lines: list[str] = []
    if only is None:
        lines.append("TICKETS FETCHED:")
        for t in graph.tickets.values():
            lines.append(f"- #{t.id} {titles.get(t.id, t.subject)} [{t.status}] ({graph.via[t.id]})")
        if graph.skipped:
            lines.append("TICKETS NOT FETCHED (their content is unknown):")
            lines += [f"- #{s.ticket_id}: {s.reason} ({s.via})" for s in graph.skipped]
        if graph.edges:
            lines += ["RELATIONS:", *(f"- #{a} {label} #{b}" for a, label, b in graph.edges)]
    for kind, title in _FACT_TITLES:
        items = [f for f in facts if f.kind is kind and in_scope(f)]
        if kind is FactKind.TICKET:  # mentions of fetched tickets are already covered by TICKETS FETCHED / links
            items = [f for f in items if int(f.value[1:]) not in graph.tickets]
            title = "TICKET REFERENCES IN TEXT (not fetched)"
        if not items:
            if only is None:
                lines.append(f"{title}: none found in ticket data")  # say so explicitly: absence is information
            continue
        lines.append(f"{title}:")
        lines += [f"- {f.value} (found in: {', '.join(f.sources)})" for f in items[:limit]]
        if len(items) > limit:
            lines.append(f"- ... and {len(items) - limit} more")
    return "\n".join(lines)


def render_claims(sections: Mapping[Section, Sequence[Claim]]) -> str:
    """Compact text form of claims, used as input to later passes."""
    out: list[str] = []
    for section, claims in sections.items():
        if claims:
            out.append(f"{SECTION_INFO[section].title}:")
            out += [f"- [{c.basis}] {c.text} ({', '.join(c.sources)})" for c in claims]
    return "\n".join(out)


def parse_json_object(raw: str) -> dict:
    """Parse a model reply as a JSON object (tolerates markdown code fences).

    Raises:
        ValueError: not valid JSON, or not an object.
    """
    try:
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value is not an object")
    return data


def _known_references(graph: TicketGraph, facts: Sequence[Fact]) -> KnownReferences:
    """Every identifier the model is allowed to mention."""
    tags = {f"#{t.id}" for t in graph.tickets.values()}
    tags |= {f"#{t.id} J{j.id}" for t in graph.tickets.values() for j in t.journals}
    ids = set(graph.tickets) | {x for a, _, b in graph.edges for x in (a, b)} | {s.ticket_id for s in graph.skipped}
    ids |= {int(f.value[1:]) for f in facts if f.kind is FactKind.TICKET}
    return KnownReferences(
        ticket_ids=frozenset(ids),
        merge_requests=frozenset(f.value for f in facts if f.kind is FactKind.MR),
        commits=frozenset(f.value[:7] for f in facts if f.kind is FactKind.COMMIT),
        tags=frozenset(tags),
    )


class AnalysisPipeline:
    """Runs the LLM passes for one ticket graph."""

    def __init__(self, model: LanguageModel) -> None:
        self._model = model

    def run(
        self,
        graph: TicketGraph,
        facts: Sequence[Fact],
        rendered: Mapping[int, RenderedTicket],
        titles: Mapping[int, str] | None = None,
    ) -> PipelineResult:
        """Analyse the graph. ``titles`` maps ticket ids to display subjects (English when translated).

        Small inputs go straight to consolidation ("direct"); larger ones are condensed ticket by ticket
        first ("map-reduce"). If the model reports a context overflow in direct mode, the run falls back
        to map-reduce instead of failing.

        Raises:
            LLMError: the root ticket (or the consolidation) could not be analysed.
        """
        return _Run(self._model, graph, facts, titles or {}).execute(rendered)


class _Run:
    """State of a single pipeline run (warnings, rejected statements); not reusable."""

    def __init__(
        self, model: LanguageModel, graph: TicketGraph, facts: Sequence[Fact], titles: Mapping[int, str]
    ) -> None:
        self._model = model
        self._graph = graph
        self._facts = facts
        self._titles = titles
        self._validator = ClaimValidator(_known_references(graph, facts))
        self._warnings: list[str] = []
        self._dropped: list[DroppedClaim] = []

    # ----- orchestration -------------------------------------------------------------------------------------------

    def execute(self, rendered: Mapping[int, RenderedTicket]) -> PipelineResult:
        root = self._graph.root_id
        facts_block = facts_text(self._graph, self._facts, titles=self._titles)
        budget = self._budget(SYSTEM_JSON, consolidate_prompt(root, facts_block, ""))
        full_texts = [r.text() for r in rendered.values()]

        sections: Digest | None = None
        mode = "direct"
        if sum(estimate_tokens(t) for t in full_texts) <= budget:
            try:
                log.info("pass 1/2: consolidated analysis (direct)")
                sections = self._consolidate(facts_block, "\n\n".join(full_texts))
            except ContextOverflowError:
                self._warnings.append("The model's context window overflowed in direct mode; analysed ticket by ticket")
        if sections is None:
            mode = "map-reduce"
            sections = self._map_reduce(rendered, facts_block, budget)

        log.info("final pass: short summary")
        summary = self._summary(sections)
        if self._dropped:
            self._warnings.append(
                f"{len(self._dropped)} model statement(s) rejected: "
                "they cited identifiers not present in the ticket data"
            )
        return PipelineResult(sections, summary, mode, tuple(self._warnings), tuple(self._dropped))

    def _map_reduce(self, rendered: Mapping[int, RenderedTicket], facts_block: str, budget: int) -> Digest:
        """Condense each ticket, then consolidate the digests."""
        digests: dict[int, Digest] = {}
        failed: dict[int, str] = {}
        for number, (ticket_id, ticket) in enumerate(rendered.items(), 1):
            log.info("digest %d/%d: ticket #%d", number, len(rendered), ticket_id)
            try:
                digests[ticket_id] = self._digest_with_fallback(ticket)
            except LLMError as exc:
                if ticket_id == self._graph.root_id:
                    raise
                failed[ticket_id] = str(exc)
                self._warnings.append(f"Related ticket #{ticket_id} could not be analysed and was left out: {exc}")
        root = self._graph.root_id
        try:
            return self._consolidate(facts_block, self._fit(digests, failed, budget))
        except ContextOverflowError:
            self._warnings.append(f"Consolidation overflowed the context window; retried with less detail for #{root}")
            return self._consolidate(facts_block, self._fit(digests, failed, int(budget * 0.6)))

    # ----- pass 1: one ticket ----------------------------------------------------------------------------------------

    def _digest_with_fallback(self, ticket: RenderedTicket) -> Digest:
        """Digest a ticket; on context overflow retry once with chunks half as large."""
        try:
            return self._digest(ticket, 1.0)
        except ContextOverflowError:
            log.warning("ticket #%d overflowed the context window; retrying with smaller chunks", ticket.ticket_id)
            return self._digest(ticket, 0.5)

    def _digest(self, ticket: RenderedTicket, scale: float) -> Digest:
        """Analyse one ticket; a long conversation is processed in chronological chunks (none is dropped)."""
        facts = facts_text(self._graph, self._facts, only=ticket.ticket_id)
        free = self._budget(SYSTEM_JSON, ticket_prompt("", facts, " (part 99 of 99 of its history)"))
        parts = split_ticket(ticket, max(int(free * scale), MIN_BUDGET // 2))
        merged: dict[Section, list[Claim]] = {s: [] for s in Section}
        for number, part in enumerate(parts, 1):
            note = f" (part {number} of {len(parts)} of its history)" if len(parts) > 1 else ""
            for section, claims in self._validated(self._ask_json(ticket_prompt(part, facts, note))).items():
                known = {c.text.lower() for c in merged[section]}
                merged[section] += [c for c in claims if c.text.lower() not in known]
        return {section: tuple(claims) for section, claims in merged.items()}

    # ----- pass 2: consolidation -------------------------------------------------------------------------------------

    def _fit(self, digests: Mapping[int, Digest], failed: Mapping[int, str], budget: int) -> str:
        """Render digests within ``budget`` tokens, removing detail from related tickets first (never the root)."""
        working = {tid: dict(d) for tid, d in digests.items()}
        text = self._render_digests(working, failed)
        for section in _DROP_ORDER:
            if estimate_tokens(text) <= budget:
                return text
            for tid, digest in working.items():
                if tid != self._graph.root_id:
                    digest[section] = ()
            message = f"Related tickets: '{SECTION_INFO[section].title}' omitted to fit the context window"
            if message not in self._warnings:
                self._warnings.append(message)
            text = self._render_digests(working, failed)
        if estimate_tokens(text) > budget:
            self._warnings.append("Per-ticket analyses were clipped to fit the context window")
            text = clip(text, budget)
        return text

    def _render_digests(
        self, digests: Mapping[int, Mapping[Section, tuple[Claim, ...]]], failed: Mapping[int, str]
    ) -> str:
        blocks = []
        for tid, ticket in self._graph.tickets.items():
            header = f"=== ANALYSIS OF TICKET #{tid} [{ticket.status}] {self._titles.get(tid, ticket.subject)} ==="
            if tid in failed:
                blocks.append(f"{header}\n(analysis failed; content unknown)")
            else:
                blocks.append(f"{header}\n{render_claims(digests[tid]) or '(nothing reported)'}")
        return "\n\n".join(blocks)

    def _consolidate(self, facts_block: str, material: str) -> Digest:
        prompt = consolidate_prompt(self._graph.root_id, facts_block, material)
        return self._validated(self._ask_json(prompt))

    # ----- pass 3: summary -------------------------------------------------------------------------------------------

    def _summary(self, sections: Mapping[Section, tuple[Claim, ...]]) -> str:
        """Short summary; sentences that name unknown identifiers are removed."""
        prompt = summary_prompt(self._graph.root_id, render_claims(sections))
        completion = self._model.generate(SYSTEM_TEXT, prompt)
        if completion.truncated:
            self._warnings.append("The short summary hit the output limit and may be cut off")
        sentences = [s for s in re.split(r"(?<=[.!?。])\s+", completion.text.strip()) if s]
        kept = []
        for sentence in sentences:
            if reason := self._validator.check_text(sentence):
                self._dropped.append(DroppedClaim("summary", sentence[:300], reason))
            else:
                kept.append(sentence)
        return " ".join(kept[:5]) or "Not available: no verifiable summary could be generated."

    # ----- helpers ---------------------------------------------------------------------------------------------------

    def _budget(self, *fixed_parts: str) -> int:
        """Tokens left for variable input after the fixed prompt parts and the reserved output."""
        used = sum(estimate_tokens(p) for p in fixed_parts)
        free = int(self._model.context_tokens * SAFETY_FACTOR) - self._model.max_output_tokens - used
        return max(free, MIN_BUDGET)

    def _validated(self, raw: dict) -> Digest:
        report = self._validator.validate(raw)
        self._dropped.extend(report.dropped)
        return report.sections

    def _ask_json(self, prompt: str) -> dict:
        """Ask for a JSON object; retry once with a repair hint if the reply is invalid or was cut off."""
        problem = ""
        for _ in range(MAX_JSON_ATTEMPTS):
            text = repair_prompt(prompt, problem) if problem else prompt
            completion = self._model.generate(SYSTEM_JSON, text, SECTION_SCHEMA)
            if completion.truncated:
                problem = "the reply was cut off at the output-token limit"
                log.warning("model reply truncated; retrying with a brevity hint")
                continue
            try:
                return parse_json_object(completion.text)
            except ValueError as exc:
                problem = f"invalid JSON: {exc}"
                log.warning("model returned %s; retrying", problem)
        raise InvalidModelOutputError(f"model output unusable after {MAX_JSON_ATTEMPTS} attempts: {problem}")
