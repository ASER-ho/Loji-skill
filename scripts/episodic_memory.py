#!/usr/bin/env python3
"""Authorized local Episode and calibration operations for Loji hosts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

if __package__:
    from . import judgment_ledger, memory_io, memory_schema as schema
    from .migrate_memory import AccessError, authorize, update
else:
    import judgment_ledger
    import memory_io
    import memory_schema as schema
    from migrate_memory import AccessError, authorize, update


def _load(memory, policy, consent, *, write=False, requested=False):
    authorize(policy, consent, write=write, requested=requested)
    if write and Path(memory).is_symlink():
        raise schema.FormatError("cannot update memory through a symbolic link")
    snapshot = memory_io.read(memory)
    doc = schema.parse(snapshot.text)
    if doc.version != 2:
        raise schema.FormatError("Memory schema 1 has no Episodes; do not migrate automatically")
    return doc, snapshot


def _check_refs(episodes, judgments):
    for ep in episodes:
        schema.require(set(ep["related_judgments"]) <= judgments.keys(),
                       "Episode references an unknown Judgment ID")


def _ledger(episodes, path, policy, consent):
    if not episodes:
        return {}, None
    if path is None:
        raise AccessError("Judgment references cannot be verified without an authorized ledger")
    ledger, version = judgment_ledger.load_ledger(path, policy=policy, consent=consent)
    judgments = {j.id: j for j in ledger.judgments}
    _check_refs(episodes, judgments)
    return judgments, version


def context(memory, ledger=None, *, policy, consent, domain=None, as_of=None):
    """Project the authorized current state; no search, write, or backup reads."""
    today = as_of or date.today().isoformat()
    schema.require(schema.valid_date(today), "invalid as-of date")
    if domain is not None:
        _key(domain, "domain")
    doc, _ = _load(memory, policy, consent)
    judgments, _ = _ledger(doc.episodes, ledger, policy, consent)
    eligible = [
        ep for ep in doc.episodes
        if ep["date"] <= today and (ep["expires_on"] is None or ep["expires_on"] >= today)
    ]
    disputed = {ep["relevance"] for ep in eligible if ep["state"] == "unresolved"}
    current = []
    for ep in eligible:
        if ep["state"] != "active" or ep["relevance"] in disputed:
            continue
        active_refs = [ref for ref in ep["related_judgments"] if judgments[ref].status == "active"]
        if not active_refs:
            continue
        current.append({
            **ep,
            "related_judgments": active_refs,
            "replaces": None,  # No superseded Episode identifiers in the current view.
            "historical_judgment_ids": [
                ref for ref in ep["related_judgments"] if ref not in active_refs
            ],
        })
    active_ids = dict.fromkeys(ref for ep in current for ref in ep["related_judgments"])
    return {
        "episodes": current, "unresolved": sorted(disputed),
        "judgment_evidence": {
            ref: {"stance": judgments[ref].stance, "basis": judgments[ref].basis}
            for ref in active_ids
        },
        "calibration": doc.calibration.get(domain, {"mode": "normal"})["mode"],
    }


def _key(value, label):
    schema.require(isinstance(value, str) and schema.KEY.fullmatch(value), f"invalid {label}")
    return value


def _record_outcome(calibration, data):
    schema.require(data.keys() == {
        "domain", "id", "evidence", "completed", "disputed", "hit",
    }, "invalid outcome fields")
    domain = _key(data["domain"], "domain")
    oid = _key(data["id"], "outcome ID")
    schema.require(type(data["completed"]) is bool and type(data["disputed"]) is bool,
                   "outcome requires explicit completion/dispute flags")
    if not data["completed"] or data["disputed"] or not schema.nonempty(data["evidence"]):
        return False
    schema.require(type(data["hit"]) is bool, "verified outcome needs a hit or a miss")
    old = calibration.get(domain, {}).get("outcome_ids", {})
    if oid in old:
        schema.require(old[oid] is data["hit"], "conflicting result for existing outcome ID")
        return False
    outcomes = {**old, oid: data["hit"]}
    calibration[domain] = {**schema.outcome_stats(outcomes), "outcome_ids": outcomes}
    return True


def _add_episode(episodes, data):
    record = dict(data)
    replaces = record.pop("replaces", None)
    record.setdefault("id", f"E-{uuid4().hex}")
    record.setdefault("expires_on", None)
    schema.require("state" not in record, "new Episode state is assigned by the writer")
    record["state"] = "active"
    if replaces is not None:
        schema.require(record.get("kind") == "correction_or_learning",
                       "replacement must be a correction")
        old = _find(episodes, replaces)
        schema.require(old["state"] in ("active", "unresolved") and
                       old["relevance"] == record.get("relevance") and
                       schema.valid_date(record.get("date")) and old["date"] <= record["date"],
                       "invalid correction target")
        old["state"] = "corrected"
    record["replaces"] = replaces
    episodes.append(record)
    return record["id"]


def _find(episodes, eid):
    for ep in episodes:
        if ep["id"] == eid:
            return ep
    raise schema.FormatError("Episode not found")


def mutate(
    memory, ledger, action, data, *, policy, consent,
    user_requested=False, eligible_and_private=False,
):
    """The host attests to the semantic and privacy checks before any write.

    Maintenance requires a specific user request here even in auto mode.
    The same ID never identifies two Episodes in one Memory document.
    """
    if action not in ("add", "transition", "forget", "outcome", "forget-domain"):
        raise schema.FormatError("unknown Memory operation")
    authorize(policy, consent, write=True, requested=user_requested is True)
    if action in ("add", "outcome") and eligible_and_private is not True:
        raise AccessError("host must verify semantic eligibility and privacy before recording")
    if action in ("transition", "forget", "forget-domain") and user_requested is not True:
        raise AccessError("maintenance requires a specific user request")
    schema.require(isinstance(data, dict), "operation requires a JSON object")
    doc, snapshot = _load(memory, policy, consent, write=True, requested=user_requested is True)
    _, ledger_version = _ledger(doc.episodes, ledger, policy, consent)
    eid = None
    if action == "add":
        eid = _add_episode(doc.episodes, data)
    elif action == "transition":
        schema.require(data.keys() == {"id", "state"}, "invalid transition fields")
        ep = _find(doc.episodes, data["id"])
        schema.require(
            ep["state"] in ("active", "unresolved") and
            data["state"] in ("archived", "deprecated", "unresolved"),
            "cannot reactivate or overwrite historical Episodes",
        )
        ep["state"] = data["state"]
    elif action == "forget":
        schema.require(data.keys() == {"id"}, "invalid forget fields")
        doc.episodes.remove(_find(doc.episodes, data["id"]))
        for ep in doc.episodes:
            if ep["replaces"] == data["id"]:
                ep["replaces"] = None
    elif action == "outcome":
        if not _record_outcome(doc.calibration, data):
            return {"status": "no_op"}
    elif action == "forget-domain":
        schema.require(data.keys() == {"domain"}, "invalid forget-domain fields")
        if doc.calibration.pop(_key(data["domain"], "domain"), None) is None:
            return {"status": "no_op"}

    schema.validate_episodes(doc.episodes)
    schema.validate_calibration(doc.calibration)
    if action == "add":
        _, checked = _ledger(doc.episodes, ledger, policy, consent)
        if ledger_version is not None and checked != ledger_version:
            raise memory_io.MemoryConflictError("Judgment ledger changed; re-read before writing")
    rendered = doc.render_v2()
    schema.parse(rendered)
    result = update(Path(memory), rendered, snapshot)
    return {"status": "updated", "id": eid, "backup": str(result.backup_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("context", "add", "transition", "forget", "outcome", "forget-domain"))
    parser.add_argument("--memory", required=True)
    parser.add_argument("--ledger")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--consent", required=True)
    parser.add_argument("--domain")
    parser.add_argument("--as-of", help="defaults to the local calendar date")
    parser.add_argument("--user-requested", action="store_true")
    parser.add_argument("--eligible-and-private", action="store_true",
                        help="assert the host performed semantic eligibility and privacy checks")
    args = parser.parse_args(argv)
    auth = {"policy": args.policy, "consent": args.consent}
    try:
        if args.action == "context":
            result = context(args.memory, args.ledger, domain=args.domain, as_of=args.as_of, **auth)
        else:
            authorize(**auth, write=True, requested=args.user_requested)
            data = schema.decode_json(sys.stdin.buffer.read().decode("utf-8"))
            result = mutate(
                args.memory, args.ledger, args.action, data, user_requested=args.user_requested,
                eligible_and_private=args.eligible_and_private, **auth,
            )
    except (OSError, ValueError, memory_io.MemoryIOError, judgment_ledger.JudgmentLedgerError) as exc:
        print(f"Memory operation refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
