#!/usr/bin/env python3
"""Upgrade an installed Loji-skill copy without touching user data.

README repeatedly warns users not to re-clone over an existing install, because
a plain copy would overwrite ``memory.md``, ``JUDGMENTS.md`` and
``memory.state.json``. This script performs that upgrade safely:

1. verify the target really is a Loji-skill installation;
2. back up every user-data file before anything is written;
3. stage the new content from a local directory, a ``.tar.gz`` or a ``.zip``;
4. copy staged files in, never overwriting user data;
5. re-run the repository validators that shipped with the new content;
6. roll back automatically if any step fails.

Nothing is deleted: files that exist only in the old install stay in place, so
a failed or partial upgrade is always recoverable.

Usage:
    python scripts/upgrade.py --source path/to/Loji-skill-master
    python scripts/upgrade.py --source master.tar.gz --root ~/.codex/skills/loji-skill
    python scripts/upgrade.py --dry-run
    python scripts/upgrade.py --list-backups

Exit codes:
    0  upgrade completed, or dry run finished
    1  upgrade failed and was rolled back
    2  invalid arguments or target
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ARCHIVE_URL = (
    "https://codeload.github.com/ASER-ho/Loji-skill/tar.gz/refs/heads/master"
)
BACKUP_DIR_NAME = ".upgrade-backup"

# User data. Never overwritten by an upgrade, always backed up first.
PROTECTED_EXACT = ("memory.md", "JUDGMENTS.md", "memory.state.json")
PROTECTED_PREFIXES = ("memory.md.", "JUDGMENTS.md.")
# Local-only directories that never come from upstream and never get replaced.
SKIP_DIRS = {".git", BACKUP_DIR_NAME, "__pycache__", "node_modules", ".venv"}

REQUIRED_MARKERS = ("SKILL.md", "references/LORE.md")
VALIDATORS = ("scripts/validate_repo.py", "scripts/check_docs_consistency.py")


class UpgradeError(RuntimeError):
    """Any condition that must abort the upgrade."""


def is_protected(path: Path) -> bool:
    name = path.name
    if name in PROTECTED_EXACT:
        return True
    return any(name.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def resolve_root(raw: str | None) -> Path:
    root = Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()
    if not (root / "SKILL.md").is_file():
        raise UpgradeError(
            f"{root} does not look like a Loji-skill install: SKILL.md is missing. "
            "Pass --root <install directory>."
        )
    for marker in REQUIRED_MARKERS:
        if not (root / marker).exists():
            raise UpgradeError(f"{root} is missing {marker}; refusing to upgrade.")
    return root


def stage_source(source: str | None, workdir: Path) -> Path:
    """Materialise the incoming tree and return its root directory."""
    if source is None:
        print(f"Downloading {DEFAULT_ARCHIVE_URL}")
        try:
            with urllib.request.urlopen(DEFAULT_ARCHIVE_URL, timeout=60) as response:
                blob = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise UpgradeError(
                f"download failed ({exc}). Pass --source with a local checkout or archive."
            ) from exc
        archive = workdir / "master.tar.gz"
        archive.write_bytes(blob)
        return extract(archive, workdir)

    location = Path(source).expanduser().resolve()
    if location.is_dir():
        return location
    if not location.is_file():
        raise UpgradeError(f"--source not found: {location}")
    return extract(location, workdir)


def extract(archive: Path, workdir: Path) -> Path:
    target = workdir / "src"
    target.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive) or archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if member.startswith("/") or ".." in Path(member).parts:
                    raise UpgradeError(f"archive member escapes the tree: {member}")
            zf.extractall(target)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                if member.name.startswith("/") or ".." in Path(member.name).parts:
                    raise UpgradeError(f"archive member escapes the tree: {member.name}")
                if member.issym() or member.islnk():
                    raise UpgradeError(f"archive contains a link: {member.name}")
            tf.extractall(target)
    else:
        raise UpgradeError(f"unsupported archive type: {archive}")

    # GitHub archives wrap everything in one top-level directory.
    entries = [entry for entry in target.iterdir() if entry.name not in SKIP_DIRS]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return target


def iter_files(base: Path):
    for path in sorted(base.rglob("*")):
        relative = path.relative_to(base)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.is_file():
            yield relative, path


def backup(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = root / BACKUP_DIR_NAME / stamp
    destination.mkdir(parents=True, exist_ok=False)
    saved = 0
    for name in PROTECTED_EXACT:
        source = root / name
        if source.exists():
            shutil.copy2(source, destination / name)
            saved += 1
    for path in root.iterdir():
        if path.is_file() and path.name.startswith(PROTECTED_PREFIXES):
            shutil.copy2(path, destination / path.name)
            saved += 1
    print(f"Backup: {destination} ({saved} file(s))")
    if saved == 0:
        print("Note: no user data files found; nothing needed protecting.")
    return destination


def apply(root: Path, source: Path, dry_run: bool, rollback_dir: Path | None = None) -> list[str]:
    written: list[str] = []
    total = 0
    for relative, path in iter_files(source):
        total += 1
        if is_protected(relative):
            print(f"  skip (user data): {relative}")
            continue
        destination = root / relative
        if dry_run:
            changed = not destination.exists() or destination.read_bytes() != path.read_bytes()
            if changed:
                written.append(str(relative))
            continue
        if rollback_dir is not None and destination.is_file():
            saved = rollback_dir / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        written.append(str(relative))
    print(f"Source files: {total}; {'would update' if dry_run else 'updated'}: {len(written)}")
    return written


def run_validator(root: Path, script: str) -> None:
    path = root / script
    if not path.exists():
        print(f"Validator absent, skipped: {script}")
        return
    print(f"Running {script}")
    result = subprocess.run([sys.executable, str(path)], cwd=root)
    if result.returncode != 0:
        raise UpgradeError(f"{script} failed with exit code {result.returncode}")


def restore(root: Path, snapshot: Path) -> None:
    if not snapshot.exists():
        return
    for path in snapshot.iterdir():
        if path.is_file():
            shutil.copy2(path, root / path.name)
    print(f"Restored user data from {snapshot}")


def restore_tree(root: Path, rollback_dir: Path | None) -> None:
    """Put every file that the upgrade overwrote back to its previous content."""
    if rollback_dir is None or not rollback_dir.exists():
        print("Note: no previously existing files were overwritten.")
        return
    restored = 0
    for relative, path in iter_files(rollback_dir):
        shutil.copy2(path, root / relative)
        restored += 1
    print(f"Restored {restored} overwritten file(s) from the pre-upgrade snapshot")


def list_backups(root: Path) -> int:
    store = root / BACKUP_DIR_NAME
    if not store.exists():
        print("No backups recorded.")
        return 0
    for entry in sorted(store.iterdir()):
        if entry.is_dir():
            count = sum(1 for _ in entry.iterdir())
            print(f"{entry.name}  ({count} file(s))")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upgrade an installed Loji-skill copy, protecting user data."
    )
    parser.add_argument("--source", help="local checkout or .tar.gz/.zip archive")
    parser.add_argument("--root", help="install directory (default: current directory)")
    parser.add_argument("--dry-run", action="store_true", help="report changes only")
    parser.add_argument("--list-backups", action="store_true", help="list backups and exit")
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="do not run the repository validators after copying",
    )
    args = parser.parse_args(argv)

    try:
        root = resolve_root(args.root)
        if args.list_backups:
            return list_backups(root)

        with tempfile.TemporaryDirectory(prefix="loji-upgrade-") as tmp:
            source = stage_source(args.source, Path(tmp))
            if not (source / "SKILL.md").is_file():
                raise UpgradeError(f"staged source has no SKILL.md: {source}")

            rollback_dir = Path(tmp) / "rollback"
            rollback_dir.mkdir(parents=True, exist_ok=True)

            print(f"Target: {root}")
            snapshot = backup(root) if not args.dry_run else None
            written = apply(root, source, args.dry_run, rollback_dir)
            if args.dry_run:
                print("Dry run complete; nothing was written.")
                return 0

            try:
                if not args.skip_validate:
                    for script in VALIDATORS:
                        run_validator(root, script)
            except UpgradeError:
                restore_tree(root, rollback_dir)
                if snapshot is not None:
                    restore(root, snapshot)
                raise

        print(f"Upgrade complete: {len(written)} file(s) updated.")
        print(f"Rollback available at {root / BACKUP_DIR_NAME}")
        return 0
    except UpgradeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
