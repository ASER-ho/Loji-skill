"""Reliable local memory I/O for Loji.

Design goals:
- Detect concurrent changes with SHA256 (authoritative) plus mtime_ns/size.
- Protect cooperating writers with a dedicated advisory lock file.
- Never overwrite an existing memory file during initialization.
- Keep the original file intact on every pre-replace failure.
- Never auto-restore a backup over a target that may contain newer writes.

Limitations (reported explicitly, not hidden):
- Advisory locks only protect processes that use this module.
- External writers that ignore ``memory.md.lock`` can still lose updates in
  the check-to-replace window.
- Network filesystems, sync clients, and antivirus tools may weaken
  ``os.replace`` atomicity or lock semantics.
- A failure after ``os.replace`` can leave a new file in place; recovery is
  reported with the verified backup path and requires an explicit decision.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


DEFAULT_TIMEOUT = 10.0
POLL_INTERVAL = 0.05
LOCK_SUFFIX = ".lock"
O_BINARY = getattr(os, "O_BINARY", 0)


class MemoryIOError(Exception):
    """Base class for memory I/O failures."""


class MemoryConflictError(MemoryIOError):
    """The on-disk version does not match the expected version."""


class MemoryVersionRequiredError(MemoryIOError):
    """An update was attempted without an expected version token."""


class MemoryLockUnavailableError(MemoryIOError):
    """No usable advisory-lock backend is available."""


class MemoryLockTimeoutError(MemoryIOError):
    """The advisory lock could not be acquired before the timeout."""


class MemoryBackupError(MemoryIOError):
    """A backup could not be created or verified."""


class MemoryWriteError(MemoryIOError):
    """A write or replace operation failed."""


class MemoryPostWriteVerificationError(MemoryIOError):
    """The target did not verify after ``os.replace``."""

    def __init__(
        self,
        message: str,
        *,
        backup_path: Path | None,
        intended_sha256: str,
        target_version: "MemoryVersion | None",
        recovery_required: bool,
        published_version: "MemoryVersion | None" = None,
        published_identity: tuple[int, int] | None = None,
    ) -> None:
        super().__init__(message)
        self.backup_path = backup_path
        self.intended_sha256 = intended_sha256
        self.target_version = target_version
        self.recovery_required = recovery_required
        self.published_version = published_version
        self.published_identity = published_identity


class MemoryAlreadyExistsError(MemoryIOError):
    """Initialization refused because the target already exists."""


@dataclass(frozen=True)
class MemoryVersion:
    sha256: str
    mtime_ns: int | None
    size: int


@dataclass(frozen=True)
class MemoryReadResult:
    data: bytes
    text: str
    version: MemoryVersion


@dataclass(frozen=True)
class AtomicWriteResult:
    backup_path: Path | None
    version: MemoryVersion


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_from_bytes(data: bytes, *, mtime_ns: int | None) -> MemoryVersion:
    return MemoryVersion(sha256=sha256_bytes(data), mtime_ns=mtime_ns, size=len(data))


def read_bytes(path: Path | str) -> bytes:
    return Path(path).read_bytes()


def read_text(path: Path | str) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _read_stable(path: Path) -> tuple[bytes, MemoryVersion]:
    """Read bytes and a token, retrying if the file changes mid-read."""
    for _ in range(3):
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        if (
            getattr(before, "st_mtime_ns", None),
            before.st_size,
        ) == (
            getattr(after, "st_mtime_ns", None),
            after.st_size,
        ):
            return data, version_from_bytes(
                data, mtime_ns=getattr(after, "st_mtime_ns", None)
            )
    raise MemoryConflictError(f"file changed while reading: {path}")


def read_version(path: Path | str) -> MemoryVersion:
    _, version = _read_stable(Path(path))
    return version


def read(path: Path | str) -> MemoryReadResult:
    """Return content and version token from one stable read.

    The content is decoded as UTF-8. The version token is computed from the
    exact same bytes, so callers can pass it directly to ``atomic_write``.
    """
    data, version = _read_stable(Path(path))
    return MemoryReadResult(data=data, text=data.decode("utf-8"), version=version)


def lock_path_for(path: Path | str) -> Path:
    return Path(str(path) + LOCK_SUFFIX)


def _lock_backend() -> str | None:
    if fcntl is not None:
        return "posix"
    if msvcrt is not None:
        return "windows"
    return None


def _try_lock(fd: int, backend: str) -> bool:
    if backend == "posix":
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError) as exc:
            errno = getattr(exc, "errno", None)
            if errno in (11, 13, 35):  # EAGAIN / EACCES / EWOULDBLOCK
                return False
            raise
    if backend == "windows":
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            errno = getattr(exc, "errno", None)
            if errno in (13, 36):  # EACCES / EDEADLK on Windows
                return False
            raise
    raise MemoryLockUnavailableError("no advisory lock backend available")


def _unlock(fd: int, backend: str) -> None:
    if backend == "posix":
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif backend == "windows":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def exclusive_lock(path: Path | str, timeout: float = DEFAULT_TIMEOUT) -> Iterator[None]:
    """Acquire an advisory exclusive lock next to ``path``.

    The lock file is separate from the memory file so that ``os.replace`` on
    the memory file cannot invalidate the lock.
    """
    backend = _lock_backend()
    if backend is None:
        raise MemoryLockUnavailableError("no advisory lock backend available")

    lock_file = lock_path_for(path)
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR | O_BINARY, 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            if _try_lock(fd, backend):
                acquired = True
                break
            if time.monotonic() >= deadline:
                raise MemoryLockTimeoutError(
                    f"timed out after {timeout:.1f}s waiting for {lock_file}"
                )
            time.sleep(POLL_INTERVAL)

        # Initialize the lock file's first byte only after the exclusive lock
        # is held. Writing before lock acquisition is a shared-write race
        # (both processes can observe size 0 and write the same region).
        if os.fstat(fd).st_size == 0:
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b"\0")
            os.fsync(fd)

        yield
    finally:
        if acquired:
            try:
                _unlock(fd, backend)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def _check_expected(current: MemoryVersion, expected: MemoryVersion) -> None:
    if current.sha256 != expected.sha256:
        raise MemoryConflictError(
            "content conflict: "
            f"expected sha256={expected.sha256}, current sha256={current.sha256}"
        )
    if expected.mtime_ns is not None and current.mtime_ns != expected.mtime_ns:
        raise MemoryConflictError(
            "metadata conflict (mtime_ns): "
            f"expected {expected.mtime_ns}, current {current.mtime_ns}"
        )
    if current.size != expected.size:
        raise MemoryConflictError(
            f"metadata conflict (size): expected {expected.size}, current {current.size}"
        )


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _safe_unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def _cleanup_temp(temp_path: Path) -> str | None:
    """Remove a temp file after its handle is closed.

    Returns a diagnostic string when removal fails; the caller must include
    it in the raised error so the leftover file can be inspected.
    """
    try:
        temp_path.unlink()
        return None
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"could not remove temp file {temp_path}: {exc}"


def _fsync_parent_dir(path: Path) -> None:
    """Best-effort directory fsync; not available on Windows."""
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _unique_backup_path(path: Path) -> Path:
    for _ in range(20):
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        candidate = Path(f"{path}.bak.{stamp}-{os.getpid()}-{secrets.token_hex(4)}")
        if not candidate.exists():
            return candidate
    raise MemoryBackupError(f"could not allocate a unique backup path for {path}")


def backup(path: Path | str, expected: MemoryVersion | None = None) -> Path:
    """Create and verify a non-overwriting backup of ``path``."""
    path = Path(path)
    try:
        data, current = _read_stable(path)
    except OSError as exc:
        raise MemoryBackupError(f"cannot read source for backup: {exc}") from exc

    if expected is not None:
        _check_expected(current, expected)

    backup_path = _unique_backup_path(path)
    fd = -1
    try:
        fd = os.open(
            backup_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | O_BINARY,
            0o600,
        )
        _write_all(fd, data)
        os.fsync(fd)
    except OSError as exc:
        raise MemoryBackupError(f"cannot create backup {backup_path}: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)

    try:
        backup_data = backup_path.read_bytes()
    except OSError as exc:
        raise MemoryBackupError(f"cannot read back backup {backup_path}: {exc}") from exc

    if backup_data != data or sha256_bytes(backup_data) != current.sha256:
        raise MemoryBackupError(f"backup verification failed: {backup_path}")

    return backup_path


def _write_temp(path: Path, data: bytes) -> Path:
    fd, temp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp_path = Path(temp_name)

    try:
        _write_all(fd, data)
        os.fsync(fd)
    except BaseException as exc:
        close_error: OSError | None = None
        try:
            os.close(fd)
        except OSError as close_exc:
            close_error = close_exc
        cleanup_error = _cleanup_temp(temp_path)

        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise

        details: list[str] = []
        if isinstance(exc, MemoryWriteError):
            details.append(str(exc))
        elif isinstance(exc, OSError):
            details.append(f"temporary write failed: {exc}")
        else:
            details.append(f"temporary write failed: {type(exc).__name__}: {exc}")
        if close_error is not None:
            details.append(f"close failed: {close_error}")
        if cleanup_error is not None:
            details.append(cleanup_error)
        raise MemoryWriteError("; ".join(details)) from exc
    else:
        try:
            os.close(fd)
        except OSError as exc:
            cleanup_error = _cleanup_temp(temp_path)
            detail = f"temporary close failed: {exc}"
            if cleanup_error is not None:
                detail += f"; {cleanup_error}"
            raise MemoryWriteError(detail) from exc

    try:
        written = temp_path.read_bytes()
    except OSError as exc:
        cleanup_error = _cleanup_temp(temp_path)
        detail = f"cannot read back temporary file: {exc}"
        if cleanup_error is not None:
            detail += f"; {cleanup_error}"
        raise MemoryWriteError(detail) from exc

    if written != data or sha256_bytes(written) != sha256_bytes(data):
        cleanup_error = _cleanup_temp(temp_path)
        detail = "temporary file verification failed"
        if cleanup_error is not None:
            detail += f"; {cleanup_error}"
        raise MemoryWriteError(detail)

    return temp_path


def atomic_write(
    path: Path | str,
    data: str | bytes,
    expected: MemoryVersion,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> AtomicWriteResult:
    """Atomically write ``data`` if the on-disk version matches ``expected``.

    A verified backup is always created before the target is replaced.
    """
    if expected is None:
        raise MemoryVersionRequiredError("expected MemoryVersion is required for updates")

    path = Path(path)
    payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    intended_sha256 = sha256_bytes(payload)

    with exclusive_lock(path, timeout=timeout):
        try:
            current = read_version(path)
        except FileNotFoundError as exc:
            raise MemoryConflictError(
                f"target disappeared after read: {path}"
            ) from exc
        except OSError as exc:
            raise MemoryWriteError(f"cannot read target: {exc}") from exc

        _check_expected(current, expected)

        backup_path = backup(path, current)
        temp_path = _write_temp(path, payload)

        try:
            published_stat = temp_path.stat()
            published_version = version_from_bytes(payload, mtime_ns=published_stat.st_mtime_ns)
            published_identity = (published_stat.st_dev, published_stat.st_ino)
            _check_expected(read_version(path), current)
            os.replace(temp_path, path)
        except (MemoryConflictError, FileNotFoundError):
            _safe_unlink(temp_path)
            raise
        except OSError as exc:
            _safe_unlink(temp_path)
            try:
                after = read_version(path)
                original_intact = after.sha256 == current.sha256
            except OSError:
                original_intact = False
            raise MemoryWriteError(
                "replace failed: "
                f"{exc}; original_intact={original_intact}; "
                f"backup={backup_path}"
            ) from exc

        _fsync_parent_dir(path)

        try:
            post = read_version(path)
        except (OSError, MemoryConflictError) as exc:
            raise MemoryPostWriteVerificationError(
                f"cannot verify target after replace: {exc}",
                backup_path=backup_path,
                intended_sha256=intended_sha256,
                target_version=None,
                recovery_required=True,
                published_version=published_version,
                published_identity=published_identity,
            ) from exc

        if post.sha256 != intended_sha256 or post.size != len(payload):
            if post.sha256 == current.sha256:
                # The original content is still present; no rollback needed.
                raise MemoryPostWriteVerificationError(
                    "post-write verification failed but original content remains",
                    backup_path=backup_path,
                    intended_sha256=intended_sha256,
                    target_version=post,
                    recovery_required=False,
                )
            # Unknown content may include an external writer's new data.
            # Never auto-restore over it.
            raise MemoryPostWriteVerificationError(
                "post-write verification failed; target may contain newer data",
                backup_path=backup_path,
                intended_sha256=intended_sha256,
                target_version=post,
                recovery_required=True,
                published_version=published_version,
                published_identity=published_identity,
            )

        return AtomicWriteResult(backup_path=backup_path, version=post)


def restore_backup(
    backup_path: Path | str,
    target_path: Path | str,
    *,
    expected_target_sha256: str,
    expected_backup_sha256: str,
    expected_target_version: MemoryVersion | None = None,
    expected_target_identity: tuple[int, int] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> MemoryVersion:
    """Restore a verified backup only if the target still has the expected hash.

    This is deliberately guarded: the caller must state which target content
    they are willing to replace. It is never called automatically by
    :func:`atomic_write`.
    """
    backup_path = Path(backup_path)
    target_path = Path(target_path)

    if not expected_backup_sha256:
        raise MemoryVersionRequiredError(
            "expected_backup_sha256 is required for restore"
        )

    def check_identity() -> None:
        if expected_target_identity is not None:
            stat = target_path.stat()
            if (stat.st_dev, stat.st_ino) != expected_target_identity:
                raise MemoryConflictError("refusing restore: target identity changed")

    with exclusive_lock(target_path, timeout=timeout):
        try:
            check_identity()
            current = read_version(target_path)
        except FileNotFoundError as exc:
            raise MemoryConflictError("target disappeared before restore") from exc

        if expected_target_version is not None:
            _check_expected(current, expected_target_version)
        if current.sha256 != expected_target_sha256:
            raise MemoryConflictError(
                "refusing restore: target changed "
                f"(expected {expected_target_sha256}, current {current.sha256})"
            )

        try:
            backup_data = backup_path.read_bytes()
        except OSError as exc:
            raise MemoryBackupError(f"cannot read backup: {exc}") from exc

        backup_sha256 = sha256_bytes(backup_data)
        if backup_sha256 != expected_backup_sha256:
            raise MemoryConflictError("refusing restore: backup checksum mismatch")

        temp_path = _write_temp(target_path, backup_data)
        try:
            check_identity()
            _check_expected(read_version(target_path), current)
            os.replace(temp_path, target_path)
        except (MemoryConflictError, FileNotFoundError):
            _safe_unlink(temp_path)
            raise
        except OSError as exc:
            _safe_unlink(temp_path)
            raise MemoryWriteError(f"restore replace failed: {exc}") from exc

        _fsync_parent_dir(target_path)
        try:
            post = read_version(target_path)
        except (OSError, MemoryConflictError) as exc:
            raise MemoryPostWriteVerificationError(
                f"cannot verify restored target: {exc}",
                backup_path=backup_path,
                intended_sha256=backup_sha256,
                target_version=None,
                recovery_required=True,
            ) from exc
        if post.sha256 != backup_sha256:
            raise MemoryPostWriteVerificationError(
                "restore verification failed",
                backup_path=backup_path,
                intended_sha256=backup_sha256,
                target_version=post,
                recovery_required=True,
            )
        return post


def _exclusive_publish(temp_path: Path, target_path: Path) -> None:
    """Publish a complete temp file without overwriting an existing target."""
    if os.name == "nt":
        # On Windows, os.rename raises FileExistsError if target exists.
        os.rename(temp_path, target_path)
        return
    # POSIX: hard-link is atomic and fails if the target already exists.
    os.link(temp_path, target_path)
    os.unlink(temp_path)


def init_memory(
    template_path: Path | str,
    target_path: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> MemoryVersion:
    """Create ``target_path`` from ``template_path`` only if it is absent."""
    template_path = Path(template_path)
    target_path = Path(target_path)

    if not template_path.exists():
        raise FileNotFoundError(f"template not found: {template_path}")

    return publish_new(target_path, template_path.read_bytes(), timeout=timeout)


def publish_new(
    target_path: Path | str,
    data: bytes,
    *,
    before_publish: Callable[[], None] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> MemoryVersion:
    """Publish verified bytes without replacing any existing target."""
    target_path = Path(target_path)
    with exclusive_lock(target_path, timeout=timeout):
        if target_path.exists() or target_path.is_symlink():
            raise MemoryAlreadyExistsError(f"target already exists: {target_path}")

        temp_path = _write_temp(target_path, data)
        try:
            if before_publish is not None:
                before_publish()
            try:
                _exclusive_publish(temp_path, target_path)
            except FileExistsError as exc:
                _safe_unlink(temp_path)
                raise MemoryAlreadyExistsError(
                    f"target already exists: {target_path}"
                ) from exc
            except OSError:
                _safe_unlink(temp_path)
                raise
        finally:
            _safe_unlink(temp_path)

        try:
            post = read_version(target_path)
        except (OSError, MemoryConflictError) as exc:
            raise MemoryPostWriteVerificationError(
                f"cannot verify initialized target: {exc}",
                backup_path=None,
                intended_sha256=sha256_bytes(data),
                target_version=None,
                recovery_required=True,
            ) from exc
        if post.sha256 != sha256_bytes(data) or post.size != len(data):
            raise MemoryPostWriteVerificationError(
                "initialization verification failed",
                backup_path=None,
                intended_sha256=sha256_bytes(data),
                target_version=post,
                recovery_required=True,
            )
        return post
