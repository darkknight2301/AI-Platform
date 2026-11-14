"""Guards the Python 3.10 / 3.12 compatibility promise."""

import enum
import json
import sys
import unittest
from pathlib import Path

from rmsum.domain.compat import _BackportStrEnum

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


class BackportStrEnumTests(unittest.TestCase):
    """The 3.10 fallback must behave like ``enum.StrEnum`` (it is exercised here even on 3.12)."""

    class Colour(_BackportStrEnum):
        RED = "red"

    def test_behaves_like_a_string(self):
        red = self.Colour.RED
        self.assertEqual((str(red), f"{red}", "{}".format(red), red == "red"), ("red", "red", "red", True))
        self.assertIs(self.Colour("red"), red)
        self.assertEqual(json.dumps({red: [red]}), '{"red": ["red"]}')
        self.assertIsInstance(red, str)

    def test_models_use_a_working_str_enum(self):
        from rmsum.domain.models import Basis, Section

        self.assertEqual(f"{Basis.CONFIRMED} {Section.BLOCKERS}", "confirmed blockers")
        self.assertIsInstance(Section.BLOCKERS, enum.Enum)


@unittest.skipIf(sys.version_info < (3, 12), "the static checker needs the 3.12 tokenizer; run it on 3.12")
class CompatibilityCheckerTests(unittest.TestCase):
    def problems(self, source: str) -> list[str]:
        import check_compat

        return check_compat.syntax_problems(Path("x.py"), source) + check_compat.fstring_problems(Path("x.py"), source)

    def test_detects_3_12_only_syntax(self):
        cases = {
            "type Alias = int\n": "type X",
            'name = "a"\nprint(f"{name["x"]}")\n': "reuses",
            "print(f'{\"a\\n\".join([])}')\n": "backslash",
            'print(f"{"nested"}")\n': "reuses",
            "print(f'''{\n  1 # comment\n}''')\n": "comment",
            "try:\n    pass\nexcept* ValueError:\n    pass\n": "except*",
        }
        for source, expected in cases.items():
            with self.subTest(source):
                self.assertTrue(any(expected in p for p in self.problems(source)), self.problems(source))

    def test_accepts_3_10_compatible_f_strings(self):
        source = (
            "d = {'a': 1}\n"
            'print(f"{d[\'a\']} {\', \'.join([])}")\n'
            "print(f'''{d[\"a\"]}''')\n"
            'print(f"line\\n{1 + 1}")\n'
        )
        self.assertEqual(self.problems(source), [])

    def test_the_project_itself_is_clean(self):
        import check_compat

        self.assertEqual(check_compat.main(), 0)


if __name__ == "__main__":
    unittest.main()
