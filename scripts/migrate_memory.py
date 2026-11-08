#!/usr/bin/env python3
"""Explicit Memory schema migration; never run during initialization or recall."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import judgment_ledger, memory_io, memory_schema
else:
    import judgment_ledger
    import memory_io
    import memory_schema


class AccessError(PermissionError):
    """The host did not authorize this operation."""


@dataclass(frozen=True)
class MigrationResult:
    status: str
    backup: Path | None = None


def authorize(policy, consent, *, write=False, requested=False):
    if not isinstance(policy, str) or not isinstance(consent, str):
        raise AccessError("host policy/consent required")
    decision = judgment_ledger.resolve_access(policy, consent, user_requested_write=requested)
    if not decision.can_read or (write and not decision.can_write):
        raise AccessError(decision.reason)


def update(path, payload, snapshot):
    """Use the published Memory IO transaction and its guarded recovery."""
    try:
        return memory_io.atomic_write(path, payload, snapshot.version)
    except memory_io.MemoryPostWriteVerificationError as failure:
        if not failure.recovery_required:
            raise
        if (failure.published_version is None or failure.backup_path is None or
                failure.published_identity is None or not failure.published_identity[1]):
            raise memory_io.MemoryWriteError(
                f"verification failed; manual recovery required; backup={failure.backup_path}"
            ) from failure
        try:
            memory_io.restore_backup(
                failure.backup_path, path,
                expected_target_sha256=failure.intended_sha256,
                expected_target_version=failure.published_version,
                expected_target_identity=failure.published_identity,
                expected_backup_sha256=snapshot.version.sha256,
            )
        except (OSError, memory_io.MemoryIOError) as recovery:
            raise memory_io.MemoryWriteError(
                f"verification failed; recovery refused or failed ({recovery}); "
                f"backup={failure.backup_path}"
            ) from failure
        raise memory_io.MemoryWriteError(
            f"verification failed; original bytes restored; backup={failure.backup_path}"
        ) from failure


def migrate(
    source, *, policy, consent, dry_run=False, migration_authorized=False,
    in_place=False, target=None,
):
    """Migrate only the explicitly named source; dry-run does not acquire locks."""
    authorize(policy, consent, write=not dry_run, requested=migration_authorized)
    if not dry_run and migration_authorized is not True:
        raise AccessError("migration requires specific user authorization in every mode")
    if in_place == (target is not None):
        raise ValueError("choose exactly one of in-place migration or a separate target")
    source = Path(source)
    if source.is_symlink():
        raise ValueError("source must not be a symbolic link")
    target = source if in_place else Path(target)
    if not in_place and (
        source.resolve() == target.resolve() or target.exists() or target.is_symlink()
    ):
        raise memory_io.MemoryAlreadyExistsError("separate target must not exist")
    snapshot = memory_io.read(source)
    doc = memory_schema.parse(snapshot.text)
    if doc.version == 2:
        return MigrationResult("no_op")
    payload = memory_schema.upgrade(doc)
    if dry_run:
        return MigrationResult("would_migrate")
    if in_place:
        result = update(source, payload, snapshot)
        return MigrationResult("migrated", result.backup_path)

    def confirm_source():
        if memory_io.read_version(source) != snapshot.version:
            raise memory_io.MemoryConflictError("source changed before publication")

    with memory_io.exclusive_lock(source):
        confirm_source()
        memory_io.publish_new(target, payload.encode("utf-8"), before_publish=confirm_source)
    return MigrationResult("migrated")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--consent", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--in-place", action="store_true")
    target.add_argument("--target")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--authorize-migration", action="store_true",
                        help="assert explicit user authorization for this exact migration")
    args = parser.parse_args(argv)
    try:
        result = migrate(
            args.source, policy=args.policy, consent=args.consent, target=args.target,
            in_place=args.in_place, dry_run=args.dry_run,
            migration_authorized=args.authorize_migration,
        )
    except (OSError, ValueError, memory_io.MemoryIOError) as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1
    print({
        "no_op": "schema 2 valid; no changes",
        "would_migrate": "schema 1 valid; would set schema 2 and add two empty sections",
        "migrated": "schema 2 migrated",
    }[result.status])
    if result.backup:
        print(f"verified original backup: {result.backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
