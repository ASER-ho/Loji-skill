"""Deterministic checks for Loji runtime state-machine invariants.

The checker is deliberately data-driven through
``tests/fixtures/state_invariants.json`` so that positive and negative
cases can be exercised without touching the real runtime files.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "state_invariants.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def check_text(rel_path: str, text: str, fixture: dict | None = None) -> list[str]:
    """Check one runtime file's text against the invariant fixture."""
    fixture = fixture or load_fixture()
    errors: list[str] = []

    for phrase in fixture.get("required_phrases", {}).get(rel_path, []):
        if phrase not in text:
            errors.append(f"{rel_path}: missing required phrase: {phrase}")

    for phrase in fixture.get("forbidden_phrases", {}).get(rel_path, []):
        if phrase in text:
            errors.append(f"{rel_path}: forbidden phrase present: {phrase}")

    lines = text.splitlines()
    for row in fixture.get("route_trigger_rows", []):
        if row.get("file") != rel_path:
            continue
        marker = row["marker"]
        matching = [line for line in lines if marker in line]
        if not matching:
            errors.append(f"{rel_path}: route row marker not found: {marker}")
            continue
        for line in matching:
            for token in row.get("forbidden", []):
                if token in line:
                    errors.append(
                        f"{rel_path}: forbidden route trigger token "
                        f"'{token}' in: {line.strip()}"
                    )

    return errors


def check(root: Path | str | None = None) -> list[str]:
    """Check all runtime files under ``root`` and return error strings."""
    base = Path(root) if root is not None else ROOT
    fixture = load_fixture()
    errors: list[str] = []

    for rel_path in fixture.get("runtime_files", []):
        path = base / rel_path
        if not path.exists():
            errors.append(f"{rel_path}: file not found")
            continue
        errors.extend(check_text(rel_path, path.read_text(encoding="utf-8"), fixture))

    return errors


class StateInvariantTests(unittest.TestCase):
    def test_repository_invariants(self) -> None:
        self.assertEqual(check(ROOT), [])

    def test_negative_injected_military_route(self) -> None:
        bad = '| **统辖** | "效率优先""军服" | 效率>一切 |'
        errors = check_text("references/STATE_MACHINES.md", bad)
        self.assertTrue(any("军服" in error for error in errors), errors)

    def test_negative_injected_servant_route(self) -> None:
        bad = '| "温柔一点""常服""征酱" | **人民公仆** | 温度>效率 |'
        errors = check_text("references/LORE.md", bad)
        self.assertTrue(
            any("常服" in error or "征酱" in error for error in errors),
            errors,
        )

    def test_negative_missing_required_phrase(self) -> None:
        errors = check_text("references/STATE_MACHINES.md", "no version here")
        self.assertTrue(
            any("版本对应" in error for error in errors),
            errors,
        )


if __name__ == "__main__":
    unittest.main()
