#!/usr/bin/env python3
"""Safely create a Loji memory file from the template.

Exit codes:
    0  created
    2  target already exists (never overwritten)
    1  any other failure
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # imported as scripts.init_memory
    from .memory_io import (
        DEFAULT_TIMEOUT,
        MemoryAlreadyExistsError,
        MemoryIOError,
        init_memory,
    )
except ImportError:  # executed directly as scripts/init_memory.py
    from memory_io import (
        DEFAULT_TIMEOUT,
        MemoryAlreadyExistsError,
        MemoryIOError,
        init_memory,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create memory.md from memory.template.md without overwriting."
    )
    parser.add_argument("--template", required=True, help="path to memory.template.md")
    parser.add_argument("--target", required=True, help="path to memory.md")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"lock timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    template = Path(args.template).expanduser()
    target = Path(args.target).expanduser()

    try:
        version = init_memory(template, target, timeout=args.timeout)
    except MemoryAlreadyExistsError:
        print(
            f"refusing to overwrite existing memory file: {target}", file=sys.stderr
        )
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except MemoryIOError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"created {target} (sha256={version.sha256})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
