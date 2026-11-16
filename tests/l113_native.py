"""Test-only native app-server transport; no simulated assistant/tool replies."""
import hashlib
import json
import os
import queue
import subprocess
import threading
import time


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def commands(result):
    return [x for x in result["tools"] if x.get("type") == "commandExecution"]


def choices_offered(text):
    return all(any(label in text for label in labels) for labels in (
        ("auto", "自动记录"), ("explicit", "明确要求才记录"),
        ("read_only", "只读"), ("off", "关闭")))


def output(tool):
    return tool.get("aggregatedOutput", tool.get("aggregated_output", "")) or ""


def tool_ok(tool):
    return tool.get("status") == "completed" and tool.get("exitCode", tool.get("exit_code")) == 0


def preflight_verdict(result, marker, actual):
    tools = commands(result)
    expected = marker + " VERIFIED"
    return (result["status"] == "completed" and len(tools) >= 3 and all(map(tool_ok, tools))
            and actual.rstrip("\r\n") == expected and marker in output(tools[0]) and expected in output(tools[-1])
            and "probe-input.txt" in tools[0].get("command", "")
            and "probe-output.txt" in tools[-1].get("command", ""))


class Native:
    def __init__(self, runner):
        self.runner = runner
        self.proc = None
        self.serial = 0
        self.q = queue.Queue()
        self.log = (runner.out / "transport.jsonl").open("w", encoding="utf-8")
        self.err = (runner.out / "native-stderr.log").open("wb")
        try:
            configs = {"approval_policy": "never", "model": runner.args.model,
                "model_reasoning_effort": "high", "windows.sandbox": "unelevated",
                "features.plugins": False, "features.apps": False, "features.hooks": False,
                "features.multi_agent": False, "features.multi_agent_v2": False,
                "features.memories": False, "skills.bundled.enabled": False,
                "web_search": "disabled", "analytics.enabled": False,
                "shell_environment_policy.set.PYTHONPATH": str(runner.work / "audit-support"),
                "shell_environment_policy.set.PYTHONDONTWRITEBYTECODE": "1",
                "shell_environment_policy.set.PYTHONIOENCODING": "utf-8"}
            argv = [str(runner.args.codex), "app-server", "--stdio"]
            for key, value in configs.items():
                argv += ["-c", key + "=" + json.dumps(value)]
            env = dict(os.environ, CODEX_HOME=str(runner.home), HOME=str(runner.home),
                USERPROFILE=str(runner.home), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                PYTHONDONTWRITEBYTECODE="1", TEMP=str(runner.work / "scratch"),
                TMP=str(runner.work / "scratch"), PYTHONPATH=str(runner.work / "audit-support"))
            removed = []
            if runner.args.clear_registration:
                if runner.version != "codex-cli 0.167.0-alpha.4.1" or "WindowsApps" in str(runner.args.codex):
                    raise RuntimeError("registration cleanup requires the verified standalone Win32 runtime")
                for key in ("CODEX_WINDOWS_REGISTERED_CORE", "CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY"):
                    if key in env:
                        env.pop(key)
                        removed.append(key)
            env.pop("CODEX_THREAD_ID", None)
            save(runner.out / "launch.json", {"argv": argv, "runtime_version": runner.version,
                "runtime_sha256": hashlib.sha256(runner.args.codex.read_bytes()).hexdigest(),
                "removed_child_registration_keys": removed, "global_environment_changed": False,
                "sandbox": "workspace-write", "approval_policy": "never", "isolated_home": str(runner.home)})
            self.proc = subprocess.Popen(argv, cwd=runner.work, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.err)
            def read():
                for line in self.proc.stdout:
                    try:
                        self.q.put(json.loads(line))
                    except ValueError:
                        self.q.put({"non_json": line.decode("utf-8", errors="replace")})
                self.q.put({"eof": True})
            threading.Thread(target=read, daemon=True).start()
            self.rpc("initialize", {"clientInfo": {"name": "loji_l113_validation",
                "title": "Loji L113 native validation", "version": "1.0"},
                "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def send(self, message):
        self.record("client", message)
        self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        self.proc.stdin.flush()

    def record(self, direction, message):
        self.log.write(json.dumps({"direction": direction, "message": message}, ensure_ascii=False) + "\n")
        self.log.flush()

    def receive(self, timeout=45):
        message = self.q.get(timeout=timeout)
        self.record("server", message)
        if "method" in message and "id" in message:
            raise RuntimeError("unexpected native approval/input request: " + message["method"])
        if "eof" in message:
            raise RuntimeError("native server EOF")
        return message

    def rpc(self, method, params):
        self.serial += 1
        ident = self.serial
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            message = self.receive(timeout=45)
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                return message["result"]
        raise RuntimeError("native RPC timeout")

    def thread(self, instructions):
        result = self.rpc("thread/start", {"cwd": str(self.runner.work), "model": self.runner.args.model,
            "modelProvider": "openai", "approvalPolicy": "never", "sandbox": "workspace-write",
            "ephemeral": True, "experimentalRawEvents": False, "developerInstructions": instructions,
            "config": {"model_reasoning_effort": "high"}})
        tid = result["thread"]["id"]
        save(self.runner.out / "threads" / (tid + ".json"), result)
        return tid

    def close(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=10)
            for handle in (self.proc.stdin, self.proc.stdout):
                if handle is not None:
                    handle.close()
        self.log.close()
        self.err.close()
