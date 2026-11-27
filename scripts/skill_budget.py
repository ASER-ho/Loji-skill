#!/usr/bin/env python3
"""Enforce the budget of Loji's always-loaded Skill."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_LINES = 250
MAX_HAN = 3900
MAX_PARAGRAPH = 120
SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"

HAN = re.compile(r"[\u4e00-\u9fff]")
FENCE = re.compile(r"(`{3,}|~{3,})(.*)")
LIST_ITEM = re.compile(r"(?:[-+*]|\d{1,9}[.)])\s+")
STRUCTURE = re.compile(r"#{1,6}(?:\s|$)|>|\|.*\|$")
THEMATIC_BREAK = re.compile(r"([-*_])(?:\s*\1){2,}$")


@dataclass(frozen=True)
class SkillBudget:
    lines: int
    han: int
    paragraphs: tuple[tuple[int, int], ...]

    @property
    def longest_paragraph(self) -> int:
        return max((length for _, length in self.paragraphs), default=0)

    def errors(self, *, max_lines: int = MAX_LINES) -> list[str]:
        errors: list[str] = []
        if self.lines > max_lines:
            errors.append(f"SKILL.md: {self.lines} physical lines > {max_lines}")
        if self.han > MAX_HAN:
            errors.append(f"SKILL.md: {self.han} Han characters > {MAX_HAN}")
        for line, length in self.paragraphs:
            if length > MAX_PARAGRAPH:
                errors.append(
                    f"SKILL.md:{line}: prose paragraph of {length} characters"
                    f" > {MAX_PARAGRAPH}. Split the prose into shorter paragraphs or a list."
                )
        return errors


def _paragraphs(lines: list[str]) -> tuple[tuple[int, int], ...]:
    first = 0
    if lines and lines[0] == "---":
        try:
            first = lines.index("---", 1) + 1
        except ValueError:
            pass

    paragraphs: list[tuple[int, int]] = []
    pending: list[str] = []
    start = 0
    fence = ""
    item_indent = 0
    for number, raw in enumerate(lines[first:], first + 1):
        expanded = raw.expandtabs(4)
        line = expanded.strip()
        indent = len(expanded) - len(expanded.lstrip())
        marker = FENCE.fullmatch(line)
        item = LIST_ITEM.match(line)

        if fence:
            if (
                marker
                and marker[1].startswith(fence)
                and not marker[2].strip()
            ):
                fence = ""
            continue
        if marker:
            kind = "fence"
        elif not line:
            kind = "blank"
        elif STRUCTURE.match(line) or THEMATIC_BREAK.match(line):
            kind = "structure"
        elif item:
            kind = "list"
        elif item_indent and indent >= item_indent:
            kind = "structure"
        elif indent >= 4 and not pending:
            kind = "code"
        else:
            kind = "prose"

        if kind == "prose":
            if not pending:
                start = number
            pending.append(line)
        elif pending:
            paragraphs.append((start, len(" ".join(pending))))
            pending.clear()

        if kind == "list":
            item_indent = indent + item.end()
        elif line and indent < item_indent:
            item_indent = 0
        if kind == "fence":
            fence = marker[1]

    if pending:
        paragraphs.append((start, len(" ".join(pending))))
    return tuple(paragraphs)


def measure(text: str) -> SkillBudget:
    lines = text.splitlines()
    return SkillBudget(len(lines), len(HAN.findall(text)), _paragraphs(lines))


def main() -> int:
    try:
        budget = measure(SKILL.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        print(f"ERROR: SKILL.md: {exc}")
        return 1
    errors = budget.errors()
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(
        f"OK: SKILL.md within budget ({budget.lines} lines, {budget.han} Han characters,"
        f" longest prose paragraph {budget.longest_paragraph} characters)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
