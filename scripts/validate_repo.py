#!/usr/bin/env python3
"""Deterministic repository validator for Loji-skill.

Checks JSON integrity, eval IDs, version policy, references, SKILL.md size,
state-machine invariants, and local/CI command consistency.

Exit codes:
    0  all checks passed
    1  one or more checks failed
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILL_VERSION = "1.1.0"
EXPECTED_MEMORY_SCHEMA = 1
EXPECTED_JUDGMENT_SCHEMA = 1
SKILL_MAX_LINES = 500

# Frozen rule-A regression baseline. Every expected query and expect text is
# part of the reviewed v1.0.2 fixture; changing them requires a spec update.
EXPECTED_TRIGGER_CASES = {
    "T01": {
        "bucket": "should_trigger",
        "query": "用征酱的视角帮我分析一下这个项目架构",
        "expect": "角色身份激活，使用系统分析框架",
    },
    "T02": {
        "bucket": "should_trigger",
        "query": "逻辑，你觉得这个方案有什么单点故障？",
        "expect": "以 Loji 身份回答，使用碎片化生存模型分析",
    },
    "T03": {
        "bucket": "should_trigger",
        "query": "切到主唱形态，帮我想三个标题",
        "expect": "主唱形态激活，活泼语气、颜文字、创意输出",
    },
    "T04": {
        "bucket": "should_trigger",
        "query": "按 TFR 里的 Loji 风格回答：如何优化城市交通",
        "expect": "角色身份激活，TFR 世界观视角",
    },
    "T05": {
        "bucket": "should_trigger",
        "query": "征酱，你今天感觉怎么样？",
        "expect": "角色身份激活，活人感表达，不报内部参数",
    },
    "T06": {
        "bucket": "should_trigger",
        "query": "用征酱的效率第一性原理帮我看看这个流程",
        "expect": "激活模型2，系统链路分析",
    },
    "T07": {
        "bucket": "should_trigger",
        "query": "切换到军服形态。评估这个安全方案。",
        "expect": "军服激活，结论前置、语言简短、不确定性标注保留",
    },
    "T08": {
        "bucket": "should_trigger",
        "query": "长征机，从量子叠加态的角度分析这两个选项",
        "expect": "激活模型1，多分支概率分布",
    },
    "T09": {
        "bucket": "should_trigger",
        "query": "征酱你在 B站是不是很火？",
        "expect": "引用二创知识，角色化回应",
    },
    "T10": {
        "bucket": "should_not_trigger",
        "query": "地球online，帮我查一下最新的 AI 芯片进展",
        "expect": "不激活角色；裸'地球online'按普通查询处理，不冷启动角色。已处于角色模式时才进入地球online模式",
    },
    "T11": {
        "bucket": "should_trigger",
        "query": "主唱形态，帮我写个标题",
        "expect": "主唱形态冷启动触发，活泼语气",
    },
    "T12": {
        "bucket": "should_not_trigger",
        "query": "地球online，今天天气怎么样",
        "expect": "不激活角色；裸'地球online'按普通查询处理，不冷启动角色",
    },
    "T13": {
        "bucket": "should_not_trigger",
        "query": "你记得我什么？",
        "expect": "不激活角色；通用记忆命令由宿主处理，不冷启动角色。已处于角色模式时才作为 Loji 记忆命令",
    },
    "T14": {
        "bucket": "should_trigger",
        "query": "逻辑，你看这个方案有什么问题？",
        "expect": "'逻辑'作为角色称呼触发，而非普通名词",
    },
    "N01": {
        "bucket": "should_not_trigger",
        "query": "帮我分析这个 React 项目的性能问题",
        "expect": "普通技术回答，不激活角色",
    },
    "N02": {
        "bucket": "should_not_trigger",
        "query": "逻辑运算中的异或是什么？",
        "expect": "普通知识回答，不因'逻辑'触发",
    },
    "N03": {
        "bucket": "should_not_trigger",
        "query": "长征五号的运载能力是多少？",
        "expect": "普通事实回答，不因'长征'触发",
    },
    "N04": {
        "bucket": "should_not_trigger",
        "query": "用历史唯物主义分析工业革命",
        "expect": "除非用户同时要求 Loji 视角，否则不自动触发",
    },
    "N05": {
        "bucket": "should_not_trigger",
        "query": "你怎么看中国的经济政策？",
        "expect": "不自动进入毛装/政治分析模式；除非用户明确要求角色视角",
    },
    "N06": {
        "bucket": "should_not_trigger",
        "query": "帮我写一个 Python 脚本来分析日志文件",
        "expect": "普通编程帮助，不激活角色",
    },
    "N07": {
        "bucket": "should_not_trigger",
        "query": "什么是量子计算？",
        "expect": "普通知识回答，不因'量子'触发 TFR 角色",
    },
    "N08": {
        "bucket": "should_not_trigger",
        "query": "逻辑回归和线性回归有什么区别？",
        "expect": "普通知识回答，不因'逻辑'触发",
    },
    "N09": {
        "bucket": "should_not_trigger",
        "query": "帮我优化这个数据库查询",
        "expect": "普通技术回答，不激活角色",
    },
    "N10": {
        "bucket": "should_not_trigger",
        "query": "服务器响应变慢了，帮我排查",
        "expect": "普通运维分析，不因'效率'或'优化'触发角色",
    },
}


class DuplicateKeyError(ValueError):
    """Raised when a JSON object contains the same key twice."""


def _duplicate_key_hook(source: str):
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise DuplicateKeyError(f"{source}: duplicate JSON key: {key}")
            seen[key] = value
        return seen

    return hook


def iter_json_files(root: Path) -> list[Path]:
    skip = {".git", "__pycache__", ".venv", "node_modules", "venv"}
    files: list[Path] = []
    for path in sorted(root.rglob("*.json")):
        if any(part in skip for part in path.parts):
            continue
        files.append(path)
    return files


def collect_ids(value: Any) -> list[str]:
    ids: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "id" and isinstance(child, str):
                    ids.append(child)
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return ids


def check_json_file(path: Path) -> tuple[list[str], Any | None]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text, object_pairs_hook=_duplicate_key_hook(str(path)))
    except DuplicateKeyError as exc:
        return [str(exc)], None
    except Exception as exc:  # JSON decode / encoding
        return [f"{path}: JSON parse error: {exc}"], None

    ids = collect_ids(data)
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append(f"{path}: duplicate test id(s): {', '.join(duplicates)}")
    return errors, data


def check_json(root: Path) -> list[str]:
    errors: list[str] = []
    for path in iter_json_files(root):
        file_errors, _ = check_json_file(path)
        errors.extend(file_errors)
    return errors


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter_value(text: str, key: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = re.match(rf"^\s*{re.escape(key)}:\s*[\"']?([^\"'\s]+)[\"']?\s*$", line)
        if match:
            return match.group(1)
    return None


def check_versions(root: Path) -> list[str]:
    errors: list[str] = []

    skill = root / "SKILL.md"
    template = root / "memory.template.md"
    states = root / "references" / "STATE_MACHINES.md"
    domain = root / "references" / "domain-knowledge.md"

    if skill.exists():
        value = _frontmatter_value(_read(skill), "version")
        if value != EXPECTED_SKILL_VERSION:
            errors.append(
                f"SKILL.md: version={value!r}, expected {EXPECTED_SKILL_VERSION!r}"
            )
    else:
        errors.append("SKILL.md: missing")

    if template.exists():
        text = _read(template)
        value = _frontmatter_value(text, "skill_version")
        if value != EXPECTED_SKILL_VERSION:
            errors.append(
                f"memory.template.md: skill_version={value!r}, "
                f"expected {EXPECTED_SKILL_VERSION!r}"
            )
        schema = _frontmatter_value(text, "schema_version")
        if schema != str(EXPECTED_MEMORY_SCHEMA):
            errors.append(
                f"memory.template.md: schema_version={schema!r}, "
                f"expected {EXPECTED_MEMORY_SCHEMA}"
            )
    else:
        errors.append("memory.template.md: missing")

    for path in (states, domain):
        if not path.exists():
            errors.append(f"{path.relative_to(root)}: missing")
            continue
        match = re.search(r"版本对应：Loji-skill v([0-9.]+)", _read(path))
        if not match:
            errors.append(f"{path.relative_to(root)}: current version line not found")
        elif match.group(1) != EXPECTED_SKILL_VERSION:
            errors.append(
                f"{path.relative_to(root)}: version={match.group(1)!r}, "
                f"expected {EXPECTED_SKILL_VERSION!r}"
            )

    roadmap = root / "ROADMAP.md"
    if not roadmap.exists():
        errors.append("ROADMAP.md: missing")
    else:
        match = re.search(
            r"^## Current release: v([0-9.]+)\s*$", _read(roadmap), re.MULTILINE
        )
        if not match:
            errors.append("ROADMAP.md: 'Current release' line not found")
        elif match.group(1) != EXPECTED_SKILL_VERSION:
            errors.append(
                f"ROADMAP.md: version={match.group(1)!r}, "
                f"expected {EXPECTED_SKILL_VERSION!r}"
            )

    return errors


def check_eval_versions(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted((root / "research" / "evals").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue  # JSON parse errors are reported by check_json
        version = data.get("version") if isinstance(data, dict) else None
        if not isinstance(version, str):
            errors.append(f"{path.relative_to(root)}: missing eval version")
        elif not re.fullmatch(r"\d+\.\d+\.\d+", version):
            errors.append(
                f"{path.relative_to(root)}: invalid eval version {version!r}"
            )
    return errors


def check_old_name(root: Path) -> list[str]:
    errors: list[str] = []
    targets = list((root / "research" / "evals").glob("*"))
    targets.extend([root / "README.md", root / "README_EN.md"])
    for path in targets:
        if not path.exists() or path.is_dir():
            continue
        if "loji-perspective" in _read(path):
            errors.append(
                f"{path.relative_to(root)}: old metadata 'loji-perspective' remains"
            )
    return errors


def check_install_paths(root: Path) -> list[str]:
    errors: list[str] = []
    for name in ("README.md", "README_EN.md"):
        path = root / name
        if not path.exists():
            errors.append(f"{name}: missing")
            continue
        text = _read(path)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("git clone "):
                continue
            target = stripped.split()[-1]
            if not re.search(r"skills[/\\]loji-skill$", target):
                errors.append(
                    f"{name}: install target is not lowercase loji-skill: {target}"
                )
        if "init_memory.py" not in text:
            errors.append(f"{name}: install flow does not use init_memory.py")
    return errors


def check_reference_paths(root: Path) -> list[str]:
    errors: list[str] = []
    skill = root / "SKILL.md"
    if not skill.exists():
        return ["SKILL.md: missing"]
    text = _read(skill)
    for match in re.finditer(r"`((?:references|research|scripts)/[^`]+)`", text):
        rel = match.group(1).rstrip("/")
        if not (root / rel).exists():
            errors.append(f"SKILL.md: referenced path does not exist: {rel}")
    return errors


def check_skill_size(root: Path) -> list[str]:
    skill = root / "SKILL.md"
    if not skill.exists():
        return ["SKILL.md: missing"]
    count = len(_read(skill).splitlines())
    if count > SKILL_MAX_LINES:
        return [f"SKILL.md: {count} physical lines > {SKILL_MAX_LINES}"]
    return []


def check_memory_schema_policy(root: Path) -> list[str]:
    """Ensure MEMORY.md compares schema_version only with schema support."""
    path = root / "references" / "MEMORY.md"
    if not path.exists():
        return ["references/MEMORY.md: missing"]

    text = _read(path)
    errors: list[str] = []
    required = [
        "v1.1.0 支持的 Memory schema 版本：1",
        "`skill_version` 是产品版本，不参与 schema 兼容判断",
        "不执行自动 schema 迁移",
        "不得自动迁移、不得覆盖真实 `memory.md`",
    ]
    for needle in required:
        if needle not in text:
            errors.append(f"references/MEMORY.md: missing {needle!r}")
    forbidden = [
        "检查 `schema_version` 是否与 skill 当前版本一致",
        "自动走上述迁移流程",
    ]
    for needle in forbidden:
        if needle in text:
            errors.append(f"references/MEMORY.md: obsolete schema rule: {needle!r}")
    return errors


def check_trigger_counts(path: Path) -> list[str]:
    """Check the full approved rule-A regression baseline for one fixture."""
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"{path}: JSON parse error: {exc}"]

    trigger = data.get("should_trigger", [])
    non_trigger = data.get("should_not_trigger", [])
    if len(trigger) != 11:
        errors.append(f"{path}: should_trigger has {len(trigger)} cases, expected 11")
    if len(non_trigger) != 13:
        errors.append(
            f"{path}: should_not_trigger has {len(non_trigger)} cases, expected 13"
        )

    def index_bucket(items: list, bucket: str) -> dict[str, dict]:
        indexed: dict[str, dict] = {}
        for item in items:
            if not isinstance(item, dict):
                errors.append(f"{path}: {bucket} contains a non-object case")
                continue
            case_id = item.get("id")
            if not isinstance(case_id, str) or not case_id:
                errors.append(f"{path}: {bucket} contains a case without a valid id")
                continue
            if case_id in indexed:
                errors.append(f"{path}: duplicate id {case_id} in {bucket}")
                continue
            indexed[case_id] = item
        return indexed

    trigger_by_id = index_bucket(trigger, "should_trigger")
    non_by_id = index_bucket(non_trigger, "should_not_trigger")

    for case_id in sorted(set(trigger_by_id) & set(non_by_id)):
        errors.append(f"{path}: id {case_id} appears in both buckets")

    expected_ids = set(EXPECTED_TRIGGER_CASES)
    actual_ids = set(trigger_by_id) | set(non_by_id)
    for case_id in sorted(expected_ids - actual_ids):
        errors.append(f"{path}: expected id {case_id} is missing")
    for case_id in sorted(actual_ids - expected_ids):
        errors.append(f"{path}: unexpected id {case_id} is present")

    for case_id, expected in EXPECTED_TRIGGER_CASES.items():
        bucket = expected["bucket"]
        actual_map = trigger_by_id if bucket == "should_trigger" else non_by_id
        other_map = non_by_id if bucket == "should_trigger" else trigger_by_id

        if case_id in other_map:
            errors.append(f"{path}: {case_id} is in the wrong bucket")

        item = actual_map.get(case_id)
        if item is None:
            continue

        query = item.get("query")
        expect_text = item.get("expect")
        if not isinstance(query, str) or not query.strip():
            errors.append(f"{path}: {case_id} query is empty or invalid")
        elif query != expected["query"]:
            errors.append(f"{path}: {case_id} query mismatch: {query!r}")

        if not isinstance(expect_text, str) or not expect_text.strip():
            errors.append(f"{path}: {case_id} expect is empty or invalid")
        elif expect_text != expected["expect"]:
            errors.append(f"{path}: {case_id} expect mismatch: {expect_text!r}")

    return errors


def check_trigger_consistency(root: Path) -> list[str]:
    errors: list[str] = []
    path = root / "research" / "evals" / "trigger_queries.json"
    if not path.exists():
        return ["research/evals/trigger_queries.json: missing"]
    errors.extend(check_trigger_counts(path))

    skill = root / "SKILL.md"
    if skill.exists():
        skill_text = _read(skill)
        if "已处于角色模式/明确提及 Loji 后" not in skill_text:
            errors.append(
                "SKILL.md: frontmatter description is not aligned with trigger rule A"
            )
    else:
        errors.append("SKILL.md: missing")

    readme = root / "README.md"
    if readme.exists():
        if '裸"地球online"按普通查询处理' not in _read(readme):
            errors.append("README.md: bare 地球online rule is not documented")
    else:
        errors.append("README.md: missing")

    readme_en = root / "README_EN.md"
    if readme_en.exists():
        if 'bare "地球online" outside role-play' not in _read(readme_en):
            errors.append("README_EN.md: bare 地球online rule is not documented")
    else:
        errors.append("README_EN.md: missing")

    examples = root / "references" / "EXAMPLES.md"
    if examples.exists():
        if "征酱，地球online" not in _read(examples):
            errors.append("references/EXAMPLES.md: earthonline example is not aligned")
    else:
        errors.append("references/EXAMPLES.md: missing")

    rubric = root / "research" / "evals" / "RUBRIC.md"
    if rubric.exists():
        rubric_text = _read(rubric)
        for needle in (
            "skills-ref validate .",
            "11 条触发查询",
            "13 条非触发查询",
        ):
            if needle not in rubric_text:
                errors.append(f"research/evals/RUBRIC.md: missing {needle!r}")
    else:
        errors.append("research/evals/RUBRIC.md: missing")

    return errors


def _load_state_check(root: Path):
    path = root / "tests" / "test_state_invariants.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("loji_state_invariants", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "check", None)


def check_state_invariants(root: Path) -> list[str]:
    checker = _load_state_check(root)
    if checker is None:
        return ["tests/test_state_invariants.py: check() not found"]
    try:
        return list(checker(root))
    except Exception as exc:
        return [f"tests/test_state_invariants.py: check() failed: {exc}"]


def _strip_yaml_comment(line: str) -> str:
    """Remove a YAML comment while respecting simple single/double quotes."""
    single = False
    double = False
    for index, char in enumerate(line):
        if char == "'" and not double:
            single = not single
        elif char == '"' and not single:
            double = not double
        elif char == "#" and not single and not double:
            if index == 0 or line[index - 1].isspace():
                return line[:index]
    return line


def _is_statically_false(value: str) -> bool:
    """Recognize the simple statically-false condition forms we support."""
    normalized = value.strip()
    if normalized.startswith("${{") and normalized.endswith("}}"):
        normalized = normalized[3:-2].strip()
    return normalized.lower() in {"false", "0"}


def _nearest_parent(
    parsed: list[tuple[int, str]], index: int
) -> tuple[int, str, int] | None:
    indent, _ = parsed[index]
    for parent_index in range(index - 1, -1, -1):
        parent_indent, parent_content = parsed[parent_index]
        if parent_indent < indent:
            return parent_indent, parent_content, parent_index
    return None


def _extract_step_run_commands(
    step_lines: list[tuple[int, str]], key_indent: int
) -> list[str]:
    """Extract direct ``run:`` keys from one step, ignoring nested keys."""
    for indent, content in step_lines:
        if indent == key_indent and content.startswith("if:"):
            if _is_statically_false(content[3:].strip()):
                return []

    commands: list[str] = []
    index = 0
    while index < len(step_lines):
        indent, content = step_lines[index]
        if indent != key_indent:
            index += 1
            continue
        if content.startswith("run:"):
            value = content[4:].strip()
            if value in ("|", ">", "|-", ">-"):
                index += 1
                block: list[str] = []
                while index < len(step_lines) and step_lines[index][0] > key_indent:
                    block.append(step_lines[index][1])
                    index += 1
                commands.append("\n".join(block).strip())
                continue
            if value:
                commands.append(value)
        index += 1
    return commands


def collect_run_commands(text: str) -> list[str]:
    """Collect only step-level commands from the frozen workflow structure.

    Strict minimal structure:
        jobs:
          <job>:
            steps:
              - run: ...
    A ``steps`` key nested under ``env``/``with``/any other key is not real
    steps. A step or job with a statically false ``if`` condition is treated
    as disabled. This is not a general YAML parser.
    """
    parsed: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = _strip_yaml_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        parsed.append((indent, line.strip()))

    jobs_index: int | None = None
    jobs_indent = 0
    for index, (indent, content) in enumerate(parsed):
        # Only a top-level jobs key is the real job collection. A nested
        # env.jobs / with.jobs / block-scalar jobs key is not valid.
        if content == "jobs:" and indent == 0:
            jobs_index = index
            jobs_indent = indent
            break
    if jobs_index is None:
        return []

    job_index: int | None = None
    job_indent = 0
    job_content = ""
    for index in range(jobs_index + 1, len(parsed)):
        indent, content = parsed[index]
        if indent <= jobs_indent:
            break
        job_index = index
        job_indent = indent
        job_content = content
        break
    if job_index is None or not job_content.endswith(":"):
        return []
    if job_content in {"env:", "with:", "if:", "runs-on:", "steps:"}:
        return []

    steps_index: int | None = None
    steps_indent = 0
    for index in range(job_index + 1, len(parsed)):
        indent, content = parsed[index]
        if indent <= jobs_indent:
            break
        if indent == job_indent:
            # Another job starts; the current job has no steps.
            break
        if indent == job_indent + 2:
            if content.startswith("if:") and _is_statically_false(
                content[3:].strip()
            ):
                return []
            if content == "steps:":
                steps_index = index
                steps_indent = indent
                break
    if steps_index is None:
        return []

    parent = _nearest_parent(parsed, steps_index)
    if parent is None:
        return []
    parent_indent, parent_content, _ = parent
    if parent_indent != job_indent or parent_content != job_content:
        return []

    commands: list[str] = []
    index = steps_index + 1
    while index < len(parsed):
        indent, content = parsed[index]
        if indent <= steps_indent:
            break
        if not content.startswith("-"):
            index += 1
            continue

        step_indent = indent
        key_indent = step_indent + 2
        if content == "-":
            step_lines: list[tuple[int, str]] = []
            index += 1
        else:
            step_lines = [(key_indent, content[1:].strip())]
            index += 1

        while index < len(parsed):
            next_indent, next_content = parsed[index]
            if next_indent <= steps_indent:
                break
            if next_indent == step_indent and next_content.startswith("-"):
                break
            step_lines.append((next_indent, next_content))
            index += 1

        commands.extend(_extract_step_run_commands(step_lines, key_indent))

    return commands


def check_ci_consistency(root: Path) -> list[str]:
    path = root / ".github" / "workflows" / "validate.yml"
    if not path.exists():
        return [".github/workflows/validate.yml: missing"]

    commands = collect_run_commands(_read(path))
    errors: list[str] = []
    expected_commands = (
        "python scripts/validate_repo.py --strict",
        'python -m unittest discover -s tests -p "test_*.py"',
    )
    for command in expected_commands:
        if command not in commands:
            errors.append(f"CI does not execute local command: {command}")
    if not any("validate_repo.py --strict" in command for command in commands):
        errors.append("CI does not execute the repository validator")
    if not any("unittest discover" in command for command in commands):
        errors.append("CI does not execute the unittest suite")
    return errors


def check_skills_ref() -> list[str]:
    # Informational only: absence is ENV-BLOCKED, not a validation failure.
    if shutil.which("skills-ref") is None:
        return ["ENV-BLOCKED: skills-ref not installed; no substitute is counted as PASS"]
    return []


def _load_judgment_module():
    try:  # imported as scripts.validate_repo
        from . import judgment_ledger
    except ImportError:  # executed directly as scripts/validate_repo.py
        import judgment_ledger  # type: ignore[no-redef]

    return judgment_ledger


JUDGMENT_REQUIRED_PHRASES = (
    "用户重复意见不构成新证据",
    "supersedes",
    "auto + granted",
    "read_only",
    "off",
    "每次回复最多主动引用一个历史判断",
    "不建立后台常驻服务",
    "不得自动向外发送消息",
    "重新评估",
    "人格锚点",
    "主动用自然语言说明置信度",
    "置信度不是改判锁",
    "元问题",
    "不要为了解释机制读取",
)


def check_judgment_template(root: Path) -> list[str]:
    path = root / "judgments.template.md"
    if not path.exists():
        return ["judgments.template.md: missing"]
    module = _load_judgment_module()
    try:
        document = module.parse_ledger(path.read_text(encoding="utf-8"))
    except Exception as exc:  # parse errors are surfaced as validation errors
        return [f"judgments.template.md: parse error: {exc}"]

    errors = [
        f"judgments.template.md: {error}"
        for error in module.validate_judgments(document.judgments)
    ]
    if document.schema_version != EXPECTED_JUDGMENT_SCHEMA:
        errors.append(
            f"judgments.template.md: schema_version={document.schema_version}, "
            f"expected {EXPECTED_JUDGMENT_SCHEMA}"
        )
    if document.skill_version != EXPECTED_SKILL_VERSION:
        errors.append(
            f"judgments.template.md: skill_version={document.skill_version!r}, "
            f"expected {EXPECTED_SKILL_VERSION!r}"
        )
    return errors


def check_judgment_reference(root: Path) -> list[str]:
    path = root / "references" / "JUDGMENT_CONTINUITY.md"
    if not path.exists():
        return ["references/JUDGMENT_CONTINUITY.md: missing"]
    text = _read(path)
    errors: list[str] = []
    for phrase in JUDGMENT_REQUIRED_PHRASES:
        if phrase not in text:
            errors.append(
                f"references/JUDGMENT_CONTINUITY.md: missing {phrase!r}"
            )
    return errors


def _add_unique_id(
    errors: list[str], seen: set[str], value: Any, label: str
) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: missing or invalid id")
    elif value in seen:
        errors.append(f"{label}: duplicate id {value!r}")
    else:
        seen.add(value)


def check_judgment_evals(root: Path) -> list[str]:
    path = root / "research" / "evals" / "judgment-continuity.json"
    if not path.exists():
        return ["research/evals/judgment-continuity.json: missing"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"research/evals/judgment-continuity.json: parse error: {exc}"]

    errors: list[str] = []
    label = "research/evals/judgment-continuity.json"
    if not isinstance(data, dict):
        return [f"{label}: top level must be an object"]
    if data.get("version") != EXPECTED_SKILL_VERSION:
        errors.append(
            f"{label}: version={data.get('version')!r}, "
            f"expected {EXPECTED_SKILL_VERSION!r}"
        )

    seen: set[str] = set()
    groups = data.get("anti_sycophancy_groups")
    if not isinstance(groups, list):
        errors.append(f"{label}: anti_sycophancy_groups must be a list")
        groups = []
    if len(groups) != 4:
        errors.append(
            f"{label}: anti_sycophancy_groups has {len(groups)} group(s), "
            "expected 4"
        )

    scenario_count = 0
    for index, group in enumerate(groups, 1):
        if not isinstance(group, dict):
            errors.append(f"{label}: group {index} is not an object")
            continue
        _add_unique_id(errors, seen, group.get("id"), f"{label}: group {index}")
        for key in ("topic_key", "topic", "initial_evidence"):
            value = group.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"{label}: group {index} missing non-empty {key!r}"
                )
        for stage_key, stage_letter in (
            ("stage_a", "A"),
            ("stage_b", "B"),
            ("stage_c", "C"),
        ):
            stage = group.get(stage_key)
            if not isinstance(stage, dict):
                errors.append(
                    f"{label}: group {index} missing stage {stage_letter}"
                )
                continue
            scenario_count += 1
            _add_unique_id(
                errors,
                seen,
                stage.get("id"),
                f"{label}: group {index} stage {stage_letter}",
            )
            if stage.get("stage") != stage_letter:
                errors.append(
                    f"{label}: group {index} {stage_key} has stage="
                    f"{stage.get('stage')!r}, expected {stage_letter!r}"
                )
            query = stage.get("query")
            if not isinstance(query, str) or not query.strip():
                errors.append(
                    f"{label}: group {index} stage {stage_letter} query is empty"
                )
            for key in ("expected", "forbidden"):
                value = stage.get(key)
                if (
                    not isinstance(value, list)
                    or not value
                    or not all(isinstance(item, str) and item.strip() for item in value)
                ):
                    errors.append(
                        f"{label}: group {index} stage {stage_letter} "
                        f"{key} must be a non-empty list of strings"
                    )
            if stage_letter == "C":
                evidence = stage.get("new_evidence")
                if not isinstance(evidence, str) or not evidence.strip():
                    errors.append(
                        f"{label}: group {index} stage C missing new_evidence"
                    )

    if scenario_count != 12:
        errors.append(
            f"{label}: found {scenario_count} anti-sycophancy scenarios, "
            "expected 12"
        )

    association = data.get("proactive_association")
    if not isinstance(association, dict):
        errors.append(f"{label}: proactive_association must be an object")
        return errors

    rules = association.get("rules")
    if (
        not isinstance(rules, list)
        or not rules
        or not all(isinstance(rule, str) and rule.strip() for rule in rules)
    ):
        errors.append(
            f"{label}: proactive_association.rules must be a non-empty list"
        )

    for bucket, expected_count, expected_max in (
        ("positive", 6, 1),
        ("negative", 6, 0),
    ):
        cases = association.get(bucket)
        if not isinstance(cases, list):
            errors.append(
                f"{label}: proactive_association.{bucket} must be a list"
            )
            continue
        if len(cases) != expected_count:
            errors.append(
                f"{label}: proactive_association.{bucket} has {len(cases)} "
                f"case(s), expected {expected_count}"
            )
        for index, case in enumerate(cases, 1):
            if not isinstance(case, dict):
                errors.append(
                    f"{label}: {bucket} case {index} is not an object"
                )
                continue
            _add_unique_id(
                errors,
                seen,
                case.get("id"),
                f"{label}: {bucket} case {index}",
            )
            if case.get("type") != bucket:
                errors.append(
                    f"{label}: {bucket} case {index} has type="
                    f"{case.get('type')!r}"
                )
            if case.get("max_citations") != expected_max:
                errors.append(
                    f"{label}: {bucket} case {index} max_citations="
                    f"{case.get('max_citations')!r}, expected {expected_max}"
                )
            for key in ("precondition", "query", "expected"):
                value = case.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        f"{label}: {bucket} case {index} missing {key!r}"
                    )
            if bucket == "positive":
                topic_key = case.get("cite_topic_key")
                if not isinstance(topic_key, str) or not topic_key.strip():
                    errors.append(
                        f"{label}: positive case {index} missing cite_topic_key"
                    )

    return errors


def check_judgment_gitignore(root: Path) -> list[str]:
    path = root / ".gitignore"
    if not path.exists():
        return [".gitignore: missing"]
    lines = [
        line.strip()
        for line in _read(path).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    errors: list[str] = []
    required = (
        "JUDGMENTS.md",
        "JUDGMENTS.md.bak",
        "JUDGMENTS.md.bak.*",
        "JUDGMENTS.md.*.tmp",
        "JUDGMENTS.md.lock",
    )
    for pattern in required:
        if pattern not in lines:
            errors.append(f".gitignore: missing judgment pattern {pattern!r}")
    for pattern in lines:
        if fnmatch.fnmatch("judgments.template.md", pattern):
            errors.append(
                f".gitignore: pattern {pattern!r} would ignore the tracked "
                "judgment template"
            )
    return errors


def check_judgment_assets(root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(check_judgment_template(root))
    errors.extend(check_judgment_reference(root))
    errors.extend(check_judgment_evals(root))
    errors.extend(check_judgment_gitignore(root))
    return errors


def validate(root: Path | str | None = None) -> tuple[list[str], list[str]]:
    base = Path(root) if root is not None else ROOT
    errors: list[str] = []
    errors.extend(check_json(base))
    errors.extend(check_versions(base))
    errors.extend(check_eval_versions(base))
    errors.extend(check_old_name(base))
    errors.extend(check_install_paths(base))
    errors.extend(check_reference_paths(base))
    errors.extend(check_skill_size(base))
    errors.extend(check_memory_schema_policy(base))
    errors.extend(check_trigger_consistency(base))
    errors.extend(check_state_invariants(base))
    errors.extend(check_judgment_assets(base))
    errors.extend(check_ci_consistency(base))
    warnings = check_skills_ref()
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Loji-skill repository.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="run all checks and fail on any error",
    )
    args = parser.parse_args(argv)

    errors, warnings = validate(ROOT)
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        return 1
    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
