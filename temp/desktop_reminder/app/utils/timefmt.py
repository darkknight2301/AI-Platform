"""Small time parsing/formatting helpers (no GUI dependencies)."""
import re
from datetime import datetime
from typing import Tuple

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*$")


def parse_hhmm(text: str) -> Tuple[int, int]:
    """Parse 'HH:MM' (24h) or 'H:MM AM/PM'. Raises ValueError when invalid."""
    if not isinstance(text, str):
        raise ValueError("time must be a string")
    m = _TIME_RE.match(text)
    if not m:
        raise ValueError("invalid time %r (expected HH:MM)" % (text,))
    hour, minute, suffix = int(m.group(1)), int(m.group(2)), m.group(3)
    if suffix:
        if not 1 <= hour <= 12:
            raise ValueError("invalid 12-hour time %r" % (text,))
        hour = hour % 12 + (12 if suffix.lower() == "pm" else 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("time out of range %r" % (text,))
    return hour, minute


def normalize_hhmm(text: str) -> str:
    h, m = parse_hhmm(text)
    return "%02d:%02d" % (h, m)


def format_12h(hhmm: str) -> str:
    """'13:00' -> '01:00 PM'."""
    try:
        h, m = parse_hhmm(hhmm)
    except ValueError:
        return str(hhmm)
    return datetime(2000, 1, 1, h, m).strftime("%I:%M %p")


def format_iso_short(iso: str) -> str:
    """ISO timestamp -> 'Mon 08 Oct 10:30 AM' (or '' when missing/invalid)."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%a %d %b %I:%M %p")
    except ValueError:
        return ""
