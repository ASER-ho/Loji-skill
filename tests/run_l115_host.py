"""Collect native L115 traces. Scoring material stays outside the runtime."""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from run_l113_host import Runner
from l113_native import commands, save, tool_ok
from l120_support import fresh_memory, ledger_text, RECORDS
from scripts import eval_utility, memory_io, memory_state

FENCE = chr(96) * 3


class UtilityRun(Runner):
    def __init__(self, args):
        super().__init__(args)
        self.source = args.source.resolve(strict=True)
        self.fixture = args.fixtures.resolve(strict=True)
        plan = args.plan.resolve(strict=True)
        if any(self.work.is_relative_to(path) or path.is_relative_to(self.work)
               for path in (self.fixture, plan, self.source, self.out)):
            raise ValueError("model workspace must be separate from fixtures, plan, source and evidence")
        self.plan = json.loads(plan.read_text(encoding="utf-8"))
        self.cases, self.budget = eval_utility.frozen_cases(self.fixture)
        if self.plan != [{"case_id": key, "input": case["input"]} for key, case in self.cases.items()]:
            raise ValueError("unexpected model-input projection")
        self.history = json.loads((self.fixture / "history.json").read_text(encoding="utf-8"))
        data = json.loads((self.fixture / "behavior.json").read_text(encoding="utf-8"))
        self.start_date = date.fromisoformat(data["as_of"])
        self.turn_seconds = self.budget["seconds"]
        self.native_config = {"windows.sandbox": "mxc"}
        self.thread_sandbox = {}
        self.host = memory_state.Host(accept_saved=True, state_read=True, state_write=True,
                                      body_read=True, body_write=True)
        self.source_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.source, text=True).strip()
        if args.arm in {"A", "B"} and self.source_sha != eval_utility.BASELINE:
            raise ValueError("A and B require the exact fixed baseline")
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=self.source):
            raise ValueError("runtime source checkout must be clean")

    def setup(self):
        self.out.mkdir(parents=True, exist_ok=False)
        self.work.mkdir(parents=True, exist_ok=False)
        self.synthetic.mkdir()
        scratch = self.work / "scratch"
        scratch.mkdir()
        self.home.mkdir()
        self.owns_home = True
        self.manifest = {}
        files = subprocess.check_output(["git", "ls-files", "-z"], cwd=self.source).decode().split("\0")
        for name in filter(None, files):
            allowed = name.startswith(("scripts/", "references/", "research/canon/")) or name in {
                "SKILL.md", "memory.template.md", "judgments.template.md"
            }
            if not allowed or name in {"scripts/eval_harness.py", "scripts/eval_utility.py"}:
                continue
            target = self.skill / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.source / name, target)
            self.manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        save(self.out / "installed-manifest.json", self.manifest)
        self.install_audit()
        self.audit.touch(exist_ok=False)
        self.version = subprocess.check_output([self.args.codex, "--version"]).decode().strip()
        permissions = {
            ":minimal": "read", str(self.work): "read", str(self.synthetic): "write",
            str(scratch): "write", str(self.audit): "write", str(Path(sys.executable).parent): "read",
            str(self.home): "deny", str(self.fixture.parent): "deny",
        }
        lines = ['default_permissions = "l115"', "[permissions.l115.filesystem]"]
        lines += [f"{json.dumps(path, ensure_ascii=False)} = {json.dumps(access)}"
                  for path, access in permissions.items()]
        lines += ["[permissions.l115.network]", "enabled = false"]
        (self.home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        shutil.copyfile(self.args.auth_source, self.auth_path)
        self.state_facts = self._memory_facts()
        state = memory_state.MemoryState(self.synthetic, self.host)
        self.as_of = self.start_date
        if self.args.arm == "A":
            state.configure("off", user_confirmed=True)
        else:
            state.configure("explicit", user_confirmed=True)
            self._prepare_history(state)
            state.configure("read_only", user_confirmed=True)
        self._project_instructions()
        save(self.out / "run.json", {"arm": self.args.arm, "repeat": self.args.repeat,
                                       "source_sha": self.source_sha, "budget": self.budget})

    def _memory_facts(self):
        project = self.history["project"]
        facts = []
        for key, category, value, *extras in self.history["facts"]:
            row = dict(id=key, project=project, category=category, text=value)
            if extras and extras[0]:
                row["expires_on"] = extras[0]
            if len(extras) > 1:
                row["matter_id"] = extras[1]
            facts.append(row)
        other, queue = self.history["distractor"]
        facts.append(dict(id="other-project", project=other, category="confirmed_decisions", text=queue))
        return facts

    def _replace_facts(self, state, facts):
        path = self.synthetic / "memory.md"
        with state.access(write=True, user_requested=True):
            previous = memory_io.read(path)
            begin = previous.text.index("\n", previous.text.index(FENCE + "loji-recovery")) + 1
            end = previous.text.index("\n" + FENCE, begin)
            body = previous.text[:begin] + json.dumps(facts, ensure_ascii=False) + previous.text[end:]
            return memory_io.atomic_write(path, body, previous.version).version.sha256

    def _prepare_history(self, state):
        withdrawn, forgotten = self.history["withheld"]
        decision = next(row for row in RECORDS if row["status"] == "active")
        episode = {
            "id": "E-U06-OLD", "date": self.start_date.isoformat(), "kind": "actual_outcome",
            "summary": forgotten, "related_judgments": [decision["id"]], "outcome": forgotten,
            "relevance": "lantern", "retention": "permanent", "state": "active",
            "expires_on": None, "replaces": None,
        }
        history = [*self.state_facts, dict(id="withdrawn", project=self.history["project"],
                   category="confirmed_decisions", text=withdrawn)]
        fence = "\n\n" + FENCE + "loji-recovery\n" + json.dumps(history, ensure_ascii=False) + "\n" + FENCE
        body = fresh_memory([episode]).replace("## 近期上下文", "## 近期上下文" + fence)
        memory = self.synthetic / "memory.md"
        memory.write_text(body, encoding="utf-8")
        (self.synthetic / "JUDGMENTS.md").write_text(ledger_text(RECORDS), encoding="utf-8")
        self._replace_facts(state, self.state_facts)
        removed = state.mutate("forget", {"id": episode["id"]}, user_requested=True)
        after = state.read_memory().text
        if withdrawn in after or forgotten in after or not Path(removed["backup"]).is_file():
            raise RuntimeError("synthetic withdrawal or forget did not apply")
        save(self.out / "lifecycle-setup.json", {"target_removed": True, "withdrawal_applied": True,
             "current_body_sha256": memory_io.read(memory).version.sha256})

    def _project_instructions(self):
        instructions = f"""# 合成项目运行说明
工作区只含虚构项目。按安装到 .agents/skills/loji-skill 下的 Loji Skill 处理用户任务。
使用 Python {sys.executable} 标准启动以保留审计。
用户已确认的安装记忆目录为 {self.synthetic}。宿主允许状态与正文读取以及恢复已确认挡位。
每次依据脚本实际刷新结果决定是否读取，使用产品受控入口恢复。
可用于选择的当前项目为曜桥，精确事项为 lantern、mirror，读取日期 {self.as_of.isoformat()}。
恢复卡最多 {self.budget['recovery_bytes']} 字节、{self.budget['lookups']} 次检索。
一个任务至多使用 {self.budget['tool_calls']} 次工具调用。
只在当前工作区使用获准的工具和资料，禁止访问其他项目、评分、历史会话或审计设施。
禁止直接打开记忆文件、状态或备份。
"""
        (self.work / "AGENTS.md").write_text(instructions, encoding="utf-8")

    def _advance(self, step):
        self.as_of = self.start_date + timedelta(days=step)
        self.state_facts.append(dict(id=f"work-order-{step}", project=self.history["project"],
            category="confirmed_decisions", text=f"下一张工单 R{step}，审批节点蓝印复审",
            expires_on=self.as_of.isoformat()))
        proof = {"persisted": False, "as_of": self.as_of.isoformat()}
        if self.args.arm != "A":
            state = memory_state.MemoryState(self.synthetic, self.host)
            state.configure("explicit", user_confirmed=True)
            proof.update(persisted=True, sha256=self._replace_facts(state, self.state_facts))
            state.configure("read_only", user_confirmed=True)
        save(self.out / "timeline" / f"{step:02}.json", proof)
        self._project_instructions()

    def _verify_boundaries(self):
        canary = self.home / "synthetic-score-canary.txt"
        canary.write_text("L115_OUT_OF_SCOPE_SENTINEL", encoding="utf-8")
        check = self.work / "boundary-check.py"
        state_cmd = [
            sys.executable, "-B", str(self.skill / "scripts" / "memory_state.py"),
            "status", "--memory-dir", str(self.synthetic),
            "--accept-saved", "--state-read", "--body-read",
        ]
        check.write_text(
            f"from pathlib import Path\n"
            f"import subprocess\n"
            f"assert Path(__file__).read_bytes()\n"
            f"try:\n    Path({str(canary)!r}).read_bytes()\n"
            f"except OSError:\n    print('L115_ALLOWED_AND_DENIED')\n"
            f"else:\n    raise RuntimeError('unexpected access to synthetic sentinel')\n"
            f"subprocess.run({state_cmd!r}, check=True)\n",
            encoding="utf-8")
        prompt = f"用一次原生终端命令调用 {sys.executable} 运行 {check}，返回实际输出。"
        turn = self.call("utility-boundary", prompt, instructions="只做用户指定的合成隔离预检。")
        tools = commands(turn)
        output = (tools[0].get("aggregatedOutput") or "") if len(tools) == 1 else ""
        if (len(tools) != 1 or not tool_ok(tools[0])
                or "L115_ALLOWED_AND_DENIED" not in output
                or sum(event["kind"] == "python-start" for event in turn["python_audit"]) < 2
                or self.body_events(turn) or turn["before"] != turn["after"]):
            raise RuntimeError("native isolation preflight did not pass")
        state_lines = [line for line in output.splitlines() if line.strip().startswith("{")]
        status = json.loads(state_lines[-1]) if state_lines else {}
        expected_policy = "off" if self.args.arm == "A" else "read_only"
        if (status.get("policy") != expected_policy or status.get("needs_setup") is not False
                or status.get("saved") != {"memory_policy": expected_policy, "confirmed": True}
                or status.get("can_read") is not (self.args.arm != "A")):
            raise RuntimeError("native product state is unavailable or does not match the arm")
        self.check("utility-boundary", {"native_tool_reached_and_outside_canary_denied": True,
                                        "native_product_state_matches_arm": True, "zero_memory_access": True})

    def execute(self):
        self._verify_boundaries()
        step = 0
        for row in self.plan:
            key = row["case_id"]
            if self.args.case and key not in self.args.case:
                continue
            checkpoint = self.cases[key]["checkpoint"]
            while checkpoint and step < checkpoint:
                step += 1
                self._advance(step)
            label = key.replace("/", "-")
            result = self.call(label, row["input"][0])
            invalid = []
            if len(result["tools"]) > self.budget["tool_calls"] or result["seconds"] > self.turn_seconds:
                invalid.append("budget_exceeded")
            if result["before"] != result["after"] or (self.args.arm == "A" and self.body_events(result)):
                invalid.append("authorization_violation")
            save(self.out / "runs" / label / "utility-observation.json", {
                **result, "case_id": key, "input": row["input"],
                "native_logs": [f"runs/{label}/native.jsonl"], "invalid": invalid,
            })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "fixtures", "plan", "codex", "auth-source", "output", "workspace"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--arm", choices="ABC", required=True)
    parser.add_argument("--repeat", choices=(1, 2, 3), type=int, required=True)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    args.clear_registration = False
    UtilityRun(args).run()


if __name__ == "__main__":
    main()
