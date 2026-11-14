"""Static check that the code base only uses syntax and APIs that exist in Python 3.10.

Execute it with Python 3.12 or newer (the 3.12 tokenizer is needed to look inside f-strings)::

    python tools/check_compat.py

It cannot replace running the test suite on 3.10, but it finds the mistakes that are easy to make
while developing on 3.12: PEP 695 ``type`` statements, PEP 701 f-strings (reused quotes, backslashes
or comments inside ``{...}``), ``except*``, ``X | Y`` unions in type hints (``Optional``/``Union`` are used
instead, they work on every Python 3 release), and standard-library names added in 3.11/3.12.
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Standard-library names that do not exist in Python 3.10.
NEWER_APIS = re.compile(
    r"from enum import[^\n]*\b(StrEnum|ReprEnum)\b|\benum\.(StrEnum|ReprEnum)\b|"
    r"datetime\.UTC\b|from datetime import[^\n]*\bUTC\b|getLevelNamesMapping\(|"
    r"\.enterContext\(|\.enterClassContext\(|\bimport tomllib|from tomllib|\bExceptionGroup\(|"
    r"\bBaseExceptionGroup\(|\.add_note\(|\.assertNoLogs\(|contextlib\.chdir|\bTaskGroup\(|"
    r"asyncio\.timeout\(|\bfile_digest\(|itertools\.batched|from itertools import[^\n]*\bbatched\b|"
    r"typing import[^\n]*\b(Self|override|LiteralString|Never|assert_never|TypeVarTuple|Unpack|reveal_type|"
    r"dataclass_transform|NotRequired|Required)\b|\bre\.NOFLAG\b|\bonexc="
)


# Files whose purpose is to deal with these names (the backport, its test, and this checker's own patterns).
ALLOWED_FILES = {"check_compat.py", "compat.py", "test_compat.py"}


def _type_like(node: ast.AST) -> bool:
    """True for what a type hint is made of: names, dotted names, subscripts of those, None, forward-ref strings."""
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Constant):
        return node.value is None or isinstance(node.value, str)
    if isinstance(node, ast.Attribute):
        return _type_like(node.value)
    if isinstance(node, ast.Subscript):
        return _type_like(node.value)
    return False


def _union_operands(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union_operands(node.left) + _union_operands(node.right)
    return [node]


def syntax_problems(path: Path, source: str) -> list[str]:
    """PEP 604 / PEP 695 / PEP 654 syntax found through the AST.

    ``X | Y`` is reported only when every operand looks like a type, so ``set(a) | {1}`` and ``1 | 2`` pass.
    (A bitwise OR of two plain names would be reported too; the project has none.)
    """
    problems = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            if all(_type_like(o) for o in _union_operands(node)):
                problems.append(f"{path}:{line}: 'X | Y' union in a type hint or alias; use typing.Optional / Union")
        elif isinstance(node, ast.TypeAlias):
            problems.append(f"{path}:{line}: 'type X = ...' statement needs Python 3.12 (use typing.TypeAlias)")
        elif isinstance(node, ast.TryStar):
            problems.append(f"{path}:{line}: 'except*' needs Python 3.11")
        elif getattr(node, "type_params", None):
            problems.append(f"{path}:{line}: generic syntax (PEP 695) needs Python 3.12")
    return problems


def fstring_problems(path: Path, source: str) -> list[str]:
    """f-string constructs that only PEP 701 (3.12) allows: reused quotes, backslashes, comments, newlines."""
    problems = []
    stack: list[dict] = []  # one entry per f-string being tokenised: delimiter and brace depth
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        line = tok.start[0]
        if tok.type == tokenize.FSTRING_START:
            if stack and stack[-1]["depth"] > 0 and _reuses(stack[-1]["delim"], tok.string):
                problems.append(f"{path}:{line}: f-string nested in an f-string reuses the outer quote type")
            delim = tok.string.lstrip("rRfFbBuU")
            stack.append({"delim": delim, "depth": 0})
        elif tok.type == tokenize.FSTRING_END and stack:
            stack.pop()
        elif stack and tok.type == tokenize.OP and tok.string == "{":
            stack[-1]["depth"] += 1
        elif stack and tok.type == tokenize.OP and tok.string == "}" and stack[-1]["depth"] > 0:
            stack[-1]["depth"] -= 1
        elif stack and stack[-1]["depth"] > 0:
            top = stack[-1]
            if tok.type == tokenize.STRING:
                opening = tok.string.lstrip("rRfFbBuU")
                if _reuses(top["delim"], opening):
                    problems.append(f"{path}:{line}: string in an f-string expression reuses the f-string's quote type")
                if "\\" in tok.string:
                    problems.append(f"{path}:{line}: backslash inside an f-string expression")
            elif tok.type == tokenize.COMMENT:
                problems.append(f"{path}:{line}: comment inside an f-string expression")
            elif tok.type == tokenize.NL and len(top["delim"]) == 1:
                problems.append(f"{path}:{line}: line break inside an f-string expression of a single-quoted f-string")
    return problems


def _reuses(outer: str, inner_opening: str) -> bool:
    """True if a string starting with ``inner_opening`` would terminate an f-string delimited by ``outer``."""
    return inner_opening.startswith(outer)


def main() -> int:
    if sys.version_info < (3, 12):
        print("run this checker with Python 3.12 or newer", file=sys.stderr)
        return 2
    problems: list[str] = []
    for path in sorted(p for d in ("src", "tests", "tools") for p in (ROOT / d).rglob("*.py")):
        source = path.read_text("utf-8")
        rel = path.relative_to(ROOT)
        problems += syntax_problems(rel, source)
        problems += fstring_problems(rel, source)
        for number, text in enumerate(source.splitlines(), 1):
            if path.name not in ALLOWED_FILES and NEWER_APIS.search(text):
                problems.append(f"{rel}:{number}: uses an API newer than Python 3.10: {text.strip()[:80]}")
    problems = list(dict.fromkeys(problems))  # a union nested in a union is reported once per line
    for problem in problems:
        print(problem)
    print(f"{len(problems)} Python 3.10 compatibility problem(s) found")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
