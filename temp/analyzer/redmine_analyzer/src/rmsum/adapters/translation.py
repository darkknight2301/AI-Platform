"""Batch translation through the existing ``api.translate(text) -> str``.

Translating many texts in one call gives the translator more context (consistent terminology) and
far fewer round trips. Texts are joined with numbered markers and split again afterwards; if the
translator mangles the markers, the batch is retried text by text so nothing is misaligned.
"""

import importlib
import logging
import re
from collections.abc import Callable, Iterator, Mapping
from typing import Optional

from ..config import TranslateCfg

log = logging.getLogger(__name__)

_MARKER = "@@SEG-{}@@"
_MARKER_RE = re.compile(r"@@SEG-(\d+)@@")


class BatchTranslator:
    """``TextTranslator`` that groups texts into size-limited batches."""

    def __init__(self, translate_fn: Callable[[str], str], max_chars: int, max_items: int) -> None:
        self._fn = translate_fn
        self._max_chars = max_chars
        self._max_items = max_items

    def translate(self, texts: Mapping[str, str]) -> dict[str, str]:
        """Translate ``{key: text}``; identical texts are translated once. Failed keys are omitted."""
        by_text: dict[str, list[str]] = {}
        for key, text in texts.items():
            by_text.setdefault(text, []).append(key)
        result: dict[str, str] = {}
        for batch in self._batches(list(by_text)):
            for text, translated in self._translate_batch(batch).items():
                for key in by_text[text]:
                    result[key] = translated
        return result

    def _batches(self, texts: list[str]) -> Iterator[list[str]]:
        """Group texts in order; a single over-long text forms its own batch."""
        batch: list[str] = []
        size = 0
        for text in texts:
            if batch and (size + len(text) > self._max_chars or len(batch) >= self._max_items):
                yield batch
                batch, size = [], 0
            batch.append(text)
            size += len(text)
        if batch:
            yield batch

    def _call(self, text: str) -> Optional[str]:
        """One call to the translate API; None on any failure (the external API may raise anything)."""
        try:
            out = self._fn(text)
        except Exception as exc:
            log.warning("translation call failed: %s", exc)
            return None
        return out if isinstance(out, str) and out.strip() else None

    def _translate_batch(self, batch: list[str]) -> dict[str, str]:
        if len(batch) > 1:
            payload = "\n".join(f"{_MARKER.format(i)}\n{text}" for i, text in enumerate(batch))
            if (out := self._call(payload)) is not None and (parts := self._split(out, len(batch))) is not None:
                return dict(zip(batch, parts))
            log.warning("batch translation of %d texts was not usable; translating one by one", len(batch))
        singles = {text: self._call(text) for text in batch}
        return {text: out for text, out in singles.items() if out is not None}

    @staticmethod
    def _split(output: str, expected: int) -> Optional[list[str]]:
        """Split a batch reply on its markers; None unless every marker came back once, in order, with text."""
        pieces = _MARKER_RE.split(output)
        indices, bodies = pieces[1::2], [p.strip() for p in pieces[2::2]]
        if indices != [str(i) for i in range(expected)] or not all(bodies):
            return None
        return bodies


def load_translator(cfg: TranslateCfg) -> Optional[BatchTranslator]:
    """Import ``<cfg.module>.translate``; returns None (with a warning) when translation is off or unavailable."""
    if not cfg.enabled:
        return None
    try:
        function = importlib.import_module(cfg.module).translate
    except (ImportError, AttributeError) as exc:
        log.warning("translation disabled, cannot load %s.translate: %s", cfg.module, exc)
        return None
    return BatchTranslator(function, cfg.batch_chars, cfg.batch_items)
