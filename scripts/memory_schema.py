"""Loji's local Markdown format. Legacy sections are opaque, lossless text."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

SKILL_VERSION = "1.1.1"
SECTIONS = (
    "用户明确要求记住", "稳定偏好", "近期上下文", "用户纠正过的内容",
    "Loji 的观察", "归档", "不应记录",
)
EPISODES = "共同经历"
CALIBRATION = "协作校准"
V2_SECTIONS = (*SECTIONS[:5], EPISODES, CALIBRATION, *SECTIONS[5:])
KINDS = ("important_joint_decision", "actual_outcome", "correction_or_learning")
STATES = ("active", "archived", "corrected", "deprecated", "unresolved")
MAX_ACTIVE = 50
KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
JUDGMENT_ID = re.compile(r"J-[A-Za-z0-9._-]{1,62}\Z")
EPISODE_ID = re.compile(r"E-[A-Za-z0-9._-]{1,62}\Z")
FIELDS = {
    "id", "date", "kind", "summary", "related_judgments", "outcome",
    "relevance", "retention", "state", "expires_on", "replaces",
}


class FormatError(ValueError):
    """Unsupported, malformed or inconsistent local state."""


def require(condition: Any, message: str) -> None:
    if not condition:
        raise FormatError(message)


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def decode_json(payload: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_):
        raise FormatError("nonfinite JSON number")

    try:
        return json.loads(payload, object_pairs_hook=pairs, parse_constant=reject_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise FormatError("invalid JSON") from exc


def validate_episodes(episodes: Any) -> None:
    require(isinstance(episodes, list), "episodes must be an array")
    by_id = {}
    active = 0
    for entry in episodes:
        require(isinstance(entry, dict) and entry.keys() == FIELDS, "invalid episode fields")
        key = entry["id"]
        require(isinstance(key, str) and EPISODE_ID.fullmatch(key), "invalid Episode ID")
        require(key not in by_id, "duplicate Episode ID")
        by_id[key] = entry
        require(valid_date(entry["date"]), "invalid Episode date")
        require(entry["kind"] in KINDS and entry["state"] in STATES, "invalid Episode kind/state")
        require(nonempty(entry["summary"]) and nonempty(entry["relevance"]), "empty Episode text")
        refs = entry["related_judgments"]
        require(isinstance(refs, list) and refs and all(
            isinstance(ref, str) and JUDGMENT_ID.fullmatch(ref) for ref in refs
        ) and len(refs) == len(set(refs)), "Episode needs distinct Judgment IDs")
        require(entry["outcome"] is None or nonempty(entry["outcome"]), "invalid Episode outcome")
        require(entry["kind"] != "actual_outcome" or entry["outcome"] is not None,
                "actual outcome requires evidence")
        require(entry["retention"] in ("permanent", "project"), "invalid Episode retention")
        expiry = entry["expires_on"]
        require(expiry is None or (
            entry["retention"] == "project" and valid_date(expiry) and expiry >= entry["date"]
        ), "invalid Episode expiry")
        active += entry["state"] in ("active", "unresolved")
    require(active <= MAX_ACTIVE, "Episode capacity reached; archive explicitly")
    replaced_ids = set()
    for entry in episodes:
        replaces = entry["replaces"]
        if replaces is None:
            continue
        require(isinstance(replaces, str) and replaces != entry["id"] and replaces in by_id,
                "invalid Episode correction reference")
        old = by_id[replaces]
        require(replaces not in replaced_ids and entry["kind"] == "correction_or_learning" and
                old["state"] == "corrected" and entry["date"] >= old["date"] and
                entry["relevance"] == old["relevance"], "invalid Episode correction history")
        replaced_ids.add(replaces)
    # Equal dates are valid, so use graph traversal rather than dates to reject cycles.
    resolved = set()
    for entry in episodes:
        seen = set()
        key = entry["id"]
        while key is not None and key not in resolved:
            require(key not in seen, "cyclic Episode correction history")
            seen.add(key)
            key = by_id[key]["replaces"]
        resolved.update(seen)


def stats(n: int, hits: int, misses: int) -> dict:
    require(all(type(x) is int and x >= 0 for x in (n, hits, misses)) and n == hits + misses,
            "invalid calibration counts")
    mode = "normal"
    if n >= 5:
        if 5 * hits >= 4 * n:
            mode = "high_value_signal"
        elif 2 * hits <= n:
            mode = "verify_more"
    return dict(verified_outcomes=n, hits=hits, misses=misses, mode=mode)


def outcome_stats(outcomes: dict[str, bool]) -> dict:
    return stats(len(outcomes), sum(outcomes.values()), len(outcomes) - sum(outcomes.values()))


def validate_calibration(calibration: Any) -> None:
    require(isinstance(calibration, dict), "invalid calibration")
    for domain, item in calibration.items():
        require(isinstance(domain, str) and KEY.fullmatch(domain), "invalid calibration domain")
        require(isinstance(item, dict) and item.keys() == {
            "verified_outcomes", "hits", "misses", "mode", "outcome_ids",
        }, "invalid calibration fields")
        outcomes = item["outcome_ids"]
        require(isinstance(outcomes, dict) and all(
            isinstance(k, str) and KEY.fullmatch(k) and type(v) is bool
            for k, v in outcomes.items()
        ), "invalid calibration outcome IDs")
        actual = {k: v for k, v in item.items() if k != "outcome_ids"}
        stats(item["verified_outcomes"], item["hits"], item["misses"])
        require(actual == outcome_stats(outcomes), "calibration summary disagrees with evidence")
# Supported frontmatter is a single flat mapping of scalar values, with
# optional comments. YAML collections, tags and aliases are not interpreted.
FIELD = re.compile(r"([A-Za-z_][A-Za-z0-9_.-]*):[ \t]*(.*)")
TOKEN = re.compile(r'''(?:"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^#"'\[\]{}!&*|>@%:]*?)(?=[ \t]*(?:#|$))''')
HEADING = re.compile(r" {0,3}##[ \t]+(.+?)[ \t]*")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")


@dataclass
class Document:
    text: str
    newline: str
    metadata: dict[str, str]
    tokens: dict[str, tuple[int, int]]
    sections: dict[str, tuple[int, int, int]]
    episodes: list[dict]
    calibration: dict

    @property
    def version(self) -> int:
        return int(self.metadata["schema_version"])

    def render_v2(self) -> str:
        return self.text[:self.sections[EPISODES][0]] + render_sections(
            self.episodes, self.calibration, self.newline
        ) + self.text[self.sections[CALIBRATION][2]:]


def render_sections(episodes: list, calibration: dict, newline: str) -> str:
    def block(name, tag, data):
        # ASCII JSON escapes keep a literal newline or fence in user data from
        # becoming Markdown structure.
        payload = json.dumps(data, ensure_ascii=True, indent=2, allow_nan=False)
        return f"## {name}\n\n```{tag}\n{payload}\n```\n\n"

    return (block(EPISODES, "loji-episodes", episodes) +
            block(CALIBRATION, "loji-calibration", calibration)).replace("\n", newline)


def _block(text: str, tag: str) -> Any:
    match = re.fullmatch(r"\s*```" + tag + r"\r?\n(.*?)\r?\n```[ \t]*\s*", text, re.S)
    require(match is not None, "missing or malformed " + tag + " block")
    return decode_json(match[1])


def parse(text: str) -> Document:
    require("\0" not in text and "\r" not in text.replace("\r\n", ""), "invalid text")
    opening = re.match(r"\ufeff?---(\r?\n)", text)
    require(opening is not None, "missing Memory frontmatter")
    newline = opening[1]
    closing = re.compile(r"^---\r?$", re.M).search(text, opening.end())
    require(closing is not None, "unclosed Memory frontmatter")
    metadata, tokens = {}, {}
    offset = opening.end()
    for line in text[offset:closing.start()].splitlines(keepends=True):
        if line.strip() and not line.lstrip().startswith("#"):
            match = FIELD.fullmatch(line.rstrip("\r\n"))
            require(match is not None, "frontmatter must be a flat scalar mapping")
            key, raw = match.groups()
            require(key not in metadata, "duplicate frontmatter key")
            token = TOKEN.match(raw)
            require(token is not None, "unsupported frontmatter value")
            # A comment is only valid after whitespace (or on an empty value).
            rest = raw[token.end():]
            require(not rest or rest[0].isspace() or not token[0],
                    "malformed frontmatter comment")
            metadata[key] = token[0]
            start = offset + match.start(2)
            tokens[key] = (start, start + token.end())
        offset += len(line)

    require(metadata.get("schema_version") in ("1", "2"), "unsupported Memory schema")
    def enum(key, values):
        value = metadata.get(key)
        require(value is not None and any(value in (v, '"' + v + '"', "'" + v + "'")
                                           for v in values), "invalid " + key)
    enum("memory_policy", ("auto", "explicit", "read_only", "off", "unset"))
    enum("memory_consent", ("granted", "pending", "denied"))
    if "skill_version" in metadata:
        require(re.fullmatch(r"""(?:"\d+\.\d+\.\d+"|'\d+\.\d+\.\d+'|\d+\.\d+\.\d+)""",
                             metadata["skill_version"]), "invalid skill_version")
    if "conversation_count" in metadata:
        require(re.fullmatch(r"0|[1-9][0-9]*", metadata["conversation_count"]),
                "invalid conversation_count")
    for key in ("created_at", "last_updated"):
        if key in metadata:
            value = metadata[key]
            # Published template and date format; accept timestamps already
            # written by hosts as scalar metadata without rewriting them.
            require(value in ('""', "''", "", "null") or re.fullmatch(
                r"""(?:"[^"\r\n]+"|'[^'\r\n]+'|[0-9][0-9TZ .+\-]*)""", value
            ), "invalid " + key)

    sections = {}
    required = SECTIONS if metadata["schema_version"] == "1" else V2_SECTIONS
    offset = closing.end()
    previous = None
    fence = None
    comment = False
    for line in text[offset:].splitlines(keepends=True):
        content = line.rstrip("\r\n")
        m = FENCE.fullmatch(content)
        if fence is not None:
            if m and m[1][0] == fence[0] and len(m[1]) >= len(fence) and not m[2].strip():
                fence = None
        elif comment or content.lstrip().startswith("<!--"):
            comment = "-->" not in content
        elif m:
            fence = m[1]
        else:
            m = HEADING.fullmatch(content)
            if m:
                name = re.sub(r"[ \t]+#+$", "", m[1])
                if previous in sections:
                    sections[previous] = (*sections[previous][:2], offset)
                require(name not in sections, "duplicate Memory section")
                if name in required:
                    sections[name] = (offset, offset + len(line), len(text))
                else:
                    require(name not in (EPISODES, CALIBRATION), "schema/section mismatch")
                previous = name
        offset += len(line)
    require(fence is None and not comment, "unclosed Memory fence or comment")
    require(tuple(sections) == required, "missing or out-of-order Memory section")
    episodes, calibration = [], {}
    if required == V2_SECTIONS:
        require(sections[EPISODES][2] == sections[CALIBRATION][0],
                "managed sections must be adjacent")
        episodes = _block(text[slice(*sections[EPISODES][1:])], "loji-episodes")
        calibration = _block(text[slice(*sections[CALIBRATION][1:])], "loji-calibration")
        validate_episodes(episodes)
        validate_calibration(calibration)
    return Document(text, newline, metadata, tokens, sections, episodes, calibration)


def upgrade(doc: Document) -> str:
    if doc.version == 2:
        return doc.text
    insert_at = doc.sections["归档"][0]
    changes = [
        (insert_at, insert_at, render_sections([], {}, doc.newline)),
        (*doc.tokens["schema_version"], "2"),
    ]
    if "skill_version" in doc.tokens:
        changes.append((*doc.tokens["skill_version"], '"' + SKILL_VERSION + '"'))
    else:
        start = doc.tokens["schema_version"][0]
        start = doc.text.rfind("\n", 0, start) + 1
        changes.append((start, start, f'skill_version: "{SKILL_VERSION}"{doc.newline}'))
    result = doc.text
    for start, end, replacement in sorted(changes, reverse=True):
        result = result[:start] + replacement + result[end:]
    parse(result)
    return result
