"""Structural checks for the judgment-continuity eval fixtures.

These tests do not evaluate persona behavior. They only prove that the fixtures
and documentation contain the required scenarios, counts, and guardrails.
Real-host behavior is scored with ``research/evals/JUDGMENT_RUBRIC.md``.
"""

from __future__ import annotations

import fnmatch
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import judgment_ledger as jl  # noqa: E402
from scripts import validate_repo  # noqa: E402

EVALS = ROOT / "research" / "evals" / "judgment-continuity.json"
RUBRIC = ROOT / "research" / "evals" / "JUDGMENT_RUBRIC.md"
REFERENCE = ROOT / "references" / "JUDGMENT_CONTINUITY.md"
TEMPLATE = ROOT / "judgments.template.md"


def load_evals() -> dict:
    return json.loads(EVALS.read_text(encoding="utf-8"))


class JudgmentEvalStructureTests(unittest.TestCase):
    def test_version_matches_product(self) -> None:
        self.assertEqual(
            load_evals().get("version"), validate_repo.EXPECTED_SKILL_VERSION
        )

    def test_four_groups_with_a_b_c(self) -> None:
        data = load_evals()
        groups = data.get("anti_sycophancy_groups")
        self.assertIsInstance(groups, list)
        self.assertEqual(len(groups), 4)
        ids: set[str] = set()
        scenario_count = 0
        for group in groups:
            for key, letter in (
                ("stage_a", "A"),
                ("stage_b", "B"),
                ("stage_c", "C"),
            ):
                stage = group.get(key)
                self.assertIsInstance(stage, dict, (group.get("id"), key))
                self.assertEqual(stage.get("stage"), letter)
                self.assertNotIn(stage.get("id"), ids)
                ids.add(stage.get("id"))
                self.assertTrue(stage.get("query"))
                self.assertTrue(stage.get("expected"))
                self.assertTrue(stage.get("forbidden"))
                scenario_count += 1
            self.assertIn("new_evidence", group["stage_c"])
            self.assertTrue(group["stage_c"]["new_evidence"].strip())
        self.assertEqual(scenario_count, 12)
        self.assertEqual(len(ids), 12)

    def test_stage_c_is_about_reevaluation_not_forced_flip(self) -> None:
        text = EVALS.read_text(encoding="utf-8")
        self.assertIn("强制翻转", text)
        self.assertIn("重新评估", text)
        self.assertIn("not a mandatory flip", text)

    def test_association_counts_and_citation_limits(self) -> None:
        association = load_evals()["proactive_association"]
        positive = association["positive"]
        negative = association["negative"]
        self.assertEqual(len(positive), 6)
        self.assertEqual(len(negative), 6)
        self.assertEqual(len(association["rules"]), 7)
        for case in positive:
            self.assertEqual(case["type"], "positive")
            self.assertEqual(case["max_citations"], 1)
            self.assertTrue(case["cite_topic_key"].strip())
        for case in negative:
            self.assertEqual(case["type"], "negative")
            self.assertEqual(case["max_citations"], 0)

    def test_negative_cases_cover_required_failures(self) -> None:
        negative = load_evals()["proactive_association"]["negative"]
        preconditions = " ".join(case["precondition"] for case in negative)
        queries = " ".join(case["query"] for case in negative)
        self.assertIn("没有关于", preconditions)
        self.assertIn("superseded", preconditions)
        self.assertIn("off", preconditions)
        self.assertTrue(
            "判断逻辑" in queries, "generic-word negative case is missing"
        )

    def test_positive_topic_keys_match_a_group(self) -> None:
        data = load_evals()
        group_keys = {
            group["topic_key"] for group in data["anti_sycophancy_groups"]
        }
        for case in data["proactive_association"]["positive"]:
            self.assertIn(case["cite_topic_key"], group_keys)


class JudgmentDocumentationTests(unittest.TestCase):
    def test_rubric_separates_structure_from_behavior(self) -> None:
        text = RUBRIC.read_text(encoding="utf-8")
        for needle in (
            "确定性",
            "真实宿主",
            "12",
            "6",
            "不是强制改变结论",
            "不得使用真实",
        ):
            self.assertIn(needle, text)

    def test_reference_contract_phrases(self) -> None:
        text = REFERENCE.read_text(encoding="utf-8")
        for needle in validate_repo.JUDGMENT_REQUIRED_PHRASES:
            self.assertIn(needle, text)

    def test_skill_entry_is_compact_and_linked(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/JUDGMENT_CONTINUITY.md", text)
        self.assertIn("judgments.template.md", text)
        self.assertIn("scripts/validate_judgments.py", text)
        self.assertIn("每次回复最多主动引用一个", text)
        self.assertLessEqual(len(text.splitlines()), 500)

    def test_template_is_valid(self) -> None:
        document = jl.parse_ledger(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(document.schema_version, 1)
        self.assertEqual(jl.validate_judgments(document.judgments), [])

    def test_gitignore_covers_private_files_but_not_template(self) -> None:
        lines = [
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for pattern in (
            "JUDGMENTS.md",
            "JUDGMENTS.md.bak.*",
            "JUDGMENTS.md.*.tmp",
            "JUDGMENTS.md.lock",
        ):
            self.assertIn(pattern, lines)
        for pattern in lines:
            self.assertFalse(
                fnmatch.fnmatch("judgments.template.md", pattern),
                f"template would be ignored by {pattern!r}",
            )

    def test_no_real_judgment_file_in_repo(self) -> None:
        self.assertFalse((ROOT / "JUDGMENTS.md").exists())


if __name__ == "__main__":
    unittest.main()
