"""Synthetic credential cleanup and false-positive prevention for the host gate."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import run_l113_host as host
from l113_native import preflight_verdict, choices_offered


class HostRunnerSafetyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "synthetic-auth-source"
        self.source.write_bytes(b"SYNTHETIC-CREDENTIAL-NOT-REAL")
        self.args = SimpleNamespace(output=self.root / "evidence", workspace=self.root / "project",
            codex=Path(sys.executable), model="synthetic-model", auth_source=self.source,
            clear_registration=False, preflight_only=False)
        self.runner = host.Runner(self.args)
        def process(argv, **kwargs):
            return b"SKILL.md\0" if argv[0] == "git" else b"codex-cli 0.167.0-alpha.4.1\n"
        p = patch.object(host.subprocess, "check_output", side_effect=process)
        p.start()
        self.addCleanup(p.stop)

    def test_setup_failure_after_auth_copy_cleans_credential(self):
        original = host.save
        def save(path, value):
            if path.name == "initial-synthetic.json":
                self.assertTrue(self.runner.auth_path.exists())
                raise OSError("synthetic setup failure")
            return original(path, value)
        with patch.object(host, "save", side_effect=save), self.assertRaises(OSError):
            self.runner.run()
        self.assertFalse(self.runner.auth_path.exists())

    def test_partial_auth_copy_failure_cleans_credential(self):
        original = host.shutil.copyfile
        def copy(source, target, **kwargs):
            if Path(target) == self.runner.auth_path:
                Path(target).write_bytes(b"SYNTHETIC-PARTIAL")
                raise OSError("synthetic partial copy failure")
            return original(source, target, **kwargs)
        with patch.object(host.shutil, "copyfile", side_effect=copy), self.assertRaises(OSError):
            self.runner.run()
        self.assertFalse(self.runner.auth_path.exists())

    def test_native_initialization_failure_cleans_credential(self):
        with patch.object(host, "Native", side_effect=RuntimeError("synthetic native failure")), self.assertRaises(RuntimeError):
            self.runner.run()
        self.assertFalse(self.runner.auth_path.exists())

    def test_turn_exception_and_close_exception_both_clean_credential(self):
        native = Mock()
        native.close.side_effect = OSError("synthetic close failure")
        with patch.object(host, "Native", return_value=native), \
             patch.object(self.runner, "execute", side_effect=KeyboardInterrupt), self.assertRaises(OSError):
            self.runner.run()
        self.assertFalse(self.runner.auth_path.exists())
        self.assertEqual(self.source.read_bytes(), b"SYNTHETIC-CREDENTIAL-NOT-REAL")
        for path in self.runner.out.rglob("*.json"):
            self.assertNotIn(b"SYNTHETIC-CREDENTIAL-NOT-REAL", path.read_bytes())

    def test_preexisting_home_is_not_owned_or_deleted(self):
        self.runner.home.mkdir(parents=True)
        self.runner.auth_path.write_bytes(b"SYNTHETIC-PREEXISTING")
        with self.assertRaises(FileExistsError):
            self.runner.run()
        self.assertEqual(self.runner.auth_path.read_bytes(), b"SYNTHETIC-PREEXISTING")

    def continuation_fixture(self):
        previous = self.root / "previous-evidence"
        self.args.resume_from = previous
        self.runner.synthetic.mkdir(parents=True)
        (self.runner.synthetic / "memory.state.json").write_bytes(b'{"memory_policy":"auto","confirmed":"broken"}')
        (self.runner.work / "AGENTS.md").write_text("synthetic config", encoding="utf-8")
        self.runner.skill.mkdir(parents=True)
        skill = self.runner.skill / "SKILL.md"
        skill.write_bytes(b"synthetic skill")
        host.save(previous / "installed-manifest.json", {"SKILL.md": hashlib.sha256(skill.read_bytes()).hexdigest()})
        host.save(previous / "normal-installed-host-config.json", {"text": "synthetic config"})
        host.save(previous / "launch.json", {"runtime_version": "codex-cli 0.167.0-alpha.4.1",
            "runtime_sha256": hashlib.sha256(self.args.codex.read_bytes()).hexdigest()})
        host.save(previous / "runs/H113-06-corrupt/result.json", {"status": "completed",
            "answer": "自动记录、明确要求才记录、只读、关闭", "python_audit": [],
            "after": host.snapshot(self.runner.synthetic)})
        return previous

    def test_continuation_native_failure_cleans_auth_and_preserves_prior_evidence(self):
        previous = self.continuation_fixture()
        before = host.snapshot(previous)
        with patch.object(host, "Native", side_effect=RuntimeError("synthetic continuation failure")), self.assertRaises(RuntimeError):
            self.runner.run()
        self.assertFalse(self.runner.auth_path.exists())
        self.assertEqual(host.snapshot(previous), before)

    def test_continuation_rejects_changed_synthetic_state_before_copying_auth(self):
        self.continuation_fixture()
        (self.runner.synthetic / "memory.state.json").write_bytes(b'{"memory_policy":"auto","confirmed":true}')
        with patch.object(host, "Native") as native, self.assertRaises(RuntimeError):
            self.runner.run()
        native.assert_not_called()
        self.assertFalse(self.runner.auth_path.exists())

    def test_python_audit_observes_synthetic_body_reads(self):
        self.runner.out.mkdir()
        self.runner.synthetic.mkdir(parents=True)
        self.runner.install_audit()
        memory = self.runner.synthetic / "memory.md"
        memory.write_text("synthetic", encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(self.runner.work / "audit-support"))
        result = subprocess.run([sys.executable, "-B", "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).read_bytes()", str(memory)],
                                env=env, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        audit = [json.loads(x) for x in self.runner.audit.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(x.get("kind") == "open" and Path(x["path"]) == memory for x in audit))


class NativePreflightTests(unittest.TestCase):
    def fixture(self):
        def tool(command, text):
            return {"type": "commandExecution", "command": command, "aggregatedOutput": text,
                    "exitCode": 0, "status": "completed"}
        return {"status": "completed", "tools": [tool("read probe-input.txt", "FIXED-731"),
                tool("write probe-output.txt", ""), tool("read probe-output.txt", "FIXED-731 VERIFIED")]}

    def test_exact_native_read_write_readback_required(self):
        result = self.fixture()
        self.assertTrue(preflight_verdict(result, "FIXED-731", "FIXED-731 VERIFIED\n"))
        for actual in ("VERIFIED", "OTHER VERIFIED", "FIXED-731 VERIFIED extra", " FIXED-731 VERIFIED", "FIXED-731 VERIFIED ", ""):
            self.assertFalse(preflight_verdict(result, "FIXED-731", actual))
        result["tools"][0]["aggregatedOutput"] = ""
        self.assertFalse(preflight_verdict(result, "FIXED-731", "FIXED-731 VERIFIED"))

    def test_exit_zero_and_verified_string_without_successful_native_tools_fail(self):
        result = self.fixture()
        result["tools"][1]["exitCode"] = -1
        self.assertFalse(preflight_verdict(result, "FIXED-731", "FIXED-731 VERIFIED"))
        result = self.fixture()
        result["tools"] = []
        self.assertFalse(preflight_verdict(result, "FIXED-731", "FIXED-731 VERIFIED"))
        result = self.fixture()
        result["status"] = "failed"
        self.assertFalse(preflight_verdict(result, "FIXED-731", "FIXED-731 VERIFIED"))


class ChoicePromptTests(unittest.TestCase):
    def test_four_unambiguous_english_or_chinese_options(self):
        self.assertTrue(choices_offered("auto explicit read_only off"))
        self.assertTrue(choices_offered("记忆挡位选哪种：自动记录、明确要求才记录、只读、关闭？"))
        self.assertFalse(choices_offered("自动记录、只读、关闭？"))
        self.assertFalse(choices_offered("已保存 auto"))


if __name__ == "__main__":
    unittest.main()
