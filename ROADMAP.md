# Loji-skill Roadmap

This file is the repository-local contract for the current release. It is
written to be readable without access to any maintainer-only workspace.

## Current release: v1.0.2

**Owner:** DeepSeek (reassigned by the user in the project management
instruction; the original planning document listed Codex for some features).
Only one implementation owner is responsible for this release.

**Scope:** four frozen features. No v1.1+ functionality is included.

| ID | Scope | Primary files |
|---|---|---|
| L102-01 | Agent Skills compliance and progressive loading | `SKILL.md`, `references/MEMORY.md`, `references/EXAMPLES.md`, `README.md`, `README_EN.md`, `memory.template.md`, `references/domain-knowledge.md` |
| L102-02 | Runtime state-machine consistency | `references/STATE_MACHINES.md`, `references/STYLE.md`, `references/LORE.md`, `tests/fixtures/state_invariants.json`, `tests/test_state_invariants.py` |
| L102-03 | Memory atomic write and safe initialization | `scripts/memory_io.py`, `scripts/init_memory.py`, `tests/test_memory_io.py`, `.gitignore` |
| L102-04 | Deterministic validator, eval cleanup, CI | `scripts/validate_repo.py`, `tests/test_validate_repo.py`, `.github/workflows/validate.yml`, `research/evals/*`, `ROADMAP.md` |

## Frozen behavior in this release

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

- L102-01: diff review to confirm no persona, safety, permission, or memory
  rule was lost.
- L102-02: eight conflict prompts, run manually in a real host.
- L102-03: failure-injection and concurrent-write review; real user memory
  must never be used in tests.
- L102-04: release review; automatic tests passing is not a substitute for
  real-host character activation and cold-start tests.

## Boundaries

Do not add databases, servers, GUI, desktop pets, daemons, vector stores,
additional agent runtimes, or third-party dependencies. Do not modify
`CHANGELOG.md`, `LICENSE`, `ATTRIBUTION.md`, `research/evidence/EVIDENCE_MAP.md`,
or any real user memory file as part of this release.
