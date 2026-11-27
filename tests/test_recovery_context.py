"""Recovery under exact scope, established authority, and bounded reads."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from l120_support import ROOT, fresh_memory, ledger_text
from scripts import evidence_identity as evidence, memory_io as io, memory_state as ms
from scripts import recovery_context as recovery


FIXTURE = json.loads((ROOT / "tests/fixtures/project_context_recovery.json").read_text(encoding="utf-8"))
HOST = ms.Host(accept_saved=True, state_read=True, state_write=True, body_read=True)
PROJECT = "海燕"


def fact(key, category, text, **fields):
    return dict(id=key, project=PROJECT, category=category, text=text, **fields)


class RecoveryContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        self.memory = self.folder / "memory"
        self.memory.mkdir()
        self.project = self.folder / "project"
        self.project.mkdir()
        self.state = ms.MemoryState(self.memory, HOST)
        self.case = copy.deepcopy(FIXTURE["cases"]["recoverable"])
        self.case["judgments"][0]["basis"] = ["直接证据：阈值 [source_id:artifact:judgment]"]
        self.case["episodes"][1]["summary"] += " [source_id:artifact:matter]"
        self.selection = recovery.Selection(PROJECT, self.case["expected"]["matters"], FIXTURE["as_of"])
        self.records = [
            fact("goal", "active_goal", "在九月底完成可验证迁移"),
            fact("budget", "hard_constraints", "预算上限 88 合成单位"),
            fact("deadline", "hard_constraints", "截止 2040-09-30"),
            fact("region", "confirmed_decisions", "将新域名限于合成站点", matter_id="lantern-lab"),
            fact("disputed-decision", "confirmed_decisions", "假定未决归属已定", matter_id="north-docket"),
            fact("waiting", "pending_items", "核实队列归属后再推进灰度"),
            fact("summary", "pending_items", "记录尚待比较", matter_id="lantern-lab", summary_source_id="note:summary"),
            {**fact("unrelated", "hard_constraints", "不相关信息"), "project": "琥珀"},
            fact("expired", "hard_constraints", "已过期信息", expires_on="2040-01-01"),
        ]
        self.write_memory()
        self.state.configure("read_only", user_confirmed=True)
        self.identities = []
        for name in ("judgment", "matter", "project"):
            filename = name + ".txt"
            (self.project / filename).write_text(name + " original", encoding="utf-8")
            self.identities.append(evidence.observe(self.project, "artifact:" + name, filename))

    def write_memory(self):
        body = fresh_memory(self.case["episodes"])
        block = "\n\n```loji-recovery\n" + json.dumps(self.records, ensure_ascii=False) + "\n```\n"
        (self.memory / "memory.md").write_text(body.replace("## 近期上下文", "## 近期上下文" + block),
                                              encoding="utf-8")
        (self.memory / "JUDGMENTS.md").write_text(ledger_text(self.case["judgments"]), encoding="utf-8")

    def recover(self, **overrides):
        options = {"byte_budget": 4096, "lookup_budget": 4, "project_root": self.project,
                   "identities": self.identities, **overrides}
        return recovery.recover(self.state, self.selection, **options)

    def lookup(self, key, **overrides):
        options = {"byte_budget": 4096, "lookup_budget": 3, "project_root": self.project,
                   "identities": self.identities, **overrides}
        return recovery.lookup(self.state, self.selection, key, **options)

    def test_compacted_context_restores_all_required_synthetic_facts_and_ignores_noise(self):
        # A new instance receives only the same scoped local state. Excess
        # history enters after the required project records in a fresh turn.
        self.records.extend(fact(f"long-{i}", "pending_items", "拟造的历史噪声" * 120) for i in range(400))
        self.write_memory()
        self.state = ms.MemoryState(self.memory, HOST)
        result = self.recover()
        self.assertEqual([row["id"] for row in result["active_goal"]], ["goal"])
        self.assertEqual([row["id"] for row in result["hard_constraints"]], ["budget", "deadline"])
        self.assertEqual({row["id"] for row in result["confirmed_decisions"]}, {"region", "E-TIDE", "E-LAMP", "E-CACHE"})
        self.assertEqual(result["unresolved_conflicts"], [{"matter_id": "north-docket"}])
        self.assertIn("waiting", [row["id"] for row in result["pending_items"]])
        self.assertNotIn("J-CACHE-OLD", str(result))
        self.assertNotIn("E-OTHER", str(result))
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(recovery.encode(result)), 4096)

    def test_privilege_denied_or_unknown_opens_no_private_body(self):
        self.state.configure("off", user_confirmed=True)
        path = self.memory / ms.STATE_NAME
        denied_states = {"off": path.read_bytes(), "invalid": b"invalid", "missing": None}
        malformed = [{"relative_path": "../outside"}]
        with (patch.object(io, "read", side_effect=AssertionError("private body read")),
              patch.object(recovery, "_identity_map", side_effect=AssertionError("identities parsed"))):
            for status, data in denied_states.items():
                with self.subTest(status=status):
                    if data is None:
                        path.unlink()
                    else:
                        path.write_bytes(data)
                    self.assertEqual(self.recover(identities=malformed), recovery.empty_card())
                    self.assertEqual(self.lookup("artifact:judgment", identities=malformed),
                                     {"status": "evidence_insufficient", "reason": "authorization"})

    def test_future_judgment_is_excluded_from_direct_and_episode_references(self):
        tide = next(row for row in self.case["judgments"] if row["id"] == "J-TIDE")
        tide.update(created_at="2099-01-01", updated_at="2099-01-01")
        cache = next(row for row in self.case["episodes"] if row["id"] == "E-CACHE")
        cache["related_judgments"].append(tide["id"])
        self.selection = recovery.Selection(PROJECT, self.selection.matters, self.selection.as_of, tide["id"])
        self.write_memory()
        with patch.object(evidence, "verify", wraps=evidence.verify) as verify:
            result = self.recover()
            verified_sources = {call.args[1].source_id for call in verify.call_args_list}
        self.assertNotIn("artifact:judgment", verified_sources)
        decisions = {row["id"] for row in result["confirmed_decisions"]}
        self.assertNotIn("E-TIDE", decisions)
        self.assertIn("E-CACHE", decisions)
        judgments = {row["id"] for row in result["judgments"]}
        self.assertNotIn("J-TIDE", judgments)
        self.assertIn("J-CACHE-NEW", judgments)

    def test_read_only_recovery_preserves_all_files_and_never_bootstraps_a_lock(self):
        def snapshot():
            return {p.relative_to(self.folder).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.folder.rglob("*") if p.is_file()}

        before = snapshot()
        self.assertEqual(len(self.recover()["hard_constraints"]), 2)
        self.assertEqual(self.lookup("artifact:judgment")["status"], "found")
        self.assertEqual(before, snapshot())
        io.lock_path_for(self.state._transaction_path()).unlink()
        before = snapshot()
        with patch.object(io, "read", side_effect=AssertionError("private body read")):
            self.assertEqual(self.recover(), recovery.empty_card())
        self.assertEqual(before, snapshot())

    def test_lookup_zero_does_no_io_and_small_budget_does_not_open_the_ledger(self):
        with patch.object(self.state, "access", side_effect=AssertionError("state touched")):
            self.assertTrue(self.recover(lookup_budget=0)["truncated"])
            self.assertEqual(self.lookup("artifact:judgment", lookup_budget=0)["reason"], "lookup_budget")
        with patch.object(recovery.jl, "load_ledger", side_effect=AssertionError("ledger touched")):
            result = self.recover(lookup_budget=1)
        self.assertEqual(len(result["hard_constraints"]), 2)
        self.assertEqual(result["unresolved_conflicts"], [{"matter_id": "north-docket"}])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["judgments"], [])

    def test_hard_wire_budget_counts_non_ascii_and_sources_and_rejects_impossible_limit(self):
        enough = self.recover()
        full_size = len(recovery.encode(enough))
        self.assertEqual(enough, self.recover(byte_budget=full_size))
        tight = self.recover(byte_budget=full_size - 1)
        self.assertTrue(tight["truncated"])
        self.assertLessEqual(len(recovery.encode(tight)), full_size - 1)
        minimal = self.recover(byte_budget=recovery.MIN_BYTE_BUDGET)
        self.assertTrue(minimal["truncated"])
        self.assertEqual(minimal["sources"], [])
        with patch.object(self.state, "access", side_effect=AssertionError("state touched")):
            with self.assertRaises(ValueError):
                self.recover(byte_budget=recovery.MIN_BYTE_BUDGET - 1)

    def test_exact_four_tiers_and_evidence_exhaustion(self):
        with patch.object(evidence, "verify", wraps=evidence.verify) as verify:
            item = self.lookup("note:summary", accept_summary=True)
            self.assertEqual(item["level"], "card")
            verify.assert_not_called()
            tiers = {"judgment": "judgment_source", "matter": "matter_record", "project": "project_record"}
            for source, tier in tiers.items():
                data = self.lookup("artifact:" + source)
                self.assertEqual(data, {"status": "found", "level": tier, "content": source + " original"})
            self.assertEqual(verify.call_count, 3)
            missing = self.lookup("not-present")
            self.assertEqual(missing["status"], "evidence_insufficient")
            self.assertEqual(verify.call_count, 3)
            limited = self.lookup("artifact:matter", lookup_budget=2)
            self.assertEqual(limited, {"status": "evidence_insufficient", "reason": "lookup_budget"})
            self.assertEqual(verify.call_count, 3)

    def test_episode_summary_requires_valid_registered_file_evidence(self):
        source = "artifact:matter"
        verified = self.lookup(source, accept_summary=True)
        self.assertEqual(verified["level"], "card")
        self.assertIn("小范围灰度决策", verified["content"])
        self.assertEqual(self.lookup(source, accept_summary=True, identities=()),
                         {"status": "evidence_insufficient", "reason": "unregistered_source"})
        (self.project / "matter.txt").write_text("changed", encoding="utf-8")
        self.assertEqual(self.lookup(source, accept_summary=True),
                         {"status": "evidence_insufficient", "reason": "file_stale"})
        (self.project / "matter.txt").unlink()
        self.assertEqual(self.lookup(source, accept_summary=True),
                         {"status": "evidence_insufficient", "reason": "file_missing"})

    def test_only_explicit_unlinked_notes_can_supply_summary_without_fingerprint(self):
        self.records.append(fact("untyped", "pending_items", "文字标记 [source_id:note:untyped]"))
        self.write_memory()
        self.assertEqual(self.lookup("note:untyped", accept_summary=True)["status"], "evidence_insufficient")
        self.assertEqual(self.lookup("note:summary", accept_summary=True)["level"], "card")
        self.case["episodes"][1]["summary"] += " [source_id:note:summary]"
        self.write_memory()
        self.assertEqual(self.lookup("note:summary", accept_summary=True)["status"], "evidence_insufficient")

    def test_change_requires_reevaluation_and_late_lookup_returns_no_content(self):
        path = self.project / "judgment.txt"
        path.write_text("changed and unverified", encoding="utf-8")
        result = self.recover()
        self.assertIn({"source_id": "artifact:judgment", "status": "stale"}, result["evidence_status"])
        self.assertTrue(next(row for row in result["judgments"] if row["id"] == "J-TIDE")["requires_recheck"])
        self.assertTrue(next(row for row in result["confirmed_decisions"] if row["id"] == "E-TIDE")["requires_recheck"])
        refused = self.lookup("artifact:judgment", accept_summary=True)
        self.assertEqual(refused, {"status": "evidence_insufficient", "reason": "file_stale"})

    def test_observation_reads_only_a_referenced_file(self):
        def observe(name):
            return recovery.observe(self.state, self.selection, "artifact:" + name, name + ".txt",
                                    project_root=self.project, byte_budget=4096, lookup_budget=3)

        with patch.object(evidence, "observe", wraps=evidence.observe) as callback:
            self.assertEqual(observe("project"), {"status": "unknown", "reason": "source_not_linked"})
            callback.assert_not_called()
            result = observe("matter")
            self.assertEqual(evidence.Identity.from_mapping(result).sha256, self.identities[1].sha256)
            self.assertEqual(result["relative_path"], "matter.txt")
            self.assertEqual(result["status"], "valid")
            self.assertNotIn(str(self.project), json.dumps(result))

    def test_cli_wire_format_and_exact_scope(self):
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/recovery_context.py"), "recover",
            "--memory-dir", str(self.memory), "--accept-saved", "--state-read", "--body-read",
            "--byte-budget", "265", "--lookup-budget", "1",
        ], input=json.dumps({"project": PROJECT, "as_of": FIXTURE["as_of"], "matters": []}).encode(),
           capture_output=True, check=True)
        self.assertLessEqual(len(result.stdout), 265)
        self.assertTrue(json.loads(result.stdout)["truncated"])
        self.assertEqual(json.loads(result.stdout)["unresolved_conflicts"], [])


class EvidenceIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.path = self.project / "config.json"
        self.path.write_bytes(b"original")
        self.identity = evidence.observe(self.project, "artifact:config", self.path.name)

    def test_valid_stale_missing_and_unreadable(self):
        self.assertEqual(evidence.verify(self.project, self.identity), ("valid", b"original"))
        self.path.write_bytes(b"modified")
        self.assertEqual(evidence.verify(self.project, self.identity), ("stale", None))
        self.path.unlink()
        self.assertEqual(evidence.verify(self.project, self.identity), ("missing", None))
        with patch.object(evidence, "_read_project_file", side_effect=PermissionError):
            self.assertEqual(evidence.verify(self.project, self.identity), ("unknown", None))

    def test_nonfiles_oversize_out_of_scope_and_memory_directories_are_inaccessible(self):
        legal = self.identity.to_dict()
        for name in ("../private", "C:/private", "x/file:stream", "dir\\file", "a/../b", "COM1.txt"):
            with self.subTest(name=name), self.assertRaises(evidence.EvidenceError):
                evidence.Identity.from_mapping({**legal, "relative_path": name})
        self.assertEqual(evidence.verify(self.project, self.identity, excluded=self.project), ("unknown", None))
        self.path.write_bytes(b"x" * (evidence.FILE_LIMIT + 1))
        self.assertEqual(evidence.verify(self.project, self.identity), ("unknown", None))

    def test_symlink_or_windows_junction_outside_scope(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "config.json").write_bytes(b"original")
        link = self.project / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if sys.platform != "win32":
                self.skipTest("symlinks unavailable")
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
                                    capture_output=True)
            if result.returncode:
                self.skipTest("junctions unavailable")
        identity = evidence.Identity.from_mapping({**self.identity.to_dict(), "relative_path": "linked/config.json"})
        self.assertEqual(evidence.verify(self.project, identity), ("unknown", None))


if __name__ == "__main__":
    unittest.main()
