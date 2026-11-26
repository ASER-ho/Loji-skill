"""State integrity, crash recovery, and rollback fault injection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import memory_io as io, memory_schema as schema
from scripts import memory_state as ms, safe_state_write as safe
from scripts import episodic_memory as episode
from scripts.migrate_memory import migrate


HOST = ms.Host(accept_saved=True, state_read=True, state_write=True,
               body_read=True, body_write=True)


class SafeStateTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.target = self.root / "memory.md"
        self.target.write_bytes(b"old")

    def test_abrupt_exit_leaves_original_and_cleans_only_confirmed_stale(self):
        process = subprocess.run([
            sys.executable, "-B", "-c",
            "import os,sys; from scripts import memory_io as io; from pathlib import Path;"
            "io.os.replace=lambda src,dst:os._exit(42);"
            "p=Path(sys.argv[1]);io.atomic_write(p,b'new',io.read_version(p))",
            str(self.target),
        ], capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 42, process.stderr.decode())
        self.assertEqual(self.target.read_bytes(), b"old")
        lock = io.lock_path_for(self.target)
        original_lock_id = safe.identity(lock.stat())
        before = safe.inspect(self.root, self.target.name)
        self.assertEqual(before["owner"]["status"], "retained")
        self.assertEqual([x["status"] for x in before["temps"]], ["retained"])
        unowned = self.root / "memory.md.unknown.tmp"
        unowned.write_bytes(b"unowned")
        nonce = "0123456789abcdef"
        active = self.root / f"memory.md.loji-{os.getpid()}-1-{nonce}.new.tmp"
        active.write_bytes(b"active")
        real_time = time.time_ns()
        with patch.object(safe.time, "time_ns", return_value=real_time + 120_000_000_000):
            result = safe.inspect(self.root, self.target.name, cleanup=True)
        self.assertEqual(result["owner"]["status"], "removed")
        self.assertEqual({item["status"] for item in result["temps"]}, {"removed", "retained"})
        self.assertEqual(safe.identity(lock.stat()), original_lock_id)
        self.assertTrue(active.exists())
        self.assertTrue(unowned.exists())
        io.atomic_write(self.target, b"retry", io.read_version(self.target))
        self.assertEqual(self.target.read_bytes(), b"retry")

    def test_crash_after_hardlink_publish_repairs_only_the_paired_temp(self):
        target = self.root / "JUDGMENTS.md"
        process = subprocess.run([
            sys.executable, "-B", "-c",
            "import os,sys; from scripts import memory_io as io; from pathlib import Path;"
            "publish=lambda src,dst:(os.link(src,dst),os._exit(43));"
            "io._exclusive_publish=publish;io.publish_new(Path(sys.argv[1]),b'complete')",
            str(target),
        ], capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 43, process.stderr.decode())
        self.assertEqual(target.stat().st_nlink, 2)
        with self.assertRaises(safe.PathBoundaryError):
            io.read(target)
        before = safe.inspect(self.root, target.name, cleanup=True)
        self.assertEqual(before["status"], "linked_target")
        real_time = time.time_ns()
        with patch.object(safe.time, "time_ns", return_value=real_time + 120_000_000_000):
            repaired = safe.inspect(self.root, target.name, cleanup=True)
        self.assertEqual(repaired["status"], "ok")
        self.assertEqual([x["status"] for x in repaired["temps"]], ["removed"])
        self.assertEqual(target.stat().st_nlink, 1)
        self.assertEqual(io.read(target).data, b"complete")

    def test_active_kernel_lock_cannot_be_cleared(self):
        process = subprocess.Popen([
            sys.executable, "-B", "-c",
            "import sys; from scripts import memory_io as io;"
            "lock=io.exclusive_lock(sys.argv[1],track_owner=True);lock.__enter__();"
            "print('locked',flush=True);sys.stdin.readline();lock.__exit__(None,None,None)",
            str(self.target),
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with self.assertRaises(io.MemoryLockTimeoutError):
                safe.inspect(self.root, self.target.name, cleanup=True)
        finally:
            process.communicate("done\n", timeout=10)
        self.assertEqual(process.returncode, 0)

    def test_junction_or_symlink_parent_rejected_before_read_or_write(self):
        with tempfile.TemporaryDirectory() as outside:
            real = Path(outside) / "memory.md"
            real.write_bytes(b"outside")
            linked = self.root / "alias"
            if os.name == "nt":
                import _winapi
                _winapi.CreateJunction(str(Path(outside).resolve()), str(linked))
            else:
                linked.symlink_to(outside, target_is_directory=True)
            try:
                with self.assertRaises(safe.PathBoundaryError):
                    io.atomic_write(linked / real.name, b"denied", io.read_version(real))
                with self.assertRaises(safe.PathBoundaryError):
                    io.read(linked / real.name)
                self.assertEqual(real.read_bytes(), b"outside")
                self.assertEqual(list(Path(outside).iterdir()), [real])
            finally:
                linked.rmdir() if os.name == "nt" else linked.unlink()

    def test_read_only_recovery_never_creates_a_lock_or_changes_a_state_file(self):
        state = ms.MemoryState(self.root, HOST)
        state.path.write_text(json.dumps({"memory_policy": "read_only", "confirmed": True}),
                              encoding="utf-8")
        original = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with self.assertRaises(io.MemoryLockUnavailableError), state.access(readonly_lock=True):
            self.fail("missing lock must not grant body access")
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, original)
        state.configure("read_only", user_confirmed=True)
        lock = io.lock_path_for(state._transaction_path())
        stamp = lock.stat().st_mtime_ns
        with state.access(readonly_lock=True) as auth:
            self.assertTrue(auth.can_read)
            self.assertFalse(auth.can_write)
        self.assertEqual(lock.stat().st_mtime_ns, stamp)

    def test_old_recovery_receipt_conflicts_with_later_write_even_same_hash(self):
        original = io.read_version(self.target)
        real_read = io.read_version
        def fault(path):
            if path.read_bytes() == b"migrated":
                raise OSError("synthetic readback fault")
            return real_read(path)

        with patch.object(io, "read_version", side_effect=fault):
            with self.assertRaises(io.MemoryPostWriteVerificationError) as error:
                io.atomic_write(self.target, b"migrated", original,
                                allow_lossless_recovery=True)
        receipt = error.exception.restore_point
        self.assertIsNotNone(receipt)
        io.atomic_write(self.target, b"forgotten", io.read_version(self.target))
        io.atomic_write(self.target, b"migrated", io.read_version(self.target))
        with self.assertRaises(io.MemoryConflictError):
            io.restore_backup(receipt)
        self.assertEqual(self.target.read_bytes(), b"migrated")

    def test_episode_forget_readback_failure_cannot_resurrect_deleted_entry(self):
        from l120_support import RECORDS, episode as fixture_episode, fresh_memory, ledger_text
        record = fixture_episode({
            "id": "E-synthetic", "kind": "important_joint_decision", "date": "2026-11-26",
            "summary": "synthetic prior result", "state": "active",
            "related_judgments": ["J-SYN-002"], "outcome": None, "relevance": "synthetic",
            "retention": "project", "expires_on": None, "replaces": None,
        })
        ledger = self.root / "JUDGMENTS.md"
        ledger.write_bytes(ledger_text(RECORDS).encode())
        self.target.write_bytes(fresh_memory([record]).encode())
        inputs = dict(policy="explicit", consent="granted", user_requested=True)
        real_read = io.read_version
        def fault(path):
            if b"synthetic prior result" not in path.read_bytes():
                raise OSError("synthetic readback fault")
            return real_read(path)

        with patch.object(io, "read_version", side_effect=fault):
            with self.assertRaises(io.MemoryPostWriteVerificationError) as error:
                episode.mutate(self.target, ledger, "forget", {"id": "E-synthetic"}, **inputs)
        self.assertIsNone(error.exception.restore_point)
        self.assertEqual(schema.parse(self.target.read_text(encoding="utf-8")).episodes, [])

    def test_migration_reauthorizes_and_refuses_superseded_legacy_cli(self):
        from l120_support import FIXTURES
        V1 = (FIXTURES / "memory-v1.synthetic.md").read_bytes()
        self.target.write_bytes(V1)
        state = ms.MemoryState(self.root, HOST)
        state.configure("explicit", user_confirmed=True)
        self.assertEqual(state.migrate(dry_run=True).status, "would_migrate")
        ms.MemoryState(self.root, HOST).configure("read_only", user_confirmed=True)
        with self.assertRaises(ms.AccessError):
            state.migrate(user_requested=True)
        args = [sys.executable, "-B", "scripts/migrate_memory.py", "--source",
                str(self.target), "--policy", "explicit", "--consent", "granted",
                "--in-place", "--authorize-migration"]
        denied = subprocess.run(args, capture_output=True, text=True, timeout=15)
        self.assertEqual(denied.returncode, 1)
        self.assertIn("configured installation requires memory_state.py migrate", denied.stderr)
        self.assertEqual(self.target.read_bytes(), V1)
        self.assertFalse(list(self.root.glob("memory.md.bak.*")))
        state.configure("explicit", user_confirmed=True)
        self.assertEqual(state.migrate(user_requested=True).status, "migrated")
        self.assertEqual(schema.parse(self.target.read_text(encoding="utf-8")).version, 2)

    def test_future_schema_is_never_migrated_or_rewritten(self):
        tmpl = Path(__file__).resolve().parents[1] / "memory.template.md"
        unknown = tmpl.read_text(encoding="utf-8").replace("schema_version: 2", "schema_version: 99")
        self.target.write_text(unknown, encoding="utf-8")
        original = self.target.read_bytes()
        with self.assertRaisesRegex(schema.FormatError, "unsupported Memory schema"):
            migrate(self.target, policy="explicit", consent="granted",
                    migration_authorized=True, in_place=True)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.target])
