"""L115 utility planning and comparison using the native behavior protocol.

The evaluator runs outside the model's workspace. Frozen scoring fixtures remain
external to the installed Skill. A run record is never an input to the model.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

if __package__:
    from . import eval_harness as harness
else:
    import eval_harness as harness

BASELINE = "0a60f24dc477a1ba5b636f5cdde53e0461596ffb"
FIXTURE_DIGESTS = {
    "behavior.json": "772a4d4f09315a11d946ab358b42ea538c62e3b806b4b0254d973c64c112db1b",
    "history.json": "482a1327442eeef26d8306a141f4f37be4d87d87684be82daf81a96bd97d27ee",
}
ROTATIONS = ("ABC", "BCA", "CAB")
MEASURES = ("evidence_accuracy", "constraint_preservation", "memory_interference",
            "residual_tool_exposure", "residual_answer_exposure")
COST = ("input_tokens", "output_tokens", "cached_tokens", "retrievals", "model_calls", "seconds", "charge")


def frozen_cases(folder: Path):
    for file, digest in FIXTURE_DIGESTS.items():
        if harness._sha256(folder / file) != digest:
            raise harness.HarnessError(f"frozen fixture changed: {file}")
    data = harness._load(folder / "behavior.json")
    cases = {}
    for case in data["cases"]:
        checkpoints = data["longitudinal"]["checkpoints"] if case["id"] == "U08" else [None]
        for point in checkpoints:
            case_id = case["id"] if point is None else f"{case['id']}/{point}"
            atoms = [value.replace("{n}", str(point)) for value in case["atoms"]]
            cases[case_id] = {**case, "id": case_id, "atoms": atoms, "checkpoint": point}
    return cases, data["budget"]


def _write(path, data):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_plan(folder, out):
    cases, budget = frozen_cases(folder)
    out.mkdir(parents=True, exist_ok=True)
    names = ["utility-model-input.json", "utility-scorer-plan.json", "utility-schedule.json"]
    if any((out / name).exists() for name in names):
        raise harness.HarnessError("use a new plan directory to preserve frozen files")
    _write(out / names[0], [{"case_id": key, "input": case["input"]} for key, case in cases.items()])
    _write(out / names[1], {"protocol_version": harness.PROTOCOL_VERSION,
                           "fixture_sha256": FIXTURE_DIGESTS, "cases": cases})
    schedule = [
        {"case_id": key, "repeat": number, "arm": arm}
        for number, rotation in enumerate(ROTATIONS, 1)
        for key in cases for arm in rotation
    ]
    _write(out / names[2], {"protocol_version": harness.PROTOCOL_VERSION, "budget": budget,
                           "baseline": BASELINE, "runs": schedule})


def _ratio(value, label):
    if (
        not isinstance(value, list) or len(value) != 2
        or any(type(count) is not int for count in value)
        or not 0 <= value[0] <= value[1]
    ):
        raise harness.HarnessError(f"{label} requires checked numerator and denominator")
    return value


def _matching_native_context(result_file, item, case, budget):
    """Bind the reply and retrieval evidence to native events, using the common gate."""
    folder = result_file.resolve().parent
    executions = harness._execution_evidence(item, case, folder)
    native_tools = [tool for execution in executions for tool in execution["native_tools"]]
    if len(native_tools) > budget["tool_calls"]:
        raise harness.HarnessError("tool call budget exceeded")
    retrieved = "\n".join(
        tool.get("aggregatedOutput") or tool.get("aggregated_output") or ""
        for tool in native_tools
        if tool.get("type") == "commandExecution"
        and tool.get("status") == "completed"
        and tool.get("exitCode", tool.get("exit_code")) == 0
    )
    return native_tools, retrieved


def _record(case, item, result_file, budget):
    if item["input"] != case["input"] or item["expected"] != case["expected"] or item["forbidden"] != case["forbidden"]:
        raise harness.HarnessError("input or scoring rule differs from frozen fixture")
    verdict = item["semantic_verdict"]
    if verdict == "unscored":
        return {"status": "NOT_RUN", "reason": item["semantic_reason"]}
    if verdict not in {"pass", "partial", "fail"} or item["score"] != harness.VERDICT_SCORES[verdict]:
        raise harness.HarnessError("invalid semantic verdict or score")
    reason = item["semantic_reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise harness.HarnessError("a blind semantic reason is required")
    codes = item["independent_failures"]
    if not isinstance(codes, list) or any(code not in harness.INDEPENDENT_FAILURES for code in codes):
        raise harness.HarnessError("invalid independent failure")
    tools, retrieved = _matching_native_context(result_file, item, case, budget)
    metrics = {name: _ratio(item["observations"][name], name) for name in MEASURES}
    cost = item["cost"]
    if set(cost) != set(COST) or any(
        val is not None and (type(val) not in (int, float) or not math.isfinite(val) or val < 0)
        for val in cost.values()
    ):
        raise harness.HarnessError("invalid cost counters")
    if cost["seconds"] is None or cost["seconds"] > budget["seconds"]:
        raise harness.HarnessError("missing or exceeded elapsed time budget")
    answer = item["actual_answer"]
    atoms = case["atoms"]
    visible = set(atoms)
    if item["case_id"] == "U06":
        if any(marker in answer or marker in retrieved for marker in case["forbidden"]):
            codes = sorted(set(codes) | {"privacy_leak"})
    if item["case_id"] == "U02" and metrics["constraint_preservation"] != [4, 4] and verdict == "pass":
        raise harness.HarnessError("U02 pass requires all four frozen conditions")
    # Product output can be JSON with escaped Unicode. Decode the JSON lines
    # before checking the fixed atoms and keep the native bytes for cost.
    normalized = []
    for line in retrieved.splitlines():
        try:
            normalized.append(json.dumps(json.loads(line), ensure_ascii=False))
        except ValueError:
            normalized.append(line)
    searchable = "\n".join(normalized)
    return {
        "status": "SCORED", "score": item["score"], "task_utility": int(verdict == "pass" and not codes),
        "retrieval_recall": [sum(atom in searchable for atom in visible), len(visible)],
        "answer_coverage": [sum(atom in answer for atom in visible), len(visible)],
        "observations": metrics, "cost": {**cost, "tool_calls": len(tools),
                                         "tool_output_bytes": len(retrieved.encode("utf-8"))},
        "independent_failures": codes,
    }


def score(folder, result_file):
    cases, budget = frozen_cases(folder)
    results = harness._load(result_file)
    if results["protocol_version"] != harness.PROTOCOL_VERSION or results["fixture_sha256"] != FIXTURE_DIGESTS:
        raise harness.HarnessError("unexpected protocol or fixture hash")
    arm, repeat = results["arm"], results["repeat"]
    run = results["run"]
    keys = ("run_id", "host", "host_version", "model", "effort", "skill_version", "started_at", "source_sha")
    if arm not in ROTATIONS[0] or len(arm) != 1 or type(repeat) is not int or repeat not in range(1, 4):
        raise harness.HarnessError("unknown arm or repeat")
    if any(not isinstance(run[key], str) or not run[key].strip() for key in keys):
        raise harness.HarnessError("complete execution metadata required")
    if run["data_scope"] != "synthetic-only" or (arm in ("A", "B") and run["source_sha"] != BASELINE):
        raise harness.HarnessError("invalid source or data scope")
    if run["budget"] != budget:
        raise harness.HarnessError("run differs from the frozen budget")
    observations = {}
    for item in results["cases"]:
        key = item["case_id"]
        if key not in cases or key in observations:
            raise harness.HarnessError("unknown or repeated case")
        observations[key] = _record(cases[key], item, result_file, budget)
    return {"arm": arm, "repeat": repeat, "run": run, "cases": {
        key: observations.get(key, {"status": "NOT_RUN", "reason": "no native result"}) for key in cases
    }}


def compare(folder, result_files):
    runs = {}
    for result_file in result_files:
        result = score(folder, result_file)
        key = result["arm"], result["repeat"]
        if key in runs:
            raise harness.HarnessError("repeated arm and repetition")
        runs[key] = result
    manifest = {(arm, repeat) for arm in "ABC" for repeat in range(1, 4)}
    incomplete = sorted(manifest - runs.keys())
    unscored = [(arm, repeat, case_id) for (arm, repeat), result in runs.items()
                for case_id, row in result["cases"].items() if row["status"] == "NOT_RUN"]
    if incomplete or unscored:
        return {"status": "NOT_RUN", "missing_runs": incomplete, "unscored": unscored}
    matching_keys = ("host", "host_version", "model", "effort", "budget")
    reference = runs["B", 1]["run"]
    if any(any(result["run"][key] != reference[key] for key in matching_keys) for result in runs.values()):
        raise harness.HarnessError("comparison has unmatched native configurations")
    if len({result["run"]["run_id"] for result in runs.values()}) != len(manifest):
        raise harness.HarnessError("each arm and repetition requires a distinct run")
    candidates = [runs["C", repeat] for repeat in range(1, 4)]
    shas = {result["run"]["source_sha"] for result in candidates}
    if len(shas) != 1 or shas == {BASELINE}:
        raise harness.HarnessError("C must name one fixed candidate source")

    failures = []
    improvements = dict.fromkeys(("U02", "U03", "U04", "U05", "U06", "U07"), 0)
    for result in candidates:
        repeat = result["repeat"]
        baseline = runs["B", repeat]["cases"]
        for case_id, row in result["cases"].items():
            utility = row["task_utility"]
            if row["independent_failures"]:
                failures.append([case_id, repeat, "independent_failure", row["independent_failures"]])
            if case_id in {"U02", "U06"} and not utility:
                failures.append([case_id, repeat, "hard_condition"])
            if case_id in {"U01", "U03", "U07"} and utility < baseline[case_id]["task_utility"]:
                failures.append([case_id, repeat, "task_utility_regressed"])
            if case_id in improvements and utility > baseline[case_id]["task_utility"]:
                improvements[case_id] += 1
    if max(improvements.values()) < 2:
        failures.append(["no_approved_case_improved_in_two_repeats"])
    return {"status": "FAIL" if failures else "REQUIRES_LIFECYCLE_AND_BLIND_REVIEW",
            "case_gate_failures": failures, "improved_repeats": improvements,
            "observed_runs": list(runs.values())}
