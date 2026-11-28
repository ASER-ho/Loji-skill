# Loji-skill Roadmap

This file is the repository-local contract for the current release. It is
written to be readable without access to any maintainer-only workspace.

## Current release: v1.1.5

> The `loji-dsh` 1.0.1 packaging and CI changes are recorded in [CHANGELOG.md](CHANGELOG.md).

**Theme:** Memory Integrity & Experience Reliability

**Status:** RELEASED / v1.1.5.
**Authorization:** L115-DEV-01 / L115-ACCEPTANCE-REVISION-01 /
L115-CORRECTION-01 / L115-RELEASE-01.
**Implementation:** Claude. **Independent review and release:** management window.
**Branch:** implementation/loji-1.1.5-memory-integrity.
**Baseline:** 0a60f24dc477a1ba5b636f5cdde53e0461596ffb (v1.1.4).
**Accepted functional candidate:** 486e7eaf32f9d4047d398b0ce776a4b67b5266af.

Scope is limited to five modules:

| ID | Scope | Limits |
|---|---|---|
| L115-01 | Task-utility evaluation plan, single-arm scoring and paired comparison | No valid native data means NOT_RUN; deterministic checks do not replace behavior evidence |
| L115-02 | Registered evidence association in recovery cards | One read per file ID per call; expired, other-matter and conflict-suppressed candidates do not trigger reads; observe/lookup scope unchanged |
| L115-03 | Complete semantic units and truncation-safe recovery | Whole unit omitted when over budget; related decisions and Judgments suppressed when a key restriction is omitted |
| L115-04 | Read-only derivation impact and residue audit | No deletion, tombstone, archive cleanup or write; approved backups only |
| L115-05 | Four-tier historical-experience credibility | Only `reference` is usable; one experience stays local to its conditions |

L115-06 remains `RESEARCH_ONLY`. Release validation: 355 Python tests, 16 DSH
tests, official skills-ref 0.1.0, strict checks, documentation consistency,
skill budget and 12/12 deterministic retrieval. B/C behavior evidence was
collected on a synthetic Claude Code host. Exceptions are preserved rather than
rewritten: U02 exact-name recovery is 2/3; U08 has 12 state advances and three
real model-session checkpoints (the full 12-session chain is deferred to the
research pool); two runs used nine tool calls. U06 returned JADE-4 three times
per C arm with no forbidden marker exposure. No complete forgetting, stable
Token/cost/latency or task-performance gain, or automatic long-term learning is
claimed. Memory/Judgment schemas remain 2/1; `loji-dsh` remains 1.0.1.

## Previous release: v1.1.4

**Status:** RELEASED / v1.1.4. **Candidate:** `bb533271a6aaae02adf83d12d0830731bf6c9fca`.
Theme: Memory & Reasoning Enhancements. See [CHANGELOG.md](CHANGELOG.md) for
the full L114 scope, validation and limits.

## Previous release: v1.1.3

**Status:** RELEASED / v1.1.3.
**Authorization:** L113-DEV-01 / L113-CORRECTION-AND-GATE-01 / L113-RELEASE-01. **Owner:** Codex.
**Branch:** implementation/loji-1.1.3-memory-state.
**Accepted functional candidate:** b92e1c74d81a7eee1f63491ebede1060bf5b7681.
**Released baseline:** cff04c7574c2668ad3c543506bf79d905f03364c (v1.1.2).

Scope: installation-scoped memory.state.json, first-choice confirmation,
host-accepted cross-session restoration, explicit switching/reset, safe failure
and cooperative concurrency. The two state fields are memory_policy and
confirmed. Memory/Judgment schemas remain 2/1. Saved state never grants host
permissions on its own. A host must supply the trusted configured directory,
acceptance and tool capabilities. No automatic private-memory migration.

No Project Ledger, v1.1.4 retrieval ranking, consolidation or personality
evolution. L113-RELEASE-01 accepts final review and authorizes publication after
the fixed release commit passes the required local and remote CI checks.
No untested host is claimed supported. The initial environment failures are
preserved in the evidence. The verified existing standalone Win32 Codex CLI
0.167.0-alpha.4.1 and native app-server, using gpt-6.1-sol, passed the synthetic
preflight and H113-01–07 across independent sessions. Ordinary project setup
was tested through the documented one-time AGENTS.md workflow, without
injecting a saved policy or previous conversation into restoration prompts.
The 240-test regression retains all original 192 tests. Official skills-ref
0.1.0, strict validation and complete-patch replay passed final acceptance.
These results do not imply support for user-level installations,
all Codex clients, Claude Code or DSH. A pure Skill does not provide OS-level
isolation or general host permission grants. Failed saves suspend the current
session's old authorization; other sessions may still see the old saved state.
See references/CODEX_SETUP.md and
references/MEMORY.md §5.1 for support limits and the trust contract.

## Previous release: v1.1.2

**Status:** RELEASED / v1.1.2.
**Authorization:** L112-RELEASE-01. **Owner:** Codex.
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
and H112-01–04 native-host validation. Release preparation synchronized versions
and documentation and passed regression, official validation and a minimal
host smoke test. L112-RELEASE-01 authorizes publication after the final
status-only checks and CI gates. It does not authorize Project Ledger work.
At the v1.1.2 release, long-term project persistence A1–A4 was NOT_RUN and was
not a mandatory gate for that limited interface release. Subsequent
LOJI-L130-DISCOVERY-01 was partially accepted: A1, A2 and A4 PASS; A3 PARTIAL.
Original A3 recovered facts but did not autonomously use matter filtering;
the explicit-scope control does not upgrade that result. The historical
preparation isolation deviation remains part of the partial acceptance.
These results do not establish that adding a Project Ledger is necessary.
This release does not authorize v1.2 implementation.

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
