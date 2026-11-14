"""Japanese text detection."""

import re

# Hiragana, Katakana (+ extensions), CJK ideographs, half-width Katakana
_JAPANESE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def has_japanese(text: str) -> bool:
    """True if ``text`` contains any Japanese character."""
    return bool(_JAPANESE.search(text))


def japanese_paragraphs(text: str) -> str:
    """Only the paragraphs of ``text`` that contain Japanese (used to avoid repeating English text)."""
    return "\n\n".join(p for p in _PARAGRAPH_BREAK.split(text) if has_japanese(p))
