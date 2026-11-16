"""Contract checks for the L114-02/04/05 reference documents."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import validate_repo  # noqa: E402


class L114DocumentTests(unittest.TestCase):
    def test_repository_documents_carry_required_rules(self) -> None:
        self.assertEqual(validate_repo.check_l114_docs(ROOT), [])

    def test_missing_document_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            errors = validate_repo.check_l114_docs(Path(tmp))
            self.assertTrue(any("CONTEXT_LOADING" in error for error in errors))
            self.assertTrue(any("MEMORY_CURATION" in error for error in errors))
            self.assertTrue(any("PERSONA_STRUCTURE_AUDIT" in error for error in errors))

    def test_removed_rule_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "references").mkdir()
            (root / "research").mkdir()
            for rel_path in validate_repo.L114_DOC_REQUIREMENTS:
                (root / rel_path).write_text("blank\n", encoding="utf-8")
            errors = validate_repo.check_l114_docs(root)
            self.assertTrue(errors)

    def test_skill_index_links_new_documents(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/CONTEXT_LOADING.md", text)
        self.assertIn("references/MEMORY_CURATION.md", text)
        self.assertLessEqual(len(text.splitlines()), 500)

    def test_audit_does_not_redefine_anchors(self) -> None:
        text = (ROOT / "research/PERSONA_STRUCTURE_AUDIT.md").read_text(encoding="utf-8")
        self.assertIn("未改动项", text)
        self.assertIn("8+1 锚点文本与语义", text)


if __name__ == "__main__":
    unittest.main()
