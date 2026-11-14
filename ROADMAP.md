# Loji-skill Roadmap

This file is the repository-local contract for the current release. It is
written to be readable without access to any maintainer-only workspace.

## Current release candidate: v1.1.2

**Status:** FUNCTIONAL_ACCEPTANCE_PASS / RELEASE_PREPARATION_AUTHORIZED / NOT_RELEASED.
**Authorization:** L112-RELEASE-PREP-01. **Owner:** Codex.
**Branch:** implementation/loji-1.1.2-matters.
**Accepted functional candidate:** e8ce4a4e2e8de5db53379d16a3453617a71711d2,
based on released v1.1.1 commit a2c07cc41fe09047ccecc5c4dff747f5f920ea2f.

The only new feature is optional, caller-supplied exact matter filtering in
`context` / `--matters`. Omitting the scope preserves v1.1.1 behavior; an empty
or unmatched scope does not fall back to all matters. Authorization, full source
reads, validation, historical references and lifecycle rules remain unchanged.
Memory schema stays at 2 and Judgment schema at 1. An incomplete scope can omit
relevant conflicts; this is not automatic project identification, security
isolation or complete project recovery. No measured Token or cost saving ratio
is claimed.

The functional candidate passed 192 regression tests, official skills-ref 0.1.0
and H112-01–04 native-host validation. Release preparation synchronizes versions
and documentation, followed by regression, official validation and a minimal
host smoke test. It does not authorize publication or Project Ledger work.
Long-term project persistence A1–A4 remains NOT_RUN for future v1.2 requirements
validation and is not a mandatory gate for this limited interface release.
Push, merge, tag and release require separate authorization.

See [Memory rules](references/EPISODIC_MEMORY.md) for the interface contract.

## Released baseline: v1.1.1

**Authorization:** L111-DEV-01. **Owner:** Codex.
**Released commit:** a2c07cc41fe09047ccecc5c4dff747f5f920ea2f (tag v1.1.1).
The former v1.2 plan shipped under v1.1.1; L120 identifiers are retained.

| ID | Scope |
|---|---|
| L120-01 | Explicit Memory schema 1 → 2 migration with safe IO |
| L120-02 | Local Episodes linked to existing schema 1 Judgment IDs |
| L120-03 | Domain calibration from verified results |
| L120-04 | Current, authorized state across fresh sessions |

See [Memory rules](references/EPISODIC_MEMORY.md) for the product contract.
The acceptance commands below still apply. v1.1.1 kept the existing persona,
forms, routes, mental models, and Judgment schema.

## Released baseline: v1.1.0

**Owner:** DeepSeek (v1.0.2 and v1.1.0). Only one implementation owner is
responsible for this release.

**Branch:** `review/loji-1.1` (based on v1.0.2 commit `4f4a4cd`).

**Scope:** four judgment-continuity features. No other version work is
included.

| ID | Scope | Primary files |
|---|---|---|
| L110-01 | Judgment ledger schema, validation, safe writes, gitignore | `judgments.template.md`, `scripts/judgment_ledger.py`, `scripts/validate_judgments.py`, `.gitignore`, `tests/test_judgment_ledger.py` |
| L110-02 | Evidence-driven revision contract and compact load entry | `references/JUDGMENT_CONTINUITY.md`, `SKILL.md`, `references/MEMORY.md` |
| L110-03 | Anti-sycophancy A/B/C evals and real-host rubric | `research/evals/judgment-continuity.json`, `research/evals/JUDGMENT_RUBRIC.md`, `tests/test_judgment_evals.py` |
| L110-04 | Limited proactive association (positive and negative cases) | `references/JUDGMENT_CONTINUITY.md`, `research/evals/judgment-continuity.json`, `tests/test_judgment_evals.py` |

## Frozen baseline behavior (v1.1.0)

All v1.0.2 behavior remains frozen, including:

- Form and route are orthogonal: `军服` does not auto-trigger 统辖; `常服` does
  not auto-trigger 公仆; `征酱` is a character address, not a route trigger.
- Memory policy has four states: `auto`, `explicit`, `read_only`, `off`.
- Locked military form does not force a form switch; only expression density
  changes.
- Cross-form switches are not annotated.
- Trigger rule A: bare “地球online” and bare generic memory commands do not
  cold-start the character. They work as shorthands only when already in
  Loji role-play mode or after Loji/征酱 is explicitly mentioned.
- `memory.template.md` remains the schema skeleton (`schema_version: 1`);
  `references/MEMORY.md` holds behavior rules.

New in v1.1.0:

- `JUDGMENTS.md` is a private judgment ledger. It inherits the same
  policy/consent contract as `memory.md`; reading is denied when the policy is
  `off` or unknown, and the ledger is never read to discover the policy.
- User position is stored separately from Loji's stance. Repeated user
  opinions or a changed user attitude do not count as new evidence.
- A revision creates a new record with `supersedes`; the previous record keeps
  its original stance and basis and moves to `status: superseded`.
- Proactive association is limited to a matching `topic_key` or an explicit
  user mention, at most one historical judgment per reply.
- No automatic outbound messages, background service, daemon, database, or
  third-party dependency is added.

## Acceptance commands

Run from the repository root:

```bash
python scripts/validate_repo.py --strict
python -m unittest discover -s tests -p "test_*.py"
```

If the official validator is installed:

```bash
skills-ref validate .
```

If `skills-ref` is unavailable, record `ENV-BLOCKED`; do not substitute a
local structural check as a `skills-ref` PASS.

## Human review gates

- L110-01: schema, reference, cycle, revision-history, concurrent-write and
  failure-protection review; real user memory and real `JUDGMENTS.md` must
  never be used in tests.
- L110-02: confirm the authorization gate happens before any read, and that
  `lesson` cannot alter persona anchors, authorization boundaries, or safety
  rules.
- L110-03: 12 anti-sycophancy scenarios in a real host. Stage C must test
  re-evaluation, not a mandatory flip. JSON structure checks are not behavior
  acceptance.
- L110-04: 6 positive and 6 negative association scenarios in a real host.
- Cross-session: with authorization granted, restore a judgment across
  sessions and verify its basis; do not use real user data.

## v1.1.0 release boundaries

Do not add databases, servers, GUI, desktop pets, daemons, vector stores,
additional agent runtimes, or third-party dependencies. Do not modify
`CHANGELOG.md`, `LICENSE`, `ATTRIBUTION.md`, `research/evidence/EVIDENCE_MAP.md`,
or any real user memory/judgment file as part of this release.
