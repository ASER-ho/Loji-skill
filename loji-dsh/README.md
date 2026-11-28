# loji-dsh — DeepSeek Harness adapter

This directory contains the DSH-specific integration for the main [Loji-skill](../README.md) project. It is not a second skill repository.

| Identifier | Value |
| --- | --- |
| Package name | loji-dsh |
| Current package version | 1.0.1 |
| Registered skill name | loji-skill |
| Current bundled skill version | 1.1.5 (from root SKILL.md) |
| Reserved preset ID | loji |
| Reserved preset display name | 长征机/逻辑 |

The root package.json remains the sole DSH installation manifest; it points into this directory. The provider reads the canonical root SKILL.md and uses the root as resource base for references/ and research/. The generated Cordis patch embeds only the selected canonical persona rules; it is not a separate authoritative source.

## Version policy

The new package name loji-dsh starts at 1.0.0 (the former package dsh-loji was a different package identity). **Pure upstream skill content/version syncs do not change the adapter version.** Changes to DSH integration or the loji-dsh package version require maintainer review. Record and compare actual Git commit hashes for content updates: a deliberately fixed package version cannot communicate every revision and may not trigger conventional version-based update detection.

To sync the bundled skill's metadata after a SKILL.md change, from repository root run:

```bash
npm run sync:meta
npm run check:meta
npm test
```

The curated skill description is kept in loji-dsh/lib/skill-meta.json. The sync script derives only skill name and version from root SKILL.md.

## Installation and migration

The repository URL is unchanged: `dsh plugin add github:ASER-ho/Loji-skill`. Its package identity has changed to loji-dsh. Before installing, inspect any prior dsh-loji installation and remove it to avoid double registration. A user-supplied filesystem skill with the same name may take precedence; do not delete user-owned files automatically.

## Preset implementation

Preset ID `loji` is displayed as `长征机/逻辑`. `cordis.patch.yml` declares both the host `loji-skill` provider and the agent preset. `scripts/gen-preset-patch.mjs` deterministically rebuilds the patch from the pinned DSH standard snapshot (`0.2.2-rc.5`, source repository version) and the authoritative character/permission sections in root `SKILL.md`. No unverified 111-line standalone persona is copied or claimed. The standard tool list is otherwise retained unchanged. The pinned snapshot is reproduced from official DSH commit `9c2670d3bce5275e0d1610272958121af87787bb` (web-app `0.2.2-rc.5`).

Use `npm run gen:preset` to regenerate and `npm run check:preset` to check drift. `python loji-dsh/scripts/validate_patch.py` parses DSH's `!!js` tags as *unevaluated strings* to validate structure, counts and persona content. Mode visibility and service wiring were observed in a real DSH Desktop host (`0.2.2-rc.5`): the preset appears in a new session, both modes complete two real multiround dialogues, and the four runtime services report `supported`. See [Desktop acceptance](../docs/DESKTOP_ACCEPTANCE.md).

## Packaged artifact and Desktop acceptance

The CI also runs `npm pack`, extracts the **actual distributable archive**, imports its plugin entrypoint, registers the `loji-skill` candidate with a test service, loads the bundled root `SKILL.md`, and checks that the preset patch and referenced resources were included. This is a stronger packaging check than checking source files alone, but does **not** prove DSH Desktop has mounted the plugin.

**Target template:** DSH Web App `0.2.2-rc.5` public snapshot (23 top-level preset entries). It was migrated from the earlier `0.2.2-rc.1` snapshot after the real diff was reduced to three changes: `skill-filesystem` gained `config.customSkillDirs`, `tool-subagent-control` gained `config.interrupt: false`, and `tool-office` was added after `present`. The installed Desktop host is `0.2.2-rc.5`, so the diagnostic now reports `drift: matched` and `overall: supported`. Compare its installed `standard.patch.yml` and available modules first; a future host version that differs is reported as `unknown` rather than assumed compatible.

### Read-only installation diagnostics

Run from the repository or an extracted package with Node.js 22 or later.

```powershell
node loji-dsh/scripts/verify-install.mjs --home 'C:\path\to\isolated-dsh' --profile web
node loji-dsh/scripts/verify-install.mjs --package-root .
node loji-dsh/scripts/gen-preset-patch.mjs --check --host-standard 'C:\path\to\standard.patch.yml' --host-version 0.2.3-alpha.2
```

`--home` defaults to the calling process's `DSH_HOME` when set, then uses the home reported by the DSH shell. Supply the profile ID from the active launch or host diagnostics. With no explicit profile, resolution requires one candidate directory and matching DSH launcher facts or an operator observation. Multiple candidates, conflicting evidence and unavailable files produce an `unknown` result. `--package-root` can inspect a package independently or confirm an intentionally linked package. A runtime result requires that the path match the selected profile's installed package. [DSH shell environment](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/shell/shell-env/README.md)

The script reads the selected profile's package manifest and the Loji bundle's entrypoint, metadata, preset and resources. The resource stage includes the recovery guide and its Python runtime dependencies in the package fingerprint. A missing resource fails the stage and invalidates previous observations.

The diagnostic looks for `@deepseek-ai/dsh-web-app/presets/standard.patch.yml` in the installation reported by a matching DSH launcher, then in the profile's own packages if the launcher was unavailable. For layouts that ship the standard template elsewhere, pass its path and the observed runtime version with `--host-standard` and `--host-version`. An explicit template still requires agreement with any discovered launcher version and shipped template. A conflict, a version mismatch or an unrecognized template layout leaves compatibility unknown. The report lists added or missing top-level plugin IDs, changed stanza fields and order changes. [Upstream Standard preset](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/web-app/presets/standard.patch.yml)

After testing the installed bundle in the real host, copy the diagnostic report's `profile.fingerprint` and `packageDigest` into a local observations JSON file. Record only measured booleans and the actual provider rank. Omit any check you could not observe. Use `--observations <file>` to associate the results with the selected installation. This records operator observations, which should be refreshed after changes to the profile, package or host. A synthetic observations file tests the diagnostic contract only. Keep transcripts, credentials, local paths and raw configuration out of the observations file.

```json
{
  "profileId": "web",
  "profileFingerprint": "<from report>",
  "packageDigest": "<from report>",
  "kind": "web",
  "hostVersion": "0.2.2-rc.5",
  "checks": {
    "entryLoaded": true,
    "providerRegistered": true,
    "providerSelected": true,
    "providerRank": 600,
    "presetLoaded": true,
    "presetSelected": true,
    "presetResources": true,
    "standardResources": true,
    "presetDialogue": true,
    "standardDialogue": true,
    "sessionController": true
  }
}
```

Check the loaded plugin rows in DSH's Built-in plugins screen. Select the Loji preset and invoke `skill("loji-skill")`. Confirm the winning provider and resolve a packaged `references/` and `research/` file. Repeat resource resolution in Standard mode and record the outcome of real multiround dialogue in both modes. Verify session creation and mode changes before marking `sessionController`. Record the exact tested commit separately.

The install check exits with 0 for a matching template and complete observations, 1 for a failed stage, and 2 for insufficient or conflicting evidence. The preset generation check exits with 1 for a stale generated artifact and 2 when an explicitly supplied host template remains unmatched or unavailable.

**Real Windows/DSH acceptance (executed 2026-11-26, DSH Desktop `0.2.2-rc.5`):** recorded results, including digests, drill outcomes and the drift limitation, are in [Desktop acceptance](../docs/DESKTOP_ACCEPTANCE.md). The procedure for a fresh host remains: first record the currently installed `dsh-loji` bundle and any custom `loji-skill` copies; back up affected profile configuration. For a controlled test, install the exact commit of this PR using the DSH plugin manager, then inspect its plugin diagnostic for both `loji-skill` and `preset-loji`. Open a new session, select `长征机/逻辑`, verify that the role persists across ordinary turns, and invoke `skill("loji-skill")` to confirm which provider and file actually won. Also verify Standard mode remains unchanged. Record the tested Desktop version, exact Git commit, observed roster and tool output, and any errors. Do not claim this acceptance passed until those observations exist.
