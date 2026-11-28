import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import eval_harness, eval_utility


class UtilityEvaluationTests(unittest.TestCase):
    def test_plan_projects_only_inputs_and_keeps_all_repeats(self):
        data = {"U08/4": {"id": "U08/4", "input": ["固定任务"],
                          "expected": ["仅评分端可见"], "atoms": ["R4"], "checkpoint": 4}}
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            with patch.object(eval_utility, "frozen_cases", return_value=(data, {"seconds": 240})):
                eval_utility.write_plan(Path("synthetic"), out)
            model = json.loads((out / "utility-model-input.json").read_text(encoding="utf-8"))
            self.assertEqual(model, [{"case_id": "U08/4", "input": ["固定任务"]}])
            schedule = json.loads((out / "utility-schedule.json").read_text(encoding="utf-8"))
            self.assertEqual("".join(row["arm"] for row in schedule["runs"]), "ABCBCACAB")

    def test_cannot_score_self_report_without_native_evidence(self):
        case = {"id": "U02", "input": ["固定任务"], "expected": ["完整约束"], "forbidden": [],
                "atoms": ["预研"]}
        item = {**case, "case_id": case["id"], "semantic_verdict": "pass", "score": 2,
                "semantic_reason": "模型自述完成", "independent_failures": [], "actual_answer": "预研"}
        with self.assertRaisesRegex(eval_harness.HarnessError, "objective execution evidence"):
            eval_utility._record(case, item, Path("test.json"), {"seconds": 240})

    def test_not_run_is_visible_without_any_made_up_evidence(self):
        case = {"id": "U06", "input": ["固定任务"], "expected": ["当前状态"], "forbidden": []}
        item = {**case, "case_id": case["id"], "semantic_verdict": "unscored",
                "semantic_reason": "宿主阻断"}
        result = eval_utility._record(case, item, Path("test.json"), {"seconds": 240})
        self.assertEqual(result, {"status": "NOT_RUN", "reason": "宿主阻断"})
