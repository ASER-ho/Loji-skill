"""Tests for read-only memory curation suggestions (L114-04).

The tool must classify duplicates without merging, keep protected records out
of merge suggestions, and never modify the authorized source files.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import judgment_ledger as jl  # noqa: E402
from scripts import memory_curation as curation  # noqa: E402
from scripts import memory_schema as schema  # noqa: E402
from scripts.memory_state import MemoryState, Host


def configured(folder, policy="read_only"):
    state = MemoryState(folder.resolve(), Host(True, True, True, True, True))
    state.configure(policy, user_confirmed=True)
    return state


def cli(folder):
    return ["--memory-dir", str(folder.resolve()), "--accept-saved", "--state-read", "--body-read"]


def judgment():
    return jl.Judgment(
        id="J-CUR",
        topic_key="curation.synthetic",
        topic="合成整理测试",
        stance="合成判断。",
        confidence="medium",
        basis=["直接证据：合成整理数据。"],
        user_position="unknown",
        would_change_if=["无。"],
        status="active",
        created_at="2039-12-01",
        updated_at="2039-12-01",
        supersedes=None,
    )


def ep(eid, *, relevance="dup", kind="important_joint_decision", date="2040-01-01",
       summary="同一条合成记录。", retention="project", state="active",
       expires_on=None, replaces=None, outcome=None):
    return {
        "id": eid, "date": date, "kind": kind, "summary": summary,
        "related_judgments": ["J-CUR"], "outcome": outcome, "relevance": relevance,
        "retention": retention, "state": state, "expires_on": expires_on,
        "replaces": replaces,
    }


def build(folder: Path):
    episodes = [
        ep("E-D1"), ep("E-D2"),
        ep("E-P1", retention="permanent"), ep("E-P2", retention="permanent"),
        ep("E-R1", relevance="reinforce", summary="合成补强 A。"),
        ep("E-R2", relevance="reinforce", summary="合成补强 B。"),
        ep("E-T1", relevance="series", date="2040-01-01", summary="合成系列 A。"),
        ep("E-T2", relevance="series", date="2040-02-01", summary="合成系列 B。"),
        ep("E-U1", relevance="conflict-cur", state="unresolved", summary="未决 A。"),
        ep("E-U2", relevance="conflict-cur", summary="未决 B。"),
        ep("E-X1", relevance="expired", date="2038-12-01", expires_on="2039-01-01",
           summary="过期记录。"),
        ep("E-F1", relevance="future", date="2041-01-01", summary="未来记录。"),
        ep("E-C1", relevance="correction", state="corrected", summary="旧纠正。"),
        ep("E-C2", relevance="correction", kind="correction_or_learning",
           date="2040-01-02", summary="新纠正。", replaces="E-C1"),
    ]
    template = (ROOT / "memory.template.md").read_text(encoding="utf-8")
    doc = schema.parse(template)
    doc.episodes[:] = episodes
    memory = folder / "memory.md"
    memory.write_text(doc.render_v2(), encoding="utf-8")
    ledger = folder / "JUDGMENTS.md"
    ledger.write_text(
        '---\nschema_version: 1\nskill_version: "1.1.3"\n---\n\n'
        + jl.render_judgment(judgment()) + "\n",
        encoding="utf-8",
    )
    return memory, ledger


class CurationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.memory, self.ledger = build(self.folder)
        with curation._load(configured(self.folder)) as doc:
            self.result = curation.analyze(doc, as_of="2040-03-01")

    def test_mode_is_suggestions_only(self) -> None:
        self.assertEqual(self.result["mode"], "suggestions_only")
        self.assertEqual(self.result["writes"], 0)

    def test_exact_duplicates_split_by_protection(self) -> None:
        groups = {tuple(g["ids"]): g for g in self.result["exact_duplicate_groups"]}
        self.assertEqual(groups[("E-D1", "E-D2")]["action"], "review_merge")
        self.assertFalse(groups[("E-D1", "E-D2")]["protected"])
        self.assertEqual(groups[("E-P1", "E-P2")]["action"], "review_only")
        self.assertTrue(groups[("E-P1", "E-P2")]["protected"])

    def test_reinforcement_and_series_are_distinguished(self) -> None:
        reinforcement = {g["ids"][0] for g in self.result["evidence_reinforcement_candidates"]}
        self.assertIn("E-R1", reinforcement)
        series = {g["relevance"] for g in self.result["different_time_series"]}
        self.assertIn("series", series)
        self.assertNotIn("reinforce", series)

    def test_conflict_is_never_a_merge_target(self) -> None:
        conflict = next(c for c in self.result["conflicts"] if c["relevance"] == "conflict-cur")
        self.assertEqual(conflict["action"], "do_not_merge")
        self.assertEqual(conflict["suppressed_active_ids"], ["E-U2"])
        for group in self.result["exact_duplicate_groups"]:
            self.assertNotIn("E-U1", group["ids"])

    def test_correction_chain_is_protected(self) -> None:
        protected_ids = {
            eid for g in self.result["exact_duplicate_groups"] if g["protected"]
            for eid in g["ids"]
        }
        self.assertNotIn("E-C1", protected_ids)

    def test_lifecycle_observations(self) -> None:
        self.assertEqual(self.result["lifecycle"]["expired_active"], ["E-X1"])
        self.assertEqual(self.result["lifecycle"]["future_active"], ["E-F1"])

    def test_no_summary_text_in_report(self) -> None:
        text = json.dumps(self.result, ensure_ascii=False)
        self.assertNotIn("同一条合成记录", text)
        self.assertNotIn("合成补强", text)


class CurationCliTests(unittest.TestCase):
    def test_cli_is_read_only_and_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            memory, ledger = build(folder)
            configured(folder)
            initial_names = {p.name for p in folder.iterdir()}
            before = (
                hashlib.sha256(memory.read_bytes()).hexdigest(),
                hashlib.sha256(ledger.read_bytes()).hexdigest(),
            )
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = curation.main(cli(folder) + ["--as-of", "2040-03-01"])
            self.assertEqual(code, 0, err.getvalue())
            data = json.loads(out.getvalue())
            self.assertEqual(data["writes"], 0)
            after = (
                hashlib.sha256(memory.read_bytes()).hexdigest(),
                hashlib.sha256(ledger.read_bytes()).hexdigest(),
            )
            self.assertEqual(before, after)
            self.assertEqual({p.name for p in folder.iterdir()}, initial_names)

    def test_off_is_denied_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            memory, ledger = build(folder)
            configured(folder, "off")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = curation.main(cli(folder))
            self.assertEqual(code, 1)
            self.assertIn("refused", err.getvalue())

    def test_schema_one_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            memory = folder / "memory.md"
            text = (ROOT / "memory.template.md").read_text(encoding="utf-8")
            text = text.replace("schema_version: 2", "schema_version: 1")
            memory.write_text(text, encoding="utf-8")
            configured(folder)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = curation.main(cli(folder))
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
