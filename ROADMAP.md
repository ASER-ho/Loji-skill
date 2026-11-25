# Loji-skill Roadmap

This file is the repository-local contract for the current release. It is
written to be readable without access to any maintainer-only workspace.

## Current release: v1.1.4

> **Unreleased work on `master`:** the `loji-dsh` agent preset
> (`feat(loji-dsh): add 长征机/逻辑 agent preset (#2)`) and the engineering
> hardening batch are recorded under `## Unreleased` in `CHANGELOG.md`. They are
> not part of v1.1.4 and have not completed real desktop acceptance.

**Theme:** Memory & Reasoning Enhancements

**Status:** RELEASED / v1.1.4.
**Authorization:** L114-DEV-01 / L114-FINAL-GATE-01 /
L114-CONTEXT-FIX-01 / L114-RELEASE-01.
**Implementation:** Claude. **Independent review, correction, host validation
and release:** Codex.
**Branch:** implementation/loji-1.1.4-core-enhancements.
**Baseline:** 9001e1fcc3b67e0822f5528951ae4390cd5c65da (v1.1.3).
**Accepted functional candidate:** bb533271a6aaae02adf83d12d0830731bf6c9fca.

Scope is limited to five modules:

| ID | Scope | Limits |
|---|---|---|
| L114-01 | Unified behavior-eval protocol, fixed fidelity/retrieval/evidence samples, deterministic harness | No third-party eval platform or model service; scoring fixed before behavior runs |
| L114-02 | On-demand loading, joint ordinary-Memory/context project recovery, matter discovery, single-transaction reuse | One authorized full-context fallback when scope remains incomplete and the user has not limited it; no filesystem-wide scan, automatic project map or new retrieval algorithm |
| L114-03 | Evidence tiers in existing `basis`, re-verification and partial-invalidation rules | No new ledger fields or schema migration; validator checks structure only |
| L114-04 | Duplicate taxonomy and read-only consolidation suggestions | No automatic merge/delete, background job or database; Memory/Judgment schema stay 2/1 |
| L114-05 | Positive behavior phrasing, persona-structure audit, source provenance | Core anchors, routes, forms, models and heuristics unchanged; no third-party character identities |

L114-DEV-01 delivered 277 tests. L114-FINAL-GATE-01 independently reviewed and
corrected authorization, legacy-basis compatibility and objective scoring
evidence; 301 tests and H114-01, 02, 04, 05 plus H113-01–07 passed. The initial
engineering host environment block was resolved using the verified standalone
Codex 0.167.0-alpha.4.1 native app-server and an actually available model.
These are v1.1.4 host executions, not transferred v1.1.3 acceptance.

Historical H114-03 remains PARTIAL. After the joint recovery and scope-fallback
correction, L114-CONTEXT-FIX-01 R1–R4 passed: original small data, two independent
large-data sessions and the exact-scope control recovered all six frozen fact
groups; nonprefix related matters and ambiguous ownership were also checked.
Ordinary Memory facts cannot be replaced by Episode output, and raw historical
Episodes remain subject to existing context and judgment validation. User scope
restrictions, fresh authorization, locks and host limits remain in effect.

The final 309-test regression retains all 240 formal baseline tests. Strict
checks, official skills-ref 0.1.0 and complete-patch replay passed. Host evidence
covers project-level Codex installation and fixed synthetic data, with off body
reads and all read_only body writes at zero, and host denial overriding saved
auto. It does not establish automatic recovery across all scales, models,
installation methods or hosts; Claude Code and DSH were not accepted here.
No significant persona or judgment score improvement, stable Token, cost,
latency or overall task-performance benefit is claimed. Curation remains
suggestions only. No Project Ledger, database, vector index, background service
or new Memory/Judgment schema is introduced. L114-RELEASE-01 authorizes release
after final document-only local checks and branch/master/tag CI gates.

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
