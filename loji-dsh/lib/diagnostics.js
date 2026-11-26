import { createHash } from "node:crypto";
import { readFileSync, realpathSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, isAbsolute, join, relative } from "node:path";
import { isBelow, selectProfile, compareStandard, summarizeCapabilities, versionOrNull } from "./host-capabilities.js";
import { normalizeNewlines, PATCH_PATH, renderPreset, SNAPSHOT_PATH } from "./preset.js";

const MAX_INPUT_BYTES = 2 * 1024 * 1024;
const ENTRY = "loji-dsh/lib/index.js";
const META = "loji-dsh/lib/skill-meta.json";
const STAGE_KEYS = ["package", "entry", "skillProvider", "preset", "persona", "resources", "modes"];
const snapshotFile = new URL("../../" + SNAPSHOT_PATH, import.meta.url);

/** Read only bounded, regular text files. No external code or YAML expressions are evaluated. */
export function readText(path) {
  const stat = statSync(path);
  if (!stat.isFile() || stat.size > MAX_INPUT_BYTES) throw new Error("Invalid input file");
  const content = readFileSync(path);
  if (content.length > MAX_INPUT_BYTES) throw new Error("Input exceeded byte limit");
  return content.toString("utf8");
}

function readPackageText(root, name) {
  const expected = join(root, name);
  const target = realpathSync(expected);
  if (!isBelow(root, target) || relative(expected, target) !== "") {
    throw new Error("Package path is redirected");
  }
  return readText(target);
}

const stage = (status, code, evidence = "static") => ({ status, code, evidence });
const unknownStage = () => stage("unknown", "runtime_observation_required");

function resolveBundle(directory, explicitRoot) {
  try {
    const requested = explicitRoot ? realpathSync(explicitRoot) : null;
    if (!directory) return requested ? { root: requested } : { reason: "profile_unresolved" };
    const installed = realpathSync(join(directory, "node_modules", "loji-dsh"));
    if (requested && requested !== installed) return { reason: "package_source_conflict" };
    if (!requested && !isBelow(directory, installed)) return { reason: "external_bundle_root_requires_explicit_path" };
    return { root: installed, installed: true };
  } catch (error) {
    const missing = error.code === "ENOENT" && directory && !explicitRoot;
    return { reason: missing ? "profile_package_missing" : "package_root_unavailable", missing };
  }
}

function inspectBundle(bundle, directory, stages) {
  const digest = createHash("sha256");
  const read = (name) => {
    const content = readPackageText(bundle.root, name);
    digest.update(JSON.stringify([name, content]));
    return content;
  };
  let pristine = true;
  const check = (key, code, fn) => {
    try {
      return fn();
    } catch {
      pristine = false;
      stages[key] = stage("fail", code);
      return null;
    }
  };

  const manifest = check("package", "invalid_package_manifest", () => {
    const parsed = JSON.parse(read("package.json"));
    if (parsed.name !== "loji-dsh" || !versionOrNull(parsed.version)) throw new Error("Package identity mismatch");
    stages.package = stage("pass", bundle.installed ? "package_found_in_profile" : "package_found_at_explicit_path");
    return parsed;
  });
  if (!manifest) return { present: false, packageDigest: null };
  if (bundle.installed) {
    check("package", "profile_manifest_unavailable", () => {
      const content = readPackageText(directory, "package.json");
      digest.update(JSON.stringify(["profile/package.json", content]));
      const profileManifest = JSON.parse(content);
      const selected = profileManifest.dsh?.profile?.bundles;
      if (!Array.isArray(selected)) {
        pristine = false;
        stages.package = stage("unknown", "profile_bundle_selection_unverified");
      } else if (!selected.includes("loji-dsh")) {
        pristine = false;
        stages.package = stage("fail", "bundle_not_enabled_in_profile_manifest");
      }
    });
  }

  check("entry", "entrypoint_unavailable", () => {
    if (manifest.main !== ENTRY || manifest.exports?.["."] !== "./" + ENTRY) throw new Error("Entrypoint mismatch");
    if (!read(ENTRY).trim()) throw new Error("Entrypoint is empty");
    stages.entry = stage("unknown", "entrypoint_found_loading_unverified");
  });
  check("skillProvider", "skill_metadata_unavailable", () => {
    const metadata = JSON.parse(read(META));
    if (metadata.name !== "loji-skill" || !versionOrNull(metadata.version)) throw new Error("Metadata identity mismatch");
    stages.skillProvider = { ...stage("unknown", "provider_registration_unverified"), expectedRank: 600 };
  });
  let present = false;
  const patch = check("preset", "preset_declaration_unavailable", () => {
    if (manifest.dsh?.bundle?.patch !== "./" + PATCH_PATH) throw new Error("Bundle patch mismatch");
    const text = normalizeNewlines(read(PATCH_PATH));
    present = true;
    if (!/^ {4}- id: loji-skill\n {6}name: loji-dsh$/m.test(text)
      || !/^ {4}- id: preset-loji\n {6}name: '@deepseek-ai\/dsh-agent-preset'$/m.test(text)
      || !/^ {8}id: loji\n {8}name: 长征机\/逻辑$/m.test(text)) {
      throw new Error("Preset declaration mismatch");
    }
    stages.preset = stage("unknown", "preset_declaration_found_loading_unverified");
    return text;
  });
  const skill = check("persona", "canonical_skill_unavailable", () => {
    const text = read("SKILL.md");
    if (!/^name: loji-skill\r?$/m.test(text)) throw new Error("Skill identity mismatch");
    return text;
  });
  if (skill !== null && patch !== null) {
    check("persona", "generated_persona_mismatch", () => {
      const template = read(SNAPSHOT_PATH);
      if (patch !== renderPreset(skill, template)) throw new Error("Generated preset differs from canonical input");
      stages.persona = stage("pass", "generated_persona_matches_canonical_source");
    });
  }
  if (skill !== null) {
    const references = [...new Set([
      "references/STYLE.md", "research/ANALYSIS_MODELS.md",
      ...[...skill.matchAll(/(?:references|research)\/[a-zA-Z0-9_.-]+(?:\/[a-zA-Z0-9_.-]+)*\.(?:md|json)\b/g)]
        .map(match => match[0])
        .filter(path => !path.split("/").some(part => part === ".." || part === ".")),
    ])].sort();
    check("resources", "package_resource_unavailable", () => {
      for (const name of references) read(name);
      stages.resources = { ...stage("unknown", "package_resources_found_resolution_unverified"), checkedFiles: references.length };
    });
  }
  return { present, packageDigest: pristine ? digest.digest("hex") : null };
}

function applyObservations(stages, observed) {
  if (!observed) return;
  const joinChecks = (values) => {
    if (values.some(value => value === false)) return "fail";
    return values.every(value => value === true) ? "pass" : "unknown";
  };
  const rank = Number.isInteger(observed.providerRank) ? observed.providerRank === 600 : undefined;
  const checks = {
    entry: [observed.entryLoaded],
    skillProvider: [observed.providerRegistered, observed.providerSelected, rank],
    preset: [observed.presetLoaded, observed.presetSelected],
    resources: [observed.presetResources, observed.standardResources],
    modes: [observed.presetDialogue, observed.standardDialogue],
  };
  for (const [key, values] of Object.entries(checks)) {
    if (stages[key].status === "fail") continue;
    const status = joinChecks(values);
    if (status !== "unknown") {
      stages[key] = { ...stages[key], ...stage(status,
        status === "pass" ? `${key}_observed` : `${key}_observation_failed`, "operator_observation") };
    }
  }
}

function readStandard({ standardPath, version, directory, installDir }) {
  if (standardPath) {
    try {
      return { text: readText(standardPath), version };
    } catch {
      return { version };
    }
  }
  if (installDir && isAbsolute(installDir)) {
    let runtimeVersion;
    try {
      const root = realpathSync(installDir);
      const manifest = JSON.parse(readPackageText(root, "package.json"));
      if (manifest.name === "@deepseek-ai/dsh") runtimeVersion = versionOrNull(manifest.version);
      const fromLauncher = createRequire(join(root, "package.json"));
      const module = fromLauncher.resolve("@deepseek-ai/dsh-web-app/package.json");
      const app = JSON.parse(readText(module));
      if (runtimeVersion && app.name === "@deepseek-ai/dsh-web-app") {
        const text = readPackageText(realpathSync(dirname(module)), "presets/standard.patch.yml");
        return { text, version: runtimeVersion };
      }
    } catch {
      // Development or older installations may expose only the runtime version.
    }
    if (runtimeVersion) return { version: runtimeVersion };
  }
  if (!directory) return { version };
  try {
    const root = realpathSync(join(directory, "node_modules", "@deepseek-ai", "dsh-web-app"));
    if (!isBelow(directory, root)) return { version };
    const manifest = JSON.parse(readPackageText(root, "package.json"));
    if (manifest.name !== "@deepseek-ai/dsh-web-app") return { version };
    return { text: readPackageText(root, "presets/standard.patch.yml"), version: versionOrNull(manifest.version) };
  } catch {
    return { version };
  }
}

export function verifyInstallation({ home, profileId, packageRoot, standardPath, hostVersion, observation, launcher } = {}) {
  const selection = selectProfile(home, profileId, observation, launcher);
  const { profile, directory } = selection;
  const bundle = resolveBundle(directory, packageRoot);
  const stages = Object.fromEntries(STAGE_KEYS.map(key => [key, unknownStage()]));
  const inspection = bundle.root ? inspectBundle(bundle, directory, stages) : { present: false, packageDigest: null };
  if (!bundle.root) stages.package = stage(bundle.missing ? "fail" : "unknown", bundle.reason);

  const standard = readStandard({
    standardPath, directory, version: versionOrNull(hostVersion),
    installDir: selection.launched ? launcher.installDir : undefined,
  });
  const suppliedVersion = versionOrNull(hostVersion);
  const observedVersion = versionOrNull(observation?.hostVersion);
  const conflictingVersions = new Set([standard.version, suppliedVersion,
    selection.observed ? observedVersion : null].filter(Boolean)).size > 1;
  let runtimeEvidence = observation ? "observation_scope_or_package_mismatch" : "observation_not_supplied";
  let observed;
  if (selection.observed && bundle.installed && inspection.packageDigest
    && observation?.packageDigest === inspection.packageDigest
    && observation.checks && typeof observation.checks === "object" && !Array.isArray(observation.checks)
    && !conflictingVersions) {
    observed = observation.checks;
    runtimeEvidence = "operator_observation_matches_profile_and_package";
  } else if (selection.observed) {
    if (!selection.launched) profile.confidence = "low";
    profile.kind = "unknown";
  }
  applyObservations(stages, observed);
  const version = conflictingVersions ? null : standard.version ?? suppliedVersion ?? (observed ? observedVersion : null);
  let drift = compareStandard(readText(snapshotFile), standard.text, version);
  if (conflictingVersions) {
    drift = { ...drift, drift: null, status: "unknown", reason: "conflicting_version_sources" };
  }
  return {
    ...summarizeCapabilities({ profile, hostVersion: version, drift, present: inspection.present, stages, observed }),
    drift, stages, runtimeEvidence, packageDigest: inspection.packageDigest,
  };
}
