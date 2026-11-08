"""Tests for memory_io and init_memory.

All files live under TemporaryDirectory. No real memory.md is touched.
"""

from __future__ import annotations

import inspect
import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import memory_io  # noqa: E402


def _worker_atomic_write(path, expected, new_text, barrier, queue):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts import memory_io as mio

    try:
        barrier.wait(timeout=10)
        mio.atomic_write(path, new_text, expected, timeout=10)
        queue.put("ok")
    except mio.MemoryConflictError:
        queue.put("conflict")
    except Exception as exc:  # pragma: no cover - diagnostic path
        queue.put(
            f"error:{type(exc).__name__}:{exc}:"
            f"errno={getattr(exc, 'errno', None)}:"
            f"winerror={getattr(exc, 'winerror', None)}:"
            f"filename={getattr(exc, 'filename', None)}"
        )


def _worker_init(template, target, barrier, queue):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts import memory_io as mio

    try:
        barrier.wait(timeout=10)
        mio.init_memory(template, target, timeout=10)
        queue.put("ok")
    except mio.MemoryAlreadyExistsError:
        queue.put("exists")
    except Exception as exc:  # pragma: no cover - diagnostic path
        queue.put(
            f"error:{type(exc).__name__}:{exc}:"
            f"errno={getattr(exc, 'errno', None)}:"
            f"winerror={getattr(exc, 'winerror', None)}:"
            f"filename={getattr(exc, 'filename', None)}"
        )


def _worker_lock_init(path, barrier, queue):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts import memory_io as mio

    try:
        barrier.wait(timeout=10)
        with mio.exclusive_lock(path, timeout=10):
            queue.put("locked")
    except Exception as exc:  # pragma: no cover - diagnostic path
        queue.put(
            f"error:{type(exc).__name__}:{exc}:"
            f"errno={getattr(exc, 'errno', None)}:"
            f"winerror={getattr(exc, 'winerror', None)}:"
            f"filename={getattr(exc, 'filename', None)}"
        )


class MemoryIOTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.template = self.dir / "memory.template.md"
        self.template.write_text("TEMPLATE\n", encoding="utf-8", newline="")
        self.target = self.dir / "memory.md"

    def _write_initial(self, text: str = "V0\n"):
        self.target.write_text(text, encoding="utf-8", newline="")
        return memory_io.read_version(self.target)

    def test_read_version_and_successful_write(self) -> None:
        v0 = self._write_initial("V0\n")
        result = memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertEqual(memory_io.read_text(self.target), "V1\n")
        self.assertIsNotNone(result.backup_path)
        self.assertEqual(memory_io.read_text(result.backup_path), "V0\n")
        self.assertEqual(result.version.sha256, memory_io.sha256_bytes(b"V1\n"))

    def test_read_returns_content_and_version(self) -> None:
        v0 = self._write_initial("V0\n")
        result = memory_io.read(self.target)
        self.assertEqual(result.data, b"V0\n")
        self.assertEqual(result.text, "V0\n")
        self.assertEqual(result.version, v0)
        self.assertEqual(result.version.size, 3)
        self.assertEqual(result.version.sha256, memory_io.sha256_bytes(b"V0\n"))
        self.assertIsNotNone(result.version.mtime_ns)

    def test_read_is_read_only(self) -> None:
        self._write_initial("V0\n")
        before_bytes = self.target.read_bytes()
        before_stat = self.target.stat()
        before_entries = sorted(path.name for path in self.dir.iterdir())
        result = memory_io.read(self.target)
        after_bytes = self.target.read_bytes()
        after_stat = self.target.stat()
        after_entries = sorted(path.name for path in self.dir.iterdir())
        self.assertEqual(result.data, before_bytes)
        self.assertEqual(before_bytes, after_bytes)
        self.assertEqual(before_stat.st_mtime_ns, after_stat.st_mtime_ns)
        self.assertEqual(before_stat.st_size, after_stat.st_size)
        self.assertEqual(before_entries, after_entries)

    def test_read_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            memory_io.read(self.dir / "missing.md")

    def test_conflict_when_content_changed(self) -> None:
        v0 = self._write_initial("V0\n")
        self.target.write_text("EXTERNAL\n", encoding="utf-8", newline="")
        with self.assertRaises(memory_io.MemoryConflictError):
            memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertEqual(memory_io.read_text(self.target), "EXTERNAL\n")

    def test_conflict_when_mtime_changed(self) -> None:
        v0 = self._write_initial("V0\n")
        new_ns = (v0.mtime_ns or 0) + 10_000_000
        os.utime(self.target, ns=(new_ns, new_ns))
        with self.assertRaises(memory_io.MemoryConflictError):
            memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertEqual(memory_io.read_text(self.target), "V0\n")

    def test_backup_failure_leaves_original(self) -> None:
        v0 = self._write_initial("V0\n")
        with mock.patch(
            "scripts.memory_io.backup",
            side_effect=memory_io.MemoryBackupError("boom"),
        ):
            with self.assertRaises(memory_io.MemoryBackupError):
                memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertEqual(memory_io.read_text(self.target), "V0\n")

    def test_temp_write_failure_leaves_original(self) -> None:
        v0 = self._write_initial("V0\n")
        with mock.patch(
            "scripts.memory_io._write_temp",
            side_effect=memory_io.MemoryWriteError("boom"),
        ):
            with self.assertRaises(memory_io.MemoryWriteError):
                memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertEqual(memory_io.read_text(self.target), "V0\n")

    def test_replace_failure_leaves_original_and_cleans_temp(self) -> None:
        v0 = self._write_initial("V0\n")
        with mock.patch(
            "scripts.memory_io.os.replace",
            side_effect=OSError("replace boom"),
        ):
            with self.assertRaises(memory_io.MemoryWriteError):
                memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertEqual(memory_io.read_text(self.target), "V0\n")
        self.assertEqual(list(self.dir.glob("memory.md.*.tmp")), [])

    def test_post_verify_failure_does_not_auto_restore(self) -> None:
        v0 = self._write_initial("V0\n")
        fake = memory_io.MemoryVersion(
            sha256="0" * 64, mtime_ns=None, size=999
        )
        with mock.patch(
            "scripts.memory_io.read_version",
            side_effect=[v0, v0, fake],
        ):
            with self.assertRaises(memory_io.MemoryPostWriteVerificationError) as cm:
                memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertTrue(cm.exception.recovery_required)
        self.assertIsNotNone(cm.exception.backup_path)
        # The new content stays; no unsafe automatic rollback.
        self.assertEqual(memory_io.read_text(self.target), "V1\n")
        self.assertEqual(
            memory_io.read_text(cm.exception.backup_path), "V0\n"
        )

    def test_no_backup_bypass_parameter(self) -> None:
        v0 = self._write_initial("V0\n")
        self.assertNotIn(
            "create_backup", inspect.signature(memory_io.atomic_write).parameters
        )
        with self.assertRaises(TypeError):
            memory_io.atomic_write(self.target, "V1\n", v0, create_backup=False)
        self.assertEqual(memory_io.read_text(self.target), "V0\n")

    def test_temp_write_failure_closes_before_cleanup(self) -> None:
        v0 = self._write_initial("V0\n")
        events: list[tuple[str, object]] = []
        real_close = os.close
        real_cleanup = memory_io._cleanup_temp
        real_write_all = memory_io._write_all
        calls = {"count": 0, "temp_fd": None}

        def close_wrapper(fd):
            events.append(("close", fd))
            return real_close(fd)

        def cleanup_wrapper(path):
            events.append(("cleanup", str(path)))
            return real_cleanup(path)

        def write_all_wrapper(fd, data):
            calls["count"] += 1
            if calls["count"] == 1:
                return real_write_all(fd, data)  # backup write
            calls["temp_fd"] = fd
            raise OSError("write boom")  # temp write

        with mock.patch(
            "scripts.memory_io._write_all", side_effect=write_all_wrapper
        ), mock.patch(
            "scripts.memory_io.os.close", side_effect=close_wrapper
        ), mock.patch(
            "scripts.memory_io._cleanup_temp", side_effect=cleanup_wrapper
        ):
            with self.assertRaises(memory_io.MemoryWriteError):
                memory_io.atomic_write(self.target, "V1\n", v0)

        self.assertEqual(memory_io.read_text(self.target), "V0\n")
        temp_fd = calls["temp_fd"]
        self.assertIsNotNone(temp_fd)
        close_positions = [
            i for i, event in enumerate(events) if event == ("close", temp_fd)
        ]
        cleanup_positions = [
            i for i, event in enumerate(events) if event[0] == "cleanup"
        ]
        self.assertTrue(close_positions, events)
        self.assertTrue(cleanup_positions, events)
        self.assertLess(min(close_positions), min(cleanup_positions), events)

    def test_temp_cleanup_failure_is_reported(self) -> None:
        v0 = self._write_initial("V0\n")
        real_write_all = memory_io._write_all
        calls = {"count": 0}

        def write_all_wrapper(fd, data):
            calls["count"] += 1
            if calls["count"] == 1:
                return real_write_all(fd, data)  # backup write
            raise OSError("write boom")  # temp write

        with mock.patch(
            "scripts.memory_io._write_all", side_effect=write_all_wrapper
        ), mock.patch(
            "scripts.memory_io._cleanup_temp",
            return_value="could not remove temp file XYZ",
        ):
            with self.assertRaises(memory_io.MemoryWriteError) as cm:
                memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertIn("could not remove temp file XYZ", str(cm.exception))
        self.assertEqual(memory_io.read_text(self.target), "V0\n")

    def test_lock_unavailable_refuses_write(self) -> None:
        v0 = self._write_initial("V0\n")
        with mock.patch("scripts.memory_io._lock_backend", return_value=None):
            with self.assertRaises(memory_io.MemoryLockUnavailableError):
                memory_io.atomic_write(self.target, "V1\n", v0)
        self.assertEqual(memory_io.read_text(self.target), "V0\n")

    def test_backups_are_unique(self) -> None:
        v0 = self._write_initial("V0\n")
        r1 = memory_io.atomic_write(self.target, "V1\n", v0)
        v1 = memory_io.read_version(self.target)
        r2 = memory_io.atomic_write(self.target, "V2\n", v1)
        self.assertNotEqual(r1.backup_path, r2.backup_path)
        self.assertEqual(memory_io.read_text(r1.backup_path), "V0\n")
        self.assertEqual(memory_io.read_text(r2.backup_path), "V1\n")

    def test_guarded_restore(self) -> None:
        v0 = self._write_initial("V0\n")
        result = memory_io.atomic_write(self.target, "V1\n", v0)
        v1 = memory_io.read_version(self.target)
        restored = memory_io.restore_backup(
            result.backup_path,
            self.target,
            expected_target_sha256=v1.sha256,
            expected_backup_sha256=v0.sha256,
        )
        self.assertEqual(restored.sha256, v0.sha256)
        self.assertEqual(memory_io.read_text(self.target), "V0\n")

    def test_guarded_restore_refuses_changed_target(self) -> None:
        v0 = self._write_initial("V0\n")
        result = memory_io.atomic_write(self.target, "V1\n", v0)
        self.target.write_text("EXTERNAL\n", encoding="utf-8", newline="")
        with self.assertRaises(memory_io.MemoryConflictError):
            memory_io.restore_backup(
                result.backup_path,
                self.target,
                expected_target_sha256=v0.sha256,
                expected_backup_sha256=v0.sha256,
            )
        self.assertEqual(memory_io.read_text(self.target), "EXTERNAL\n")

    def test_guarded_restore_rejects_wrong_backup_hash(self) -> None:
        v0 = self._write_initial("V0\n")
        result = memory_io.atomic_write(self.target, "V1\n", v0)
        v1 = memory_io.read_version(self.target)
        with self.assertRaises(memory_io.MemoryConflictError):
            memory_io.restore_backup(
                result.backup_path,
                self.target,
                expected_target_sha256=v1.sha256,
                expected_backup_sha256="0" * 64,
            )
        self.assertEqual(memory_io.read_text(self.target), "V1\n")

    def test_guarded_restore_requires_backup_hash(self) -> None:
        v0 = self._write_initial("V0\n")
        result = memory_io.atomic_write(self.target, "V1\n", v0)
        v1 = memory_io.read_version(self.target)
        with self.assertRaises(memory_io.MemoryVersionRequiredError):
            memory_io.restore_backup(
                result.backup_path,
                self.target,
                expected_target_sha256=v1.sha256,
                expected_backup_sha256=None,
            )
        self.assertEqual(memory_io.read_text(self.target), "V1\n")

    def test_init_creates_and_refuses_existing(self) -> None:
        version = memory_io.init_memory(self.template, self.target)
        self.assertEqual(version.sha256, memory_io.sha256_bytes(b"TEMPLATE\n"))
        original = self.target.read_bytes()
        with self.assertRaises(memory_io.MemoryAlreadyExistsError):
            memory_io.init_memory(self.template, self.target)
        self.assertEqual(self.target.read_bytes(), original)

    def test_init_cli_exit_codes(self) -> None:
        script = ROOT / "scripts" / "init_memory.py"
        # success
        proc = subprocess.run(
            [sys.executable, str(script), "--template", str(self.template),
             "--target", str(self.target)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        original = self.target.read_bytes()
        # existing
        proc = subprocess.run(
            [sys.executable, str(script), "--template", str(self.template),
             "--target", str(self.target)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(self.target.read_bytes(), original)

    def test_concurrent_initialization(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(2)
        queue = ctx.Queue()
        procs = [
            ctx.Process(
                target=_worker_init,
                args=(str(self.template), str(self.target), barrier, queue),
            )
            for _ in range(2)
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=30)
        results = sorted(queue.get(timeout=5) for _ in range(2))
        for proc in procs:
            if proc.is_alive():  # pragma: no cover - safety
                proc.terminate()
                proc.join(timeout=5)
        self.assertEqual(results, ["exists", "ok"])
        self.assertEqual(memory_io.read_text(self.target), "TEMPLATE\n")
        lock_path = memory_io.lock_path_for(self.target)
        self.assertTrue(lock_path.exists())
        self.assertEqual(lock_path.stat().st_size, 1)

    def test_concurrent_lock_file_initialization(self) -> None:
        target = self.dir / "memory.md"
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(2)
        queue = ctx.Queue()
        procs = [
            ctx.Process(
                target=_worker_lock_init,
                args=(str(target), barrier, queue),
            )
            for _ in range(2)
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=30)
        results = sorted(queue.get(timeout=5) for _ in range(2))
        for proc in procs:
            if proc.is_alive():  # pragma: no cover - safety
                proc.terminate()
                proc.join(timeout=5)
        self.assertEqual(results, ["locked", "locked"])
        lock_path = memory_io.lock_path_for(target)
        self.assertTrue(lock_path.exists())
        self.assertEqual(lock_path.stat().st_size, 1)

    def test_two_process_atomic_write_conflict(self) -> None:
        v0 = self._write_initial("V0\n")
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(2)
        queue = ctx.Queue()
        procs = [
            ctx.Process(
                target=_worker_atomic_write,
                args=(
                    str(self.target),
                    v0,
                    text,
                    barrier,
                    queue,
                ),
            )
            for text in ("V1a\n", "V1b\n")
        ]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(timeout=30)
        results = sorted(queue.get(timeout=5) for _ in range(2))
        for proc in procs:
            if proc.is_alive():  # pragma: no cover - safety
                proc.terminate()
                proc.join(timeout=5)
        self.assertEqual(results, ["conflict", "ok"])
        self.assertIn(memory_io.read_text(self.target), ("V1a\n", "V1b\n"))
        backups = list(self.dir.glob("memory.md.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(memory_io.read_text(backups[0]), "V0\n")
        lock_path = memory_io.lock_path_for(self.target)
        self.assertTrue(lock_path.exists())
        self.assertEqual(lock_path.stat().st_size, 1)

    def test_no_real_repo_memory_touched(self) -> None:
        self.assertFalse((ROOT / "memory.md").exists())
        self.assertFalse((ROOT / "memory.md.bak").exists())


if __name__ == "__main__":
    unittest.main()
