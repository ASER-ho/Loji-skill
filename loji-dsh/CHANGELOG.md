# loji-dsh changelog

## 1.0.1 — smaller install package

- Ship the runtime files without the repository banner, top-level tests, documentation or Python bytecode. The adapter bundles skill 1.1.4 and the rc.5 preset.

## 1.0.0 — independent adapter foundation

- Moved DSH-specific integration into `loji-dsh/` while keeping the repository installation URL.
- Renamed package identity from `dsh-loji` to `loji-dsh`.
- Preserved the registered skill `loji-skill` and its root skill/resource paths.
- Separated DSH package version `1.0.0` from the bundled Loji-skill version `1.1.4`.
- Reserved future preset ID `loji` and display name `长征机/逻辑`; no persona preset is shipped in this release.

## 1.0.0 release — preset, diagnostics, rc.5 snapshot

Released as tag `loji-dsh-v1.0.0`. Package version stays `1.0.0`; the bundled skill stays `1.1.4`.

- Added preset ID `loji` with display name `长征机/逻辑` alongside the `loji-skill` provider.
- Generated the persona deterministically from canonical SKILL.md and the pinned DSH standard snapshot.
- Added static YAML/schema checks, source-drift tests, and `scripts/gen-preset-patch.mjs --check`.
- Pinned the verified DSH `0.2.2-rc.1` standard snapshot (22 plugins) instead of adopting the newer `0.2.3-alpha.2` development template.
- Added read-only installation diagnostics: profile resolution, `packageDigest` + `profile.fingerprint` identification of what the host actually loaded, and a version-drift report that keeps `unknown` as a first-class outcome.
- Migrated the pinned snapshot to `0.2.2-rc.5` (23 plugins; `skill-filesystem` gains `config.customSkillDirs`, `tool-subagent-control` gains `config.interrupt: false`, `tool-office` added after `present`). `verify-install` now reports `drift: matched` and `overall: supported` (exit 0) against the installed Desktop host.
- Real Windows DSH Desktop acceptance for the 1.0.0 artifact: both modes two multiround dialogues, packaged `references/` and `research/` resolution, preset visibility, the memory contract (a conversational codename is not written to disk), an authorized memory write read back by a fresh session, and upgrade / rollback / bundle-missing conflict drills. See [Desktop acceptance](../docs/DESKTOP_ACCEPTANCE.md).
