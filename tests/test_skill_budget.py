"""Regressions for the byte-independent Skill context budget."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import skill_budget  # noqa: E402


class SkillBudgetTests(unittest.TestCase):
    def test_repository_fits(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(skill_budget.measure(text).errors(), [])

    def test_exact_limits_are_accepted(self) -> None:
        frontmatter = ["---", "description: >"]
        frontmatter += ["  " + "汉" * 100] * 39 + ["---"]
        lines = frontmatter + ["a" * 120, ""] + ["# Heading"] * 206
        budget = skill_budget.measure("\n".join(lines))
        self.assertEqual((budget.lines, budget.han, budget.longest_paragraph), (250, 3900, 120))
        self.assertEqual(budget.errors(), [])

    def test_wrapped_paragraph_is_measured_as_one(self) -> None:
        text = "# Example\n\n" + "a" * 60 + "\n" + "b" * 60 + "\n\nshort"
        budget = skill_budget.measure(text)
        self.assertEqual(budget.paragraphs, ((3, 121), (6, 5)))
        self.assertIn("SKILL.md:3: prose paragraph of 121 characters", budget.errors()[0])

    def test_han_from_all_structures_is_counted(self) -> None:
        text = "---\ndescription: " + "一" * 3901 + "\n---\n# Heading"
        budget = skill_budget.measure(text)
        self.assertEqual(budget.longest_paragraph, 0)
        self.assertEqual(budget.errors(), ["SKILL.md: 3901 Han characters > 3900"])

    def test_list_table_quote_heading_and_fenced_code_are_not_prose(self) -> None:
        long = "x" * 130
        text = "\n".join((
            "# " + long,
            "| " + long + " |",
            "> " + long,
            "11) " + long,
            "    " + long,
            "* " + long,
            "",
            "~~~md",
            long,
            "~~~",
            "",
            "ordinary",
        ))
        self.assertEqual(skill_budget.measure(text).paragraphs, ((12, 8),))

    def test_cli_rejects_one_over_budget_line_from_any_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dest = root / "scripts" / "skill_budget.py"
            dest.parent.mkdir()
            shutil.copyfile(ROOT / "scripts" / "skill_budget.py", dest)
            (root / "SKILL.md").write_text("a" * 121 + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(dest)],
                cwd=dest.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("SKILL.md:1: prose paragraph of 121 characters > 120", result.stdout)


if __name__ == "__main__":
    unittest.main()
