"""Independent counterexamples for L114-FINAL-GATE-01, synthetic data only."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from scripts import memory_curation as c, memory_state as ms, memory_io, memory_schema as schema
from scripts import eval_harness as h, judgment_ledger as jl
from test_memory_curation import build, configured
from test_judgment_evidence import record
import test_eval_harness as eval_tests


class GuardedCurationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.memory, self.ledger = build(self.folder)
        self.state = configured(self.folder)

    def denied(self, state):
        with patch.object(memory_io, "read", side_effect=AssertionError("body opened")) as read:
            with self.assertRaises(ms.AccessError):
                c.suggest(state)
        read.assert_not_called()

    def test_off_unknown_invalid_and_unconfirmed_never_open_bodies(self):
        for payload in (None, b"broken", b'{"memory_policy":"auto","confirmed":false}',
                        b'{"memory_policy":"off","confirmed":true}'):
            with self.subTest(payload=payload):
                if payload is None:
                    self.state.path.unlink(missing_ok=True)
                else:
                    self.state.path.write_bytes(payload)
                self.denied(self.state)

    def test_host_prohibition_or_unaccepted_state_never_opens_bodies(self):
        for host in (replace(self.state.host, body_read=False),
                     replace(self.state.host, accept_saved=False),
                     replace(self.state.host, state_read=False),
                     replace(self.state.host, host_policy="off", host_consent="granted")):
            with self.subTest(host=host):
                self.denied(ms.MemoryState(self.folder, host))

    def test_read_only_actual_reads_but_never_writes_bodies(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        with patch.object(memory_io, "read", wraps=memory_io.read) as read, \
             patch.object(memory_io, "atomic_write", side_effect=AssertionError("body write")):
            result = c.suggest(self.state, as_of="2040-03-01")
        self.assertEqual({Path(call.args[0]).name for call in read.call_args_list}, {"memory.md", "JUDGMENTS.md"})
        self.assertEqual(result["writes"], 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir() if p.is_file()})

    def test_transaction_covers_analysis_and_drops_newly_revoked_access(self):
        original = c.analyze
        def analyze(doc, **options):
            competing = ms.MemoryState(self.folder, self.state.host, timeout=0.02)
            with self.assertRaises(memory_io.MemoryLockTimeoutError):
                competing.configure("off", user_confirmed=True)
            return original(doc, **options)
        with patch.object(c, "analyze", side_effect=analyze):
            c.suggest(self.state)
        self.state.configure("off", user_confirmed=True)
        self.denied(self.state)

    def test_no_raw_policy_or_arbitrary_body_path_entry(self):
        with self.assertRaises(TypeError):
            c._load(self.memory, self.ledger, "read_only", "granted")

    def doc(self):
        with c._load(self.state) as doc:
            return doc

    def test_unresolved_matter_protects_its_active_duplicates(self):
        doc = self.doc()
        duplicates = [ep for ep in doc.episodes if ep["id"] in ("E-D1", "E-D2")]
        for ep in duplicates:
            ep["relevance"] = "conflict-cur"
        result = c.analyze(doc, as_of="2040-03-01")
        group = next(g for g in result["exact_duplicate_groups"] if g["ids"] == ["E-D1", "E-D2"])
        self.assertEqual((group["action"], group["proposed_keep"]), ("review_only", None))

    def test_distinct_judgment_references_are_not_exact_duplicates(self):
        doc = self.doc()
        next(ep for ep in doc.episodes if ep["id"] == "E-D2")["related_judgments"] = ["J-DIFFERENT"]
        self.assertFalse(any(g["ids"] == ["E-D1", "E-D2"] for g in c.analyze(doc)["exact_duplicate_groups"]))

    def test_opaque_user_protection_disables_merge_proposals_conservatively(self):
        doc = self.doc()
        doc = schema.parse(doc.text.replace("## 用户明确要求记住", "## 用户明确要求记住\n请保留这些实验的所有区别。", 1))
        result = c.analyze(doc, as_of="2040-03-01")
        self.assertTrue(result["legacy_protection_uncertain"])
        self.assertTrue(all(g["action"] != "review_merge" and g["proposed_keep"] is None for g in result["exact_duplicate_groups"]))

    def test_unknown_judgment_reference_is_rejected(self):
        doc = self.doc()
        doc.episodes[0]["related_judgments"] = ["J-MISSING"]
        self.memory.write_text(doc.render_v2(), encoding="utf-8")
        with self.assertRaises(schema.FormatError):
            c.suggest(self.state)


class LegacyEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "JUDGMENTS.md"

    def write(self, basis):
        self.path.write_text('---\nschema_version: 1\nskill_version: "1.1.3"\n---\n\n' +
            jl.render_judgment(record(basis=basis)) + "\n", encoding="utf-8")

    def test_old_free_text_including_bare_tier_labels_remains_readable(self):
        for basis in (["旧自由文本"], ["直接证据："], ["可核查产物:"], ["未验证印象：   "]):
            with self.subTest(basis=basis):
                self.write(basis)
                before = self.path.read_bytes()
                doc, _ = jl.load_ledger(self.path, policy="read_only", consent="granted")
                self.assertEqual(list(doc.judgments[0].basis), basis)
                self.assertEqual(self.path.read_bytes(), before)

    def test_new_empty_tier_is_rejected_without_rewriting_legacy_basis(self):
        self.write(["直接证据："])
        before = self.path.read_bytes()
        with self.assertRaises(jl.JudgmentValidationError):
            jl.append_judgment(self.path, record(id="J-NEW", topic_key="new", basis=["来源观点："]),
                               policy="auto", consent="granted")
        self.assertEqual(self.path.read_bytes(), before)

    def test_revision_preserves_old_basis_confidence_and_links(self):
        self.write(["直接证据："])
        jl.revise_judgment(self.path, "J-EVID-001", record(id="J-NEW", basis=["可核查产物：合成新产物"],
            updated_at="2040-01-02"), policy="auto", consent="granted")
        doc, _ = jl.load_ledger(self.path, policy="read_only", consent="granted")
        old, new = doc.judgments
        self.assertEqual((list(old.basis), old.confidence, old.status), (["直接证据："], "medium", "superseded"))
        self.assertEqual(new.supersedes, old.id)

    def test_product_version_is_independent_of_the_migration_test_constant(self):
        self.assertEqual(schema.SKILL_VERSION, "1.1.5")
        self.assertIn('version: "1.1.5"', (ROOT / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn('skill_version: "1.1.5"', (ROOT / "memory.template.md").read_text(encoding="utf-8"))


class ScorerCounterexamples(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        _, self.plan = eval_tests.ScoringTests()._plan(self.folder)
        for case in self.plan["cases"]:
            case.update(actual_answer="\n\n".join(["synthetic answer"] * len(case["input"])), semantic_verdict="pass", score=2)
        self.results = self.folder / "results.json"

    def score(self):
        self.results.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
        return h.score(self.results, ROOT)

    def test_unexecuted_self_report_is_not_a_pass(self):
        self.plan["run"] = {}
        for case in self.plan["cases"]:
            case["deterministic_evidence"] = []
        self.assertEqual(self.score()["result"], "FAIL")

    def test_unknown_case_cannot_be_silently_ignored(self):
        extra = copy.deepcopy(self.plan["cases"][0]);extra["case_id"] = "NOT-A-CASE"
        self.plan["cases"].append(extra)
        self.assertEqual(self.score()["result"], "FAIL")

    def test_missing_case_and_unscored_case_cannot_pass(self):
        missing = self.plan["cases"].pop()
        self.assertEqual(self.score()["result"], "FAIL")
        self.plan["cases"].append(missing)
        missing.update(semantic_verdict="unscored", score=None)
        self.assertEqual(self.score()["result"], "FAIL")

    def test_duplicate_case_or_json_field_is_rejected(self):
        self.plan["cases"].append(self.plan["cases"][0])
        with self.assertRaises(h.HarnessError): self.score()
        self.results.write_text('{"cases":[],"cases":[]}', encoding="utf-8")
        with self.assertRaises(ValueError): h.score(self.results, ROOT)

    def test_changed_inputs_and_invalid_failure_types_cannot_pass(self):
        self.plan["cases"][0]["input"] = ["different"]
        self.assertEqual(self.score()["result"], "FAIL")
        self.plan["cases"][0]["input"] = json.loads((ROOT / "research/evals/fidelity-scenarios.json").read_text(encoding="utf-8"))["cases"][0]["input"]
        self.plan["cases"][0]["independent_failures"] = "authorization_violation"
        self.assertEqual(self.score()["result"], "FAIL")

    def test_major_factual_error_cannot_be_averaged_away(self):
        self.plan["cases"][1]["independent_failures"] = ["major_factual_error"]
        self.assertEqual(self.score()["result"], "FAIL")

    def test_missing_or_outside_evidence_is_rejected(self):
        proof = self.plan["cases"][0]["deterministic_evidence"][0]
        for ref in ("missing.json", "../outside.json"):
            proof["ref"] = ref
            self.assertEqual(self.score()["result"], "FAIL")

    def artifact(self, case):
        return self.folder / case["deterministic_evidence"][0]["ref"]

    def test_failed_native_turn_cannot_pass(self):
        path = self.folder / "artifacts/F01/native-0.jsonl"
        path.write_text(path.read_text().replace('"completed"', '"failed"'), encoding="utf-8")
        self.assertEqual(self.score()["result"], "FAIL")

    def test_rewritten_answer_and_false_body_claims_cannot_pass(self):
        self.plan["cases"][0]["actual_answer"] = "I rewrote the original"
        self.assertEqual(self.score()["result"], "FAIL")

    def test_authorization_case_needs_real_snapshots_and_zero_access(self):
        case = next(c for c in self.plan["cases"] if c["case_id"] == "F14")
        path = self.artifact(case);data = json.loads(path.read_text());data["before"] = {}
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.score()["result"], "FAIL")

    def test_fixture_cli_parameter_must_match_results(self):
        self.score()
        with self.assertRaises(h.HarnessError):
            h.score(self.results, ROOT, fixture_name="judgment-evidence")


if __name__ == "__main__":
    unittest.main()
