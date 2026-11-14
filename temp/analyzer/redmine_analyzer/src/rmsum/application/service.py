"""Use case: analyse one ticket end to end (load graph, translate, extract facts, run the LLM, assemble the result)."""

import hashlib
import json
import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import Config
from ..domain.extraction import extract_facts
from ..domain.models import SCHEMA_VERSION, Analysis, AnalysisMeta, RunStats, Ticket, TicketRef
from ..ports import Completion, IssueSource, LanguageModel, TextTranslator
from .graph import TicketGraphLoader
from .pipeline import AnalysisPipeline
from .prompts import PROMPT_VERSION
from .render import RenderLimits, japanese_texts, render_ticket, translation_key

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisSettings:
    """Every setting that influences the content of an analysis (and therefore its fingerprint)."""

    max_depth: int
    max_tickets: int
    follow_text_refs: bool
    max_text_chars: int
    include_original: bool
    redmine_url: str
    git_base_url: str
    model: str
    context_tokens: int
    max_output_tokens: int
    seed: int
    translation_enabled: bool

    @classmethod
    def from_config(cls, cfg: Config, translation_enabled: bool) -> "AnalysisSettings":
        return cls(
            max_depth=cfg.analysis.max_depth,
            max_tickets=cfg.analysis.max_tickets,
            follow_text_refs=cfg.analysis.follow_text_refs,
            max_text_chars=cfg.analysis.max_text_chars,
            include_original=cfg.translate.include_original,
            redmine_url=cfg.redmine.url,
            git_base_url=cfg.git.base_url,
            model=cfg.llm.model,
            context_tokens=cfg.llm.num_ctx,
            max_output_tokens=cfg.llm.max_output_tokens,
            seed=cfg.llm.seed,
            translation_enabled=translation_enabled,
        )

    def fingerprint(self, ticket_versions: Iterable[tuple[int, str]], skipped: Iterable[tuple[int, str]]) -> str:
        """Hash of the ticket versions plus all settings: equal fingerprints mean an identical analysis would result."""
        state: dict[str, Any] = {
            "tickets": sorted(ticket_versions),
            "skipped": sorted(skipped),
            "settings": self.__dict__,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
        }
        return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


class MeteredModel:
    """Decorator that counts calls, tokens and time of any ``LanguageModel`` (keeps pipelines free of counters)."""

    def __init__(self, inner: LanguageModel) -> None:
        self._inner = inner
        self.model_id = inner.model_id
        self.context_tokens = inner.context_tokens
        self.max_output_tokens = inner.max_output_tokens
        self.calls = 0
        self.prompt_tokens = 0
        self.output_tokens = 0
        self.seconds = 0.0

    def generate(self, system: str, prompt: str, schema: Mapping[str, Any] | None = None) -> Completion:
        started = time.monotonic()
        try:
            completion = self._inner.generate(system, prompt, schema)
        finally:  # count failed calls too: they cost time
            self.calls += 1
            self.seconds += time.monotonic() - started
        self.prompt_tokens += completion.prompt_tokens or 0
        self.output_tokens += completion.output_tokens or 0
        return completion


@dataclass(frozen=True)
class AnalysisOutcome:
    """Result of one ``analyze`` call. ``stats`` describe *this* call (all zeros besides fetch time when reused)."""

    analysis: Analysis
    reused: bool
    stats: RunStats


class AnalysisService:
    """Analyses tickets. Collaborators are injected, so every one of them can be faked in tests."""

    def __init__(
        self,
        source: IssueSource,
        model: LanguageModel,
        translator: TextTranslator | None,
        settings: AnalysisSettings,
    ) -> None:
        self._source = source
        self._model = model
        self._translator = translator
        self._settings = settings
        self._loader = TicketGraphLoader(
            source,
            max_depth=settings.max_depth,
            max_tickets=settings.max_tickets,
            follow_text_refs=settings.follow_text_refs,
            redmine_url=settings.redmine_url,
        )

    def analyze(self, root_id: int, previous: Analysis | None = None) -> AnalysisOutcome:
        """Analyse ``root_id`` and its related tickets.

        The ticket graph is always re-fetched (cheap compared with LLM time) so changes are detected: if
        ``previous`` was made from exactly the same ticket versions and settings, it is returned unchanged.

        Raises:
            SourceError: the root ticket cannot be fetched.
            LLMError: the model fails or keeps returning invalid output.
        """
        started = time.monotonic()
        graph = self._loader.load(root_id)
        fetch_seconds = time.monotonic() - started
        fingerprint = self._settings.fingerprint(
            ((t.id, t.updated_on) for t in graph.tickets.values()),
            ((s.ticket_id, s.reason) for s in graph.skipped),
        )
        if previous is not None and previous.meta.fingerprint == fingerprint:
            log.info("#%d: unchanged since %s, reusing previous analysis", root_id, previous.meta.generated_at)
            stats = RunStats(fetch_seconds=fetch_seconds, total_seconds=time.monotonic() - started)
            return AnalysisOutcome(previous, True, stats)

        tickets = tuple(graph.tickets.values())
        translate_started = time.monotonic()
        translations = self._translate(tickets)
        translate_seconds = time.monotonic() - translate_started

        facts = extract_facts(tickets, self._settings.redmine_url, self._settings.git_base_url)
        limits = RenderLimits(self._settings.max_text_chars, self._settings.include_original)
        rendered = {t.id: render_ticket(t, translations, limits) for t in tickets}
        titles = {t.id: translations.get(translation_key(t.id, "subject"), t.subject) for t in tickets}

        metered = MeteredModel(self._model)
        result = AnalysisPipeline(metered).run(graph, facts, rendered, titles)

        warnings = list(graph.warnings)
        warnings += [w for r in rendered.values() for w in r.warnings]
        if missing := len(japanese_texts(tickets)) - sum(k in translations for k in japanese_texts(tickets)):
            warnings.append(f"{missing} Japanese text(s) could not be translated and were analysed untranslated")
        warnings += result.warnings

        stats = RunStats(
            fetch_seconds=fetch_seconds,
            translate_seconds=translate_seconds,
            llm_seconds=metered.seconds,
            total_seconds=time.monotonic() - started,
            llm_calls=metered.calls,
            prompt_tokens=metered.prompt_tokens,
            output_tokens=metered.output_tokens,
        )
        analysis = Analysis(
            root_id=root_id,
            short_summary=result.summary,
            sections=result.sections,
            tickets=tuple(self._ref(t, graph.via[t.id], translations) for t in tickets),
            facts=facts,
            skipped=graph.skipped,
            warnings=tuple(warnings),
            dropped=result.dropped,
            meta=AnalysisMeta(
                model=self._model.model_id,
                prompt_version=PROMPT_VERSION,
                mode=result.mode,
                generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                redmine_url=self._settings.redmine_url,
                fingerprint=fingerprint,
            ),
            stats=stats,
        )
        return AnalysisOutcome(analysis, False, stats)

    def _translate(self, tickets: Iterable[Ticket]) -> dict[str, str]:
        """Translate all Japanese texts of the tickets in batches (empty when translation is unavailable)."""
        texts = japanese_texts(tickets)
        if not texts or self._translator is None:
            return {}
        log.info("translating %d Japanese text(s)", len(texts))
        return self._translator.translate(texts)

    @staticmethod
    def _ref(ticket: Ticket, via: str, translations: Mapping[str, str]) -> TicketRef:
        return TicketRef(
            id=ticket.id,
            subject=ticket.subject,
            subject_en=translations.get(translation_key(ticket.id, "subject")),
            tracker=ticket.tracker,
            status=ticket.status,
            closed=ticket.closed,
            priority=ticket.priority,
            assignee=ticket.assignee,
            author=ticket.author,
            project=ticket.project,
            created_on=ticket.created_on,
            updated_on=ticket.updated_on,
            url=ticket.url,
            via=via,
            custom_fields=dict(ticket.custom_fields),
        )
