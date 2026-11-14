"""Token estimation and text clipping. A tokenizer-free heuristic keeps the dependency list short."""

import math


def estimate_tokens(text: str) -> int:
    """Conservative token estimate: ~3.2 ASCII characters, or one non-ASCII character, per token.

    Deliberately pessimistic for Japanese, which tokenises at roughly one token per character.
    """
    ascii_chars = len(text.encode("ascii", "ignore"))
    return math.ceil(ascii_chars / 3.2 + (len(text) - ascii_chars))


def clip(text: str, limit: int) -> str:
    """Shorten ``text`` to at most ``limit`` characters, keeping head and tail and marking the cut."""
    if len(text) <= limit:
        return text
    keep = max(limit - 60, 0) // 2
    if not keep:
        return text[:limit]
    return f"{text[:keep]}\n[... {len(text) - 2 * keep} characters omitted ...]\n{text[-keep:]}"
