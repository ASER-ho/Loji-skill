#!/usr/bin/env python3
"""Private judgment ledger for Loji.

The ledger is a Markdown file (``JUDGMENTS.md``) with a minimal frontmatter
and one fenced ``judgment`` block per record. Each block body is strict JSON,
so the format is parsed with the Python standard library only — no YAML or
third-party dependency.

Design constraints:

- The host authorization decision is resolved *before* the ledger is opened.
  ``JUDGMENTS.md`` is never read to discover the policy.
- Every write reuses :mod:`scripts.memory_io` for the advisory lock, verified
  backup, atomic replace, and conflict detection. There is no second storage
  path.
- A revision appends a new record and marks the previous record
  ``superseded``. The previous record's stance, basis, user position and
  confidence are never rewritten.
- Prose outside judgment blocks is preserved by targeted block replacement.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

try:  # imported as scripts.judgment_ledger
    from . import memory_io
except ImportError:  # executed directly as scripts/judgment_ledger.py
    import memory_io  # type: ignore[no-redef]


SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
CONFIDENCE_VALUES = frozenset({"low", "medium", "high"})
STATUS_VALUES = frozenset({"active", "superseded", "retracted"})

REQUIRED_FIELDS = (
    "id",
    "topic_key",
    "topic",
    "stance",
    "confidence",
    "basis",
    "user_position",
    "would_change_if",
    "status",
    "created_at",
    "updated_at",
    "supersedes",
)
OPTIONAL_FIELDS = ("outcome", "lesson")
ALLOWED_FIELDS = frozenset(REQUIRED_FIELDS + OPTIONAL_FIELDS)

MAX_BASIS = 5
MIN_BASIS = 1
MAX_WOULD_CHANGE_IF = 3
MAX_TOPIC_KEY_LENGTH = 128

ID_RE = re.compile(r"^J-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FENCE_OPEN = "```judgment"
FENCE_CLOSE = "```"

VALID_POLICIES = frozenset({"auto", "explicit", "read_only", "off"})
UNKNOWN_POLICIES = frozenset({"", "unknown", "unset"})


class JudgmentLedgerError(Exception):
    """Base class for judgment-ledger failures."""


class JudgmentAccessError(JudgmentLedgerError):
    """The host authorization state does not permit this operation."""


class JudgmentParseError(JudgmentLedgerError):
    """The ledger text is not a well-formed ledger document."""


class JudgmentValidationError(JudgmentLedgerError):
    """One or more judgment records violate the schema contract."""


class _DuplicateKeyError(ValueError):
    """A JSON object repeated a key."""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyError(f"duplicate JSON key: {key}")
        seen[key] = value
    return seen


@dataclass(frozen=True)
class AccessDecision:
    can_read: bool
    can_write: bool
    reason: str


def _normalize_policy(policy: Any, consent: Any) -> tuple[Any, Any]:
    """Accept the documented ``"auto + granted"`` shorthand as well."""
    if isinstance(policy, str) and "+" in policy:
        left, right = policy.split("+", 1)
        if consent is None or str(consent).strip().lower() in UNKNOWN_POLICIES:
            consent = right.strip()
        policy = left.strip()
    if isinstance(policy, str):
        policy = policy.strip().lower()
    if isinstance(consent, str):
        consent = consent.strip().lower()
    return policy, consent


def resolve_access(
    policy: Any,
    consent: Any,
    *,
    user_requested_write: bool = False,
) -> AccessDecision:
    """Resolve read/write permission from host-provided policy and consent.

    ``off`` and unknown states deny reading as well as writing, so callers must
    call this *before* opening ``JUDGMENTS.md`` (including its frontmatter).
    """
    policy, consent = _normalize_policy(policy, consent)

    if policy in UNKNOWN_POLICIES or policy not in VALID_POLICIES:
        return AccessDecision(
            can_read=False,
            can_write=False,
            reason=f"policy is unknown or unset ({policy!r}); no read or write",
        )
    if policy == "off":
        return AccessDecision(
            can_read=False,
            can_write=False,
            reason="policy is off; no read or write",
        )
    if policy == "read_only":
        if consent != "granted":
            return AccessDecision(
                can_read=False,
                can_write=False,
                reason=(
                    f"policy is read_only but consent is {consent!r}; "
                    "read_only requires granted consent"
                ),
            )
        return AccessDecision(
            can_read=True,
            can_write=False,
            reason="policy is read_only with granted consent; read allowed, write denied",
        )
    if policy == "explicit":
        if consent != "granted":
            return AccessDecision(
                can_read=False,
                can_write=False,
                reason=f"policy is explicit but consent is {consent!r}; no read",
            )
        if user_requested_write:
            return AccessDecision(
                can_read=True,
                can_write=True,
                reason="policy is explicit and the user requested this write",
            )
        return AccessDecision(
            can_read=True,
            can_write=False,
            reason="policy is explicit; write requires an explicit user request",
        )

    # policy == "auto"
    if consent != "granted":
        return AccessDecision(
            can_read=False,
            can_write=False,
            reason=f"policy is auto but consent is {consent!r}; no read or write",
        )
    return AccessDecision(
        can_read=True,
        can_write=True,
        reason="policy is auto and consent is granted",
    )


@dataclass(frozen=True)
class Judgment:
    id: str
    topic_key: str
    topic: str
    stance: str
    confidence: str
    basis: tuple[str, ...]
    user_position: str
    would_change_if: tuple[str, ...]
    status: str
    created_at: str
    updated_at: str
    supersedes: str | None
    outcome: str | None = None
    lesson: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "basis", tuple(self.basis))
        object.__setattr__(self, "would_change_if", tuple(self.would_change_if))

    @classmethod
    def from_mapping(cls, data: Any) -> "Judgment":
        if not isinstance(data, dict):
            raise JudgmentParseError("judgment block must contain a JSON object")

        missing = [name for name in REQUIRED_FIELDS if name not in data]
        if missing:
            raise JudgmentParseError(
                f"judgment is missing required field(s): {', '.join(missing)}"
            )
        extra = sorted(set(data) - ALLOWED_FIELDS)
        if extra:
            raise JudgmentParseError(
                f"judgment contains unknown field(s): {', '.join(extra)}"
            )

        for name in (
            "id",
            "topic_key",
            "topic",
            "stance",
            "confidence",
            "user_position",
            "status",
            "created_at",
            "updated_at",
        ):
            if not isinstance(data[name], str):
                raise JudgmentParseError(f"field {name!r} must be a string")

        if not isinstance(data["basis"], list) or not all(
            isinstance(item, str) for item in data["basis"]
        ):
            raise JudgmentParseError("field 'basis' must be a list of strings")
        if not isinstance(data["would_change_if"], list) or not all(
            isinstance(item, str) for item in data["would_change_if"]
        ):
            raise JudgmentParseError(
                "field 'would_change_if' must be a list of strings"
            )
        if data["supersedes"] is not None and not isinstance(
            data["supersedes"], str
        ):
            raise JudgmentParseError("field 'supersedes' must be a string or null")

        outcome = data.get("outcome")
        lesson = data.get("lesson")
        for name, value in (("outcome", outcome), ("lesson", lesson)):
            if value is not None and not isinstance(value, str):
                raise JudgmentParseError(f"field {name!r} must be a string")

        return cls(
            id=data["id"],
            topic_key=data["topic_key"],
            topic=data["topic"],
            stance=data["stance"],
            confidence=data["confidence"],
            basis=tuple(data["basis"]),
            user_position=data["user_position"],
            would_change_if=tuple(data["would_change_if"]),
            status=data["status"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            supersedes=data["supersedes"],
            outcome=outcome,
            lesson=lesson,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "topic_key": self.topic_key,
            "topic": self.topic,
            "stance": self.stance,
            "confidence": self.confidence,
            "basis": list(self.basis),
            "user_position": self.user_position,
            "would_change_if": list(self.would_change_if),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "supersedes": self.supersedes,
        }
        if self.outcome is not None:
            data["outcome"] = self.outcome
        if self.lesson is not None:
            data["lesson"] = self.lesson
        return data


@dataclass(frozen=True)
class BlockSpan:
    start: int
    end: int
    line_no: int
    judgment: Judgment


@dataclass(frozen=True)
class LedgerDocument:
    text: str
    schema_version: int
    skill_version: str | None
    blocks: tuple[BlockSpan, ...]

    @property
    def judgments(self) -> tuple[Judgment, ...]:
        return tuple(block.judgment for block in self.blocks)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise JudgmentParseError("ledger is missing its frontmatter block")
    closing: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise JudgmentParseError("ledger frontmatter is not closed")

    values: dict[str, str] = {}
    for line in lines[1:closing]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", stripped)
        if not match:
            raise JudgmentParseError(
                f"frontmatter line is not a simple key/value pair: {stripped!r}"
            )
        key, raw = match.group(1), match.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        values[key] = raw
    return values, "".join(lines[: closing + 1])


def _extract_blocks(text: str) -> list[tuple[int, int, int, str]]:
    """Return ``(start, end, line_no, content)`` for every fenced block."""
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line)

    blocks: list[tuple[int, int, int, str]] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != FENCE_OPEN:
            index += 1
            continue

        start = offsets[index]
        cursor = index + 1
        content_lines: list[str] = []
        while cursor < len(lines) and lines[cursor].strip() != FENCE_CLOSE:
            content_lines.append(lines[cursor])
            cursor += 1
        if cursor >= len(lines):
            raise JudgmentParseError(
                f"unclosed judgment block starting at line {index + 1}"
            )

        end = offsets[cursor] + len(lines[cursor].rstrip("\r\n"))
        blocks.append((start, end, index + 1, "".join(content_lines)))
        index = cursor + 1
    return blocks


def parse_ledger(text: str) -> LedgerDocument:
    """Parse ledger text. Structural errors raise :class:`JudgmentParseError`."""
    frontmatter, _preamble_text = _parse_frontmatter(text)

    raw_schema = frontmatter.get("schema_version")
    if raw_schema is None:
        raise JudgmentParseError("ledger frontmatter is missing schema_version")
    try:
        schema_version = int(raw_schema)
    except ValueError as exc:
        raise JudgmentParseError(
            f"schema_version is not an integer: {raw_schema!r}"
        ) from exc
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise JudgmentParseError(
            f"unsupported schema_version {schema_version}; "
            f"supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    blocks: list[BlockSpan] = []
    for start, end, line_no, content in _extract_blocks(text):
        try:
            data = json.loads(content, object_pairs_hook=_no_duplicate_keys)
        except _DuplicateKeyError as exc:
            raise JudgmentParseError(
                f"judgment block at line {line_no}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise JudgmentParseError(
                f"judgment block at line {line_no} is not valid JSON: {exc}"
            ) from exc
        try:
            judgment = Judgment.from_mapping(data)
        except JudgmentParseError as exc:
            raise JudgmentParseError(
                f"judgment block at line {line_no}: {exc}"
            ) from exc
        blocks.append(
            BlockSpan(start=start, end=end, line_no=line_no, judgment=judgment)
        )

    return LedgerDocument(
        text=text,
        schema_version=schema_version,
        skill_version=frontmatter.get("skill_version"),
        blocks=tuple(blocks),
    )


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_judgments(judgments: Iterable[Judgment]) -> list[str]:
    """Return every schema or cross-record error in ``judgments``."""
    items = list(judgments)
    errors: list[str] = []

    for item in items:
        label = (
            item.id
            if isinstance(item.id, str) and item.id.strip()
            else "<missing id>"
        )
        if not isinstance(item.id, str) or not ID_RE.fullmatch(item.id):
            errors.append(
                f"{label}: id must match J-<alphanumeric/._-> and be <= 64 chars"
            )
        if not _nonempty(item.topic_key):
            errors.append(f"{label}: topic_key must be a non-empty string")
        elif len(item.topic_key) > MAX_TOPIC_KEY_LENGTH:
            errors.append(
                f"{label}: topic_key exceeds {MAX_TOPIC_KEY_LENGTH} characters"
            )
        for name in ("topic", "stance", "user_position"):
            if not _nonempty(getattr(item, name)):
                errors.append(f"{label}: {name} must be a non-empty string")

        if item.confidence not in CONFIDENCE_VALUES:
            errors.append(
                f"{label}: confidence={item.confidence!r} is not one of "
                f"{sorted(CONFIDENCE_VALUES)}"
            )
        if item.status not in STATUS_VALUES:
            errors.append(
                f"{label}: status={item.status!r} is not one of "
                f"{sorted(STATUS_VALUES)}"
            )

        if not MIN_BASIS <= len(item.basis) <= MAX_BASIS:
            errors.append(
                f"{label}: basis must contain {MIN_BASIS}-{MAX_BASIS} items "
                f"(found {len(item.basis)})"
            )
        for index, basis in enumerate(item.basis):
            if not _nonempty(basis):
                errors.append(f"{label}: basis[{index}] must be non-empty")

        if len(item.would_change_if) > MAX_WOULD_CHANGE_IF:
            errors.append(
                f"{label}: would_change_if must contain 0-"
                f"{MAX_WOULD_CHANGE_IF} items (found {len(item.would_change_if)})"
            )
        for index, condition in enumerate(item.would_change_if):
            if not _nonempty(condition):
                errors.append(
                    f"{label}: would_change_if[{index}] must be non-empty"
                )

        for name in ("created_at", "updated_at"):
            value = getattr(item, name)
            if not _valid_date(value):
                errors.append(
                    f"{label}: {name}={value!r} is not a valid YYYY-MM-DD date"
                )
        if _valid_date(item.created_at) and _valid_date(item.updated_at):
            if item.updated_at < item.created_at:
                errors.append(
                    f"{label}: updated_at is earlier than created_at"
                )

        if item.supersedes is not None:
            if not isinstance(item.supersedes, str) or not ID_RE.fullmatch(
                item.supersedes
            ):
                errors.append(
                    f"{label}: supersedes={item.supersedes!r} is not a valid id"
                )
            elif item.supersedes == item.id:
                errors.append(f"{label}: a judgment cannot supersede itself")

        if item.outcome is not None and not _nonempty(item.outcome):
            errors.append(f"{label}: outcome must be non-empty when present")
        if item.lesson is not None and not _nonempty(item.lesson):
            errors.append(f"{label}: lesson must be non-empty when present")

    by_id: dict[str, Judgment] = {}
    for item in items:
        if item.id in by_id:
            errors.append(f"{item.id}: duplicate judgment id")
        else:
            by_id[item.id] = item

    active_by_topic: dict[str, list[str]] = {}
    for item in items:
        if item.status == "active":
            active_by_topic.setdefault(item.topic_key, []).append(item.id)
    for topic_key, ids in sorted(active_by_topic.items()):
        if len(ids) > 1:
            errors.append(
                f"topic_key {topic_key!r} has multiple active judgments: "
                f"{', '.join(sorted(ids))}"
            )

    successor_count: dict[str, int] = {item.id: 0 for item in items}
    for item in items:
        if item.supersedes is None:
            continue
        target = by_id.get(item.supersedes)
        if target is None:
            errors.append(
                f"{item.id}: supersedes references missing judgment "
                f"{item.supersedes!r}"
            )
            continue
        successor_count[target.id] += 1
        if target.status != "superseded":
            errors.append(
                f"{item.id}: supersedes {target.id}, but {target.id} has "
                f"status {target.status!r} (expected 'superseded')"
            )
        if item.topic_key != target.topic_key:
            errors.append(
                f"{item.id}: topic_key differs from superseded judgment "
                f"{target.id} ({item.topic_key!r} != {target.topic_key!r})"
            )
        if (
            _valid_date(item.created_at)
            and _valid_date(target.created_at)
            and item.created_at < target.created_at
        ):
            errors.append(
                f"{item.id}: created_at is earlier than the judgment it "
                f"supersedes ({target.id})"
            )

    for item in items:
        if item.status == "superseded":
            count = successor_count.get(item.id, 0)
            if count == 0:
                errors.append(
                    f"{item.id}: status is 'superseded' but no judgment "
                    f"references it via supersedes"
                )
            elif count > 1:
                errors.append(
                    f"{item.id}: multiple judgments supersede the same record"
                )

    cycle_reported: set[frozenset[str]] = set()
    for start in items:
        seen: list[str] = []
        cursor: Judgment | None = start
        while cursor is not None and cursor.id not in seen:
            seen.append(cursor.id)
            if cursor.supersedes is None:
                cursor = None
            else:
                cursor = by_id.get(cursor.supersedes)
        if cursor is not None and cursor.id in seen:
            cycle = frozenset(seen[seen.index(cursor.id) :])
            if cycle not in cycle_reported:
                cycle_reported.add(cycle)
                errors.append(
                    "supersedes cycle detected: "
                    + " -> ".join(seen[seen.index(cursor.id) :] + [cursor.id])
                )

    return errors


def render_judgment(judgment: Judgment) -> str:
    payload = json.dumps(judgment.to_dict(), ensure_ascii=False, indent=2)
    return f"{FENCE_OPEN}\n{payload}\n{FENCE_CLOSE}"


def _append_block(text: str, judgment: Judgment) -> str:
    if text.endswith("\n\n"):
        separator = ""
    elif text.endswith("\n"):
        separator = "\n"
    elif text:
        separator = "\n\n"
    else:
        separator = ""
    return f"{text}{separator}{render_judgment(judgment)}\n"


def _require_read(policy: Any, consent: Any) -> AccessDecision:
    decision = resolve_access(policy, consent)
    if not decision.can_read:
        raise JudgmentAccessError(decision.reason)
    return decision


def load_ledger(
    path: Path | str,
    *,
    policy: Any,
    consent: Any,
) -> tuple[LedgerDocument, memory_io.MemoryVersion]:
    """Load and validate the ledger *after* the authorization check.

    The file (including its frontmatter) is not opened when the host policy
    denies reading.
    """
    _require_read(policy, consent)
    result = memory_io.read(path)
    document = parse_ledger(result.text)
    errors = validate_judgments(document.judgments)
    if errors:
        raise JudgmentValidationError("; ".join(errors))
    return document, result.version


def init_ledger(
    template_path: Path | str,
    target_path: Path | str,
    *,
    policy: Any,
    consent: Any,
    user_requested_write: bool = False,
    timeout: float = memory_io.DEFAULT_TIMEOUT,
) -> memory_io.MemoryVersion:
    """Create ``JUDGMENTS.md`` from the tracked template without overwriting."""
    decision = resolve_access(
        policy, consent, user_requested_write=user_requested_write
    )
    if not decision.can_write:
        raise JudgmentAccessError(decision.reason)
    return memory_io.init_memory(template_path, target_path, timeout=timeout)


def append_judgment(
    path: Path | str,
    judgment: Judgment,
    *,
    policy: Any,
    consent: Any,
    user_requested_write: bool = False,
    expected: memory_io.MemoryVersion | None = None,
    timeout: float = memory_io.DEFAULT_TIMEOUT,
) -> memory_io.AtomicWriteResult:
    """Append one judgment using the shared atomic-write contract."""
    decision = resolve_access(
        policy, consent, user_requested_write=user_requested_write
    )
    if not decision.can_write:
        raise JudgmentAccessError(decision.reason)

    document, version = load_ledger(path, policy=policy, consent=consent)
    combined = list(document.judgments) + [judgment]
    errors = validate_judgments(combined)
    if errors:
        raise JudgmentValidationError("; ".join(errors))

    new_text = _append_block(document.text, judgment)
    return memory_io.atomic_write(
        path,
        new_text,
        expected if expected is not None else version,
        timeout=timeout,
    )


@dataclass(frozen=True)
class RevisionResult:
    write_result: memory_io.AtomicWriteResult
    previous: Judgment
    successor: Judgment


def revise_judgment(
    path: Path | str,
    previous_id: str,
    successor: Judgment,
    *,
    policy: Any,
    consent: Any,
    user_requested_write: bool = False,
    expected: memory_io.MemoryVersion | None = None,
    timeout: float = memory_io.DEFAULT_TIMEOUT,
) -> RevisionResult:
    """Create a revision without rewriting the original stance or basis.

    The previous record keeps ``topic``/``stance``/``basis``/``user_position``/
    ``confidence`` and only moves to ``status: superseded`` with an updated
    ``updated_at``. The successor is appended and must reference the previous
    record through ``supersedes``.
    """
    decision = resolve_access(
        policy, consent, user_requested_write=user_requested_write
    )
    if not decision.can_write:
        raise JudgmentAccessError(decision.reason)

    document, version = load_ledger(path, policy=policy, consent=consent)
    previous = next(
        (item for item in document.judgments if item.id == previous_id), None
    )
    if previous is None:
        raise JudgmentValidationError(f"judgment {previous_id!r} not found")
    if previous.status != "active":
        raise JudgmentValidationError(
            f"judgment {previous_id!r} has status {previous.status!r}; "
            "only an active judgment can be revised"
        )
    if successor.id == previous.id:
        raise JudgmentValidationError("successor must have a new id")
    if successor.supersedes is None:
        successor = replace(successor, supersedes=previous.id)
    elif successor.supersedes != previous.id:
        raise JudgmentValidationError(
            f"successor.supersedes={successor.supersedes!r} does not match "
            f"{previous.id!r}"
        )
    if successor.topic_key != previous.topic_key:
        raise JudgmentValidationError(
            f"successor.topic_key={successor.topic_key!r} differs from "
            f"{previous.topic_key!r}"
        )

    updated_previous = replace(
        previous,
        status="superseded",
        updated_at=successor.updated_at,
    )
    updated_items = [
        updated_previous if item.id == previous.id else item
        for item in document.judgments
    ] + [successor]
    errors = validate_judgments(updated_items)
    if errors:
        raise JudgmentValidationError("; ".join(errors))

    block = next(
        block for block in document.blocks if block.judgment.id == previous.id
    )
    new_text = (
        document.text[: block.start]
        + render_judgment(updated_previous)
        + document.text[block.end :]
    )
    new_text = _append_block(new_text, successor)

    write_result = memory_io.atomic_write(
        path,
        new_text,
        expected if expected is not None else version,
        timeout=timeout,
    )
    return RevisionResult(
        write_result=write_result,
        previous=updated_previous,
        successor=successor,
    )
