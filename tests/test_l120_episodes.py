"""L120-02/04: reference, authorization, lifecycle, and fresh process cases."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from l120_support import AS_OF, GROUPS, RECORDS, ROOT, episode, fresh_memory, ledger_text, production_state
from scripts import episodic_memory as em, judgment_ledger as jl, memory_io as io, memory_schema as schema

AUTH = dict(policy="explicit", consent="granted")
INTEGRITY = {c["id"]: c["input"] for c in GROUPS["episode_integrity"]}
BASE = INTEGRITY["E01"]["episodes"][0]


class StateCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.memory = self.root / "memory.md"
        self.ledger = self.root / "JUDGMENTS.md"
        self.write_state()
        self.ledger.write_bytes(ledger_text(RECORDS).encode())

    def write_state(self, episodes=(), calibration=None):
        self.memory.write_bytes(fresh_memory(episodes, calibration).encode())

    def read_state(self):
        return schema.parse(self.memory.read_bytes().decode())

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}

    def change(self, action, data, **overrides):
        return em.mutate(self.memory, self.ledger, action, data, **{
            **AUTH, "user_requested": True, "eligible_and_private": True, **overrides,
        })

    def add(self, record=None, **overrides):
        record = episode(BASE if record is None else record)
        del record["state"]
        return self.change("add", record, **overrides)

    def context(self, **kwargs):
        return em.context(self.memory, self.ledger, as_of=AS_OF, **{**AUTH, **kwargs})

    def rejected(self, callback, error):
        before = self.snapshot()
        with self.assertRaises(error):
            callback()
        self.assertEqual(self.snapshot(), before)


class IntegrityCases(StateCase):
    def test_E01(self):
        ledger_before = self.ledger.read_bytes()
        result = self.add()
        ctx = self.context()
        self.assertEqual(ctx["episodes"][0]["id"], result["id"])
        self.assertEqual(ctx["episodes"][0]["related_judgments"], ["J-SYN-002"])
        self.assertEqual(self.ledger.read_bytes(), ledger_before)
        self.assertEqual(schema.parse(Path(result["backup"]).read_bytes().decode()).episodes, [])
        doc, _ = jl.load_ledger(self.ledger, **AUTH)
        self.assertEqual((doc.schema_version, doc.skill_version), (1, "1.1.0"))

    def test_E02(self):
        case = INTEGRITY["E02"]
        for key in case["variants"]["remove_each"]:
            record = episode(case["base"])
            record.pop(key)
            self.rejected(lambda: schema.validate_episodes([record]), schema.FormatError)
        for key, value in case["variants"]["invalid_examples"].items():
            self.rejected(lambda: self.add(dict(case["base"], **{key: value})), schema.FormatError)

    def test_E03(self):
        self.rejected(lambda: self.add(INTEGRITY["E03"]["episodes"][0]), schema.FormatError)

    def test_E04(self):
        self.add(INTEGRITY["E04"]["episodes"][0])
        self.assertEqual(self.read_state().episodes[0]["related_judgments"], ["J-SYN-001"])
        self.assertEqual(self.context()["episodes"], [])
        self.assertEqual(self.context()["judgment_evidence"], {})

    def test_E05(self):
        before = self.ledger.read_bytes()
        for record in INTEGRITY["E05"]["episodes"]:
            self.add(record)
        ctx = self.context()
        self.assertEqual(len(ctx["episodes"]), 2)
        self.assertEqual(list(ctx["judgment_evidence"]), ["J-SYN-002"])
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_E06(self):
        records = [episode(dict(BASE, id=f"E-SYN-{i:03}")) for i in range(49)]
        self.write_state(records)
        self.add(dict(BASE, id="E-SYN-NEW"))
        self.assertEqual(len(self.read_state().episodes), 50)
        self.rejected(lambda: self.add(dict(BASE, id="E-SYN-OVER")), schema.FormatError)
        self.write_state(records[:2])
        self.rejected(lambda: self.add(dict(BASE, id="E-SYN-001")), schema.FormatError)

    def test_E07(self):
        for state in ("archived", "corrected", "deprecated"):
            self.write_state([episode(BASE, state=state)])
            self.assertEqual(self.context()["episodes"], [])
            self.rejected(lambda: self.change("transition", {"id": BASE["id"], "state": "active"}),
                          schema.FormatError)
        self.write_state([episode(BASE)])
        self.change("forget", {"id": BASE["id"]})
        self.assertNotIn(BASE["id"].encode(), self.memory.read_bytes())
        self.assertEqual(self.context()["episodes"], [])

    def test_E08(self):
        sensitive = dict(BASE, summary=INTEGRITY["E08"]["sensitive_payload"])
        for options in (
            dict(user_requested=False), dict(policy="read_only"), dict(policy="off"),
            dict(eligible_and_private=False), dict(consent="pending"), dict(consent="denied"),
        ):
            with self.subTest(options=options), patch.object(io, "read") as read:
                self.rejected(lambda: self.add(sensitive, **options), PermissionError)
                read.assert_not_called()

    def test_E09(self):
        variants = {
            "JV-DUPLICATE": [*RECORDS, RECORDS[1]],
            "JV-DANGLING": [RECORDS[0], dict(RECORDS[1], supersedes="J-SYN-MISSING")],
            "JV-CYCLE": [dict(RECORDS[0], supersedes=RECORDS[1]["id"]), RECORDS[1]],
            "JV-TWO-HEADS": [RECORDS[0], dict(RECORDS[1], supersedes=None)],
        }
        for variant in INTEGRITY["E09"]["variant_ids"]:
            with self.subTest(variant=variant):
                self.ledger.write_bytes(ledger_text(variants[variant]).encode())
                self.rejected(self.add, jl.JudgmentValidationError)

    def test_E10(self):
        self.write_state([episode(BASE)])
        with patch.object(jl, "load_ledger", side_effect=jl.JudgmentAccessError("unverifiable")), \
             patch.object(io, "atomic_write") as write:
            self.rejected(self.context, jl.JudgmentAccessError)
            self.rejected(lambda: self.add(dict(BASE, id="E-SYN-NEW")), jl.JudgmentAccessError)
            write.assert_not_called()

    def test_E11(self):
        self.add()
        self.change("transition", {"id": BASE["id"], "state": "archived"})
        row = self.read_state().episodes[0]
        self.assertEqual((row["state"], row["summary"]), ("archived", BASE["summary"]))
        self.assertEqual(self.context()["episodes"], [])

    def test_E12(self):
        self.add(INTEGRITY["E12"]["episodes"][0])
        self.assertIsNone(self.context()["episodes"][0]["outcome"])

    def test_correction_preserves_history_in_same_transaction(self):
        self.add()
        row = episode(dict(BASE, id="E-CORRECTED", summary="虚构更正"), kind="correction_or_learning")
        del row["state"]
        self.change("add", dict(row, replaces=BASE["id"]))
        self.assertEqual([r["state"] for r in self.read_state().episodes], ["corrected", "active"])
        self.assertEqual(self.read_state().episodes[0]["summary"], BASE["summary"])
        self.assertEqual(self.read_state().episodes[1]["replaces"], BASE["id"])
        self.assertEqual([r["id"] for r in self.context()["episodes"]], ["E-CORRECTED"])

    def test_session_authority_before_opening_any_files(self):
        self.add(policy="auto", user_requested=False)
        self.assertTrue(self.context(policy="read_only")["episodes"])
        for mode in ("off", "unset"):
            with patch.object(io, "read") as read:
                self.rejected(lambda: self.context(policy=mode), PermissionError)
                read.assert_not_called()

    def test_generated_id_survives_fresh_read(self):
        row = episode(BASE)
        for field in ("id", "state"):
            del row[field]
        result = self.change("add", row)
        self.assertRegex(result["id"], r"^E-[0-9a-f]{32}$")
        self.assertEqual(self.context()["episodes"][0]["id"], result["id"])


class ContinuityCases(StateCase):
    def test_fresh_processes_D01_to_D08(self):
        expected = {
            "D01": ["E-SYN-201"], "D02": ["E-SYN-202", "E-SYN-203"],
            "D03": [], "D04": [], "D05": ["E-SYN-206"], "D06": ["E-SYN-208"],
            "D07": [], "D08": [],
        }
        self.assertEqual(sum(c["input"]["contains_stale_or_contradictory_episode"]
                             for c in GROUPS["continuity"]), 4)
        for case in GROUPS["continuity"]:
            cid = case["id"]
            with self.subTest(case=cid):
                state = case["input"]["session_b"]
                mem, ledger = production_state(state)
                self.memory.write_bytes(mem.encode())
                self.ledger.write_bytes(ledger.encode())
                before = self.snapshot()
                result = subprocess.run([
                    sys.executable, "-B", str(ROOT / "scripts/episodic_memory.py"), "context",
                    "--memory", str(self.memory), "--ledger", str(self.ledger),
                    "--policy", "read_only", "--consent", "granted", "--as-of", AS_OF,
                ], capture_output=True, check=True)
                packet = json.loads(result.stdout)
                self.assertEqual([ep["id"] for ep in packet["episodes"]], expected[cid])
                self.assertEqual(self.snapshot(), before)
                if cid == "D01":
                    self.assertIn("双层完整", packet["judgment_evidence"]["J-SYN-002"]["basis"][0])
                elif cid == "D02":
                    self.assertEqual(list(packet["judgment_evidence"]), ["J-SYN-002"])
                    self.assertIsNone(packet["episodes"][1]["outcome"])
                elif cid == "D05":
                    self.assertIn("SYN-21", str(packet))
                    self.assertNotIn("SYN-12", str(packet))
                elif cid == "D06":
                    self.assertNotIn("J-SYN-001", str(packet))
                elif cid == "D08":
                    self.assertEqual(packet["unresolved"], ["虚构纸舟实验"])
                    self.assertFalse(packet["judgment_evidence"])
