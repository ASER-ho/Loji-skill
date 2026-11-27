#!/usr/bin/env python3
"""Build a disposable, bounded view of the current authorized project."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from datetime import date

if __package__:
    from . import episodic_memory as em, evidence_identity as evidence
    from . import judgment_ledger as jl, memory_io as io, memory_schema as schema, memory_state as ms
else:
    import episodic_memory as em
    import evidence_identity as evidence
    import judgment_ledger as jl
    import memory_io as io
    import memory_schema as schema
    import memory_state as ms


PRIORITY = ("hard_constraints", "unresolved_conflicts", "active_goal",
            "confirmed_decisions", "pending_items")
MAX_REQUEST_BYTES = 256 * 1024
INSUFFICIENT = "evidence_insufficient"


def empty_card():
    return {**{key: [] for key in (*PRIORITY, "judgments", "evidence_status")},
            "truncated": False, "sources": []}


def encode(result):
    return json.dumps(result, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


MIN_BYTE_BUDGET = len(encode(empty_card()))


class _Card:
    def __init__(self, limit):
        self.result = empty_card()
        self.size = MIN_BYTE_BUDGET
        self.limit = limit
        self.source_ids = set()

    def add(self, field, item, source):
        entries = self.result[field]
        sources = self.result["sources"]
        size = len(encode(item)) + bool(entries)
        new_source = source not in self.source_ids
        if new_source:
            size += len(encode(source)) + bool(sources)
        if self.size + size > self.limit:
            self.result["truncated"] = True
            return
        self.size += size
        entries.append(item)
        if new_source:
            sources.append(source)
            self.source_ids.add(source)


@dataclass
class _Budget:
    remaining: int
    exhausted: bool = False

    def take(self):
        if self.remaining == 0:
            self.exhausted = True
            return False
        self.remaining -= 1
        return True


def _check_limits(byte_budget, lookup_budget):
    schema.require(type(byte_budget) is int and byte_budget >= MIN_BYTE_BUDGET,
                   f"byte_budget must be at least {MIN_BYTE_BUDGET}")
    schema.require(type(lookup_budget) is int and lookup_budget >= 0, "invalid lookup_budget")


@dataclass(frozen=True)
class Selection:
    """Exact scope supplied by the host from the user and verified project facts."""

    project: str
    matters: tuple[str, ...]
    as_of: str
    judgment_id: str | None = None

    def __post_init__(self):
        schema.require(schema.nonempty(self.project) and schema.valid_date(self.as_of),
                       "a project and valid as_of date are required")
        schema.require(isinstance(self.matters, (tuple, list)) and all(
            schema.nonempty(matter) for matter in self.matters), "matters must be exact names")
        schema.require(self.judgment_id is None or isinstance(self.judgment_id, str) and
                       schema.JUDGMENT_ID.fullmatch(self.judgment_id), "invalid Judgment ID")
        object.__setattr__(self, "matters", tuple(self.matters))


@dataclass
class _View:
    facts: list
    episodes: list
    unresolved: list
    judgments: dict


def _records(doc):
    """Parse only a top-level loji-recovery fence in the ordinary context section."""
    content = doc.text[slice(*doc.sections["近期上下文"][1:])]
    fence = None
    comment = False
    payload = None
    found = False
    records = []
    for line in content.splitlines():
        marker = schema.FENCE.fullmatch(line)
        if fence is not None:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = None
                if payload is not None:
                    records = schema.decode_json("\n".join(payload))
                    payload = None
            elif payload is not None:
                payload.append(line)
        elif comment or line.lstrip().startswith("<!--"):
            comment = "-->" not in line
        elif marker:
            fence = marker[1]
            if marker[2].strip() == "loji-recovery":
                schema.require(not found, "duplicate loji-recovery block")
                found = True
                payload = []
    schema.require(isinstance(records, list), "loji-recovery must be an array")
    required = {"id", "project", "category", "text"}
    optional = {"matter_id", "expires_on", "summary_source_id"}
    ids = set()
    summary_ids = set()
    for row in records:
        schema.require(isinstance(row, dict) and required <= row.keys() <= required | optional,
                       "invalid recovery record fields")
        key = row["id"]
        schema.require(isinstance(key, str) and schema.KEY.fullmatch(key) and key not in ids,
                       "invalid or duplicate recovery record ID")
        schema.require(schema.nonempty(row["project"]) and schema.nonempty(row["text"]) and
                       row["category"] in PRIORITY, "invalid recovery record")
        schema.require(row.get("matter_id") is None or schema.nonempty(row["matter_id"]),
                       "invalid recovery matter name")
        schema.require(row.get("expires_on") is None or schema.valid_date(row["expires_on"]),
                       "invalid recovery expiry")
        if "summary_source_id" in row:
            note = row["summary_source_id"]
            schema.require(isinstance(note, str) and note.startswith("note:") and len(note) > 5 and
                           evidence.SOURCE_ID.fullmatch(note) and note not in summary_ids,
                           "invalid or duplicate recovery note source ID")
            summary_ids.add(note)
        ids.add(key)
    return records


def _snapshot(state, auth, selection, budget):
    if not budget.take():
        return _View([], [], [], {})
    # Use the existing format validation and protected, fixed hosted path.
    # This optional human-readable block does not change either core schema.
    memory = io.guard.managed_path(state.folder / "memory.md", root=state.folder)
    doc = schema.parse(io.read(memory).text)
    matters = set(selection.matters)
    facts = [row for row in _records(doc) if row["project"] == selection.project and
             (row.get("matter_id") is None or row["matter_id"] in matters) and
             (row.get("expires_on") is None or row["expires_on"] >= selection.as_of)]
    episodes = [ep for ep in doc.episodes if ep["relevance"] in matters]
    unresolved = sorted({ep["relevance"] for ep in episodes if ep["state"] == "unresolved" and
                         ep["date"] <= selection.as_of and
                         (ep["expires_on"] is None or ep["expires_on"] >= selection.as_of)})
    if (not episodes and selection.judgment_id is None) or not budget.take():
        return _View(facts, [], unresolved, {})
    # Load only when scoped Episodes or an explicitly referenced Judgment need it.
    ledger = io.guard.managed_path(state.folder / "JUDGMENTS.md", root=state.folder)
    document, _ = jl.load_ledger(ledger, **auth.body_args())
    judgments = {row.id: row for row in document.judgments}
    em._check_refs(episodes, judgments)
    projected = em.project_context(replace(doc, episodes=episodes), judgments,
                                   domain=None, as_of=selection.as_of, matters=None)
    ordinary_conflicts = {row.get("matter_id") for row in facts if row["category"] == "unresolved_conflicts"}
    current_judgments = {row.id: row for row in document.judgments
                         if row.status == "active" and row.created_at <= selection.as_of}
    current_episodes = []
    for row in projected["episodes"]:
        if None in ordinary_conflicts or row["relevance"] in ordinary_conflicts:
            continue
        refs = [key for key in row["related_judgments"] if key in current_judgments]
        if refs:
            current_episodes.append({**row, "related_judgments": refs})
    ids = dict.fromkeys(key for row in current_episodes for key in row["related_judgments"])
    if selection.judgment_id in current_judgments:
        ids[selection.judgment_id] = None
    return _View(facts, current_episodes, unresolved, {key: current_judgments[key] for key in ids})


def _eligible_facts(view):
    conflicts = set(view.unresolved)
    conflicts.update(row.get("matter_id") for row in view.facts if row["category"] == "unresolved_conflicts")
    return [row for row in view.facts if row["category"] != "confirmed_decisions"
            or None not in conflicts and row.get("matter_id") not in conflicts]


def _judgment_refs(row):
    return list(dict.fromkeys(source for item in row.basis for source in evidence.references(item)))


def _episode_refs(row):
    return list(dict.fromkeys(evidence.references(row["summary"]) + evidence.references(row["outcome"] or "")))


def _identity_map(identities):
    index = {}
    for identity in identities:
        if isinstance(identity, dict):
            identity = evidence.Identity.from_mapping(identity)
        schema.require(isinstance(identity, evidence.Identity) and identity.source_id not in index,
                       "invalid or duplicate evidence identity")
        index[identity.source_id] = identity
    return index


def _probe(state, root, index, key, budget):
    identity = index.get(key)
    if identity is None or root is None:
        return "unknown", None, "unregistered_source"
    if not budget.take():
        return "unknown", None, "lookup_budget"
    status, data = evidence.verify(root, identity, excluded=state.folder)
    return status, data, None if status == "valid" else "file_" + status


def _card(view, limit, statuses, exhausted=False):
    result = _Card(limit)

    facts = _eligible_facts(view)
    for field in PRIORITY:
        for row in facts:
            if row["category"] == field:
                item = {"id": row["id"], "text": row["text"], "matter_id": row.get("matter_id")}
                if "summary_source_id" in row:
                    item["summary_source_id"] = row["summary_source_id"]
                refs = evidence.references(row["text"])
                if refs:
                    item["requires_recheck"] = any(statuses.get(key) != "valid" for key in refs)
                result.add(field, item, f"memory:{row['id']}")
        if field == "unresolved_conflicts":
            for matter in view.unresolved:
                result.add(field, {"matter_id": matter}, f"matter:{matter}")
        if field == "confirmed_decisions":
            for row in view.episodes:
                if row["kind"] != "important_joint_decision":
                    continue
                ids = _episode_refs(row) + [source for key in row["related_judgments"]
                                           for source in _judgment_refs(view.judgments[key])]
                result.add(field, {"id": row["id"], "text": row["summary"],
                                   "matter_id": row["relevance"],
                                   "requires_recheck": any(statuses.get(key) != "valid" for key in ids)},
                           f"episode:{row['id']}")
    for row in view.judgments.values():
        ids = _judgment_refs(row)
        result.add("judgments", {"id": row.id, "stance": row.stance, "basis": list(row.basis),
                                 "confidence": row.confidence,
                                 "requires_recheck": any(statuses.get(key) != "valid" for key in ids)},
                   f"judgment:{row.id}")
    for key, status in statuses.items():
        result.add("evidence_status", {"source_id": key, "status": status}, key)
    result.result["truncated"] |= exhausted
    return result.result


def _linked_sources(view):
    sources = dict.fromkeys(key for row in view.judgments.values() for key in _judgment_refs(row))
    sources.update(dict.fromkeys(key for row in view.episodes for key in _episode_refs(row)))
    return sources


def recover(state, selection, *, byte_budget, lookup_budget, project_root=None, identities=()):
    """Keep only whole records fitting the UTF-8 wire budget; never persist a card."""
    _check_limits(byte_budget, lookup_budget)
    budget = _Budget(lookup_budget)
    if lookup_budget == 0:
        return {**empty_card(), "truncated": True}
    try:
        with state.access(readonly_lock=True) as auth:
            index = _identity_map(identities)
            view = _snapshot(state, auth, selection, budget)
            statuses = {key: _probe(state, project_root, index, key, budget)[0]
                        for key in _linked_sources(view)}
            return _card(view, byte_budget, statuses, budget.exhausted)
    except (ms.AccessError, ms.StateError, io.MemoryLockUnavailableError, io.MemoryLockTimeoutError):
        return empty_card()


def _bound(result, limit):
    if len(encode(result)) > limit:
        return {"status": INSUFFICIENT, "reason": "byte_budget"}
    return result


def lookup(state, selection, source_id, *, byte_budget, lookup_budget, project_root=None,
           identities=(), accept_summary=False):
    """Progress from the card to exact Judgment, matter, and authorized project records."""
    _check_limits(byte_budget, lookup_budget)
    schema.require(isinstance(source_id, str) and evidence.SOURCE_ID.fullmatch(source_id),
                   "an exact source ID is required")
    schema.require(type(accept_summary) is bool, "accept_summary must be a boolean")
    if lookup_budget == 0:
        return {"status": INSUFFICIENT, "reason": "lookup_budget"}
    budget = _Budget(lookup_budget)
    try:
        with state.access(readonly_lock=True) as auth:
            index = _identity_map(identities)
            view = _snapshot(state, auth, selection, budget)
            probe_result = None

            def probe():
                nonlocal probe_result
                if probe_result is None:
                    probe_result = _probe(state, project_root, index, source_id, budget)
                return probe_result

            if accept_summary:
                statuses = {source_id: probe()[0]} if source_id in index else {}
                card = _card(view, byte_budget, statuses)
                non_file_source = source_id not in index and source_id not in _linked_sources(view)
                for field in PRIORITY:
                    for item in card[field]:
                        if item.get("requires_recheck"):
                            continue
                        text = item.get("text", "")
                        if (non_file_source and item.get("summary_source_id") == source_id or
                                statuses.get(source_id) == "valid" and source_id in evidence.references(text)):
                            answer = {"status": "found", "level": "card", "content": text}
                            if len(encode(answer)) <= byte_budget:
                                return answer
            # Advance only across these exact, already-authorized references.
            if any(source_id in _judgment_refs(row) for row in view.judgments.values()):
                level = "judgment_source"
            elif (any(row.get("matter_id") in selection.matters and source_id in evidence.references(row["text"])
                      for row in _eligible_facts(view)) or
                  any(source_id in _episode_refs(row) for row in view.episodes)):
                level = "matter_record"
            else:
                level = "project_record"
            _, data, reason = probe()
            if data is None:
                return {"status": INSUFFICIENT, "reason": reason}
            try:
                content = data.decode("utf-8")
            except UnicodeError:
                return {"status": INSUFFICIENT, "reason": "non_text_source"}
            return _bound({"status": "found", "level": level, "content": content}, byte_budget)
    except (ms.AccessError, ms.StateError, io.MemoryLockUnavailableError, io.MemoryLockTimeoutError):
        return {"status": INSUFFICIENT, "reason": "authorization"}


def observe(state, selection, source_id, relative_path, *, project_root, lookup_budget, byte_budget):
    """Capture an identity only for a source cited by a current Judgment or Episode."""
    _check_limits(byte_budget, lookup_budget)
    schema.require(isinstance(source_id, str) and evidence.SOURCE_ID.fullmatch(source_id),
                   "an exact source ID is required")
    if lookup_budget == 0:
        return {"status": "unknown", "reason": "lookup_budget"}
    if project_root is None:
        return {"status": "unknown", "reason": "project_root_unavailable"}
    budget = _Budget(lookup_budget)
    try:
        with state.access(readonly_lock=True) as auth:
            view = _snapshot(state, auth, selection, budget)
            if source_id not in _linked_sources(view):
                reason = "lookup_budget" if budget.exhausted else "source_not_linked"
                return {"status": "unknown", "reason": reason}
            if not budget.take():
                return {"status": "unknown", "reason": "lookup_budget"}
            identity = evidence.observe(project_root, source_id, relative_path, excluded=state.folder)
            result = identity.to_dict()
            if len(encode(result)) > byte_budget:
                return {"status": "unknown", "reason": "byte_budget"}
            return result
    except (ms.AccessError, ms.StateError, io.MemoryLockUnavailableError, io.MemoryLockTimeoutError):
        return {"status": "unknown", "reason": "authorization"}
    except (OSError, evidence.EvidenceError):
        return {"status": "unknown", "reason": "file_unavailable"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("recover", "lookup", "observe"))
    parser.add_argument("--memory-dir", required=True, help="fixed absolute path from trusted host configuration")
    parser.add_argument("--project-root", help="independently authorized absolute project evidence directory")
    parser.add_argument("--byte-budget", required=True, type=int)
    parser.add_argument("--lookup-budget", required=True, type=int)
    for flag in ("accept-saved", "state-read", "body-read"):
        parser.add_argument("--" + flag, action="store_true")
    parser.add_argument("--host-policy", choices=sorted(ms.POLICIES))
    parser.add_argument("--host-consent")
    args = parser.parse_args(argv)
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        schema.require(len(data) <= MAX_REQUEST_BYTES, "recovery request exceeds input limit")
        request = schema.decode_json(data.decode("utf-8"))
        schema.require(isinstance(request, dict), "recovery request must be an object")
        selection = Selection(project=request.pop("project", None), matters=request.pop("matters", None),
                              as_of=request.pop("as_of", date.today().isoformat()),
                              judgment_id=request.pop("judgment_id", None))
        state = ms.MemoryState(args.memory_dir, ms.Host(
            accept_saved=args.accept_saved, state_read=args.state_read, body_read=args.body_read,
            host_policy=args.host_policy, host_consent=args.host_consent,
        ))
        run = {"recover": recover, "lookup": lookup, "observe": observe}[args.action]
        result = run(state, selection, byte_budget=args.byte_budget, lookup_budget=args.lookup_budget,
                     project_root=args.project_root, **request)
    except (TypeError, ValueError, OSError, io.MemoryIOError, jl.JudgmentLedgerError) as exc:
        # Exception messages from local readers may reveal absolute paths or private data.
        print(f"Recovery request failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(encode(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
