# loji-dsh — DeepSeek Harness adapter

This directory contains the DSH-specific integration for the main [Loji-skill](../README.md) project. It is not a second skill repository.

| Identifier | Value |
| --- | --- |
| Package name | loji-dsh |
| Initial package version | 1.0.0 |
| Registered skill name | loji-skill |
| Current bundled skill version | 1.1.4 (from root SKILL.md) |
| Reserved preset ID | loji |
| Reserved preset display name | 长征机/逻辑 |

The root package.json remains the sole DSH installation manifest; it points into this directory. The provider reads the canonical root SKILL.md and uses the root as resource base for references/ and research/. No skill content is duplicated.

## Version policy

The new package name loji-dsh starts at 1.0.0 (the former package dsh-loji was a different package identity). **Pure upstream skill content/version syncs do not change loji-dsh's 1.0.0.** Changes to DSH integration or the loji-dsh package version require maintainer review. Record and compare actual Git commit hashes for content updates: a deliberately fixed package version cannot communicate every revision and may not trigger conventional version-based update detection.

To sync the bundled skill's metadata after a SKILL.md change, from repository root run:

```bash
npm run sync:meta
npm run check:meta
npm test
```

The curated skill description is kept in loji-dsh/lib/skill-meta.json. The sync script derives only skill name and version from root SKILL.md.

## Installation and migration

The repository URL is unchanged: `dsh plugin add github:ASER-ho/Loji-skill`. Its package identity has changed to loji-dsh. Before installing, inspect any prior dsh-loji installation and remove it to avoid double registration. A user-supplied filesystem skill with the same name may take precedence; do not delete user-owned files automatically.

## Preset status

The intended character mode is ID `loji`, displayed as `长征机/逻辑`. This foundation changes only provider packaging and does not ship a preset or claim runtime mode availability. The separate persona source described in the earlier draft is not in this repository; implement the preset after obtaining the actual source and validating it against the target DSH version.
