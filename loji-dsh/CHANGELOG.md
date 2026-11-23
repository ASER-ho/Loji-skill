# loji-dsh changelog

## 1.0.0 — independent adapter foundation

- Moved DSH-specific integration into `loji-dsh/` while keeping the repository installation URL.
- Renamed package identity from `dsh-loji` to `loji-dsh`.
- Preserved the registered skill `loji-skill` and its root skill/resource paths.
- Separated DSH package version `1.0.0` from the bundled Loji-skill version `1.1.4`.
- Reserved future preset ID `loji` and display name `长征机/逻辑`; no persona preset is shipped in this release.

## Preset integration (unreleased, same package 1.0.0 pending maintainer acceptance)

- Added preset ID `loji` with display name `长征机/逻辑` alongside `loji-skill` provider.
- Generated persona deterministically from canonical SKILL.md, pinned to DSH standard snapshot.
- Added static YAML/schema checks and source-drift tests. DSH Desktop end-to-end behavior remains unverified.

- Pin the verified DSH `0.2.2-rc.1` standard snapshot (22 plugins) to match the original target environment rather than using the newer `0.2.3-alpha.2` development template.
