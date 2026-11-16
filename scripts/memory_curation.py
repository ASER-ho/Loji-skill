#!/usr/bin/env python3
"""Read-only consolidation suggestions for Loji Memory.

This tool never writes bodies. Cooperative state-lock bookkeeping is permitted.
It only classifies machine-readable Episodes so a human
can decide whether to apply an existing authorized operation. It deliberately
does not use semantic similarity, vectors, a model, a database or a daemon.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

if __package__:
    from . import judgment_ledger, memory_io, memory_schema as schema, memory_state, episodic_memory
else:
    import judgment_ledger
    import memory_io
    import memory_schema as schema
    import memory_state
    import episodic_memory

PROTECTED_STATES = frozenset({"unresolved", "corrected", "deprecated", "archived"})
CAPACITY_NOTICE = 45


@contextmanager
def _load(state):
    # One state transaction covers both body reads, reference validation and
    # suggestion generation. No caller-supplied policy can replace saved state.
    with state.access() as auth:
        doc, _ = episodic_memory._load(state.folder / "memory.md", **auth.body_args())
        episodic_memory._ledger(doc.episodes, state.folder / "JUDGMENTS.md", **auth.body_args())
        yield doc


def suggest(state, *, as_of=None):
    with _load(state) as doc:
        return analyze(doc, as_of=as_of)


def _key(ep):
    return (
        ep["relevance"], ep["kind"], ep["date"], ep["summary"],
        ep["outcome"], ep["retention"], ep["expires_on"], ep["state"],
        tuple(sorted(ep["related_judgments"])),
    )


def _protected(ep):
    return (
        ep["retention"] == "permanent"
        or ep["state"] in PROTECTED_STATES
        or ep["replaces"] is not None
        or ep["kind"] == "correction_or_learning"
    )


def _group(items, key):
    groups = {}
    for ep in items:
        groups.setdefault(key(ep), []).append(ep)
    return [group for group in groups.values() if len(group) > 1]


def _ids(items):
    return sorted(ep["id"] for ep in items)


def analyze(doc, *, as_of=None):
    today = as_of or date.today().isoformat()
    schema.require(schema.valid_date(today), "invalid as-of date")
    episodes = doc.episodes
    disputed = {ep["relevance"] for ep in episodes if ep["state"] == "unresolved"}
    chain_ids = {ep["replaces"] for ep in episodes if ep["replaces"] is not None}
    # Legacy sections are deliberately opaque. Any substantive legacy content
    # may protect an Episode without naming its ID; do not guess its scope.
    uncertain_protection = any(re.sub(r"<!--.*?(?:-->|$)", "",
        doc.text[slice(*doc.sections[name][1:])], flags=re.S).strip() for name in schema.SECTIONS)

    def protected(ep):
        return (_protected(ep) or ep["id"] in chain_ids or ep["relevance"] in disputed
                or uncertain_protection or ep["date"] > today
                or (ep["expires_on"] is not None and ep["expires_on"] < today))

    exact = []
    for group in sorted(_group(episodes, _key), key=lambda g: _ids(g)):
        blocked = any(protected(ep) for ep in group)
        exact.append({
            "type": "exact_duplicate",
            "relevance": group[0]["relevance"],
            "ids": _ids(group),
            "proposed_keep": None if blocked else min(ep["id"] for ep in group),
            "action": "review_only" if blocked else "review_merge",
            "protected": blocked,
        })

    reinforcement = []
    def reinforcement_key(ep):
        return (ep["relevance"], ep["kind"], ep["date"])
    for group in sorted(_group(
        [ep for ep in episodes if ep["state"] == "active"], reinforcement_key
    ), key=lambda g: _ids(g)):
        if len({ep["summary"] for ep in group}) > 1 and not any(
            protected(ep) for ep in group
        ):
            reinforcement.append({
                "type": "evidence_reinforcement_candidate",
                "relevance": group[0]["relevance"],
                "date": group[0]["date"],
                "ids": _ids(group),
                "action": "review_only",
            })

    series = []
    by_matter = {}
    for ep in episodes:
        by_matter.setdefault((ep["relevance"], ep["kind"]), []).append(ep)
    for (relevance, kind), group in sorted(by_matter.items()):
        dates = {ep["date"] for ep in group}
        if len(dates) > 1:
            series.append({
                "type": "different_time_event",
                "relevance": relevance,
                "kind": kind,
                "ids": _ids(group),
                "action": "keep_all",
            })

    conflicts = []
    unresolved_by_matter = {}
    for ep in episodes:
        if ep["state"] == "unresolved":
            unresolved_by_matter.setdefault(ep["relevance"], []).append(ep)
    for relevance, group in sorted(unresolved_by_matter.items()):
        conflicts.append({
            "type": "unresolved_conflict",
            "relevance": relevance,
            "ids": _ids(group),
            "suppressed_active_ids": _ids([
                ep for ep in episodes
                if ep["relevance"] == relevance and ep["state"] == "active"
            ]),
            "action": "do_not_merge",
        })

    lifecycle = {
        "expired_active": sorted(
            ep["id"] for ep in episodes
            if ep["state"] == "active" and ep["expires_on"] is not None
            and ep["expires_on"] < today
        ),
        "future_active": sorted(
            ep["id"] for ep in episodes if ep["state"] == "active" and ep["date"] > today
        ),
    }
    active_count = sum(ep["state"] in ("active", "unresolved") for ep in episodes)
    result = {
        "mode": "suggestions_only",
        "writes": 0,
        "as_of": today,
        "schema_version": doc.version,
        "counts": {
            "episodes": len(episodes),
            "active_or_unresolved": active_count,
            "capacity": schema.MAX_ACTIVE,
        },
        "exact_duplicate_groups": exact,
        "evidence_reinforcement_candidates": reinforcement,
        "different_time_series": series,
        "conflicts": conflicts,
        "lifecycle": lifecycle,
        "protected_policy": (
            "permanent, unresolved, corrected, deprecated, archived and correction "
            "chains are never proposed for merge or removal"
        ),
        "legacy_protection_uncertain": bool(uncertain_protection),
        "limitations": [
            "No semantic similarity: paraphrased duplicates may be missed.",
            "Free-text legacy sections are not classified; they stay human-managed.",
            "Absence of suggestions does not mean the memory is clean.",
            "Applying a suggestion requires a separate authorized write via the existing entry point.",
        ],
    }
    if active_count >= CAPACITY_NOTICE:
        result["lifecycle"]["capacity_notice"] = (
            f"{active_count} active/unresolved Episodes; limit is {schema.MAX_ACTIVE}"
        )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", required=True, help="absolute directory from trusted host configuration")
    for flag in ("accept-saved", "state-read", "body-read"):
        parser.add_argument("--" + flag, action="store_true")
    parser.add_argument("--host-policy", choices=sorted(memory_state.POLICIES))
    parser.add_argument("--host-consent")
    parser.add_argument("--as-of", help="defaults to the local calendar date")
    args = parser.parse_args(argv)
    try:
        host = memory_state.Host(accept_saved=args.accept_saved, state_read=args.state_read,
            body_read=args.body_read, host_policy=args.host_policy, host_consent=args.host_consent)
        state = memory_state.MemoryState(args.memory_dir, host)
        result = suggest(state, as_of=args.as_of)
    except (OSError, ValueError, memory_io.MemoryIOError,
            judgment_ledger.JudgmentLedgerError) as exc:
        print(f"Memory curation refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
