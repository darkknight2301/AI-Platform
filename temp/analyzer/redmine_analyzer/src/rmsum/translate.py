"""Japanese detection and cached translation through the existing ``api.translate``."""

import hashlib
import importlib
import logging
import re
from collections.abc import Callable

from .cache import Cache
from .config import TranslateCfg
from .models import Ticket

log = logging.getLogger(__name__)

# Hiragana, Katakana (+ extensions), CJK ideographs, half-width Katakana
JAPANESE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")


def has_japanese(text: str) -> bool:
    """True if ``text`` contains any Japanese character."""
    return bool(JAPANESE.search(text))


class Translator:
    """Translates only the Japanese paragraphs of a text, caching each paragraph by hash."""

    def __init__(self, fn: Callable[[str], str], cache: Cache):
        self._fn = fn
        self._cache = cache

    def _paragraph(self, para: str) -> str | None:
        """Translate one paragraph (cached). Returns None if the API fails."""
        key = hashlib.sha256(para.encode()).hexdigest()
        if (hit := self._cache.get_translation(key)) is not None:
            return hit
        try:
            out = self._fn(para)
        except Exception as e:  # the external API may raise anything
            log.warning("translation failed: %s", e)
            return None
        if not isinstance(out, str) or not out.strip():
            log.warning("translation API returned no text")
            return None
        self._cache.put_translation(key, out)
        return out

    def to_english(self, text: str) -> str | None:
        """English version of ``text``, or None if it has no Japanese or translation failed.

        Non-Japanese paragraphs (code, logs, English text) are kept untouched.
        """
        if not has_japanese(text):
            return None
        parts = []
        for chunk in re.split(r"(\n\s*\n)", text):
            if has_japanese(chunk):
                chunk = self._paragraph(chunk)
                if chunk is None:
                    return None
            parts.append(chunk)
        return "".join(parts)


def load_translator(cfg: TranslateCfg, cache: Cache) -> Translator | None:
    """Import ``<cfg.module>.translate``; returns None (with a warning) if unavailable."""
    if not cfg.enabled:
        return None
    try:
        return Translator(importlib.import_module(cfg.module).translate, cache)
    except (ImportError, AttributeError) as e:
        log.warning("translation disabled, cannot load %s.translate: %s", cfg.module, e)
        return None


def translate_ticket(t: Ticket, tr: Translator) -> None:
    """Fill the ``*_en`` fields of a ticket and its journals (originals are kept)."""
    t.subject_en = tr.to_english(t.subject)
    t.description_en = tr.to_english(t.description)
    for j in t.journals:
        j.notes_en = tr.to_english(j.notes)
