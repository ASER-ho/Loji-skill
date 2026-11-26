import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { verifyInstallation } from "../lib/diagnostics.js";
import { compareStandard, isBelow } from "../lib/host-capabilities.js";
import { normalizeNewlines, PATCH_PATH, renderPreset, SNAPSHOT_PATH, SNAPSHOT_VERSION } from "../lib/preset.js";

const repository = fileURLToPath(new URL("../../", import.meta.url));
const read = (name) => readFileSync(join(repository, name), "utf8");
const template = normalizeNewlines(read(SNAPSHOT_PATH));
const skill = read("SKILL.md");
const validChecks = {
  entryLoaded: true, providerRegistered: true, providerSelected: true, providerRank: 600,
  presetLoaded: true, presetSelected: true, presetResources: true, standardResources: true,
  presetDialogue: true, standardDialogue: true, sessionController: true,
};

function write(root, name, value) {
  const path = join(root, name);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, typeof value === "string" ? value : JSON.stringify(value), "utf8");
  return path;
}

function fixture(t) {
  const home = mkdtempSync(join(tmpdir(), "loji-dsh-diagnostics-"));
  t.after(() => {
    const directory = realpathSync(home);
    assert.ok(isBelow(realpathSync(tmpdir()), directory));
    rmSync(directory, { recursive: true, force: true });
  });
  const profileRoot = join(home, "profiles", "web");
  const packageRoot = join(profileRoot, "node_modules", "loji-dsh");
  const webAppRoot = join(profileRoot, "node_modules", "@deepseek-ai", "dsh-web-app");
  const profileManifest = { dsh: { profile: { bundles: ["@deepseek-ai/dsh-base", "loji-dsh"] } } };
  const profileFile = write(profileRoot, "package.json", profileManifest);
  write(packageRoot, "package.json", read("package.json"));
  write(packageRoot, "loji-dsh/lib/index.js", 'throw new Error("Offline checks must not execute the entrypoint");');
  write(packageRoot, "loji-dsh/lib/skill-meta.json", read("loji-dsh/lib/skill-meta.json"));
  write(packageRoot, "SKILL.md", skill);
  write(packageRoot, SNAPSHOT_PATH, template);
  write(packageRoot, PATCH_PATH, renderPreset(skill, template));
  for (const directory of ["references", "research", "scripts"]) {
    cpSync(join(repository, directory), join(packageRoot, directory), { recursive: true });
  }
  write(webAppRoot, "package.json", { name: "@deepseek-ai/dsh-web-app", version: SNAPSHOT_VERSION });
  write(webAppRoot, "presets/standard.patch.yml", template);
  return { home, profileRoot, packageRoot, profileFile, webAppRoot };
}

function runtimeObservation(report, overrides = {}) {
  return {
    profileId: report.profile.id, profileFingerprint: report.profile.fingerprint,
    kind: "web", hostVersion: SNAPSHOT_VERSION, packageDigest: report.packageDigest,
    checks: validChecks, ...overrides,
  };
}

test("offline body identifies the static bundle while runtime support stays unknown", (t) => {
  const { home, profileFile } = fixture(t);
  const bytes = readFileSync(profileFile);
  const options = { home, profileId: "web" };
  const report = verifyInstallation(options);
  assert.equal(report.overall, "unknown");
  assert.equal(report.profile.confidence, "low");
  assert.equal(report.profile.kind, "unknown");
  assert.equal(report.drift.status, "matched");
  assert.match(report.packageDigest, /^[0-9a-f]{64}$/);
  assert.equal(report.stages.package.status, "pass");
  assert.equal(report.stages.persona.status, "pass");
  assert.equal(report.stages.entry.code, "entrypoint_found_loading_unverified");
  assert.equal(report.stages.skillProvider.expectedRank, 600);
  assert.equal(report.stages.resources.status, "unknown");
  assert.equal(report.stages.modes.status, "unknown");
  assert.deepEqual(readFileSync(profileFile), bytes);
  assert.ok(!JSON.stringify(report).includes(home));
});

test("separate, scoped observations distinguish full support, partial support, and failures", (t) => {
  const { home, profileRoot } = fixture(t);
  const options = { home, profileId: "web" };
  const report = verifyInstallation(options);
  const observation = runtimeObservation(report);
  const accepted = verifyInstallation({ ...options, observation });
  assert.equal(accepted.overall, "supported");
  assert.equal(accepted.profile.kind, "web");
  assert.equal(accepted.services.skills, "supported");
  assert.equal(accepted.services.sessionController, "supported");
  assert.equal(accepted.stages.entry.evidence, "operator_observation");

  const standalone = verifyInstallation({ home, observation });
  assert.equal(standalone.profile.source, "runtime_observation");
  assert.equal(standalone.overall, "supported");

  const missingMode = verifyInstallation({ ...options, observation: {
    ...observation, checks: { ...validChecks, standardDialogue: undefined },
  } });
  assert.equal(missingMode.overall, "unknown");
  assert.equal(missingMode.stages.modes.status, "unknown");
  const shadowed = verifyInstallation({ ...options, observation: {
    ...observation, checks: { ...validChecks, providerSelected: false, providerRank: 400 },
  } });
  assert.equal(shadowed.overall, "unsupported");
  assert.equal(shadowed.services.skills, "unsupported");

  write(profileRoot, "package.json", { dsh: { profile: { bundles: ["loji-dsh"] } } });
  const changed = verifyInstallation({ ...options, observation });
  assert.equal(changed.overall, "unknown");
  assert.equal(changed.services.skills, "unknown");
});

test("missing, ambiguous, mismatched, and explicitly selected profiles are distinct", (t) => {
  const { home, packageRoot } = fixture(t);
  const explicit = verifyInstallation({ home, profileId: "web" });
  const observation = runtimeObservation(explicit);
  assert.equal(verifyInstallation({ home }).profile.reason, "running_profile_unverified");
  mkdirSync(join(home, "profiles", "desktop"));
  assert.equal(verifyInstallation({ home, observation }).profile.reason, "ambiguous_profiles");
  assert.equal(verifyInstallation({ home, observation, profileId: "web" }).overall, "supported");
  const absent = verifyInstallation({ home, profileId: "desktop" });
  assert.equal(absent.stages.package.code, "profile_package_missing");
  assert.equal(verifyInstallation({ home, profileId: "../" }).profile.reason, "invalid_profile_id");
  const preview = verifyInstallation({ packageRoot });
  assert.equal(preview.stages.package.code, "package_found_at_explicit_path");
  assert.equal(preview.overall, "unknown");
  assert.ok(verifyInstallation({ home, profileId: "web", packageRoot: repository })
    .stages.package.code.includes("conflict"));
});

test("official launcher identity locates the running profile and its shipped template", (t) => {
  const { home, profileRoot } = fixture(t);
  const installDir = join(home, "synthetic-install", "node_modules", "@deepseek-ai", "dsh");
  const version = "0.2.3-alpha.2";
  write(installDir, "package.json", { name: "@deepseek-ai/dsh", version });
  const web = join(installDir, "node_modules", "@deepseek-ai", "dsh-web-app");
  write(web, "package.json", {
    name: "@deepseek-ai/dsh-web-app", version, exports: { "./package.json": "./package.json" },
  });
  write(web, "presets/standard.patch.yml", template);
  const launcher = { profileId: "web", directory: profileRoot, installDir };
  mkdirSync(join(home, "profiles", "node_modules"));
  const report = verifyInstallation({ home, launcher });
  assert.equal(report.profile.source, "launcher_environment");
  assert.equal(report.hostVersion, version);
  assert.equal(report.drift.drift, true);
  assert.equal(report.overall, "unknown");
  const mismatched = verifyInstallation({ home, launcher: { ...launcher, directory: installDir } });
  assert.equal(mismatched.profile.reason, "profile_sources_conflict");
  const script = join(repository, "loji-dsh", "scripts", "verify-install.mjs");
  const shell = spawnSync(process.execPath, [script], {
    encoding: "utf8",
    env: { ...process.env, DSH_HOME: "", DSH_PROFILE: "web", DSH_PROFILE_DIR: profileRoot, DSH_INSTALL_DIR: installDir },
  });
  assert.equal(shell.status, 2);
  assert.equal(JSON.parse(shell.stdout).profile.source, "launcher_environment");
});

test("an explicit template and older observations cannot hide a launcher upgrade", (t) => {
  const { home, profileRoot } = fixture(t);
  const installDir = join(home, "synthetic-install", "node_modules", "@deepseek-ai", "dsh");
  const launcher = { profileId: "web", directory: profileRoot, installDir };
  const standardPath = write(home, "operator-standard.patch.yml", template);
  write(installDir, "package.json", { name: "@deepseek-ai/dsh", version: SNAPSHOT_VERSION });
  const options = { home, profileId: "web", launcher, standardPath, hostVersion: SNAPSHOT_VERSION };
  const observation = runtimeObservation(verifyInstallation(options));
  assert.equal(verifyInstallation({ ...options, observation }).overall, "supported");

  const version = "0.2.3-alpha.2";
  write(installDir, "package.json", { name: "@deepseek-ai/dsh", version });
  const upgrade = verifyInstallation({ ...options, observation });
  assert.equal(upgrade.overall, "unknown");
  assert.equal(upgrade.drift.reason, "conflicting_version_sources");
  assert.equal(upgrade.drift.versionSources.launcher, version);
  assert.equal(upgrade.services.skills, "unknown");
  const withoutVersion = verifyInstallation({ ...options, hostVersion: undefined });
  assert.equal(withoutVersion.hostVersion, version);
  assert.equal(withoutVersion.drift.drift, true);
  rmSync(join(installDir, "package.json"));
  assert.equal(verifyInstallation({ ...options, observation }).drift.reason, "launcher_version_unverified");
});

test("a launcher template conflicting with an explicit copy keeps compatibility unknown", (t) => {
  const { home, profileRoot } = fixture(t);
  const installDir = join(home, "synthetic-install", "node_modules", "@deepseek-ai", "dsh");
  const web = join(installDir, "node_modules", "@deepseek-ai", "dsh-web-app");
  write(installDir, "package.json", { name: "@deepseek-ai/dsh", version: SNAPSHOT_VERSION });
  write(web, "package.json", { name: "@deepseek-ai/dsh-web-app", version: SNAPSHOT_VERSION });
  write(web, "presets/standard.patch.yml", template.replace("maxBytes: 65536", "maxBytes: 32768"));
  const options = {
    home, profileId: "web", launcher: { profileId: "web", directory: profileRoot, installDir },
    standardPath: write(home, "operator-standard.patch.yml", template), hostVersion: SNAPSHOT_VERSION,
  };
  const report = verifyInstallation({ ...options, observation: runtimeObservation(verifyInstallation(options)) });
  assert.equal(report.overall, "unknown");
  assert.equal(report.drift.reason, "conflicting_standard_sources");
  assert.equal(report.services.skills, "unknown");
  write(web, "package.json", { name: "@deepseek-ai/dsh-web-app", version: "0.2.3-alpha.2" });
  const differingVersion = verifyInstallation(options);
  assert.equal(differingVersion.drift.reason, "conflicting_version_sources");
  assert.equal(differingVersion.drift.versionSources.template, "0.2.3-alpha.2");
});

test("recovery contract and runtime dependency loss invalidates the package observation", (t) => {
  const { home, packageRoot } = fixture(t);
  const options = { home, profileId: "web" };
  const initial = verifyInstallation(options);
  const observation = runtimeObservation(initial);
  const guide = "references/RECOVERY_CONTEXT.md";
  const original = read(guide);
  write(packageRoot, guide, original + "\n");
  const changed = verifyInstallation({ ...options, observation });
  assert.notEqual(changed.packageDigest, initial.packageDigest);
  assert.equal(changed.services.skills, "unknown");

  for (const resource of [guide, "scripts/safe_state_write.py"]) {
    rmSync(join(packageRoot, resource));
    const missing = verifyInstallation({ ...options, observation });
    assert.equal(missing.stages.resources.status, "fail", resource);
    assert.equal(missing.stages.resources.code, "package_resource_unavailable", resource);
    assert.equal(missing.packageDigest, null, resource);
    assert.equal(missing.overall, "unknown", resource);
    write(packageRoot, resource, read(resource));
  }
  assert.equal(verifyInstallation({ ...options, observation }).overall, "supported");
});

test("diagnostics pinpoints missing bundle, entry, and resource stages", (t) => {
  const { home, packageRoot, profileRoot } = fixture(t);
  const options = { home, profileId: "web" };
  rmSync(join(packageRoot, "loji-dsh/lib/index.js"));
  rmSync(join(packageRoot, "references/STYLE.md"));
  write(packageRoot, PATCH_PATH, renderPreset(skill, template).replace("长征机/逻辑角色模式；", "unexpected"));
  let report = verifyInstallation(options);
  assert.equal(report.stages.entry.code, "entrypoint_unavailable");
  assert.equal(report.stages.resources.code, "package_resource_unavailable");
  assert.equal(report.stages.persona.code, "generated_persona_mismatch");
  assert.equal(report.packageDigest, null);
  write(profileRoot, "package.json", { dsh: { profile: { bundles: [] } } });
  report = verifyInstallation(options);
  assert.equal(report.stages.package.code, "bundle_not_enabled_in_profile_manifest");
});

test("drift reports IDs and changed field names with no values or script evaluation", (t) => {
  const { home, webAppRoot } = fixture(t);
  const options = { home, profileId: "web" };
  const initial = verifyInstallation(options);
  const alpha = template.replace("- id: tool-jobs\n            name: '@deepseek-ai/dsh-tool-jobs'",
    "- id: tool-cordis\n            name: '@deepseek-ai/dsh-tool-cordis'")
    .replace("applyPatch: false", "applyPatch: !!js SECRET_VALUE");
  write(webAppRoot, "presets/standard.patch.yml", alpha);
  write(webAppRoot, "package.json", { name: "@deepseek-ai/dsh-web-app", version: "0.2.3-alpha.2" });
  const observation = runtimeObservation(initial, { hostVersion: "0.2.3-alpha.2" });
  const report = verifyInstallation({ ...options, observation });
  assert.deepEqual(report.drift.addedPluginIds, ["tool-cordis"]);
  assert.deepEqual(report.drift.missingPluginIds, ["tool-jobs"]);
  assert.deepEqual(report.drift.changedPlugins, [{ id: "tool-fs", fields: ["config"] }]);
  assert.equal(report.drift.drift, true);
  assert.equal(report.overall, "unknown");
  assert.ok(!JSON.stringify(report).includes("SECRET_VALUE"));
  assert.equal(verifyInstallation({ ...options, observation: runtimeObservation(initial) }).drift.reason,
    "conflicting_version_sources");
  assert.equal(compareStandard(template, "{ plugins: [] }", "0.2.3-alpha.2").reason,
    "host_standard_format_unrecognized");
  assert.equal(compareStandard(template, template, undefined).drift, null);
  assert.equal(compareStandard(template, template, "0.2.3-alpha.2").drift, true);
  assert.equal(compareStandard(template, template.replace(/\n/g, "\r\n"), SNAPSHOT_VERSION).status, "matched");
});

test("rendering and check options support Windows line endings", () => {
  assert.equal(renderPreset(skill, template),
    renderPreset(normalizeNewlines(skill).replace(/\n/g, "\r\n"), template.replace(/\n/g, "\r\n")));
});

test("CLI reports JSON and never echoes unexpected diagnostic arguments", (t) => {
  const { home } = fixture(t);
  const script = join(repository, "loji-dsh", "scripts", "verify-install.mjs");
  const run = (...args) => spawnSync(process.execPath, [script, ...args], { encoding: "utf8" });
  const offline = run("--home", home, "--profile", "web");
  const report = JSON.parse(offline.stdout);
  assert.equal(offline.status, 2);
  assert.equal(report.stages.package.status, "pass");
  const observation = write(home, "observations.json", runtimeObservation(report));
  const observed = run("--home", home, "--profile", "web", "--observations", observation);
  assert.equal(observed.status, 0);
  assert.equal(JSON.parse(observed.stdout).overall, "supported");
  const invalid = run("--unexpected-secret");
  assert.equal(invalid.status, 2);
  assert.ok(!invalid.stdout.includes("unexpected-secret"));
  assert.equal(invalid.stderr, "");
});
