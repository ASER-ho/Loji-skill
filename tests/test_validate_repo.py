"""Tests for scripts/validate_repo.py.

Positive coverage runs against the real repository. Negative coverage uses
temporary directories so no permanent invalid fixtures are added.
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

from scripts import validate_repo  # noqa: E402


def _valid_trigger_fixture() -> dict:
    trigger: list[dict] = []
    non_trigger: list[dict] = []
    for case_id, spec in validate_repo.EXPECTED_TRIGGER_CASES.items():
        item = {
            "id": case_id,
            "query": spec["query"],
            "expect": spec["expect"],
        }
        if spec["bucket"] == "should_trigger":
            trigger.append(item)
        else:
            non_trigger.append(item)
    return {"should_trigger": trigger, "should_not_trigger": non_trigger}


class ValidateRepoTests(unittest.TestCase):
    def test_repository_passes(self) -> None:
        errors, _warnings = validate_repo.validate(ROOT)
        self.assertEqual(errors, [])

    def test_duplicate_json_key_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dup.json"
            path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            errors, _data = validate_repo.check_json_file(path)
            self.assertTrue(
                any("duplicate JSON key" in error for error in errors), errors
            )

    def test_version_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "references").mkdir()
            (root / "SKILL.md").write_text(
                '---\nmetadata:\n  version: "1.0.1"\n---\n', encoding="utf-8"
            )
            (root / "memory.template.md").write_text(
                '---\nskill_version: "1.0.1"\nschema_version: 1\n---\n',
                encoding="utf-8",
            )
            (root / "references" / "STATE_MACHINES.md").write_text(
                "> 版本对应：Loji-skill v1.0.1\n", encoding="utf-8"
            )
            (root / "references" / "domain-knowledge.md").write_text(
                "> 版本对应：Loji-skill v1.0.1\n", encoding="utf-8"
            )
            errors = validate_repo.check_versions(root)
            self.assertTrue(any("SKILL.md" in error for error in errors), errors)
            self.assertTrue(
                any("memory.template.md" in error for error in errors), errors
            )

    def test_missing_reference_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SKILL.md").write_text(
                "See `references/MISSING.md`.\n", encoding="utf-8"
            )
            errors = validate_repo.check_reference_paths(root)
            self.assertTrue(
                any("references/MISSING.md" in error for error in errors), errors
            )

    def test_trigger_count_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trigger_queries.json"
            data = {
                "should_trigger": [{"id": f"T{i:02d}"} for i in range(1, 11)],
                "should_not_trigger": [{"id": f"N{i:02d}"} for i in range(1, 11)],
            }
            path.write_text(json.dumps(data), encoding="utf-8")
            errors = validate_repo.check_trigger_counts(path)
            self.assertTrue(
                any("should_trigger" in error for error in errors), errors
            )
            self.assertTrue(
                any("should_not_trigger" in error for error in errors), errors
            )

    def test_old_name_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            eval_dir = root / "research" / "evals"
            eval_dir.mkdir(parents=True)
            (eval_dir / "legacy.md").write_text(
                "loji-perspective legacy metadata\n", encoding="utf-8"
            )
            (root / "README.md").write_text("ok\n", encoding="utf-8")
            (root / "README_EN.md").write_text("ok\n", encoding="utf-8")
            errors = validate_repo.check_old_name(root)
            self.assertTrue(
                any("loji-perspective" in error for error in errors), errors
            )

    def test_install_path_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "git clone https://github.com/ASER-ho/Loji-skill.git "
                "~/.claude/skills/Loji-skill\n",
                encoding="utf-8",
            )
            (root / "README_EN.md").write_text(
                "git clone https://github.com/ASER-ho/Loji-skill.git "
                "~/.claude/skills/loji-skill\n",
                encoding="utf-8",
            )
            errors = validate_repo.check_install_paths(root)
            self.assertTrue(
                any("not lowercase loji-skill" in error for error in errors),
                errors,
            )
            self.assertTrue(
                any("init_memory.py" in error for error in errors), errors
            )

    def test_skill_size_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "SKILL.md").write_text("\n".join(["x"] * 501), encoding="utf-8")
            errors = validate_repo.check_skill_size(root)
            self.assertTrue(any("501" in error for error in errors), errors)

    def test_memory_schema_policy_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "references").mkdir()
            (root / "references" / "MEMORY.md").write_text(
                "检查 `schema_version` 是否与 skill 当前版本一致；"
                "若不一致，自动走上述迁移流程。\n",
                encoding="utf-8",
            )
            errors = validate_repo.check_memory_schema_policy(root)
            self.assertTrue(errors, errors)
            self.assertTrue(
                any("obsolete schema rule" in error for error in errors), errors
            )

    def test_trigger_semantic_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trigger_queries.json"
            data = _valid_trigger_fixture()
            for item in data["should_trigger"]:
                if item["id"] == "T11":
                    item["query"] = "WRONG QUERY"
            path.write_text(json.dumps(data), encoding="utf-8")
            errors = validate_repo.check_trigger_counts(path)
            self.assertTrue(
                any("T11 query mismatch" in error for error in errors), errors
            )

    def test_trigger_t01_query_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trigger_queries.json"
            data = _valid_trigger_fixture()
            for item in data["should_trigger"]:
                if item["id"] == "T01":
                    item["query"] = "tampered T01 query"
            path.write_text(json.dumps(data), encoding="utf-8")
            errors = validate_repo.check_trigger_counts(path)
            self.assertTrue(
                any("T01 query mismatch" in error for error in errors), errors
            )

    def test_trigger_n01_expect_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trigger_queries.json"
            data = _valid_trigger_fixture()
            for item in data["should_not_trigger"]:
                if item["id"] == "N01":
                    item["expect"] = "tampered N01 expectation"
            path.write_text(json.dumps(data), encoding="utf-8")
            errors = validate_repo.check_trigger_counts(path)
            self.assertTrue(
                any("N01 expect mismatch" in error for error in errors), errors
            )

    def test_ci_env_run_forgery_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (workflow / "validate.yml").write_text(
                """jobs:
  test:
    steps:
      - name: forged validator
        env:
          run: python scripts/validate_repo.py --strict
      - name: forged tests
        env:
          run: python -m unittest discover -s tests -p "test_*.py"
      - run: echo noop
""",
                encoding="utf-8",
            )
            errors = validate_repo.check_ci_consistency(root)
            self.assertTrue(errors, errors)
            self.assertTrue(
                any("does not execute" in error for error in errors), errors
            )

    def test_ci_comment_only_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (workflow / "validate.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    steps:\n"
                "      # run: python scripts/validate_repo.py --strict\n"
                '      # run: python -m unittest discover -s tests -p "test_*.py"\n'
                "      - run: echo noop\n",
                encoding="utf-8",
            )
            errors = validate_repo.check_ci_consistency(root)
            self.assertTrue(errors, errors)
            self.assertTrue(
                any("does not execute" in error for error in errors), errors
            )

    def test_ci_statically_disabled_step_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (workflow / "validate.yml").write_text(
                """jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: disabled validator
        if: ${{ false }}
        run: python scripts/validate_repo.py --strict
      - name: disabled tests
        if: ${{ false }}
        run: python -m unittest discover -s tests -p "test_*.py"
      - run: echo noop
""",
                encoding="utf-8",
            )
            errors = validate_repo.check_ci_consistency(root)
            self.assertTrue(errors, errors)
            self.assertTrue(
                any("does not execute" in error for error in errors), errors
            )

    def test_ci_env_steps_forgery_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (workflow / "validate.yml").write_text(
                """jobs:
  test:
    runs-on: ubuntu-latest
    env:
      steps:
        - run: python scripts/validate_repo.py --strict
        - run: python -m unittest discover -s tests -p "test_*.py"
    steps:
      - run: echo noop
""",
                encoding="utf-8",
            )
            errors = validate_repo.check_ci_consistency(root)
            self.assertTrue(errors, errors)
            self.assertTrue(
                any("does not execute" in error for error in errors), errors
            )

    def test_ci_env_jobs_forgery_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows"
            workflow.mkdir(parents=True)
            text = """name: invalid-workflow

env:
  jobs:
    fake:
      steps:
        - run: python scripts/validate_repo.py --strict
        - run: python -m unittest discover -s tests -p "test_*.py"
"""
            (workflow / "validate.yml").write_text(text, encoding="utf-8")
            self.assertEqual(validate_repo.collect_run_commands(text), [])
            errors = validate_repo.check_ci_consistency(root)
            self.assertTrue(errors, errors)
            self.assertTrue(
                any("does not execute" in error for error in errors), errors
            )

    def test_ci_valid_workflow_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (workflow / "validate.yml").write_text(
                """name: valid-workflow

on:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/validate_repo.py --strict
      - run: python -m unittest discover -s tests -p "test_*.py"
""",
                encoding="utf-8",
            )
            self.assertEqual(validate_repo.check_ci_consistency(root), [])

    def test_ci_consistency_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (workflow / "validate.yml").write_text(
                "run: echo not-the-real-command\n", encoding="utf-8"
            )
            errors = validate_repo.check_ci_consistency(root)
            self.assertTrue(
                any("validate_repo.py --strict" in error for error in errors),
                errors,
            )
            self.assertTrue(
                any("unittest discover" in error for error in errors), errors
            )


if __name__ == "__main__":
    unittest.main()
