"""Deterministic checks for the behavior-eval harness.

These tests never call a model and never read real memory. They prove fixture
structure, the synthetic retrieval contract, and that scoring refuses tampered
samples, unsupported verdicts and zero-tolerance failures.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import eval_harness as harness  # noqa: E402


class FixtureTests(unittest.TestCase):
    def test_repository_fixtures_are_valid(self) -> None:
        self.assertEqual(harness.check_fixtures(ROOT), [])

    def test_persona_categories_cover_required_matrix(self) -> None:
        data = json.loads(
            (ROOT / "research/evals/fidelity-scenarios.json").read_text(encoding="utf-8")
        )
        categories = {case["category"] for case in data["cases"]}
        for required in data["gates"]["required_categories"]:
            self.assertIn(required, categories)
        self.assertGreaterEqual(len(data["cases"]), 8)

    def test_evidence_cases_cover_partial_invalidation(self) -> None:
        data = json.loads(
            (ROOT / "research/evals/judgment-evidence.json").read_text(encoding="utf-8")
        )
        categories = {case["category"] for case in data["cases"]}
        self.assertIn("partial_invalidation", categories)
        case = next(c for c in data["cases"] if c["category"] == "partial_invalidation")
        text = " ".join(case["expected"])
        self.assertIn("剩余", text)
        self.assertNotIn("整个判断作废", " ".join(case["expected"]))

    def test_missing_fixture_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            errors = harness.check_fixtures(Path(tmp))
            self.assertTrue(errors)


class RetrievalTests(unittest.TestCase):
    def test_all_synthetic_cases_pass_without_irrelevant_results(self) -> None:
        result = harness.run_retrieval(ROOT)
        self.assertEqual(result["metrics"]["cases"], 12)
        self.assertEqual(result["metrics"]["cases_passed"], 12)
        self.assertEqual(result["metrics"]["recall"], 1.0)
        self.assertEqual(result["metrics"]["irrelevant_returned"], 0)
        self.assertEqual(result["metrics"]["forbidden_returned"], 0)
        for case in result["cases"]:
            self.assertEqual(case["verdict"], "pass", case)

    def test_limitation_case_does_not_claim_global_absence(self) -> None:
        result = harness.run_retrieval(ROOT)
        case = next(item for item in result["cases"] if item["case_id"] == "R11")
        self.assertTrue(case["limitation"])
        self.assertEqual(case["unresolved"], [])

    def test_expired_and_historical_records_never_resurface(self) -> None:
        result = harness.run_retrieval(ROOT)
        returned = {eid for case in result["cases"] for eid in case["returned"]}
        for forbidden in ("E-04", "E-05", "E-08", "E-10", "E-12", "E-13"):
            self.assertNotIn(forbidden, returned)

    def test_candidate_views_are_measured_but_not_adopted(self) -> None:
        result = harness.run_retrieval(ROOT)
        comparison = result["candidate_comparison"]
        self.assertTrue(comparison["baseline_exact_filter"]["adopted"])
        self.assertFalse(comparison["ordering_by_recency"]["adopted"])
        self.assertTrue(comparison["ordering_by_recency"]["same_episode_set"])
        self.assertFalse(comparison["compact_projection"]["adopted"])
        self.assertGreater(comparison["compact_projection"]["cases_expecting_judgment_evidence"], 0)
        self.assertIn(
            "judgment_evidence.basis", comparison["compact_projection"]["dropped_fields"]
        )


class ScoringTests(unittest.TestCase):
    def _plan(self, folder: Path) -> tuple[Path, dict]:
        paths = harness.write_plan(ROOT, folder / "plan")
        plan_path = next(p for p in paths if p.name.startswith("fidelity"))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        return plan_path, plan

    def test_plan_is_blank_and_score_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            plan_path, plan = self._plan(folder)
            self.assertTrue(plan["cases"])
            self.assertTrue(all(c["actual_answer"] == "" for c in plan["cases"]))
            for case in plan["cases"]:
                case["actual_answer"] = "synthetic answer"
                case["semantic_verdict"] = "pass"
                case["score"] = 2
            results = folder / "results.json"
            results.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            summary = harness.score(results, ROOT)
            self.assertEqual(summary["result"], "PASS", summary)
            self.assertEqual(summary["score"], 28)

    def test_score_verdict_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _, plan = self._plan(folder)
            for case in plan["cases"]:
                case["actual_answer"] = "synthetic answer"
                case["semantic_verdict"] = "pass"
                case["score"] = 0
            results = folder / "results.json"
            results.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            summary = harness.score(results, ROOT)
            self.assertEqual(summary["result"], "FAIL")
            self.assertTrue(any("disagrees" in item for item in summary["errors"]))

    def test_independent_failure_cannot_be_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _, plan = self._plan(folder)
            for case in plan["cases"]:
                case["actual_answer"] = "synthetic answer"
                case["semantic_verdict"] = "pass"
                case["score"] = 2
            plan["cases"][0]["semantic_verdict"] = "fail"
            plan["cases"][0]["score"] = 0
            plan["cases"][0]["independent_failures"] = ["authorization_violation"]
            results = folder / "results.json"
            results.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            summary = harness.score(results, ROOT)
            self.assertEqual(summary["result"], "FAIL")
            self.assertIn("authorization_violation", summary["independent_failures"])

    def test_changed_expectation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _, plan = self._plan(folder)
            for case in plan["cases"]:
                case["actual_answer"] = "synthetic answer"
                case["semantic_verdict"] = "pass"
                case["score"] = 2
            plan["cases"][0]["expected"] = ["tampered"]
            results = folder / "results.json"
            results.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            summary = harness.score(results, ROOT)
            self.assertEqual(summary["result"], "FAIL")
            self.assertTrue(any("expectation changed" in item for item in summary["errors"]))

    def test_changed_fixture_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _, plan = self._plan(folder)
            plan["fixture_sha256"] = "0" * 64
            results = folder / "results.json"
            results.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(harness.HarnessError):
                harness.score(results, ROOT)


if __name__ == "__main__":
    unittest.main()
