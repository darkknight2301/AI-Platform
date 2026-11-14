"""Small backports so the code base runs on Python 3.10 and 3.12+ alike."""

import enum


class _BackportStrEnum(str, enum.Enum):
    """Minimal ``enum.StrEnum`` for Python 3.10: members are strings and print/format as their value.

    Without the ``__str__`` override, ``f"{member}"`` would yield ``Class.NAME`` on Python 3.12 and the value on 3.10,
    which would change report output between interpreters.
    """

    def __str__(self) -> str:
        return str(self.value)


# Python 3.11+ ships the real thing; prefer it there.
StrEnum = getattr(enum, "StrEnum", _BackportStrEnum)
