#!/usr/bin/env python3
"""Validate a private Loji judgment ledger.

Usage:
    python scripts/validate_judgments.py [JUDGMENTS.md]

Exit codes:
    0  ledger is valid
    1  ledger is malformed or violates the schema
    2  ledger is missing or unreadable

Authorization boundary:
- Run directly by a user, this is an explicit local maintenance action on the
  user's own file. It reads only the named path, never writes, and never
  derives policy from the ledger.
- An agent must not invoke this command (or read the ledger) to bypass the
  host memory/judgment policy. Maintenance, validation, and troubleshooting
  are not authorization. The CLI stores no permission state.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # imported as scripts.validate_judgments
    from . import memory_io
    from .judgment_ledger import (
        JudgmentParseError,
        parse_ledger,
        validate_judgments,
    )

    read_text = memory_io.read_text
except ImportError:  # executed directly as scripts/validate_judgments.py
    from memory_io import read_text  # type: ignore[no-redef]

    from judgment_ledger import (  # type: ignore[no-redef]
        JudgmentParseError,
        parse_ledger,
        validate_judgments,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a private Loji JUDGMENTS.md ledger."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="JUDGMENTS.md",
        help="ledger path (default: JUDGMENTS.md)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.path).expanduser()

    if not path.exists():
        print(f"error: ledger not found: {path}", file=sys.stderr)
        return 2
    if path.is_dir():
        print(f"error: ledger path is a directory: {path}", file=sys.stderr)
        return 2

    try:
        text = read_text(path)
    except OSError as exc:
        print(f"error: cannot read ledger: {exc}", file=sys.stderr)
        return 2

    try:
        document = parse_ledger(text)
        errors = validate_judgments(document.judgments)
    except JudgmentParseError as exc:
        print(f"ERROR: {exc}")
        print("FAILED: 1 error(s)")
        return 1

    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1

    print(
        f"OK: {len(document.judgments)} judgment(s), "
        f"schema_version={document.schema_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
