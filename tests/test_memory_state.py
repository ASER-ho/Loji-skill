"""L113: synthetic installation state and guarded production body operations."""
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from l120_support import AS_OF, RECORDS, fresh_memory, ledger_text, episode, GROUPS, ROOT
from scripts import memory_state as ms, memory_io as io, memory_schema as schema
from scripts.migrate_memory import AccessError as BodyAccessError

HOST = ms.Host(True, True, True, True, True, "auto", "granted")
BASE = GROUPS["episode_integrity"][0]["input"]["episodes"][0]


class MemoryStateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.state = ms.MemoryState(self.folder, HOST)
        (self.folder / "memory.md").write_text(fresh_memory(), encoding="utf-8")
        (self.folder / "JUDGMENTS.md").write_text(ledger_text(RECORDS), encoding="utf-8")

    def body_snapshot(self):
        return {name: (self.folder / name).read_bytes() for name in ("memory.md", "JUDGMENTS.md")}

    def choose(self, policy):
        self.state.configure(policy, user_confirmed=True)

    def record(self):
        data = episode(BASE)
        data.pop("state")
        return data

    def deny_all_body(self, state=None):
        state = state or self.state
        with patch.object(io, "read", side_effect=AssertionError("body opened")):
            for operation in (state.read_memory, state.load_judgments, state.context,
                              lambda: state.mutate("add", self.record(), user_requested=True,
                                                   eligible_and_private=True)):
                with self.assertRaises(ms.AccessError):
                    operation()

    def test_first_missing_and_legacy_frontmatter_never_read(self):
        # Legacy auto/granted in body is deliberately useless for authorization.
        memory = self.folder / "memory.md"
        memory.write_text(memory.read_text(encoding="utf-8").replace("unset", "auto").replace("pending", "granted"), encoding="utf-8")
        self.assertTrue(self.state.status()["needs_setup"])
        self.deny_all_body()
        self.assertFalse(self.state.path.exists())

    def test_four_policies_save_restore_new_instances(self):
        before = self.body_snapshot()
        for policy in sorted(ms.POLICIES):
            with self.subTest(policy=policy):
                self.choose(policy)
                self.assertEqual(ms.parse(self.state.path.read_bytes()),
                                 {"memory_policy": policy, "confirmed": True})
                fresh = ms.MemoryState(self.folder, HOST)
                status = fresh.status()
                self.assertFalse(status["needs_setup"])
                self.assertEqual(status["can_read"], policy != "off")
                self.assertEqual(status["can_write"], policy == "auto")
        self.assertEqual(before, self.body_snapshot())

    def test_strict_rejection_table(self):
        invalid = [b"", b"{", b"null", b"[]", b"true", b"\xff", b"\xef\xbb\xbf{}",
                   b'{"memory_policy":"auto","confirmed":true,"extra":1}',
                   b'{"memory_policy":"auto","memory_policy":"off","confirmed":true}',
                   b'{"memory_policy":[],"confirmed":true}',
                   b'{"memory_policy":"AUTO","confirmed":true}',
                   b'{"memory_policy":"auto","confirmed":1}',
                   b'{"memory_policy":"auto","confirmed":"true"}',
                   b'{"memory_policy":"auto"}', b" " * 1025]
        for data in invalid:
            with self.subTest(data=data[:100]):
                with self.assertRaises(ms.StateError):
                    ms.parse(data)
                self.state.path.write_bytes(data)
                self.assertTrue(self.state.status()["needs_setup"])
                self.deny_all_body()

    def test_duplicate_state_field_keeps_its_own_diagnostic(self):
        with self.assertRaises(ms.StateError) as caught:
            ms.parse(b'{"memory_policy":"off","memory_policy":"auto","confirmed":true}')
        self.assertIn("duplicate state field", str(caught.exception))
        with self.assertRaises(ms.StateError) as caught:
            ms.parse(b'{"memory_policy":"off",')
        self.assertIn("invalid state JSON", str(caught.exception))

    def test_unconfirmed_never_authorizes(self):
        self.state.path.write_text('{"memory_policy":"auto","confirmed":false}', encoding="utf-8")
        self.deny_all_body()

    def test_off_no_body_reads_and_no_repeated_setup(self):
        self.choose("off")
        self.assertFalse(self.state.status()["needs_setup"])
        self.deny_all_body(ms.MemoryState(self.folder, HOST))

    def test_read_only_reads_and_zero_body_writes(self):
        self.choose("read_only")
        before = self.body_snapshot()
        self.state.read_memory()
        self.state.load_judgments()
        self.assertEqual(self.state.context(as_of=AS_OF)["episodes"], [])
        with patch.object(io, "atomic_write", side_effect=AssertionError("body write")):
            with self.assertRaises(ms.AccessError):
                self.state.mutate("add", self.record(), user_requested=True, eligible_and_private=True)
        self.assertEqual(before, self.body_snapshot())
        self.assertFalse(list(self.folder.glob("memory.md.bak*")))

    def test_explicit_only_writes_on_request(self):
        self.choose("explicit")
        before = self.body_snapshot()
        with self.assertRaises(ms.AccessError):
            self.state.mutate("add", self.record(), eligible_and_private=True)
        self.assertEqual(before, self.body_snapshot())
        self.state.mutate("add", self.record(), user_requested=True, eligible_and_private=True)
        self.assertEqual(len(self.state.context(as_of=AS_OF)["episodes"]), 1)

    def test_auto_preserves_existing_eligibility_rules(self):
        self.choose("auto")
        with self.assertRaises(BodyAccessError):
            self.state.mutate("add", self.record(), eligible_and_private=False)
        self.assertEqual(schema.parse(self.state.read_memory().text).episodes, [])
        self.state.mutate("add", self.record(), eligible_and_private=True)
        self.assertEqual(len(self.state.context(as_of=AS_OF)["episodes"]), 1)

    def test_host_must_accept_saved_state(self):
        self.choose("auto")
        self.deny_all_body(ms.MemoryState(self.folder, replace(HOST, accept_saved=False)))
        self.deny_all_body(ms.MemoryState(self.folder, ms.Host()))

    def test_current_user_switch_and_host_ceiling(self):
        self.choose("auto")
        other_session = ms.MemoryState(self.folder, HOST)
        self.choose("off")
        self.deny_all_body(other_session)
        self.choose("explicit")
        self.assertTrue(other_session.status()["can_read"])
        self.assertFalse(other_session.status()["can_write"])
        for host in (replace(HOST, body_read=False), replace(HOST, host_policy="off"),
                     replace(HOST, host_consent="denied")):
            self.deny_all_body(ms.MemoryState(self.folder, host))
        self.choose("auto")
        for host in (replace(HOST, body_write=False), replace(HOST, host_policy="read_only"),
                     replace(HOST, host_policy="explicit")):
            restricted = ms.MemoryState(self.folder, host)
            self.assertTrue(restricted.status()["can_read"])
            with self.assertRaises(ms.AccessError):
                restricted.mutate("add", self.record(), eligible_and_private=True)

    def test_no_state_file_capability_or_rejected_access(self):
        self.choose("auto")
        self.deny_all_body(ms.MemoryState(self.folder, replace(HOST, state_read=False)))
        with patch.object(Path, "open", side_effect=PermissionError("host denied")):
            self.assertFalse(self.state.status()["can_read"])
            self.deny_all_body()

    def test_reset_keeps_bodies_and_requires_reconfirmation(self):
        self.choose("auto")
        before = self.body_snapshot()
        self.state.reset(user_requested=True)
        self.assertEqual(before, self.body_snapshot())
        self.assertTrue(ms.MemoryState(self.folder, HOST).status()["needs_setup"])
        self.deny_all_body()
        self.choose("explicit")
        self.assertTrue(self.state.status()["can_read"])

    def test_missing_or_corrupt_after_authorization_drops_stale_permission(self):
        for replacement in (None, b"broken"):
            self.choose("auto")
            self.state.read_memory()
            if replacement is None:
                self.state.path.unlink()
            else:
                self.state.path.write_bytes(replacement)
            self.deny_all_body()
            self.choose("read_only")
            self.assertTrue(self.state.status()["can_read"])

    def test_no_implicit_confirmation_or_reset(self):
        for call in (lambda: self.state.configure("auto"), lambda: self.state.reset(),
                     lambda: self.state.configure("bad", user_confirmed=True)):
            with self.assertRaises(ms.StateError):
                call()
        self.assertFalse(self.state.path.exists())

    def test_save_failure_never_announces_saved_or_reuses_old_auto(self):
        self.choose("auto")
        old = self.state.path.read_bytes()
        with patch.object(io.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(io.MemoryWriteError):
                self.state.configure("read_only", user_confirmed=True)
        self.assertEqual(old, self.state.path.read_bytes())
        self.deny_all_body()
        self.choose("off")
        self.assertFalse(self.state.status()["needs_setup"])

    def test_initial_publication_failure(self):
        with patch.object(io, "publish_new", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.choose("auto")
        self.assertFalse(self.state.path.exists())
        self.deny_all_body()

    def test_readback_failure_is_failure(self):
        with patch.object(self.state, "_saved", side_effect=ms.StateError("cannot verify")):
            with self.assertRaises(ms.StateError):
                self.choose("auto")
        self.deny_all_body()

    def test_relative_and_missing_directories_rejected_no_creation(self):
        with self.assertRaises(ms.StateError):
            ms.MemoryState("relative", HOST)
        target = self.folder / "absent"
        state = ms.MemoryState(target, HOST)
        self.assertTrue(state.status()["needs_setup"])
        with self.assertRaises(ms.StateError):
            state.configure("auto", user_confirmed=True)
        self.assertFalse(target.exists())

    def test_state_write_denied_even_when_body_allowed(self):
        self.choose("auto")
        restricted = ms.MemoryState(self.folder, replace(HOST, state_write=False))
        with self.assertRaises(ms.AccessError):
            restricted.configure("off", user_confirmed=True)
        self.deny_all_body(restricted)

    def test_lock_unavailable_fails_closed(self):
        self.choose("auto")
        with patch.object(io, "_lock_backend", return_value=None):
            self.assertFalse(self.state.status()["can_read"])
            with self.assertRaises(io.MemoryLockUnavailableError):
                self.state.read_memory()

    def test_cross_process_lock_covers_complete_body_transaction(self):
        self.choose("auto")
        source = ("import sys; from scripts.memory_state import *; "
                  "s=MemoryState(sys.argv[1],Host(True,True,True,True,True,'auto','granted'),timeout=0.1); "
                  "s.configure('off',user_confirmed=True)")
        with self.state.access(write=True):
            result = subprocess.run([sys.executable, "-B", "-c", source, str(self.folder)],
                                    cwd=ROOT, capture_output=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"MemoryLockTimeoutError", result.stderr)
            self.assertEqual(ms.parse(self.state.path.read_bytes())["memory_policy"], "auto")
        result = subprocess.run([sys.executable, "-B", "-c", source, str(self.folder)],
                                cwd=ROOT, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.deny_all_body()

    def test_fresh_process_cli_restores_without_policy_argument(self):
        self.choose("read_only")
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/memory_state.py"),
            "status", "--memory-dir", str(self.folder), "--accept-saved", "--state-read",
            "--body-read", "--body-write", "--host-policy", "auto", "--host-consent", "granted"],
            capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["saved"]["memory_policy"], "read_only")
        self.assertTrue(state["can_read"])
        self.assertFalse(state["can_write"])

    def test_no_directory_discovery_or_other_agent_access(self):
        self.choose("read_only")
        with patch.object(Path, "rglob", side_effect=AssertionError("directory search")), \
             patch.object(Path, "glob", side_effect=AssertionError("directory search")):
            self.assertTrue(self.state.status()["can_read"])
            self.state.read_memory()

    def test_linked_state_path_rejected_before_body(self):
        self.choose("auto")
        original = Path.is_symlink
        def linked(path):
            return path == self.state.path or original(path)
        with patch.object(Path, "is_symlink", linked):
            self.assertFalse(self.state.status()["can_read"])
            with self.assertRaises(ms.StateError):
                self.state.read_memory()

    def test_current_user_can_switch_off_under_host_body_prohibition(self):
        self.choose("auto")
        restricted = ms.MemoryState(self.folder, replace(HOST, body_read=False, body_write=False))
        before = self.body_snapshot()
        with patch.object(io, "read", side_effect=AssertionError("body opened")):
            restricted.configure("off", user_confirmed=True)
        self.assertEqual(restricted.status()["saved"]["memory_policy"], "off")
        self.assertEqual(before, self.body_snapshot())

    def test_state_backup_and_temporary_write_failure_keep_previous_choice(self):
        self.choose("off")
        old = self.state.path.read_bytes()
        for target, error in (("backup", io.MemoryBackupError("backup failed")),
                              ("_write_temp", io.MemoryWriteError("temp failed"))):
            with self.subTest(target=target), patch.object(io, target, side_effect=error):
                with self.assertRaises(io.MemoryIOError):
                    self.choose("auto")
                self.assertEqual(self.state.path.read_bytes(), old)
                self.deny_all_body()

    def test_schema_one_upgrade_never_recovers_frontmatter_authorization(self):
        legacy = (ROOT / "tests/fixtures/l120/memory-v1.synthetic.md").read_bytes()
        (self.folder / "memory.md").write_bytes(legacy)
        self.deny_all_body()
        self.choose("read_only")
        self.assertEqual(self.state.read_memory().data, legacy)
        with self.assertRaises(schema.FormatError):
            self.state.context(as_of=AS_OF)
        self.assertEqual((self.folder / "memory.md").read_bytes(), legacy)


class EffectivePolicyTests(unittest.TestCase):
    setUp = MemoryStateTests.setUp
    choose = MemoryStateTests.choose
    record = MemoryStateTests.record
    def test_effective_policy_matrix(self):
        rank = {p: i for i, p in enumerate(("off", "read_only", "explicit", "auto"))}
        for selected in rank:
            self.choose(selected)
            for ceiling in rank:
                for consent in ("granted", "pending", "denied"):
                    for read, write in ((True, True), (True, False), (False, True)):
                        for requested in (False, True):
                            host = replace(HOST, host_policy=ceiling, host_consent=consent,
                                           body_read=read, body_write=write)
                            state = ms.MemoryState(self.folder, host)
                            effective = min((selected, ceiling), key=rank.get)
                            if consent != "granted" or not read:
                                effective = "off"
                            elif not write and rank[effective] > rank["read_only"]:
                                effective = "read_only"
                            with self.subTest(selected=selected, ceiling=ceiling, consent=consent,
                                              read=read, write=write, requested=requested):
                                with patch.object(io, "read", side_effect=AssertionError("body opened during authorization")):
                                    with state._transaction():
                                        auth = state._authorization(requested=requested)
                                self.assertEqual(auth.body_args()["policy"], effective)
                                self.assertEqual(auth.can_read, effective != "off")
                                self.assertEqual(auth.can_write, effective == "auto" or
                                                 (effective == "explicit" and requested))

    def test_auto_under_explicit_ceiling_keeps_explicit_for_requested_write(self):
        self.choose("auto")
        state = ms.MemoryState(self.folder, replace(HOST, host_policy="explicit"))
        with state.access(write=True, user_requested=True) as auth:
            self.assertEqual(auth.body_args(), {"policy": "explicit", "consent": "granted"})
        state.mutate("add", self.record(), user_requested=True, eligible_and_private=True)
        with self.assertRaises(ms.AccessError):
            state.mutate("add", self.record(), eligible_and_private=True)

    def test_state_write_is_complete_configuration_transaction(self):
        state = ms.MemoryState(self.folder, replace(HOST, state_read=False))
        state.configure("off", user_confirmed=True)
        state.configure("explicit", user_confirmed=True)
        self.assertEqual(ms.parse(state.path.read_bytes())["memory_policy"], "explicit")
        self.assertTrue(list(self.folder.glob("memory.state.json.bak.*")))
        with self.assertRaises(ms.AccessError):
            state.read_memory()
        self.assertFalse(state.status()["can_read"])


class CLIContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        (self.folder / "memory.md").write_text(fresh_memory([episode(BASE)]), encoding="utf-8")
        (self.folder / "JUDGMENTS.md").write_text(ledger_text(RECORDS), encoding="utf-8")
        ms.MemoryState(self.folder, HOST).configure("explicit", user_confirmed=True)

    def invoke(self, legacy, action="context", *, matters=None, payload=None):
        if legacy:
            argv = [str(ROOT / "scripts/episodic_memory.py"), action,
                    "--memory", str(self.folder / "memory.md"), "--ledger", str(self.folder / "JUDGMENTS.md"),
                    "--policy", "explicit", "--consent", "granted"]
        else:
            argv = [str(ROOT / "scripts/memory_state.py"), "context" if action == "context" else "mutate",
                    "--memory-dir", str(self.folder), "--accept-saved", "--state-read", "--state-write",
                    "--body-read", "--body-write"]
            if action != "context":
                argv += ["--operation", action, "--data", payload if payload is not None else "null"]
        if action == "context":
            argv += ["--as-of", AS_OF]
        else:
            argv += ["--user-requested", "--eligible-and-private"]
        if matters is not None:
            argv += ["--matters", matters]
        return subprocess.run([sys.executable, "-B", *argv], cwd=ROOT,
                              input=payload.encode() if payload is not None else b"",
                              capture_output=True, timeout=20)

    def test_context_matches_unchanged_v112_entry(self):
        for matters in (None, "[]", '["missing"]', json.dumps([BASE["relevance"]])):
            with self.subTest(matters=matters):
                old, new = self.invoke(True, matters=matters), self.invoke(False, matters=matters)
                self.assertEqual((old.returncode, new.returncode), (0, 0), (old.stderr, new.stderr))
                self.assertEqual(json.loads(old.stdout), json.loads(new.stdout))
                self.assertEqual(bool(json.loads(new.stdout)["episodes"]), matters in (None, json.dumps([BASE["relevance"]])))

    def test_null_wrong_type_bad_items_and_json_rejected_by_both_entries(self):
        for matters in ("null", '"all"', "1", "true", "{}", '[""]', '["   "]', "[1]", "[null]", "{", "[NaN]"):
            with self.subTest(matters=matters):
                before = (self.folder / "memory.md").read_bytes()
                for legacy in (True, False):
                    self.assertNotEqual(self.invoke(legacy, matters=matters).returncode, 0)
                self.assertEqual((self.folder / "memory.md").read_bytes(), before)

    def test_noncontext_matters_refused_before_any_state_access(self):
        for legacy in (True, False):
            result = self.invoke(legacy, "forget", matters="[]", payload='{"id":"missing"}')
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"only supported for context", result.stderr)
        (self.folder / ms.STATE_NAME).unlink()
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/memory_state.py"),
                "status", "--memory-dir", str(self.folder), "--matters", "[]"], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"only supported for context", result.stderr)

    def test_mutate_strict_json_matches_unchanged_v112_entry(self):
        for payload in ('{"id":"missing","id":"other"}', '{"id":NaN}', '{"id":Infinity}',
                        '{"id":{"x":1,"x":2}}', "null", "[]", "{", ""):
            with self.subTest(payload=payload):
                before = (self.folder / "memory.md").read_bytes()
                for legacy in (True, False):
                    result = self.invoke(legacy, "forget", payload=payload)
                    self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.folder / "memory.md").read_bytes(), before)
        for legacy in (True, False):
            result = self.invoke(legacy, "forget", payload='{"id":"x","id":"y"}')
            self.assertIn(b"duplicate JSON key", result.stderr)


if __name__ == "__main__":
    unittest.main()