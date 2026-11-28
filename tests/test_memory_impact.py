"""Candidate S09/S10 coverage using generated local snapshots."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from l120_support import ROOT, RECORDS, fresh_memory, ledger_text
from scripts import memory_impact as impact, memory_io as io, memory_state as ms


class MemoryImpactTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        capabilities = ms.Host(accept_saved=True, state_read=True, state_write=True,
                               body_read=True, body_write=True)
        self.state = ms.MemoryState(self.folder, capabilities)
        self.state.configure("explicit", user_confirmed=True)

    def write_snapshots(self, episodes=(), records=RECORDS, archive=""):
        memory = fresh_memory(episodes).replace("## 归档\n", "## 归档\n" + archive + "\n")
        (self.folder / "memory.md").write_text(memory, encoding="utf-8")
        (self.folder / "JUDGMENTS.md").write_text(ledger_text(records), encoding="utf-8")

    def test_removed_episode_archive_and_individually_authorized_backup(self):
        marker = "SYNTH-FORGET-883"
        judgment = next(row for row in RECORDS if row["status"] == "active")
        episode = dict(id="E-SYNTH-FORGET", date="2040-01-01", kind="actual_outcome",
                       summary=marker, outcome=marker, related_judgments=[judgment["id"]],
                       relevance="test", retention="permanent", state="active", expires_on=None, replaces=None)
        self.write_snapshots([episode], archive=marker)
        removed = self.state.mutate("forget", {"id": episode["id"]}, user_requested=True)
        backup = Path(removed["backup"]).name
        self.state.configure("read_only", user_confirmed=True)
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        report = impact.audit(self.state, kind="episode", key=episode["id"], literal=marker, purpose="residue",
                              approved_backups=[backup], backup_indices=[1])
        carriers = {row["carrier"]: row for row in report["carriers"]}
        self.assertEqual(report["current_target"], "absent_in_checked_carriers")
        self.assertEqual(carriers["archive"]["hits"][0]["relation"], "possible")
        self.assertTrue(any(hit["basis"] == "target_present" for hit in carriers["backup"]["hits"]))
        self.assertEqual(report["unlisted_backups"], "unscanned")
        self.assertNotIn(str(self.folder), json.dumps(report))
        self.assertNotIn(marker, json.dumps(report))
        self.assertNotIn(backup, json.dumps(report))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})

    def test_impact_preserves_other_edges_and_unknown_carriers(self):
        records = [dict(row) for row in RECORDS]
        records[0]["basis"] = ["直接证据：[source_id:artifact:one]", "独立合成证据：[source_id:artifact:two]"]
        self.write_snapshots(records=records)
        backup = "memory.md.bak.20400101T010203Z-17-deadbeef"
        result = impact.audit(self.state, kind="source", key="artifact:one", purpose="impact",
                              approved_backups=[backup], backup_indices=[1])
        carriers = {row["carrier"]: row for row in result["carriers"]}
        evidence = carriers["judgment"]["hits"][0]
        self.assertEqual((evidence["edge"], evidence["other_basis"]), (1, [2]))
        self.assertEqual(carriers["calibration"]["reason"], "no_lineage_metadata")
        self.assertEqual(carriers["backup"]["state"], "unavailable")
        limited = impact.audit(self.state, kind="source", key="artifact:one", purpose="impact", lookup_budget=1)
        self.assertEqual(limited["carriers"][3]["state"], "unscanned")

    def test_unapproved_paths_and_off_never_open_bodies(self):
        with patch.object(io, "read", side_effect=AssertionError("unexpected content read")):
            with self.assertRaisesRegex(ValueError, "invalid approved backup basename"):
                impact.audit(self.state, kind="episode", key="E-TEST", purpose="impact",
                             approved_backups=["../memory.md.bak.20400101T010203Z-17-deadbeef"], backup_indices=[1])
        self.state.configure("off", user_confirmed=True)
        with patch.object(io, "read", side_effect=AssertionError("read before authorization")):
            report = impact.audit(self.state, kind="episode", key="E-TEST", purpose="residue")
        self.assertTrue(all(row["state"] == "unavailable" for row in report["carriers"]))

    def test_cli_snapshot_stability_and_output_budget(self):
        self.write_snapshots()
        request = json.dumps({"kind": "episode", "key": "E-TEST", "purpose": "residue"})
        command = [sys.executable, "-B", str(ROOT / "scripts/memory_impact.py"),
                   "--memory-dir", str(self.folder), "--accept-saved", "--state-read", "--body-read",
                   "--byte-budget", str(impact.MIN_REPORT_BYTES)]
        run = subprocess.run(command, input=request.encode("utf-8"), capture_output=True, check=True)
        self.assertLessEqual(len(run.stdout), impact.MIN_REPORT_BYTES)
        self.assertTrue(json.loads(run.stdout)["truncated"])
        with patch.object(impact, "_unchanged", return_value=False):
            result = impact.audit(self.state, kind="judgment", key=RECORDS[0]["id"], purpose="impact")
        self.assertEqual(result["current_target"], "unknown")
        self.assertEqual(result["carriers"][3]["reason"], "snapshot_changed")
