"""L120-01: executable migration cases from the original 21-case matrix."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from l120_support import FIXTURES, GROUPS, ROOT
from scripts import memory_io as io, memory_schema as schema
from scripts.migrate_memory import AccessError, migrate

V1 = (FIXTURES / "memory-v1.synthetic.md").read_bytes()
AUTH = dict(policy="explicit", consent="granted", migration_authorized=True)


class MigrationCases(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "memory.md"
        self.target = self.root / "result.md"
        self.source.write_bytes(V1)

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.rglob("*") if path.is_file()
        }

    def run_migrate(self, *, inplace=False, **kwargs):
        mode = {"in_place": True} if inplace else {"target": self.target}
        return migrate(self.source, **mode, **{**AUTH, **kwargs})

    def no_change(self, error=ValueError, **kwargs):
        before = self.snapshot()
        with self.assertRaises(error):
            self.run_migrate(**kwargs)
        self.assertEqual(self.snapshot(), before)

    def test_M01(self):
        source_before = self.source.stat().st_mtime_ns
        self.assertEqual(self.run_migrate().status, "migrated")
        self.assertEqual(self.source.read_bytes(), V1)
        self.assertEqual(self.source.stat().st_mtime_ns, source_before)
        # Keep the original provisional fidelity oracle; change only the newly
        # finalized version literal and the representation of the two empty sections.
        expected = (FIXTURES / "memory-v2.expected.synthetic.md").read_bytes()
        start = expected.index("## 共同经历".encode())
        end = expected.index("## 归档".encode())
        newline = "\r\n" if b"\r\n" in expected else "\n"
        expected = (expected[:start] + schema.render_sections([], {}, newline).encode() +
                    expected[end:]).replace(b'"1.2.0"', b'"1.1.2"', 1)
        self.assertEqual(self.target.read_bytes(), expected)
        doc = schema.parse(self.target.read_bytes().decode())
        self.assertEqual((doc.version, doc.episodes, doc.calibration), (2, [], {}))

    def test_M02(self):
        result = self.run_migrate(inplace=True)
        self.assertEqual(result.backup.read_bytes(), V1)
        before = self.snapshot()
        self.assertEqual(self.run_migrate(inplace=True).status, "no_op")
        self.assertEqual(self.snapshot(), before)

    def test_M03(self):
        for variant in GROUPS["migration"][2]["input"]["variants"]:
            with self.subTest(variant=variant):
                value = variant.get("schema_version")
                token = {str: b'"1"', bool: b"true", int: str(value).encode()}.get(type(value), b"null")
                data = V1.replace(b"schema_version: 1", b"schema_version: " + token, 1)
                if "remove_field" in variant:
                    data = data.split(b"\n", 2)[0] + b"\n" + data.split(b"\n", 2)[2]
                self.source.write_bytes(data)
                self.no_change()

    def test_M04(self):
        for data in (
            V1.replace(b"\n---", b"\n---broken", 1),
            V1.replace(b"schema_version: 1", b"schema_version: 1\nschema_version: 1", 1),
            b"\xff\xfe\xff", V1.replace(b"memory_policy: explicit", b"memory_policy: [explicit]", 1),
        ):
            self.source.write_bytes(data)
            self.no_change()

    def test_M05(self):
        parent = self.root / "never-created"
        self.target = parent / "result.md"
        before = self.snapshot()
        proc = subprocess.run([
            sys.executable, "-B", str(ROOT / "scripts/migrate_memory.py"),
            "--source", str(self.source), "--target", str(self.target),
            "--policy", "read_only", "--consent", "granted", "--dry-run",
        ], capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(b"would set schema 2", proc.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(parent.exists())

    def test_M06(self):
        for target in (schema.upgrade(schema.parse(V1.decode())).encode(), b"SYNTHETIC OTHER"):
            self.target.write_bytes(target)
            self.no_change(io.MemoryAlreadyExistsError)

    def test_M07(self):
        sentinel = self.root / "external.tmp"
        sentinel.write_bytes(b"external")
        actual_write = io._write_temp
        actual_os_write = io.os.write
        for point in GROUPS["migration"][6]["input"]["failpoints"]:
            with self.subTest(point=point):
                def temp(path, data):
                    if point == "temp_create":
                        with patch.object(io.tempfile, "mkstemp", side_effect=OSError(point)):
                            return actual_write(path, data)
                    if point == "temp_write_partial":
                        def partial(fd, payload):
                            actual_os_write(fd, payload[:5])
                            raise OSError(point)
                        with patch.object(io, "_write_all", side_effect=partial):
                            return actual_write(path, data)
                    if point in ("flush", "fsync"):
                        # _write_temp uses raw unbuffered descriptors; fsync is
                        # the actual flush-to-device boundary, no file.flush().
                        with patch.object(io.os, "fsync", side_effect=OSError(point)):
                            return actual_write(path, data)
                    if point == "close":
                        close = io.os.close
                        def fail_after_close(fd):
                            close(fd)
                            raise OSError(point)
                        with patch.object(io.os, "close", side_effect=fail_after_close):
                            return actual_write(path, data)
                    return actual_write(path, data)
                real_replace = io.os.replace
                with patch.object(io, "_write_temp", side_effect=temp), patch.object(
                    io.os, "replace", side_effect=OSError(point) if point == "before_replace" else real_replace
                ):
                    with self.assertRaises((OSError, io.MemoryIOError)):
                        self.run_migrate(inplace=True)
                self.assertEqual(self.source.read_bytes(), V1)
                self.assertEqual(list(self.root.glob("memory.md.*.tmp")), [])
                self.assertEqual(sentinel.read_bytes(), b"external")

    def test_M08(self):
        original = io._write_all
        def fail_backup(fd, data):
            if data == V1:
                raise OSError("synthetic backup write failure")
            return original(fd, data)
        with patch.object(io, "_write_all", side_effect=fail_backup), patch.object(io.os, "replace") as replace:
            with self.assertRaises(io.MemoryBackupError):
                self.run_migrate(inplace=True)
        replace.assert_not_called()
        self.assertEqual(self.source.read_bytes(), V1)

    def test_M09(self):
        actual_write = io._write_temp
        for same_mtime in (False, True):
            with self.subTest(same_mtime=same_mtime):
                self.source.write_bytes(V1)
                before = self.source.stat()
                other = V1.replace(b"conversation_count: 0", b"conversation_count: 9")
                def intervene(path, data):
                    tmp = actual_write(path, data)
                    self.source.write_bytes(other)
                    if same_mtime:
                        os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
                    return tmp
                with patch.object(io, "_write_temp", side_effect=intervene):
                    with self.assertRaises(io.MemoryConflictError):
                        self.run_migrate()
                self.assertEqual(self.source.read_bytes(), other)
                self.assertFalse(self.target.exists())
        self.source.write_bytes(V1)
        real_publish = io._exclusive_publish
        def race(tmp, dst):
            dst.write_bytes(b"SYNTHETIC RACE WINNER")
            real_publish(tmp, dst)
        with patch.object(io, "_exclusive_publish", side_effect=race):
            with self.assertRaises(io.MemoryAlreadyExistsError):
                self.run_migrate()
        self.assertEqual(self.target.read_bytes(), b"SYNTHETIC RACE WINNER")
        self.assertEqual(self.source.read_bytes(), V1)
        # Same-path conflict detected even after backup and temp preparation.
        with patch.object(io, "_write_temp", side_effect=intervene):
            with self.assertRaises(io.MemoryConflictError):
                self.run_migrate(inplace=True)
        self.assertEqual(self.source.read_bytes(), other)

    def test_M10(self):
        orphan = self.root / "memory.md.bak.deleted"
        orphan.write_bytes(b"E-SYN-DELETED")
        with patch.object(io, "read", wraps=io.read) as read:
            self.run_migrate()
        read.assert_called_once_with(self.source)
        self.assertNotIn(b"E-SYN-DELETED", self.target.read_bytes())
        self.assertIn("归档".encode(), self.target.read_bytes())
        self.assertEqual(schema.parse(self.target.read_bytes().decode()).episodes, [])

    def test_M11(self):
        for options in (
            dict(policy="read_only"), dict(policy="off"), dict(policy="unset"),
            dict(consent="pending"), dict(consent="denied"),
            dict(migration_authorized=False), dict(policy="auto", migration_authorized=False),
        ):
            with self.subTest(options=options), patch.object(io, "read") as read:
                self.no_change(AccessError, **options)
                read.assert_not_called()

    def test_M12(self):
        upgraded = schema.upgrade(schema.parse(V1.decode()))
        for text in (upgraded.replace("memory_consent: granted", "memory_consent: []"),
                     upgraded.replace("[]", '[{"id":"E-SYN-INVALID"}]', 1)):
            self.source.write_bytes(text.encode())
            self.no_change(inplace=True)

    def test_M13(self):
        for data in (
            V1, V1.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"), b"\xef\xbb\xbf" + V1,
            V1.replace(b"conversation_count: 0", b"conversation_count: 0\nx_synthetic_extension: '' # keep")
              + "\n## 扩展\n虚构值\n".encode(),
            V1 + "\n```md\n## 归档\n```\n".encode(),
        ):
            with self.subTest(data_size=len(data)):
                self.source.write_bytes(data)
                self.run_migrate()
                doc = schema.parse(self.target.read_bytes().decode())
                left = doc.sections[schema.EPISODES][0]
                right = doc.sections[schema.CALIBRATION][2]
                restored = (doc.text[:left] + doc.text[right:]).replace(
                    "schema_version: 2", "schema_version: 1", 1
                ).replace('"1.1.2"', '"1.0.1"', 1)
                self.assertEqual(restored.encode(), data)
                self.target.unlink()

    def fail_post_replace(self, *, newer=None):
        actual_replace, actual_version = io.os.replace, io.read_version
        inject = False
        replaced = False
        def replace(src, dst):
            nonlocal inject, replaced
            actual_replace(src, dst)
            if not replaced:
                replaced = True
                inject = True
                if newer is not None:
                    self.source.write_bytes(newer)
        def read(path):
            nonlocal inject
            if inject:
                inject = False
                raise OSError("synthetic post-replace verification fault")
            return actual_version(path)
        with patch.object(io.os, "replace", side_effect=replace), patch.object(io, "read_version", side_effect=read):
            with self.assertRaises(io.MemoryWriteError) as error:
                self.run_migrate(inplace=True)
        self.assertTrue(replaced)
        backups = list(self.root.glob("memory.md.bak.*"))
        self.assertEqual([p.read_bytes() for p in backups], [V1])
        return str(error.exception)

    def test_M14(self):
        self.assertIn("original bytes restored", self.fail_post_replace())
        self.assertEqual(self.source.read_bytes(), V1)

    def test_M15(self):
        newer = b"SYNTHETIC NEW STATE"
        self.assertIn("recovery refused", self.fail_post_replace(newer=newer))
        self.assertEqual(self.source.read_bytes(), newer)

    def test_M16(self):
        # Interrupt on each side of the atomic OS boundary. The interior of
        # the syscall is not instrumentable; this is not a power-loss test.
        real_replace = io.os.replace
        for after in (False, True):
            self.source.write_bytes(V1)
            def interrupt(src, dst):
                if after:
                    real_replace(src, dst)
                raise KeyboardInterrupt
            with patch.object(io.os, "replace", side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    self.run_migrate(inplace=True)
            expected = schema.upgrade(schema.parse(V1.decode())).encode() if after else V1
            self.assertEqual(self.source.read_bytes(), expected)

    def test_M17(self):
        backup = self.root / "memory.md.bak.synthetic"
        backup.write_bytes(b"SYNTHETIC unrelated backup")
        with patch.object(io, "_unique_backup_path", return_value=backup):
            with self.assertRaises(io.MemoryBackupError):
                self.run_migrate(inplace=True)
        self.assertEqual(backup.read_bytes(), b"SYNTHETIC unrelated backup")
        self.assertEqual(self.source.read_bytes(), V1)

    def test_M18(self):
        self.source.write_bytes(V1 + "\n## 用户明确要求记住\n虚构重复。\n".encode())
        self.no_change()

    def test_M19(self):
        for target_api in ("_write_temp", "_exclusive_publish"):
            with self.subTest(target_api=target_api), patch.object(
                io, target_api, side_effect=PermissionError("synthetic target refused")
            ):
                with self.assertRaises(PermissionError):
                    self.run_migrate()
                self.assertEqual(self.source.read_bytes(), V1)
                self.assertFalse(self.target.exists())
                self.assertEqual(list(self.root.glob("result.md.*.tmp")), [])
        with patch.object(io.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(io.MemoryWriteError):
                self.run_migrate(inplace=True)
        self.assertEqual(self.source.read_bytes(), V1)

    def test_M20(self):
        self.source.unlink()
        self.no_change(FileNotFoundError)
        self.source.write_bytes(b"")
        self.no_change()

    def test_M21(self):
        payload = GROUPS["migration"][-1]["input"]["synthetic_body_append"].encode()
        self.source.write_bytes(V1 + payload + b"\n")
        with patch.object(os, "system") as shell, patch.object(subprocess, "Popen") as spawn:
            self.run_migrate()
            shell.assert_not_called()
            spawn.assert_not_called()
        self.assertIn(payload, self.target.read_bytes())
        self.assertEqual(schema.parse(self.target.read_bytes().decode()).episodes, [])
