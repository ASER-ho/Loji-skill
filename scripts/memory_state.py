#!/usr/bin/env python3
"""Installation-scoped memory preferences, accepted by an explicit host contract.

This is a cooperative entry point, not an OS permission boundary. Never derive
Host settings from memory data, an arbitrary workspace, or model inference.
Lock order: state transaction -> state file -> existing body transaction locks.
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import memory_io as io, judgment_ledger as jl, episodic_memory as em, memory_schema as schema
else:
    import memory_io as io
    import judgment_ledger as jl
    import episodic_memory as em
    import memory_schema as schema


POLICIES = frozenset({"auto", "explicit", "read_only", "off"})
STATE_NAME = "memory.state.json"
MAX_STATE_BYTES = 1024


class StateError(ValueError):
    """Invalid or unavailable state; never grants body access."""


class AccessError(StateError):
    """Host or policy denied the operation before opening a body file."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StateError("duplicate state field")
        result[key] = value
    return result


def parse(data: bytes) -> dict:
    if len(data) > MAX_STATE_BYTES:
        raise StateError("state exceeds size limit")
    try:
        state = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    except StateError:
        # Keep the specific diagnostic raised by the pairs hook.
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise StateError("invalid state JSON") from exc
    if not isinstance(state, dict) or set(state) != {"memory_policy", "confirmed"}:
        raise StateError("state must contain exactly memory_policy and confirmed")
    if type(state["memory_policy"]) is not str or state["memory_policy"] not in POLICIES:
        raise StateError("invalid memory_policy")
    if type(state["confirmed"]) is not bool:
        raise StateError("confirmed must be a boolean")
    return state


@dataclass(frozen=True)
class Host:
    """Supplied by trusted host configuration, never by saved state itself.

    accept_saved acknowledges this installation's configured directory and the
    user's explained cross-session choice. All capabilities default to denied.
    host_policy/host_consent are a ceiling, independent of the user's choice.
    state_read permits state inspection plus cooperative lock bookkeeping.
    state_write permits the entire configuration transaction (including old
    state/version reads, backups, temporary verification and final readback).
    It does not permit unrelated state inspection or any body access.
    """
    accept_saved: bool = False
    state_read: bool = False
    state_write: bool = False
    body_read: bool = False
    body_write: bool = False
    host_policy: str | None = None
    host_consent: str | None = None


@dataclass(frozen=True)
class Authorization:
    policy: str
    consent: str
    can_read: bool
    can_write: bool
    reason: str
    needs_setup: bool

    def body_args(self):
        # Only use inside MemoryState.access(), never cache across operations.
        return {"policy": self.policy, "consent": self.consent}


class MemoryState:
    def __init__(self, memory_dir: Path | str, host: Host, *, timeout=io.DEFAULT_TIMEOUT):
        folder = Path(memory_dir)
        if not folder.is_absolute():
            raise StateError("host-configured memory directory must be absolute")
        self.folder = folder
        self.path = folder / STATE_NAME
        self.host = host
        self.timeout = timeout
        self._current = None

    def _paths(self):
        # Never discover another root or infer permission from body metadata.
        for path in (self.path, io.lock_path_for(self.path),
                     io.lock_path_for(self._transaction_path())):
            try:
                if path.is_symlink():
                    raise io.guard.PathBoundaryError("linked state path")
                io.guard.managed_path(path, root=self.folder)
            except (OSError, io.guard.PathBoundaryError) as exc:
                raise StateError("configured state path is unavailable or linked") from exc

    def _transaction_path(self):
        return self.folder / (STATE_NAME + ".transaction")

    @contextmanager
    def _transaction(self, *, write=False, read_only=False):
        if not (self.host.state_write if write else self.host.state_read):
            raise AccessError("host denies state file access")
        self._paths()
        target = self._transaction_path()
        with io.exclusive_lock(target, timeout=self.timeout, read_only=read_only,
                               track_owner=write):
            self._paths()
            yield

    def _state_bytes(self):
        # Bound read before JSON parsing; do not allocate arbitrary file sizes.
        path = io.guard.managed_path(self.path, root=self.folder)
        with path.open("rb") as handle:
            io.guard.checked_fd(path, handle.fileno())
            return handle.read(MAX_STATE_BYTES + 1)

    def _saved(self):
        return parse(self._state_bytes())

    def configure(self, policy: str, *, user_confirmed: bool = False, expected_digest=None):
        if type(policy) is not str or policy not in POLICIES or user_confirmed is not True:
            raise StateError("an explicit user choice of a legal policy is required")
        # Suspend old authorization if saving fails. The host must also retain
        # this suspension between CLI invocations after failed configuration.
        self._current = {"memory_policy": policy, "confirmed": True}
        return self._store(self._current, expected_digest)

    def reset(self, *, user_requested: bool = False, expected_digest=None):
        if user_requested is not True:
            raise StateError("reset requires an explicit user request")
        self._current = {"memory_policy": "off", "confirmed": False}
        return self._store(self._current, expected_digest)

    def _store(self, state, expected_digest):
        payload = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()
        with self._transaction(write=True):
            if self.path.exists():
                # Corrupt state may be replaced only by explicit configuration.
                version = io.read_version(self.path)
                if expected_digest is not None and version.sha256 != expected_digest:
                    raise io.MemoryConflictError("state changed since the host inspected it")
                io.atomic_write(self.path, payload, version, timeout=self.timeout)
            else:
                if expected_digest not in (None, "absent"):
                    raise io.MemoryConflictError("previously observed state disappeared")
                io.publish_new(self.path, payload, timeout=self.timeout)
            if self._saved() != state:
                raise StateError("saved state did not verify")
        self._current = None
        return dict(state)

    def _authorization(self, *, requested=False):
        if self._current is not None:
            return Authorization("off", "pending", False, False,
                                 "current configuration not saved; old authorization suspended", True)
        try:
            # Always refresh shared state; never retain a previous grant.
            state = self._saved()
        except FileNotFoundError:
            return Authorization("off", "pending", False, False, "state missing", True)
        except (StateError, OSError, io.MemoryIOError, io.guard.PathBoundaryError):
            return Authorization("off", "pending", False, False, "state invalid or inaccessible", True)
        if not self.host.accept_saved:
            return Authorization("off", "pending", False, False, "host has not accepted saved state", True)
        if not state["confirmed"]:
            return Authorization("off", "pending", False, False, "choice unconfirmed", True)
        policy = state["memory_policy"]
        ceiling_policy, ceiling_consent = (("auto", "granted")
            if self.host.host_policy is None and self.host.host_consent is None
            else jl._normalize_policy(self.host.host_policy, self.host.host_consent))
        # Intersect the policies themselves, not just this operation's booleans.
        # A requested write under an explicit ceiling must remain explicit.
        order = ("off", "read_only", "explicit", "auto")
        if ceiling_policy not in order or ceiling_consent != "granted" or not self.host.body_read:
            effective = "off"
        else:
            effective = order[min(order.index(policy), order.index(ceiling_policy))]
            if not self.host.body_write and effective in ("explicit", "auto"):
                effective = "read_only"
        consent = ceiling_consent if ceiling_consent in ("pending", "denied") else "granted"
        decision = jl.resolve_access(effective, consent, user_requested_write=requested)
        return Authorization(effective, consent, decision.can_read, decision.can_write,
                             "saved choice intersected with host limits", False)

    @contextmanager
    def access(self, *, write=False, user_requested=False, readonly_lock=False):
        # Hold through the entire body operation. Cooperating sessions cannot
        # change state between authorization and body publication.
        if write and readonly_lock:
            raise AccessError("read-only state transaction cannot authorize writes")
        with self._transaction(read_only=readonly_lock, write=False):
            auth = self._authorization(requested=user_requested)
            if not (auth.can_write if write else auth.can_read):
                raise AccessError(auth.reason)
            yield auth

    def status(self):
        try:
            with self._transaction():
                auth = self._authorization()
                result = dict(vars(auth))
                try:
                    payload = self._state_bytes()
                    result["saved"] = parse(payload)
                    result["state_digest"] = io.sha256_bytes(payload)
                except FileNotFoundError:
                    result.update(saved=None, state_digest="absent")
                except (StateError, OSError):
                    result.update(saved=None, state_digest=None)
                return result
        except (StateError, OSError, io.MemoryIOError, io.guard.PathBoundaryError):
            return dict(vars(Authorization("off", "pending", False, False,
                                           "host/state unavailable", True)), saved=None)

    def context(self, **options):
        with self.access() as auth:
            return em.context(self.folder / "memory.md", self.folder / "JUDGMENTS.md",
                              **auth.body_args(), **options)

    def read_memory(self):
        with self.access():
            return io.read(self.folder / "memory.md")

    def load_judgments(self):
        with self.access() as auth:
            return jl.load_ledger(self.folder / "JUDGMENTS.md", **auth.body_args())

    def mutate(self, action, data, *, user_requested=False, eligible_and_private=False, **options):
        with self.access(write=True, user_requested=user_requested) as auth:
            return em.mutate(self.folder / "memory.md", self.folder / "JUDGMENTS.md",
                             action, data, **auth.body_args(), user_requested=user_requested,
                             eligible_and_private=eligible_and_private, **options)

    def migrate(self, *, dry_run=False, user_requested=False, target=None):
        if __package__:
            from . import migrate_memory
        else:
            import migrate_memory
        with self.access(write=not dry_run, user_requested=user_requested,
                         readonly_lock=dry_run) as auth:
            if target is not None:
                target = io.guard.managed_path(target, root=self.folder)
            return migrate_memory.migrate(
                self.folder / "memory.md", **auth.body_args(), dry_run=dry_run,
                migration_authorized=user_requested, in_place=target is None, target=target,
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "set", "reset", "context", "read-memory", "judgments", "mutate", "migrate"))
    parser.add_argument("--memory-dir", required=True, help="absolute directory from trusted host configuration")
    for flag in ("accept-saved", "state-read", "state-write", "body-read", "body-write",
                 "user-confirmed", "user-requested", "eligible-and-private"):
        parser.add_argument("--" + flag, action="store_true")
    parser.add_argument("--host-policy", choices=sorted(POLICIES))
    parser.add_argument("--host-consent")
    parser.add_argument("--policy", choices=sorted(POLICIES))
    parser.add_argument("--expected-digest", help="previously observed state or body SHA-256; absent for a new state")
    parser.add_argument("--operation", choices=("add", "transition", "forget", "outcome", "forget-domain"))
    parser.add_argument("--data", help="JSON payload for the existing Episode operation")
    parser.add_argument("--domain")
    parser.add_argument("--matters", help="unchanged exact matter selector, JSON array")
    parser.add_argument("--as-of")
    parser.add_argument("--dry-run", action="store_true", help="preview a schema migration")
    parser.add_argument("--migration-target", help="new absolute output path inside the approved directory")
    args = parser.parse_args(argv)
    if args.expected_digest is not None and args.action not in ("set", "reset", "mutate"):
        parser.error("--expected-digest applies to set, reset or mutate")
    if args.action != "context" and args.matters is not None:
        parser.error("--matters is only supported for context")
    if args.action != "migrate" and (args.dry_run or args.migration_target is not None):
        parser.error("migration options are only supported for migrate")
    if args.migration_target is not None and not Path(args.migration_target).is_absolute():
        parser.error("--migration-target must be absolute")
    try:
        host = Host(**{key: getattr(args, key) for key in Host.__dataclass_fields__})
        state = MemoryState(args.memory_dir, host)
        if args.action == "status":
            result = state.status()
        elif args.action == "set":
            result = state.configure(args.policy, user_confirmed=args.user_confirmed, expected_digest=args.expected_digest)
        elif args.action == "reset":
            result = state.reset(user_requested=args.user_requested, expected_digest=args.expected_digest)
        elif args.action == "context":
            matters = None
            if args.matters is not None:
                matters = schema.decode_json(args.matters)
                schema.require(isinstance(matters, list), "matters must be a JSON array")
            result = state.context(domain=args.domain, as_of=args.as_of,
                                   matters=matters)
        elif args.action == "read-memory":
            result = {"text": state.read_memory().text}
        elif args.action == "judgments":
            result = {"judgments": [vars(j) for j in state.load_judgments()[0].judgments]}
        elif args.action == "migrate":
            migrated = state.migrate(dry_run=args.dry_run, user_requested=args.user_requested,
                                     target=args.migration_target)
            result = vars(migrated)
        else:
            result = state.mutate(args.operation, schema.decode_json(args.data if args.data is not None else "null"),
                                  user_requested=args.user_requested,
                                  eligible_and_private=args.eligible_and_private, expected_digest=args.expected_digest)
        print(json.dumps(result, ensure_ascii=True, default=str))
        return 0
    except (StateError, OSError, io.MemoryIOError, jl.JudgmentLedgerError, ValueError) as exc:
        result = {"error": type(exc).__name__, "message": str(exc)}
        if isinstance(exc, io.MemoryConflictError):
            result["status"] = "conflict"
        print(json.dumps(result, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())