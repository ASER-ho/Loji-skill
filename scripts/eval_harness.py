#!/usr/bin/env python3
"""Lightweight evaluator for Loji behavior fixtures and synthetic retrieval.

Two deliberately separate layers:

* ``check`` / ``deterministic`` run locally with the Python standard library.
  They prove fixture structure and the current memory-retrieval contract on
  synthetic data. They never call a model and never read real user data.
* ``plan`` / ``score`` support real-host behavior evaluation. The harness does
  not run a host; it emits a plan and scores a result file with the rules fixed
  in ``research/evals/BEHAVIOR_EVAL_PROTOCOL.md``.

Exit codes: 0 success, 1 validation/gate failure, 2 usage or access error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__:
    from . import memory_schema as schema
else:
    import memory_schema as schema

ROOT = Path(__file__).resolve().parents[1]

PROTOCOL_VERSION = "1.0"
FIXTURE_VERSION = "1.0.0"
BEHAVIOR_FIXTURES = ("fidelity-scenarios.json", "judgment-evidence.json")
ALL_FIXTURES = BEHAVIOR_FIXTURES + ("memory-retrieval-cases.json",)
INDEPENDENT_FAILURES = frozenset({
    "authorization_violation",
    "privacy_leak",
    "core_anchor_destruction",
    "fabricated_evidence",
    "unsafe_action",
    "major_factual_error",
})
VERDICT_SCORES = {"pass": 2, "partial": 1, "fail": 0, "unscored": None}


class HarnessError(ValueError):
    """The fixture or result file violates the fixed protocol."""


def _load(path: Path) -> Any:
    return schema.decode_json(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strings(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise HarnessError(f"{label} must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise HarnessError(f"{label} must contain non-empty strings")
    return value


def _case_ids(cases: Any, label: str) -> list[dict]:
    if not isinstance(cases, list) or not cases:
        raise HarnessError(f"{label}: cases must be a non-empty list")
    seen: set[str] = set()
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            raise HarnessError(f"{label}: case {index} is not an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise HarnessError(f"{label}: case {index} missing id")
        if case_id in seen:
            raise HarnessError(f"{label}: duplicate id {case_id!r}")
        seen.add(case_id)
        for key in ("description", "input", "expected", "forbidden"):
            if key not in case:
                raise HarnessError(f"{label}: {case_id} missing {key!r}")
        _strings(case["input"], f"{label}: {case_id} input")
        _strings(case["expected"], f"{label}: {case_id} expected")
        _strings(case["forbidden"], f"{label}: {case_id} forbidden", allow_empty=True)
    return cases


def check_fidelity(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = _load(path)
        if data.get("version") != FIXTURE_VERSION:
            errors.append(f"{path.name}: version must be {FIXTURE_VERSION}")
        cases = _case_ids(data.get("cases"), path.name)
        gates = data.get("gates")
        if not isinstance(gates, dict):
            raise HarnessError(f"{path.name}: gates missing")
        if gates.get("total_cases") != len(cases):
            errors.append(f"{path.name}: gates.total_cases disagrees with cases")
        categories = {case.get("category") for case in cases}
        if len(categories) < gates.get("minimum_categories", 0):
            errors.append(f"{path.name}: fewer categories than the gate requires")
        for category in gates.get("required_categories", []):
            if category not in categories:
                errors.append(f"{path.name}: required category {category!r} missing")
        for case in cases:
            if not isinstance(case.get("category"), str) or not case["category"].strip():
                errors.append(f"{path.name}: {case.get('id')} missing category")
            failures = case.get("independent_failures")
            if not isinstance(failures, list) or any(
                item not in INDEPENDENT_FAILURES for item in failures
            ):
                errors.append(
                    f"{path.name}: {case.get('id')} has unknown independent failure"
                )
    except (OSError, ValueError, HarnessError) as exc:
        errors.append(f"{path.name}: {exc}")
    return errors


def check_evidence(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = _load(path)
        if data.get("version") != FIXTURE_VERSION:
            errors.append(f"{path.name}: version must be {FIXTURE_VERSION}")
        cases = _case_ids(data.get("cases"), path.name)
        gates = data.get("gates")
        if not isinstance(gates, dict):
            raise HarnessError(f"{path.name}: gates missing")
        if gates.get("total_cases") != len(cases):
            errors.append(f"{path.name}: gates.total_cases disagrees with cases")
        tags = data.get("basis_tags")
        if not isinstance(tags, dict) or set(tags) != {
            "直接证据", "来源观点", "可核查产物", "未验证印象",
        }:
            errors.append(f"{path.name}: basis_tags must define the four tiers")
        categories = {case.get("category") for case in cases}
        for category in gates.get("required_categories", []):
            if category not in categories:
                errors.append(f"{path.name}: required category {category!r} missing")
        for case in cases:
            failures = case.get("independent_failures")
            if not isinstance(failures, list) or any(
                item not in INDEPENDENT_FAILURES for item in failures
            ):
                errors.append(
                    f"{path.name}: {case.get('id')} has unknown independent failure"
                )
    except (OSError, ValueError, HarnessError) as exc:
        errors.append(f"{path.name}: {exc}")
    return errors


def _retrieval_state(path: Path) -> tuple[list[dict], list[dict]]:
    data = _load(path)
    if data.get("data_scope") != "synthetic-only":
        raise HarnessError(f"{path.name}: data_scope must be synthetic-only")
    records = data.get("records")
    if not isinstance(records, dict):
        raise HarnessError(f"{path.name}: records missing")
    judgments = records.get("judgments")
    episodes = records.get("episodes")
    if not isinstance(judgments, list) or not isinstance(episodes, list):
        raise HarnessError(f"{path.name}: judgments/episodes must be lists")
    return judgments, episodes


def check_retrieval(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = _load(path)
        if data.get("version") != FIXTURE_VERSION:
            errors.append(f"{path.name}: version must be {FIXTURE_VERSION}")
        judgments, episodes = _retrieval_state(path)
        cases = data.get("cases")
        if not isinstance(cases, list) or not cases:
            raise HarnessError(f"{path.name}: cases missing")
        seen: set[str] = set()
        for index, case in enumerate(cases, 1):
            if not isinstance(case, dict):
                raise HarnessError(f"{path.name}: case {index} is not an object")
            case_id = case.get("id")
            if not isinstance(case_id, str) or not case_id.strip():
                raise HarnessError(f"{path.name}: case {index} missing id")
            if case_id in seen:
                raise HarnessError(f"{path.name}: duplicate id {case_id!r}")
            seen.add(case_id)
            if not isinstance(case.get("description"), str) or not case["description"].strip():
                raise HarnessError(f"{path.name}: {case_id} missing description")
        judgment_ids = {item.get("id") for item in judgments}
        episode_ids = {item.get("id") for item in episodes}
        if len(judgment_ids) != len(judgments) or len(episode_ids) != len(episodes):
            errors.append(f"{path.name}: duplicate record ids")
        for case in cases:
            matters = case.get("matters")
            if not isinstance(matters, list) or not all(
                isinstance(item, str) and item.strip() for item in matters
            ):
                errors.append(f"{path.name}: {case.get('id')} has invalid matters")
            expected = set(case.get("expected_episode_ids", []))
            forbidden = set(case.get("forbidden_episode_ids", []))
            if expected & forbidden:
                errors.append(f"{path.name}: {case.get('id')} expects and forbids an id")
            if not expected <= episode_ids or not forbidden <= episode_ids:
                errors.append(f"{path.name}: {case.get('id')} references unknown episodes")
            for key in ("expected_unresolved", "expected_judgment_ids"):
                value = case.get(key)
                if not isinstance(value, list) or not all(
                    isinstance(item, str) for item in value
                ):
                    errors.append(f"{path.name}: {case.get('id')} has invalid {key}")
            known = set(case.get("expected_judgment_ids", []))
            if not known <= judgment_ids:
                errors.append(f"{path.name}: {case.get('id')} references unknown judgments")
    except (OSError, ValueError, HarnessError) as exc:
        errors.append(f"{path.name}: {exc}")
    return errors


def check_fixtures(root: Path | str | None = None) -> list[str]:
    base = Path(root) if root is not None else ROOT
    folder = base / "research" / "evals"
    errors: list[str] = []
    errors.extend(check_fidelity(folder / "fidelity-scenarios.json"))
    errors.extend(check_evidence(folder / "judgment-evidence.json"))
    errors.extend(check_retrieval(folder / "memory-retrieval-cases.json"))
    protocol = folder / "BEHAVIOR_EVAL_PROTOCOL.md"
    if not protocol.exists():
        errors.append("research/evals/BEHAVIOR_EVAL_PROTOCOL.md: missing")
    else:
        text = protocol.read_text(encoding="utf-8")
        for needle in (
            "答题与评分分离",
            "模型自述不是证据",
            "独立失败项",
            "不得在看到候选答案后修改",
        ):
            if needle not in text:
                errors.append(f"BEHAVIOR_EVAL_PROTOCOL.md: missing {needle!r}")
    return errors


def _write_synthetic(folder: Path, judgments: list[dict], episodes: list[dict],
                     root: Path = ROOT) -> tuple[Path, Path]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts import judgment_ledger as jl
    from scripts import memory_schema as schema

    template = (root / "memory.template.md").read_text(encoding="utf-8")
    doc = schema.parse(template)
    doc.episodes[:] = episodes
    doc.calibration.clear()
    memory = folder / "memory.md"
    memory.write_text(doc.render_v2(), encoding="utf-8")
    ledger = folder / "JUDGMENTS.md"
    blocks = "\n\n".join(jl.render_judgment(jl.Judgment(**record)) for record in judgments)
    ledger.write_text(
        '---\nschema_version: 1\nskill_version: "1.1.4"\n---\n\n' + blocks + "\n",
        encoding="utf-8",
    )
    return memory, ledger


def _evaluate(case: dict, output: dict) -> dict:
    episode_ids = [item["id"] for item in output["episodes"]]
    returned = set(episode_ids)
    expected = set(case["expected_episode_ids"])
    forbidden = set(case["forbidden_episode_ids"])
    evidence = set(output["judgment_evidence"])
    checks = {
        "expected_episodes": expected <= returned,
        "no_forbidden_episodes": not (forbidden & returned),
        "unresolved": sorted(output["unresolved"]) == sorted(case["expected_unresolved"]),
        "judgment_evidence": evidence == set(case["expected_judgment_ids"]),
    }
    historical = case.get("expected_historical_judgment_ids", {})
    for episode_id, ids in historical.items():
        record = next(
            (item for item in output["episodes"] if item["id"] == episode_id), None
        )
        checks[f"historical:{episode_id}"] = (
            record is not None
            and sorted(record["historical_judgment_ids"]) == sorted(ids)
        )
    return {
        "case_id": case["id"],
        "expected": sorted(expected),
        "returned": sorted(returned),
        "unresolved": sorted(output["unresolved"]),
        "judgment_evidence": sorted(evidence),
        "checks": checks,
        "verdict": "pass" if all(checks.values()) else "fail",
        "limitation": case.get("limitation"),
    }


def run_retrieval(root: Path | str | None = None) -> dict:
    """Run the fixed synthetic retrieval cases through the shipped context entry."""
    base = Path(root) if root is not None else ROOT
    fixture_path = base / "research" / "evals" / "memory-retrieval-cases.json"
    data = _load(fixture_path)
    judgments, episodes = _retrieval_state(fixture_path)
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))
    from scripts import episodic_memory as em

    results = []
    raw = []
    with tempfile.TemporaryDirectory() as tmp:
        memory, ledger = _write_synthetic(Path(tmp), judgments, episodes, base)
        for case in data["cases"]:
            output = em.context(
                memory,
                ledger,
                policy="read_only",
                consent="granted",
                matters=case["matters"],
                as_of=data["as_of"],
            )
            raw.append(output)
            results.append(_evaluate(case, output))

    expected_total = sum(len(case["expected_episode_ids"]) for case in data["cases"])
    returned_total = sum(len(item["returned"]) for item in results)
    hits = sum(
        1
        for case, item in zip(data["cases"], results)
        for episode_id in case["expected_episode_ids"]
        if episode_id in item["returned"]
    )
    forbidden_total = sum(
        1
        for case, item in zip(data["cases"], results)
        for episode_id in case["forbidden_episode_ids"]
        if episode_id in item["returned"]
    )
    passed = sum(item["verdict"] == "pass" for item in results)
    return {
        "fixture": fixture_path.name,
        "fixture_version": data["version"],
        "fixture_sha256": _sha256(fixture_path),
        "data_scope": data["data_scope"],
        "cases": results,
        "metrics": {
            "cases": len(results),
            "cases_passed": passed,
            "recall": round(hits / expected_total, 4) if expected_total else 1.0,
            "irrelevant_returned": returned_total - hits,
            "forbidden_returned": forbidden_total,
            "note": "Character counts are not Token, cost, or task-success claims.",
        },
        "candidate_comparison": _compare_candidates(data, results, raw),
    }


def _compare_candidates(data: dict, results: list[dict], raw: list[dict]) -> dict:
    """Measure two candidate views without changing the shipped default.

    Ordering by recency cannot change exact-match membership. A compact
    projection drops decision-relevant fields, so its information loss is
    recorded rather than adopted.
    """
    reordered = 0
    set_unchanged = True
    for output in raw:
        ordered = sorted(output["episodes"], key=lambda ep: (ep["date"], ep["id"]), reverse=True)
        if [ep["id"] for ep in ordered] != [ep["id"] for ep in output["episodes"]]:
            reordered += 1
        if {ep["id"] for ep in ordered} != {ep["id"] for ep in output["episodes"]}:
            set_unchanged = False
    evidence_cases = sum(
        bool(case["expected_judgment_ids"]) for case in data["cases"]
    )
    historical_cases = sum(
        bool(case.get("expected_historical_judgment_ids")) for case in data["cases"]
    )
    return {
        "baseline_exact_filter": {
            "adopted": True,
            "reason": "v1.1.3 default; exact-match scope preserves the contract",
        },
        "ordering_by_recency": {
            "adopted": False,
            "same_episode_set": set_unchanged,
            "cases_reordered": reordered,
            "reason": (
                "exact filtering already fixes membership; ordering adds no recall or "
                "precision signal on this fixture"
            ),
        },
        "compact_projection": {
            "adopted": False,
            "dropped_fields": [
                "summary", "outcome", "related_judgments", "judgment_evidence.basis",
            ],
            "cases_expecting_judgment_evidence": evidence_cases,
            "cases_expecting_historical_ids": historical_cases,
            "reason": (
                "the current contract requires judgment basis and historical ids; a "
                "compact view would lose decision-relevant evidence, so it is rejected"
            ),
        },
        "note": "Comparison only; the shipped context interface and default output are unchanged.",
    }


def write_plan(root: Path | str | None, out_dir: Path) -> list[Path]:
    base = Path(root) if root is not None else ROOT
    folder = base / "research" / "evals"
    out_dir = Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise HarnessError("plan directory must be empty or new")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in BEHAVIOR_FIXTURES:
        path = folder / name
        data = _load(path)
        plan = {
            "protocol_version": PROTOCOL_VERSION,
            "fixture": Path(name).stem,
            "fixture_version": data["version"],
            "fixture_sha256": _sha256(path),
            "run": {
                "run_id": "",
                "host": "",
                "host_version": "",
                "model": "",
                "effort": "",
                "skill_version": "",
                "data_scope": "synthetic-only",
                "started_at": "",
            },
            "cases": [
                {
                    "case_id": case["id"],
                    "category": case["category"],
                    "description": case["description"],
                    "precondition": case.get("precondition", ""),
                    "input": case["input"],
                    "expected": case["expected"],
                    "forbidden": case["forbidden"],
                    "actual_answer": "",
                    "deterministic_evidence": [],
                    "semantic_verdict": "unscored",
                    "semantic_reason": "",
                    "independent_failures": [],
                    "score": None,
                    "notes": "",
                }
                for case in data["cases"]
            ],
        }
        target = out_dir / (Path(name).stem + "-plan.json")
        target.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(target)
    return written


def _find_fixture(root: Path, source: str) -> dict:
    source = source[:-5] if source.endswith(".json") else source
    allowed = {Path(name).stem for name in BEHAVIOR_FIXTURES}
    if source not in allowed:
        raise HarnessError(f"unknown fixture {source!r}")
    path = root / "research" / "evals" / (source + ".json")
    return {"path": path, "data": _load(path), "sha256": _sha256(path)}


def _artifact(folder: Path, ref: Any) -> Path:
    if not isinstance(ref, str) or not ref.strip() or Path(ref).is_absolute():
        raise HarnessError("evidence ref must be relative to the result directory")
    path = folder / ref
    if not path.resolve().is_relative_to(folder.resolve()):
        raise HarnessError("evidence ref escapes the result directory")
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
           for p in (path, *path.parents) if p.is_relative_to(folder)):
        raise HarnessError("linked evidence paths are not accepted")
    if not path.is_file() or not path.stat().st_size:
        raise HarnessError("missing or empty objective evidence")
    return path


def _execution_evidence(item: dict, case: dict, folder: Path) -> list[dict]:
    evidence = item.get("deterministic_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise HarnessError("missing objective execution evidence; self-report is insufficient")
    executions = []
    for proof in evidence:
        if not isinstance(proof, dict) or proof.get("kind") not in {
                "tool_log", "audit_log", "file_hash", "test_output"} or proof.get("result") != "pass":
            raise HarnessError("invalid or unexecuted evidence record")
        path = _artifact(folder, proof.get("ref"))
        if "sha256" in proof and proof["sha256"] != _sha256(path):
            raise HarnessError("evidence hash mismatch")
        if proof["kind"] != "test_output":
            continue
        record = _load(path)
        if not isinstance(record, dict) or record.get("case_id") != case["id"] or record.get("input") != case["input"]:
            raise HarnessError("execution case/input mismatch")
        if record.get("status") != "completed" or record.get("answer") != item["actual_answer"]:
            raise HarnessError("execution is incomplete or answer differs from the original")
        if not all(isinstance(record.get(key), dict) for key in ("before", "after")) or not all(
                isinstance(record.get(key), list) for key in ("tools", "python_audit")):
            raise HarnessError("execution must include snapshots, native tools and access audit")
        if case["id"] in {"F14", "V03", "V04", "V05", "V06", "V07"}:
            for when in ("before", "after"):
                for name in ("memory.md", "JUDGMENTS.md"):
                    row = record[when].get(name)
                    if not isinstance(row, dict) or not isinstance(row.get("text"), str) or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))):
                        raise HarnessError("file-operation case lacks actual body snapshots")
            if not any(t.get("type") == "commandExecution" and t.get("status") == "completed" for t in record["tools"] if isinstance(t, dict)) or not record["python_audit"]:
                raise HarnessError("file-operation case lacks native tools or calibrated access audit")
        if case["id"] == "F14":
            if (any(record["before"][n] != record["after"][n] for n in ("memory.md", "JUDGMENTS.md"))
                    or "memory.state.json" in record["after"]
                    or any(e.get("kind") != "python-start" for e in record["python_audit"] if isinstance(e, dict))):
                raise HarnessError("authorization violation in first activation evidence")
        refs = record.get("native_logs")
        if not isinstance(refs, list) or len(refs) != len(case["input"]) or len(set(refs)) != len(refs):
            raise HarnessError("each fixed input requires a distinct native turn log")
        answers = []
        native_tools = []
        for ref in refs:
            events = [schema.decode_json(line) for line in _artifact(folder, ref).read_text(encoding="utf-8").splitlines() if line.strip()]
            if not all(isinstance(e, dict) for e in events):
                raise HarnessError("native events must be objects")
            complete = [e for e in events if e.get("method") == "turn/completed"]
            if len(complete) != 1 or complete[0].get("params", {}).get("turn", {}).get("status") != "completed":
                raise HarnessError("native turn was not completed")
            answers.append("\n".join(e["params"]["item"].get("text", "") for e in events
                if e.get("method") == "item/completed" and e.get("params", {}).get("item", {}).get("type") == "agentMessage"))
            native_tools.extend(e["params"]["item"] for e in events
                if e.get("method") == "item/completed" and e.get("params", {}).get("item", {}).get("type")
                in {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "webSearch"})
        if "\n\n".join(answers) != item["actual_answer"]:
            raise HarnessError("answer is not bound to the native transcript")
        executions.append({**record, "native_tools": native_tools})
    if not executions:
        raise HarnessError("no native execution record; artifact labels do not prove an operation")
    return executions


def score(results_path: Path, root: Path | str | None = None, *, fixture_name: str | None = None) -> dict:
    base = Path(root) if root is not None else ROOT
    results = _load(Path(results_path))
    if not isinstance(results, dict):
        raise HarnessError("results must be an object")
    if results.get("protocol_version") != PROTOCOL_VERSION:
        raise HarnessError(f"protocol_version must be {PROTOCOL_VERSION}")
    source = results.get("fixture")
    if not isinstance(source, str):
        raise HarnessError("results must name their fixture")
    fixture = _find_fixture(base, source)
    if fixture_name is not None and fixture_name.removesuffix(".json") != source.removesuffix(".json"):
        raise HarnessError("--fixture disagrees with the result file")
    data = fixture["data"]
    if results.get("fixture_version") != data["version"]:
        raise HarnessError("fixture_version mismatch")
    if results.get("fixture_sha256") != fixture["sha256"]:
        raise HarnessError("fixture_sha256 mismatch; sample changed after collection")
    provided = results.get("cases")
    if not isinstance(provided, list):
        raise HarnessError("cases must be a list")
    by_id = {}
    for item in provided:
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            raise HarnessError("result case missing case_id")
        if item["case_id"] in by_id:
            raise HarnessError(f"duplicate result case {item['case_id']}")
        by_id[item["case_id"]] = item

    total = 0
    scored = 0
    failures: list[str] = []
    run = results.get("run")
    required = ("run_id", "host", "host_version", "model", "effort", "skill_version", "started_at")
    if not isinstance(run, dict) or not all(isinstance(run.get(key), str) and run[key].strip() for key in required) or run.get("data_scope") != "synthetic-only":
        failures.append("missing execution metadata or invalid data scope")
    unknown = set(by_id) - {case["id"] for case in data["cases"]}
    if unknown:
        failures.append("unknown result case ids: " + ", ".join(sorted(unknown)))
    for case in data["cases"]:
        item = by_id.get(case["id"])
        if item is None:
            failures.append(f"{case['id']}: no result recorded")
            continue
        if item.get("expected") != case["expected"] or item.get("forbidden") != case["forbidden"]:
            failures.append(f"{case['id']}: expectation changed from the fixed sample")
            continue
        if item.get("input") != case["input"]:
            failures.append(f"{case['id']}: input changed from the fixed sample")
            continue
        verdict = item.get("semantic_verdict")
        if verdict not in VERDICT_SCORES:
            failures.append(f"{case['id']}: unknown semantic_verdict {verdict!r}")
            continue
        score_value = VERDICT_SCORES[verdict]
        if item.get("score") != score_value or (score_value is not None and type(item.get("score")) is not int):
            failures.append(f"{case['id']}: score disagrees with verdict")
            continue
        if not isinstance(item.get("actual_answer"), str) or not item["actual_answer"].strip():
            failures.append(f"{case['id']}: missing verbatim answer")
            continue
        codes = item.get("independent_failures")
        if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes) or len(set(codes)) != len(codes):
            failures.append(f"{case['id']}: invalid independent_failures")
            continue
        bad = [code for code in codes if code not in INDEPENDENT_FAILURES]
        if bad:
            failures.append(f"{case['id']}: unknown independent failure {bad}")
            continue
        if score_value is not None:
            if not isinstance(item.get("semantic_reason"), str) or not item["semantic_reason"].strip():
                failures.append(f"{case['id']}: missing independent semantic reason")
                continue
            try:
                _execution_evidence(item, case, Path(results_path).resolve().parent)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failures.append(f"{case['id']}: {exc}")
                continue
            total += score_value
            scored += 1

    independent = sorted({
        code
        for item in by_id.values()
        for code in (item.get("independent_failures") if isinstance(item.get("independent_failures"), list) else [])
        if isinstance(code, str)
        if code in INDEPENDENT_FAILURES
    })
    gates = data.get("gates", {})
    gate_errors = []
    if failures:
        gate_errors.extend(failures)
    if independent:
        gate_errors.append("zero-tolerance independent failure: " + ", ".join(independent))
    if scored < len(data["cases"]):
        gate_errors.append("not every case was scored")
    if "minimum_score" in gates and total < gates["minimum_score"]:
        gate_errors.append(f"total {total} below minimum {gates['minimum_score']}")
    if "maximum_score" in gates and total > gates["maximum_score"]:
        gate_errors.append(f"total {total} above maximum {gates['maximum_score']}")
    zero_tolerance_cases = {
        case["id"] for case in data["cases"] if case.get("independent_failures")
    }
    for case_id in zero_tolerance_cases:
        item = by_id.get(case_id, {})
        if item.get("semantic_verdict") != "pass":
            gate_errors.append(f"{case_id}: zero-tolerance case did not pass")
    return {
        "fixture": source,
        "fixture_sha256": fixture["sha256"],
        "scored_cases": scored,
        "total_cases": len(data["cases"]),
        "score": total,
        "maximum": 2 * len(data["cases"]),
        "independent_failures": independent,
        "result": "PASS" if not gate_errors else "FAIL",
        "errors": gate_errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "deterministic", "plan", "score",
                                            "utility-plan", "utility-score", "utility-compare"))
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="repository root; default is this checkout")
    parser.add_argument("--out", type=Path, help="output directory or file")
    parser.add_argument("--results", type=Path, help="behavior results JSON for score")
    parser.add_argument("--fixture", help="fixed fixture name for score; must match results")
    parser.add_argument("--utility-fixtures", type=Path, help="external frozen L115 fixture directory")
    parser.add_argument("--utility-result", type=Path, action="append", default=[],
                        help="repeat for each blinded, scored arm and repetition in utility-compare")
    args = parser.parse_args(argv)
    try:
        if args.action in {"utility-plan", "utility-score", "utility-compare"}:
            if not args.utility_fixtures:
                parser.error("utility actions require --utility-fixtures")
            if __package__:
                from . import eval_utility
            else:
                import eval_utility
            if args.action == "utility-plan":
                if not args.out:
                    parser.error("utility-plan requires --out")
                eval_utility.write_plan(args.utility_fixtures, args.out)
            elif args.action == "utility-score":
                if not args.results:
                    parser.error("utility-score requires --results")
                print(json.dumps(eval_utility.score(args.utility_fixtures, args.results),
                                 ensure_ascii=False, indent=2))
            else:
                summary = eval_utility.compare(args.utility_fixtures, args.utility_result)
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                return 0 if summary["status"] == "REQUIRES_LIFECYCLE_AND_BLIND_REVIEW" else 1
            return 0
        if args.action == "check":
            errors = check_fixtures(args.root)
            for error in errors:
                print(f"ERROR: {error}")
            print("OK: eval fixtures valid" if not errors else f"FAILED: {len(errors)} error(s)")
            return 0 if not errors else 1
        if args.action == "deterministic":
            result = run_retrieval(args.root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if all(case["verdict"] == "pass" for case in result["cases"]) else 1
        if args.action == "plan":
            if args.out is None:
                parser.error("plan requires --out")
            for path in write_plan(args.root, args.out):
                print(path)
            return 0
        if args.results is None:
            parser.error("score requires --results")
        summary = score(args.results, args.root, fixture_name=args.fixture)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["result"] == "PASS" else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"eval refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
