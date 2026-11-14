"""Orchestrator: graph -> translation -> facts -> LLM passes -> validated Analysis.

Facts come from code; the LLM only interprets them. Every claim it returns is validated:
unknown source tags are removed, and claims naming ticket/MR/commit identifiers that do
not exist in the extracted data are dropped.
"""

import hashlib
import json
import logging
import re
from datetime import UTC, datetime

from .cache import Cache
from .config import Config
from .context import Rendered, clip, estimate_tokens, render_ticket, split_ticket
from .extract import MR, TICKET, extract_facts
from .graph import TicketGraph, build_graph
from .llm import LLMBackend, LLMError
from .models import Analysis, Claim, Fact, Ticket, TicketRef
from .prompts import (PROMPT_VERSION, SECTION_SCHEMA, SECTIONS, SYSTEM_JSON, SYSTEM_TEXT,
                      consolidate_prompt, repair_prompt, summary_prompt, ticket_prompt)
from .redmine import RedmineClient
from .translate import Translator, has_japanese, translate_ticket

log = logging.getLogger(__name__)

HEX = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)
TAG = re.compile(r"#(\d+)(?:\s*[-:,]?\s*J(\d+))?")
MIN_BUDGET = 400  # tokens; floor so tiny context windows still make progress
KINDS = (("mr", "MERGE REQUESTS"), ("branch", "BRANCHES"), ("commit", "COMMITS"),
         ("ticket", "TICKET REFERENCES IN TEXT"), ("doc", "DOCUMENTS / SPECIFICATIONS"),
         ("url", "EXTERNAL URLS"), ("attachment", "ATTACHMENT FILENAMES"))
# Detail removed first from related (non-root) tickets when digests do not fit the context.
DROP_ORDER = ("discussion_history", "technical_approach", "dependencies", "background",
              "implementation", "requirements")


def facts_text(g: TicketGraph, facts: list[Fact], only: int | None = None, limit: int = 40) -> str:
    """Render the FACTS block of a prompt (all tickets, or only those found in ticket ``only``)."""
    def mine(f: Fact) -> bool:
        return only is None or any(s == f"#{only}" or s.startswith(f"#{only} ") for s in f.sources)

    lines: list[str] = []
    if only is None:
        lines.append("TICKETS FETCHED:")
        lines += [f"- #{t.id} {t.subject_en or t.subject} [{t.status}] ({g.via[t.id]})" for t in g.tickets.values()]
        if g.skipped:
            lines += ["TICKETS NOT FETCHED (their content is unknown):", *(f"- {s}" for s in g.skipped)]
        if g.edges:
            lines += ["RELATIONS:", *(f"- #{a} {label} #{b}" for a, label, b in g.edges)]
    for kind, title in KINDS:
        items = [f for f in facts if f.kind == kind and mine(f)]
        if kind == "ticket":  # mentions of fetched tickets are already in TICKETS FETCHED / links
            items = [f for f in items if int(f.value[1:]) not in g.tickets]
            title = "TICKET REFERENCES IN TEXT (not fetched)"
        if not items:
            if only is None:
                lines.append(f"{title}: none found in ticket data")
            continue
        lines.append(f"{title}:")
        lines += [f"- {f.value} (found in: {', '.join(f.sources)})" for f in items[:limit]]
        if len(items) > limit:
            lines.append(f"- ... and {len(items) - limit} more")
    return "\n".join(lines)


def render_claims(sections: dict[str, list[Claim]]) -> str:
    """Compact text form of claims, used as input to later passes."""
    out = []
    for key, claims in sections.items():
        if claims:
            out.append(f"{SECTIONS[key][0]}:")
            out += [f"- [{c.basis}] {c.text} ({', '.join(c.sources)})" for c in claims]
    return "\n".join(out)


def _parse_json(raw: str) -> dict:
    """Parse a model reply as a JSON object (tolerates markdown code fences)."""
    try:
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
    except json.JSONDecodeError as e:
        raise ValueError(str(e)) from e
    if not isinstance(data, dict):
        raise ValueError("top-level JSON value is not an object")
    return data


def _fingerprint(g: TicketGraph, model: str) -> str:
    """Hash of everything that makes a cached analysis stale: ticket versions, prompts, model."""
    state = [sorted((t.id, t.updated_on) for t in g.tickets.values()), PROMPT_VERSION, model, sorted(g.skipped)]
    return hashlib.sha256(json.dumps(state).encode()).hexdigest()


class _Pipeline:
    """Holds the state shared by the LLM passes of one analysis run."""

    def __init__(self, llm: LLMBackend, g: TicketGraph, facts: list[Fact]):
        self.llm, self.g, self.facts = llm, g, facts
        self.warnings: list[str] = []
        self.dropped = 0
        self.tags = {f"#{t.id}" for t in g.tickets.values()}
        self.tags |= {f"#{t.id} J{j.id}" for t in g.tickets.values() for j in t.journals}
        self.ids = set(g.tickets) | {x for a, _, b in g.edges for x in (a, b)}
        self.ids |= {int(f.value[1:]) for f in facts if f.kind == "ticket"}
        self.mrs = {f.value for f in facts if f.kind == "mr"}
        self.commits = {f.value[:7] for f in facts if f.kind == "commit"}

    def _budget(self, *fixed: str) -> int:
        """Tokens left for variable input after the fixed prompt parts and the output reserve."""
        used = sum(estimate_tokens(s) for s in fixed)
        return max(int(self.llm.num_ctx * 0.9) - self.llm.max_output - used, MIN_BUDGET)

    def _text_ok(self, text: str) -> bool:
        """False if ``text`` names a ticket, MR or commit that is not in the extracted data."""
        if any(int(n) not in self.ids for n in TICKET.findall(text)):
            return False
        if any(f"!{int(m[1] or m[2])}" not in self.mrs for m in MR.finditer(text)):
            return False
        return all(h[:7].lower() in self.commits for h in HEX.findall(text)
                   if any(c.isdigit() for c in h) and any(c.isalpha() for c in h))

    def _claim(self, item) -> Claim | None:
        """Validate one model-produced claim; None if it must be dropped."""
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            return None
        text = str(item.get("text", "")).strip()
        if not text or not self._text_ok(text):
            return None
        raw = item.get("sources")
        sources: list[str] = []
        for s in raw if isinstance(raw, list) else []:
            if (m := TAG.search(str(s))):
                tag = f"#{m[1]} J{m[2]}" if m[2] else f"#{m[1]}"
                if tag in self.tags and tag not in sources:
                    sources.append(tag)
        basis = item.get("basis")
        if basis not in ("confirmed", "assumption") or (basis == "confirmed" and not sources):
            basis = "unverified"
        return Claim(text, basis, sources)

    def _claims(self, raw: dict) -> dict[str, list[Claim]]:
        """Validate and de-duplicate all sections of a model reply."""
        out: dict[str, list[Claim]] = {}
        for key in SECTIONS:
            items = raw.get(key)
            seen: set[str] = set()
            out[key] = []
            for item in items if isinstance(items, list) else []:
                claim = self._claim(item)
                if claim is None:
                    self.dropped += 1
                elif claim.text.lower() not in seen:
                    seen.add(claim.text.lower())
                    out[key].append(claim)
        return out

    def _json(self, prompt: str) -> dict:
        """Ask for JSON; on invalid output retry once with a repair hint."""
        err = ""
        for _ in range(2):
            raw = self.llm.generate(SYSTEM_JSON, repair_prompt(prompt, err) if err else prompt, SECTION_SCHEMA)
            try:
                return _parse_json(raw)
            except ValueError as e:
                err = str(e)
                log.warning("model returned invalid JSON (%s)", err)
        raise LLMError(f"model returned invalid JSON twice: {err}")

    def _digest(self, r: Rendered, tid: int) -> dict[str, list[Claim]]:
        """Pass 1: analyse one ticket; long conversations are processed in chronological chunks."""
        facts = facts_text(self.g, self.facts, only=tid)
        budget = self._budget(SYSTEM_JSON, ticket_prompt("", facts, " (part 99 of 99 of its history)"))
        parts = split_ticket(r, budget)
        merged: dict[str, list[Claim]] = {k: [] for k in SECTIONS}
        for i, part in enumerate(parts, 1):
            note = f" (part {i} of {len(parts)} of its history)" if len(parts) > 1 else ""
            for key, claims in self._claims(self._json(ticket_prompt(part, facts, note))).items():
                merged[key] += [c for c in claims if c.text.lower() not in {m.text.lower() for m in merged[key]}]
        return merged

    def _render_digests(self, digests: dict[int, dict[str, list[Claim]]]) -> str:
        """Text form of per-ticket digests for the consolidation prompt."""
        blocks = []
        for tid, sections in digests.items():
            t = self.g.tickets[tid]
            blocks.append(f"=== ANALYSIS OF TICKET #{tid} [{t.status}] {t.subject_en or t.subject} ===\n"
                          + (render_claims(sections) or "(nothing reported)"))
        return "\n\n".join(blocks)

    def _fit(self, digests: dict[int, dict[str, list[Claim]]], budget: int) -> str:
        """Render digests within ``budget``, dropping detail from related tickets first (root is kept)."""
        text = self._render_digests(digests)
        for key in DROP_ORDER:
            if estimate_tokens(text) <= budget:
                return text
            for tid, sections in digests.items():
                if tid != self.g.root_id:
                    sections[key] = []
            self.warnings.append(f"Related tickets: '{SECTIONS[key][0]}' omitted to fit the context window")
            text = self._render_digests(digests)
        if estimate_tokens(text) > budget:
            self.warnings.append("Per-ticket analyses were clipped to fit the context window")
            text = clip(text, budget)
        return text

    def _summary(self, sections: dict[str, list[Claim]]) -> str:
        """Pass 3: short summary; sentences naming unknown identifiers are removed."""
        raw = self.llm.generate(SYSTEM_TEXT, summary_prompt(self.g.root_id, render_claims(sections)))
        sentences = [s for s in re.split(r"(?<=[.!?。])\s+", raw.strip()) if s]
        kept = [s for s in sentences if self._text_ok(s)]
        if len(kept) < len(sentences):
            self.warnings.append(f"{len(sentences) - len(kept)} summary sentence(s) removed: unknown identifiers")
        return " ".join(kept[:5]) or "Not available: no verifiable summary could be generated."

    def run(self, rendered: dict[int, Rendered]) -> tuple[dict[str, list[Claim]], str, str]:
        """Run all passes. Returns ``(sections, short_summary, mode)``.

        Small ticket sets go straight to consolidation ("direct"); larger ones are first
        condensed per ticket ("map-reduce").
        """
        root = self.g.root_id
        facts = facts_text(self.g, self.facts)
        budget = self._budget(SYSTEM_JSON, consolidate_prompt(root, facts, ""))
        full = {tid: r.text() for tid, r in rendered.items()}
        if sum(map(estimate_tokens, full.values())) <= budget:
            mode, material = "direct", "\n\n".join(full.values())
        else:
            mode = "map-reduce"
            digests = {}
            for n, (tid, r) in enumerate(rendered.items(), 1):
                log.info("pass 1: ticket #%d (%d/%d)", tid, n, len(rendered))
                digests[tid] = self._digest(r, tid)
            material = self._fit(digests, budget)
        log.info("pass 2: consolidated analysis (%s)", mode)
        sections = self._claims(self._json(consolidate_prompt(root, facts, material)))
        log.info("pass 3: short summary")
        summary = self._summary(sections)
        if self.dropped:
            self.warnings.append(f"{self.dropped} model statement(s) dropped: they cited identifiers not present in the ticket data")
        return sections, summary, mode


def _ref(t: Ticket, via: str) -> TicketRef:
    """Compact reference stored in the Analysis."""
    return TicketRef(t.id, t.subject, t.subject_en, t.tracker, t.status, t.closed, t.priority, t.assignee,
                     t.author, t.project, t.created_on, t.updated_on, t.url, via, dict(t.custom_fields))


def _untranslated(g: TicketGraph) -> int:
    """Number of Japanese texts that have no English translation."""
    n = 0
    for t in g.tickets.values():
        n += sum(1 for raw, en in [(t.subject, t.subject_en), (t.description, t.description_en),
                                   *((j.notes, j.notes_en) for j in t.journals)] if has_japanese(raw) and not en)
    return n


def analyze(root_id: int, *, cfg: Config, client: RedmineClient, backend: LLMBackend, cache: Cache,
            translator: Translator | None = None, regenerate: bool = False) -> Analysis:
    """Analyse ticket ``root_id`` and its related tickets.

    The ticket graph is always re-fetched (cheap) so staleness is detected: if no ticket in it
    changed since the cached analysis, the cache is used unless ``regenerate`` is set.

    Raises:
        RedmineError: the root ticket cannot be fetched.
        LLMError: the model backend fails or keeps returning invalid output.
    """
    ac = cfg.analysis
    graph = build_graph(client, root_id, max_depth=ac.max_depth, max_tickets=ac.max_tickets,
                        follow_text_refs=ac.follow_text_refs, redmine_url=cfg.redmine.url)
    log.info("#%d: %d ticket(s) in scope, %d skipped", root_id, len(graph.tickets), len(graph.skipped))
    fp = _fingerprint(graph, backend.model_id)
    if not regenerate and (hit := cache.get_analysis(root_id, fp)):
        log.info("#%d: unchanged since last analysis, using cache", root_id)
        return hit

    if translator:
        for t in graph.tickets.values():
            translate_ticket(t, translator)
    facts = extract_facts(graph.tickets.values(), cfg.redmine.url, cfg.git.base_url)
    rendered = {tid: render_ticket(t, ac.max_text_chars, cfg.translate.include_original)
                for tid, t in graph.tickets.items()}
    pipe = _Pipeline(backend, graph, facts)
    pipe.warnings = [w for r in rendered.values() for w in r.warnings]
    if n := _untranslated(graph):
        pipe.warnings.append(f"{n} Japanese text(s) could not be translated and were analysed untranslated")
    sections, summary, mode = pipe.run(rendered)

    analysis = Analysis(
        root_id=root_id, short_summary=summary, sections=sections,
        tickets=[_ref(t, graph.via[tid]) for tid, t in graph.tickets.items()],
        facts=facts, skipped=graph.skipped, warnings=pipe.warnings,
        meta={"model": backend.model_id, "prompt_version": PROMPT_VERSION, "mode": mode,
              "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "redmine_url": cfg.redmine.url, "fingerprint": fp})
    cache.put_analysis(analysis)
    return analysis
