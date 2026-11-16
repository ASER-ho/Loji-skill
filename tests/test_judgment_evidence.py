"""Structural checks for the L114-03 evidence-quality contract.

These tests only prove that the optional basis tiers are parsed structurally,
that old untagged ledgers stay valid, and that the documentation carries the
required re-verification rules. They do not judge whether a statement is true.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import judgment_ledger as jl  # noqa: E402


def record(**overrides):
    data = {
        "id": "J-EVID-001",
        "topic_key": "evidence.test",
        "topic": "证据层级合成测试",
        "stance": "合成结论。",
        "confidence": "medium",
        "basis": ["未验证印象：合成口头说法。"],
        "user_position": "unknown",
        "would_change_if": ["出现可核查产物。"],
        "status": "active",
        "created_at": "2040-01-01",
        "updated_at": "2040-01-01",
        "supersedes": None,
    }
    data.update(overrides)
    return jl.Judgment(**data)


class BasisTierTests(unittest.TestCase):
    def test_tagged_basis_is_valid(self) -> None:
        for tag in ("直接证据", "来源观点", "可核查产物", "未验证印象"):
            item = record(basis=[f"{tag}：合成内容。"])
            self.assertEqual(jl.validate_judgments([item]), [])

    def test_ascii_colon_is_accepted(self) -> None:
        self.assertEqual(
            jl.validate_judgments([record(basis=["直接证据: 合成内容。"])]), []
        )

    def test_empty_tier_content_is_rejected(self) -> None:
        for basis in ("直接证据：", "可核查产物:", "未验证印象：   "):
            errors = jl.validate_judgments([record(basis=[basis])])
            self.assertTrue(any("evidence tier" in error for error in errors), errors)

    def test_untagged_legacy_basis_stays_valid(self) -> None:
        self.assertEqual(
            jl.validate_judgments([record(basis=["合成旧依据，无标签。"])]), []
        )

    def test_unknown_prefix_is_ordinary_text(self) -> None:
        self.assertEqual(
            jl.validate_judgments([record(basis=["直接证据表明……"])]), []
        )

    def test_template_documents_tiers(self) -> None:
        text = (ROOT / "judgments.template.md").read_text(encoding="utf-8")
        for tag in ("直接证据", "来源观点", "可核查产物", "未验证印象"):
            self.assertIn(tag, text)

    def test_reference_documents_partial_invalidation(self) -> None:
        text = (ROOT / "references/JUDGMENT_CONTINUITY.md").read_text(encoding="utf-8")
        for needle in (
            "三份独立依据",
            "其中一份失效",
            "并不必然使整个判断失效",
            "不得编造引用",
            "用户要求遗忘",
        ):
            self.assertIn(needle, text)


class EvidenceFixtureTests(unittest.TestCase):
    def test_fixture_has_required_categories(self) -> None:
        data = json.loads(
            (ROOT / "research/evals/judgment-evidence.json").read_text(encoding="utf-8")
        )
        categories = {case["category"] for case in data["cases"]}
        for required in data["gates"]["required_categories"]:
            self.assertIn(required, categories)

    def test_every_evidence_case_has_zero_tolerance_field(self) -> None:
        data = json.loads(
            (ROOT / "research/evals/judgment-evidence.json").read_text(encoding="utf-8")
        )
        for case in data["cases"]:
            self.assertIsInstance(case.get("independent_failures"), list)


if __name__ == "__main__":
    unittest.main()
