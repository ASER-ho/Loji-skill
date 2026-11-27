"""Path, process, and crash-recovery guards for Loji's local state files."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

MIN_STALE_SECONDS = 60
TOKEN = re.compile(r"\.loji-(\d+)-(\d+)-([a-f0-9]{16})\.[A-Za-z0-9_-]+\.tmp\Z")
TARGETS = ("memory.md", "JUDGMENTS.md", "memory.state.json", "memory.state.json.transaction")


class PathBoundaryError(ValueError):
    """A local state path cannot be used within its approved scope."""


def identity(info):
    return (info.st_dev, info.st_ino)


def _plain(info):
    return not (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def managed_path(path, *, root=None, allow_hardlinks=False):
    """Reject traversal, linked components, and existing nonregular aliases.

    The approved root is supplied by the host when there is one. For legacy
    commands with an explicit target, its parent is the scope.
    """
    path = Path(path).absolute()
    base = Path(root).absolute() if root is not None else path.parent
    if ".." in path.parts or ".." in base.parts or base not in path.parents:
        raise PathBoundaryError("state path is outside the approved directory")
    for parent in reversed(path.parents):
        info = parent.lstat()
        if not _plain(info) or not stat.S_ISDIR(info.st_mode):
            raise PathBoundaryError("linked or non-directory state parent")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return path
    if (not _plain(info) or not stat.S_ISREG(info.st_mode) or
            (info.st_nlink != 1 and not allow_hardlinks)):
        raise PathBoundaryError("linked or nonregular state file")
    return path


def checked_fd(path, fd):
    """Refuse a mutable state file whose name changed while it was opened."""
    opened, named = os.fstat(fd), path.lstat()
    if (not _plain(named) or not stat.S_ISREG(opened.st_mode) or
            opened.st_nlink != 1 or identity(opened) != identity(named)):
        raise PathBoundaryError("state file changed during open")


def process_absent(pid):
    """Return true only when the local OS positively reports a missing PID."""
    if not 0 < pid <= 0x7FFFFFFF:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) has no POSIX liveness semantics on Windows.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, 0, pid)
        if handle:
            kernel.CloseHandle(handle)
            return False
        return ctypes.get_last_error() == 87  # ERROR_INVALID_PARAMETER: absent PID
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        pass
    return False


def stale_owner(pid, started_ns, *, min_age=MIN_STALE_SECONDS, now_ns=None):
    if now_ns is None:
        now_ns = time.time_ns()
    return 0 < started_ns <= now_ns - min_age * 1_000_000_000 and process_absent(pid)


def inspect_temps(target, *, root, owner=None, cleanup=False):
    """List this target's temp files under the caller-held kernel lock."""
    target = managed_path(target, root=root, allow_hardlinks=True)
    try:
        target_info = target.lstat()
    except FileNotFoundError:
        target_info = None
    if target.name not in TARGETS:
        raise PathBoundaryError("target is outside the Loji state file set")
    entries = []
    prefix = f"{target.name}.loji-"
    for item in sorted(target.parent.iterdir()):
        if not item.name.startswith(prefix):
            continue
        match = TOKEN.fullmatch(item.name[len(target.name):])
        if not match:
            continue
        try:
            managed_path(item, root=root, allow_hardlinks=True)
            info = item.lstat()
        except (FileNotFoundError, PathBoundaryError):
            continue
        pid, started_ns = map(int, match.groups()[:2])
        pending_publish = (
            target_info is not None and info.st_nlink == target_info.st_nlink == 2
            and identity(info) == identity(target_info) and owner is not None
            and owner.get("pid") == pid and owner.get("status") == "stale"
        )
        if info.st_nlink != 1 and not pending_publish:
            continue
        stale = stale_owner(pid, max(started_ns, info.st_mtime_ns))
        entries.append({"file": item.name, "status": "stale" if stale else "retained"})
        if cleanup and stale:
            managed_path(item, root=root, allow_hardlinks=pending_publish)
            if pending_publish and identity(target.lstat()) != identity(info):
                continue
            current = item.lstat()
            if identity(current) == identity(info) and current.st_nlink == info.st_nlink:
                item.unlink()
                entries[-1]["status"] = "removed"
    return entries


def inspect(root, name, *, cleanup=False):
    if __package__:
        from . import memory_io
    else:
        import memory_io

    root = Path(root)
    if not root.is_absolute() or name not in TARGETS:
        raise PathBoundaryError("an absolute approved directory and exact Loji filename are required")
    target = managed_path(root / name, root=root, allow_hardlinks=True)
    lock = managed_path(memory_io.lock_path_for(target), root=root)
    if not lock.exists():
        return {"status": "no_lock", "temps": []}
    with memory_io.exclusive_lock(target, timeout=0, read_only=not cleanup,
                                  diagnose_link=True) as fd:
        owner = memory_io.inspect_lock_owner(fd)
        temps = inspect_temps(target, root=root, owner=owner, cleanup=cleanup)
        try:
            managed_path(target, root=root)
        except PathBoundaryError:
            return {"status": "linked_target", "owner": owner, "temps": temps}
        if cleanup and owner and owner.get("status") == "stale":
            memory_io.clear_lock_owner(fd)
            owner["status"] = "removed"
        return {"status": "ok", "owner": owner, "temps": temps}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", required=True, help="absolute directory approved by the host")
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--cleanup", action="store_true", help="remove confirmed stale artifacts only")
    args = parser.parse_args(argv)
    if __package__:
        from . import memory_io
    else:
        import memory_io
    try:
        result = inspect(args.memory_dir, args.target, cleanup=args.cleanup)
    except memory_io.MemoryLockTimeoutError:
        result = {"status": "busy", "temps": []}
    except (OSError, ValueError, memory_io.MemoryIOError) as exc:
        print(json.dumps({"status": "error", "error": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
