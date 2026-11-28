#!/usr/bin/env python3
"""Audit references and possible residue in explicitly approved local carriers."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date

if __package__:
    from . import evidence_identity as evidence, judgment_ledger as jl
    from . import memory_io as io, memory_schema as schema, memory_state as ms
    from . import recovery_context as recovery
else:
    import evidence_identity as evidence
    import judgment_ledger as jl
    import memory_io as io
    import memory_schema as schema
    import memory_state as ms
    import recovery_context as recovery


CARRIERS = ("memory", "recovery", "episode", "judgment", "calibration", "archive")
TARGETS = dict(memory=schema.KEY, episode=schema.EPISODE_ID, judgment=jl.ID_RE,
               source=evidence.SOURCE_ID, calibration=schema.KEY)
BACKUP = re.compile(r"(memory\.md|JUDGMENTS\.md)\.bak\.\d{8}T\d{6}Z-\d+-[a-f0-9]{8}\Z")
FILE_LIMIT = 4 * 1024 * 1024
MIN_REPORT_BYTES = 96


def _hit(row, relation, basis, **details):
    return {"row": row, "relation": relation, "basis": basis, **details}


def _text_relation(text, kind, key, literal):
    if kind == "source" and key in evidence.references(text):
        return "explicit", "source_marker"
    if literal and literal in text:
        return "possible", "literal_overlap"
    return None


def _memory_hits(doc, kind, key, literal):
    hits = dict(memory=[], recovery=[], episode=[], calibration=[], archive=[])
    ordinary_context = []
    records = recovery._records(doc, ordinary_context=ordinary_context)
    for row, section in enumerate(schema.SECTIONS, 1):
        if section == "不应记录":
            continue
        text = ("\n".join(ordinary_context) if section == "近期上下文"
                else doc.text[slice(*doc.sections[section][1:])])
        relation = _text_relation(text, kind, key, literal)
        if relation:
            name = "archive" if section == "归档" else "memory"
            hits[name].append(_hit(row, *relation))
    for row, record in enumerate(records, 1):
        if kind == "memory" and record["id"] == key:
            hits["recovery"].append(_hit(row, "explicit", "target_present"))
        elif relation := _text_relation(record["text"], kind, key, literal):
            hits["recovery"].append(_hit(row, *relation))
    for row, episode in enumerate(doc.episodes, 1):
        name = "archive" if episode["state"] == "archived" else "episode"
        if kind == "episode" and episode["id"] == key:
            hits[name].append(_hit(row, "explicit", "target_present", state=episode["state"]))
        elif kind == "episode" and key is not None and episode["replaces"] == key:
            hits[name].append(_hit(row, "derived", "replaces"))
        elif kind == "judgment" and key in episode["related_judgments"]:
            hits[name].append(_hit(row, "explicit", "related_judgments",
                                  other_references=len(episode["related_judgments"]) - 1))
        elif relation := _text_relation(episode["summary"] + "\n" + (episode["outcome"] or ""),
                                        kind, key, literal):
            hits[name].append(_hit(row, *relation))
    if kind == "calibration":
        for row, domain in enumerate(doc.calibration.values(), 1):
            if key in domain.get("outcome_ids", {}):
                hits["calibration"].append(_hit(row, "explicit", "target_present"))
    return hits


def _judgment_hits(doc, kind, key, literal):
    hits = []
    for row, judgment in enumerate(doc.judgments, 1):
        if kind == "judgment" and judgment.id == key:
            hits.append(_hit(row, "explicit", "target_present", state=judgment.status))
        elif kind == "judgment" and key is not None and judgment.supersedes == key:
            hits.append(_hit(row, "derived", "supersedes"))
        affected = []
        other = []
        for edge, text in enumerate(judgment.basis, 1):
            relation = _text_relation(text, kind, key, literal)
            if relation:
                affected.append((edge, relation))
            else:
                other.append(edge)
        for edge, relation in affected:
            hits.append(_hit(row, *relation, edge=edge, other_basis=other))
        for field in ("stance", "outcome", "lesson"):
            if relation := _text_relation(getattr(judgment, field) or "", kind, key, literal):
                hits.append(_hit(row, *relation, field=field))
    return {"judgment": hits}


def _load(path, root, kind, key, literal, ledger):
    path = io.guard.managed_path(path, root=root)
    snapshot = io.read(path, max_bytes=FILE_LIMIT)
    if ledger:
        doc = jl.parse_ledger(snapshot.text)
        if jl.validate_judgments(doc.judgments):
            raise ValueError("invalid Judgment snapshot")
        hits = _judgment_hits(doc, kind, key, literal)
    else:
        doc = schema.parse(snapshot.text)
        hits = _memory_hits(doc, kind, key, literal)
    return hits, snapshot.version


def _scan_branch(state, filename, names, request, budget, branches, missing_is_absent=False):
    if not budget.take():
        return "unscanned", "lookup_budget"
    path = state.folder / filename
    try:
        hits, version = _load(path, state.folder, *request, filename.startswith("JUDGMENTS.md"))
    except FileNotFoundError:
        return ("absent", "missing") if missing_is_absent else ("unavailable", "missing")
    except (OSError, io.guard.PathBoundaryError):
        return "unavailable", "file_unavailable"
    except (ValueError, io.MemoryIOError, jl.JudgmentLedgerError):
        return "unknown", "snapshot_unusable"
    branches.append((path, version, names, hits))
    return "checked", None


def _unchanged(path, version):
    try:
        info = io._live_stat(path)
    except (OSError, io.guard.PathBoundaryError):
        return False
    return (io.guard.identity(info), info.st_mtime_ns, info.st_ctime_ns, info.st_size) == (
        version.file_id, version.mtime_ns, version.change_ns, version.size)


def audit(state, *, kind, key=None, literal=None, purpose, carriers=CARRIERS, approved_backups=(),
          backup_indices=(), lookup_budget=4, byte_budget=4096):
    """Report local impact without copying content, scanning directories or writing state."""
    schema.require(kind in TARGETS and (key is None or isinstance(key, str) and TARGETS[kind].fullmatch(key)),
                   "invalid target")
    schema.require(literal is None or schema.nonempty(literal) and len(literal) <= 256,
                   "invalid exact literal")
    schema.require(key is not None or literal is not None, "a target is required")
    schema.require(purpose in ("impact", "residue"), "an authorized audit purpose is required")
    schema.require(type(lookup_budget) is int and lookup_budget >= 0 and type(byte_budget) is int
                   and byte_budget >= MIN_REPORT_BYTES, "invalid audit budgets")
    schema.require(isinstance(carriers, (tuple, list)) and all(n in CARRIERS for n in carriers),
                   "invalid audit carrier")
    approved_backups = tuple(approved_backups)
    schema.require(len(set(approved_backups)) == len(approved_backups)
                   and all(isinstance(name, str) and BACKUP.fullmatch(name) for name in approved_backups),
                   "invalid approved backup basename")
    schema.require(isinstance(backup_indices, (tuple, list))
                   and all(type(i) is int and 1 <= i <= len(approved_backups) for i in backup_indices),
                   "backup selector must be in the host's approved list")

    rows = {name: {"carrier": name, "state": "unscanned", "hits": []} for name in CARRIERS}
    backups = [dict(carrier="backup", index=index, state="unscanned", hits=[])
               for index in dict.fromkeys(backup_indices)]
    all_rows = [*rows.values(), *backups]
    branches = []
    budget = recovery._Budget(lookup_budget)
    request = (kind, key, literal)
    try:
        with state.access(readonly_lock=True):
            for file, selected in (("memory.md", [name for name in rows if name != "judgment" and name in carriers]),
                                   ("JUDGMENTS.md", ["judgment"] if "judgment" in carriers else [])):
                if selected:
                    status, reason = _scan_branch(state, file, [rows[n] for n in selected], request, budget, branches,
                                                  missing_is_absent=True)
                    for name in selected:
                        rows[name].update(state=status, reason=reason)
            for row in backups:
                status, reason = _scan_branch(state, approved_backups[row["index"] - 1], [row], request, budget, branches)
                row.update(state=status, reason=reason)
            for path, token, selected, hits in branches:
                unchanged = _unchanged(path, token)
                for row in selected:
                    if not unchanged:
                        row.update(state="unknown", reason="snapshot_changed")
                        continue
                    name = row["carrier"]
                    row["hits"] = hits[name] if name != "backup" else [
                        {**hit, "within": within} for within, entries in hits.items() for hit in entries
                    ]
                    if name == "calibration" and kind != "calibration":
                        row.update(state="unknown", reason="no_lineage_metadata")
    except (ms.StateError, OSError, io.MemoryIOError, io.guard.PathBoundaryError):
        for row in all_rows:
            row.update(state="unavailable", reason="authorization_or_state", hits=[])

    totals = dict(confirmed=0, possible=0, unavailable=0, unknown=0, unscanned=0)
    for row in all_rows:
        if row["state"] in ("unavailable", "unknown", "unscanned"):
            totals[row["state"]] += 1
        totals["confirmed"] += sum(hit["relation"] in ("explicit", "derived") for hit in row["hits"])
        totals["possible"] += sum(hit["relation"] == "possible" for hit in row["hits"])
    target_found = any(hit["basis"] == "target_present" for row in rows.values() for hit in row["hits"])
    identity_carriers = {"memory": ("recovery",), "episode": ("episode", "archive"),
                         "judgment": ("judgment",), "calibration": ("calibration",)}
    inspected = identity_carriers.get(kind, ())
    target = ("present" if target_found else "absent_in_checked_carriers"
              if key is not None and inspected and all(rows[n]["state"] in ("checked", "absent") for n in inspected)
              else "unknown")
    report = {"version": 1, "purpose": purpose, "as_of": date.today().isoformat(),
              "current_target": target, "scope": "selected_local_snapshot",
              "unlisted_backups": "unscanned", "carriers": all_rows, "counts": totals, "truncated": False}
    if len(recovery.encode(report)) > byte_budget:
        report["truncated"] = True
        for row in all_rows:
            row.pop("hits")
    if len(recovery.encode(report)) > byte_budget:
        return {"version": 1, "scope": "partial", "truncated": True, "reason": "byte_budget"}
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--lookup-budget", type=int, default=4)
    parser.add_argument("--byte-budget", type=int, default=4096)
    parser.add_argument("--approved-backup", action="append", default=[])
    for flag in ("accept-saved", "state-read", "body-read"):
        parser.add_argument("--" + flag, action="store_true")
    parser.add_argument("--host-policy", choices=sorted(ms.POLICIES))
    parser.add_argument("--host-consent")
    args = parser.parse_args(argv)
    try:
        data = sys.stdin.buffer.read(recovery.MAX_REQUEST_BYTES + 1)
        schema.require(len(data) <= recovery.MAX_REQUEST_BYTES, "audit request exceeds input limit")
        request = schema.decode_json(data.decode("utf-8"))
        schema.require(isinstance(request, dict), "audit request must be an object")
        state = ms.MemoryState(args.memory_dir, ms.Host(
            accept_saved=args.accept_saved, state_read=args.state_read, body_read=args.body_read,
            host_policy=args.host_policy, host_consent=args.host_consent,
        ))
        report = audit(state, approved_backups=args.approved_backup, lookup_budget=args.lookup_budget,
                       byte_budget=args.byte_budget, **request)
    except (TypeError, ValueError, OSError):
        print("Memory impact request failed", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(recovery.encode(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
