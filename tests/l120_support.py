"""Adapt the untouched synthetic research envelope to shipped formats."""

import json
from pathlib import Path

from scripts import judgment_ledger as jl, memory_schema as schema

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/l120"
GROUPS = json.loads((FIXTURES / "scenarios.synthetic.json").read_text(encoding="utf-8"))["groups"]
RECORDS = json.loads((FIXTURES / "judgments.synthetic.json").read_text(encoding="utf-8"))["records"]
AS_OF = "2040-01-04"


def ledger_text(records, *, resolve_status=True):
    records = [dict(record) for record in records]
    if resolve_status:
        superseded = {record["supersedes"] for record in records}
        for record in records:
            if record["id"] in superseded:
                record["status"] = "superseded"
    return ('---\nschema_version: 1\nskill_version: "1.1.0"\n---\n\n' +
            "\n\n".join(jl.render_judgment(jl.Judgment(**record)) for record in records))


def fresh_memory(episodes=(), calibration=None):
    template = (ROOT / "memory.template.md").read_text(encoding="utf-8")
    doc = schema.parse(template)
    doc.episodes[:] = episodes
    doc.calibration.update(calibration or {})
    return doc.render_v2()


def episode(record, *, state="active", kind=None, expires_on=None):
    return dict(
        record, state=state, expires_on=expires_on, replaces=None,
        kind=kind or ("actual_outcome" if record["outcome"] else "important_joint_decision"),
    )


def production_state(case):
    """Use only the B input; no A transcript, oracle or test instructions."""
    files = case["state_files"]
    wrappers = files["memory.synthetic.md"]["episodes"]
    records = list(files["judgments.synthetic.json"]["records"])
    episodes = []
    predecessors = {w["replaced_by"]: w["record"]["id"] for w in wrappers if "replaced_by" in w}
    for wrapped in wrappers:
        record = dict(wrapped["record"])
        if not record["related_judgments"]:
            # Prep allowed empty refs. Use a separate local synthetic judgment,
            # never point these rows at the unrelated numbered-label judgment.
            key = "J-REF-" + record["id"]
            records.append({
                **RECORDS[-1], "id": key, "topic_key": key, "topic": record["relevance"],
                "stance": record["summary"], "basis": ["虚构状态适配证据。"],
                "created_at": record["date"], "updated_at": record["date"],
                "user_position": "unknown",
                "status": "retracted" if wrapped["lifecycle"] == "corrected" else "active",
            })
            record["related_judgments"] = [key]
        state = "unresolved" if wrapped.get("conflict") == "unresolved" else wrapped["lifecycle"]
        expiry = record["date"] if wrapped.get("context_validity") == "expired" else None
        replaces = predecessors.get(record["id"])
        kind = "correction_or_learning" if replaces else None
        row = episode(record, state=state, expires_on=expiry, kind=kind)
        row["replaces"] = replaces
        episodes.append(row)
    return fresh_memory(episodes), ledger_text(records)
