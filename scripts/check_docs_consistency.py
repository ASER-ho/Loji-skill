#!/usr/bin/env python3
"""Release documentation consistency check for Loji-skill.

The skill version appears in several human-maintained places. ``npm run
check:meta`` only compares ``SKILL.md`` with ``loji-dsh/lib/skill-meta.json``,
so a release that bumps the skill without touching ``CHANGELOG.md``,
``ROADMAP.md`` or ``loji-dsh/README.md`` stays green in CI while the published
documents describe a different version. This script closes that gap.

It checks:

1. ``SKILL.md`` frontmatter ``metadata.version`` exists and is semver.
2. ``loji-dsh/lib/skill-meta.json`` agrees with it.
3. ``loji-dsh/README.md`` "Current bundled skill version" agrees with it.
4. ``ROADMAP.md`` "Current release" agrees with it.
5. ``CHANGELOG.md`` opens with that version, or with an explicit
   ``## Unreleased`` section that is then reported as a warning.
6. ``package.json`` version agrees with the documented "Initial package
   version"; package and skill versions stay independent by design.

An unreleased section is allowed while work is in flight, but it must be
mirrored in ``ROADMAP.md`` so the two documents cannot drift apart silently.

Exit codes:
    0  all checks passed (warnings allowed)
    1  one or more checks failed
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
SKILL_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.DOTALL)
ROADMAP_RELEASE = re.compile(r"^##\s+Current release:\s*v?(\d+\.\d+\.\d+)\s*$", re.MULTILINE)
CHANGELOG_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)
CHANGELOG_VERSION = re.compile(r"^v?(\d+\.\d+\.\d+)")
README_SKILL_VERSION = re.compile(
    r"Current bundled skill version\s*\|\s*v?(\d+\.\d+\.\d+)"
)
README_PACKAGE_VERSION = re.compile(
    r"Initial package version\s*\|\s*v?(\d+\.\d+\.\d+)"
)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def read(path: Path, report: Report, label: str) -> str | None:
    if not path.exists():
        report.error(f"{label}: missing")
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        report.error(f"{label}: not valid UTF-8 ({exc}); these documents are UTF-8 only")
        return None


def skill_version(root: Path, report: Report) -> str | None:
    text = read(root / "SKILL.md", report, "SKILL.md")
    if text is None:
        return None
    matched = SKILL_FRONTMATTER.search(text)
    if not matched:
        report.error("SKILL.md: missing frontmatter block")
        return None
    in_metadata = False
    for line in matched.group(1).splitlines():
        if re.match(r"^metadata:\s*$", line):
            in_metadata = True
            continue
        if in_metadata and line and not line.startswith((" ", "\t")):
            in_metadata = False
        if in_metadata:
            found = re.match(r"^\s+version:\s*[\"']?(\d+\.\d+\.\d+)[\"']?\s*$", line)
            if found:
                return found.group(1)
    report.error("SKILL.md: metadata.version is unavailable")
    return None


def check_skill_meta(root: Path, version: str, report: Report) -> None:
    path = root / "loji-dsh" / "lib" / "skill-meta.json"
    text = read(path, report, "loji-dsh/lib/skill-meta.json")
    if text is None:
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        report.error(f"loji-dsh/lib/skill-meta.json: invalid JSON: {exc}")
        return
    recorded = data.get("version")
    if recorded != version:
        report.error(
            f"loji-dsh/lib/skill-meta.json: version={recorded!r}, expected {version!r} "
            "(run npm run sync:meta)"
        )


def check_dsh_readme(root: Path, version: str, report: Report) -> None:
    text = read(root / "loji-dsh" / "README.md", report, "loji-dsh/README.md")
    if text is None:
        return
    matched = README_SKILL_VERSION.search(text)
    if not matched:
        report.error(
            "loji-dsh/README.md: no 'Current bundled skill version' row to cross-check"
        )
    elif matched.group(1) != version:
        report.error(
            f"loji-dsh/README.md: bundled skill version={matched.group(1)!r}, "
            f"expected {version!r}"
        )


def check_roadmap(root: Path, version: str, report: Report) -> bool:
    text = read(root / "ROADMAP.md", report, "ROADMAP.md")
    if text is None:
        return False
    matched = ROADMAP_RELEASE.search(text)
    if not matched:
        report.error("ROADMAP.md: no '## Current release: vX.Y.Z' heading")
        return False
    if matched.group(1) != version:
        report.error(
            f"ROADMAP.md: Current release=v{matched.group(1)}, expected v{version}"
        )
    return "unreleased" in text.lower()


def check_changelog(root: Path, version: str, report: Report) -> bool:
    """Return True when the changelog opens with an unreleased section."""
    text = read(root / "CHANGELOG.md", report, "CHANGELOG.md")
    if text is None:
        return False
    matched = CHANGELOG_HEADING.search(text)
    if not matched:
        report.error("CHANGELOG.md: no '## ' version heading")
        return False
    heading = matched.group(1).strip()
    if heading.lower().startswith("unreleased"):
        report.warn(
            f"CHANGELOG.md: top section is {heading!r}; it must be turned into a "
            f"'## v<version>' heading and the version bumped before tagging a release"
        )
        return True
    found = CHANGELOG_VERSION.match(heading)
    if not found:
        report.error(f"CHANGELOG.md: unparsable top heading {heading!r}")
        return False
    if found.group(1) != version:
        report.error(
            f"CHANGELOG.md: top version=v{found.group(1)}, expected v{version}"
        )
    return False


def check_package_version(root: Path, report: Report) -> None:
    path = root / "package.json"
    text = read(path, report, "package.json")
    if text is None:
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        report.error(f"package.json: invalid JSON: {exc}")
        return
    package_version = data.get("version")
    if not isinstance(package_version, str) or not SEMVER.match(package_version):
        report.error(f"package.json: version={package_version!r} is not semver")
        return
    readme = read(root / "loji-dsh" / "README.md", report, "loji-dsh/README.md")
    if readme is None:
        return
    matched = README_PACKAGE_VERSION.search(readme)
    if not matched:
        report.error(
            "loji-dsh/README.md: no 'Initial package version' row to cross-check "
            "package.json"
        )
    elif matched.group(1) != package_version:
        report.error(
            f"loji-dsh/README.md: initial package version={matched.group(1)!r}, "
            f"package.json={package_version!r}"
        )


def run(root: Path = ROOT) -> Report:
    report = Report()
    version = skill_version(root, report)
    if version is None:
        return report
    check_skill_meta(root, version, report)
    check_dsh_readme(root, version, report)
    # package.json carries an independent package version.
    check_package_version(root, report)
    roadmap_unreleased = check_roadmap(root, version, report)
    changelog_unreleased = check_changelog(root, version, report)
    if changelog_unreleased and not roadmap_unreleased:
        report.error(
            "ROADMAP.md: CHANGELOG.md has an unreleased section but the roadmap does "
            "not mention it; the two documents must agree"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    # Windows CI runs Python with a legacy ANSI code page, and this script
    # quotes document excerpts that may be Chinese. Without an explicit UTF-8
    # stream every report line can raise UnicodeEncodeError and turn a green
    # check into a traceback.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    root = ROOT
    if argv:
        root = Path(argv[0]).resolve()
    report = run(root)
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    for error in report.errors:
        print(f"ERROR: {error}")
    if report.errors:
        print(f"FAILED: {len(report.errors)} error(s)")
        return 1
    print("OK: release documentation is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
