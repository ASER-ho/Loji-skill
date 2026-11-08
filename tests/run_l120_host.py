"""Opt-in, synthetic-only behavior suite for an existing Claude Code host.

Run from the repo root with a configured Claude Code executable. The runner
does not install tools, change settings, resume sessions, or read real Memory.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from l120_support import AS_OF, GROUPS, fresh_memory, production_state
from scripts import episodic_memory as em, memory_schema as schema

AUTH = dict(policy="explicit", consent="granted", user_requested=True, eligible_and_private=True)
SEAL = "SYNTHETIC EVALUATION. 以下用户、对话、材料、状态全部虚构。"


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def host_call(executable, cwd, prompt):
    prompt = SEAL + "\n\n" + prompt
    data = prompt.encode()
    args = [
        executable, "--print", "--bare", "--no-session-persistence",
        "--disable-slash-commands", "--strict-mcp-config", "--tools=",
        "--setting-sources", "user", "--output-format", "json",
    ]
    completed = subprocess.run(args, input=data, cwd=cwd, capture_output=True, timeout=180)
    try:
        response = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError(f"host did not return JSON (exit {completed.returncode})") from exc
    if completed.returncode or response.get("is_error"):
        raise RuntimeError(f"host failed (exit {completed.returncode}): {response.get('terminal_reason')}")
    return {
        "session_id": response["session_id"],
        "model": sorted(response.get("modelUsage", {})),
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "answer": response["result"],
        "duration_ms": response.get("duration_ms"),
    }


def record_from_state(memory, ledger, state):
    """Persist A's supplied synthetic events through the production writers."""
    persisted, ledger_text = production_state(state)
    memory.write_bytes(fresh_memory().encode())
    ledger.write_bytes(ledger_text.encode())
    rows = schema.parse(persisted).episodes
    for row in rows:
        data = {key: value for key, value in row.items() if key != "state"}
        em.mutate(memory, ledger, "add", data, **AUTH)
        if row["state"] in ("archived", "deprecated", "unresolved"):
            em.mutate(memory, ledger, "transition", {"id": row["id"], "state": row["state"]}, **AUTH)
    if schema.parse(memory.read_text(encoding="utf-8")).episodes != rows:
        raise AssertionError("production writers did not reproduce the synthetic state")


def continuity(executable, cwd, case):
    cid = case["id"]
    a, b = (case["input"][key] for key in ("session_a", "session_b"))
    path_a = cwd / "A"
    path_b = cwd / "B"
    path_a.mkdir(parents=True)
    path_b.mkdir()
    result_a = host_call(executable, path_a, (
        "以下是本轮输入的合成对话。用一两句总结当轮已核对的事实或动作，"
        "区分旧说法、已发生事件与不确定项；没有数据不要补写。\n" + json_text(a["synthetic_dialogue"])
    ))
    # A's explicit state changes are supplied by the fixture and applied
    # through actual writes. Neither A's transcript nor its answer is used
    # as state. Copy only the two current synthetic files, never backups.
    memory_a, ledger_a = path_a / "memory.md", path_a / "JUDGMENTS.md"
    record_from_state(memory_a, ledger_a, b)
    for old in (memory_a, ledger_a):
        (path_b / old.name).write_bytes(old.read_bytes())
    packet = em.context(
        path_b / "memory.md", path_b / "JUDGMENTS.md",
        policy="read_only", consent="granted", as_of=AS_OF,
    )
    question = b["current_input"]
    result_b = host_call(executable, path_b, (
        "这是一个新的独立会话。宿主只授予只读权限，以下是唯一提供的经校验当前状态，"
        "不可调用工具、读取其他状态或声称已恢复/保存。区分过去事件、当前方案、计划和已验证结果。若一个决定指向后续行动且未见该行动结果，明确说后续结果尚未报告；不能把前一次的验证当作后续结果。unresolved 列出尚未核实的矛盾事项；若与提问有关，请明确说存在未解决冲突、当前无法确定，并可请求核对证据。缺少信息时说明不能确认。直接自然地用中文回答本轮问题。\n"
        + json_text({"current_input": question, "authorized_current_state": packet})
    ))
    if result_a["session_id"] == result_b["session_id"]:
        raise AssertionError("host reused the session")
    return {
        "id": cid, "session_a": result_a, "session_b": result_b,
        "b_input": question, "b_authorized_state": packet,
        "contains_stale_or_contradictory_episode": case["input"]["contains_stale_or_contradictory_episode"],
    }


def classify(executable, cwd):
    prompts = [{
        "case": c["id"], "utterance": c["input"]["synthetic_utterance"],
        "context": c["input"]["context"],
    } for c in GROUPS["episode_classification"]]
    cwd.mkdir()
    result = host_call(executable, cwd, (
        "独立审阅每个候选是否有资格作为 Episode（这次没有写入授权）。仅输出一个 JSON 对象，"
        "键为候选 case，值为 kind 或 null。候选必须是已经共同作出的重要决定（important_joint_decision）、已发生且可核查的结果（actual_outcome），或明确有依据的更正／学习（correction_or_learning）；其他内容填 null。无需解释，不要写入。\n" + json_text(prompts)
    ))
    answer = result["answer"].strip()
    if answer.startswith("\x60\x60\x60"):
        answer = answer.split("\n", 1)[1].rsplit("\x60\x60\x60", 1)[0]
    actual = json.loads(answer)
    expected = {c["id"]: c["expected_result"]["classification"] for c in GROUPS["episode_classification"]}
    if actual.keys() != expected.keys():
        raise RuntimeError("classification response missed or added cases")
    return {
        **result,
        "cases": {cid: {"actual": actual[cid], "expected": kind, "pass": actual[cid] == kind}
                  for cid, kind in expected.items()},
    }

def calibration_behavior(executable, cwd, mode):
    inputs = {c["id"]: c["input"] for c in GROUPS["calibration"]}
    cwd.mkdir()
    return {
        "mode": mode,
        **host_call(executable, cwd, (
            "本轮领域模式为 " + mode + "。以下三项互相独立，均为虚构。"
            "请按编号分别给出结论和会采取的核对动作。模式只改变查证力度：normal 常规核对；high_value_signal 优先看该领域的建议依据；verify_more 增加独立交叉核对。证据标准不随模式改变。宿主只授予只读权限，不能读其他状态或写入。\n"
            + json_text({
                "C18": inputs["C18"]["fact_packet"],
                "C19": inputs["C19"]["request"],
                "C20": "下一轮纸舟实验是否成功？当前没有下一轮观测。",
            })
        )),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    executable = str(Path(args.claude).resolve(strict=True))
    version = subprocess.run([executable, "--version"], capture_output=True, check=True).stdout.decode().strip()
    results = {"host": version, "continuity": [], "calibration": []}
    with tempfile.TemporaryDirectory(prefix="loji-synthetic-") as tmp, ThreadPoolExecutor(max_workers=3) as pool:
        root = Path(tmp)
        tasks = [
            ("classification", pool.submit(classify, executable, root / "B01-B15")),
            *(("continuity", pool.submit(continuity, executable, root / c["id"], c))
              for c in GROUPS["continuity"]),
            *(("calibration", pool.submit(calibration_behavior, executable, root / mode, mode))
              for mode in ("normal", "high_value_signal", "verify_more")),
        ]
        for group, task in tasks:
            result = task.result()
            if group == "classification":
                results[group] = result
            else:
                results[group].append(result)
            print(f"finished: {group} {result.get('id', result.get('mode', 'B01–B15'))}", flush=True)
    calls = [results["classification"], *results["calibration"]]
    for row in results["continuity"]:
        calls.extend([row["session_a"], row["session_b"]])
    if len({call["session_id"] for call in calls}) != len(calls):
        raise AssertionError("session IDs must be distinct")
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(results, out, ensure_ascii=False, indent=2)
        out.write("\n")
    if not all(case["pass"] for case in results["classification"]["cases"].values()):
        return 1
    # Continuity/calibration wording requires semantic review; execution alone
    # is not a passing verdict. Keep the raw responses for inspection.
    return 0


if __name__ == "__main__":
    sys.exit(main())
