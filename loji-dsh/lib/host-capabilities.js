import { createHash } from "node:crypto";
import { readdirSync, realpathSync, statSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { normalizeNewlines, SNAPSHOT_VERSION } from "./preset.js";

const PROFILE_ID = /^[a-z0-9][a-z0-9._-]{0,63}$/i;
const VERSION = /^\d{1,6}\.\d{1,6}\.\d{1,6}(?:-[0-9a-z.-]{1,64})?(?:\+[0-9a-z.-]{1,64})?$/i;
const digest = (text) => createHash("sha256").update(text).digest("hex");
const validId = (id) => typeof id === "string" && PROFILE_ID.test(id) && id.toLowerCase() !== "node_modules";

export function versionOrNull(value) {
  return typeof value === "string" && VERSION.test(value) ? value : null;
}

export function isBelow(root, path) {
  const subpath = relative(root, path);
  return subpath !== "" && subpath !== ".." && !subpath.startsWith(".." + sep) && !isAbsolute(subpath);
}

function unresolvedProfile(reason) {
  return { id: null, kind: "unknown", confidence: "unknown", source: null, reason };
}

/** Validate just the profile directory; never inspect unrelated profiles or processes. */
export function selectProfile(home, requested, observation, launcher) {
  if (requested !== undefined && !validId(requested)) {
    return { profile: unresolvedProfile("invalid_profile_id") };
  }
  if (!home) return { profile: unresolvedProfile("home_unspecified") };

  try {
    const homeDirectory = realpathSync(resolve(home));
    const profiles = realpathSync(join(homeDirectory, "profiles"));
    if (!isBelow(homeDirectory, profiles)) return { profile: unresolvedProfile("profiles_outside_home") };

    let id = requested;
    if (id === undefined) {
      const candidates = readdirSync(profiles, { withFileTypes: true })
        .filter(entry => entry.isDirectory() || entry.isSymbolicLink())
        .map(entry => entry.name)
        .filter(validId);
      if (candidates.length !== 1) {
        return { profile: unresolvedProfile(candidates.length ? "ambiguous_profiles" : "no_profiles") };
      }
      [id] = candidates;
      if (observation?.profileId !== id && launcher?.profileId !== id) {
        return { profile: unresolvedProfile("running_profile_unverified") };
      }
    }
    const directory = realpathSync(join(profiles, id));
    if (!isBelow(profiles, directory) || !statSync(directory).isDirectory()) {
      return { profile: unresolvedProfile("invalid_profile_directory") };
    }
    const fingerprint = digest(directory);
    const observed = observation?.profileFingerprint === fingerprint && observation?.profileId === id
      && ["web", "desktop"].includes(observation?.kind) && versionOrNull(observation?.hostVersion) !== null;
    let launched = false;
    if (launcher?.profileId === id && typeof launcher.directory === "string" && isAbsolute(launcher.directory)) {
      try {
        launched = relative(directory, realpathSync(launcher.directory)) === "";
      } catch {
        // Keep attribution unknown when a launcher-provided path cannot be resolved.
      }
    }
    if (requested === undefined) {
      if ((launcher && !launched) || (observation && !observed)) {
        return { profile: unresolvedProfile("profile_sources_conflict") };
      }
      if (!observed && !launched) return { profile: unresolvedProfile("running_profile_unverified") };
    }
    return {
      directory, observed, launched,
      profile: {
        id, fingerprint, kind: observed ? observation.kind : "unknown",
        confidence: observed || launched ? "high" : "low",
        source: requested !== undefined ? "explicit" : launched ? "launcher_environment" : "runtime_observation",
      },
    };
  } catch {
    return { profile: unresolvedProfile("profile_directory_unavailable") };
  }
}

/**
 * Recognize the pinned upstream block format, including nested plugin groups.
 * Stanza strings preserve expressions and multiline scalars as literal data.
 */
function inventory(patch) {
  const lines = normalizeNewlines(patch).trimEnd().split("\n");
  const section = lines.indexOf("        plugins:");
  if (section === -1 || section !== lines.lastIndexOf("        plugins:")
    || !lines.slice(0, section).includes("    - id: preset-standard")) return null;

  const plugins = new Map();
  let fields;
  let field;
  for (const line of lines.slice(section + 1)) {
    const id = line.match(/^ {10}- id: ([a-z][a-z0-9-]{0,63})\s*$/)?.[1];
    if (id) {
      if (plugins.has(id)) return null;
      fields = new Map();
      plugins.set(id, fields);
      field = null;
      continue;
    }
    if (!fields || (/\S/.test(line) && !line.startsWith("            "))) return null;
    const name = line.match(/^ {12}([a-zA-Z][a-zA-Z0-9_-]{0,63}):(?:\s|$)/)?.[1];
    if (name) {
      if (fields.has(name)) return null;
      field = name;
      fields.set(field, []);
    }
    if (field) fields.get(field).push(line);
    else if (/\S/.test(line)) return null;
  }
  if (!plugins.size || [...plugins.values()].some(fields => !fields.has("name"))) return null;
  const header = lines.slice(0, section).filter(line => line.trim() && !line.trimStart().startsWith("#"));
  return { header: header.join("\n"), plugins };
}

export function compareStandard(snapshot, installed, hostVersion) {
  const version = versionOrNull(hostVersion);
  const result = {
    snapshotVersion: SNAPSHOT_VERSION, hostVersion: version, drift: null,
    missingPluginIds: null, addedPluginIds: null, changedPlugins: null,
    orderChanged: null, presetConfigurationChanged: null, status: "unknown",
  };
  const versionDrift = version !== null && version !== SNAPSHOT_VERSION;
  if (typeof installed !== "string") {
    return { ...result, drift: versionDrift ? true : null, reason: "host_standard_unavailable" };
  }
  const before = inventory(snapshot);
  const after = inventory(installed);
  if (!before || !after) {
    return { ...result, drift: versionDrift ? true : null, reason: "host_standard_format_unrecognized" };
  }

  const oldIds = [...before.plugins.keys()];
  const newIds = [...after.plugins.keys()];
  const missingPluginIds = oldIds.filter(id => !after.plugins.has(id));
  const addedPluginIds = newIds.filter(id => !before.plugins.has(id));
  const retained = oldIds.filter(id => after.plugins.has(id));
  const orderChanged = retained.join(",") !== newIds.filter(id => before.plugins.has(id)).join(",");
  const changedPlugins = retained.flatMap(id => {
    const oldFields = before.plugins.get(id);
    const newFields = after.plugins.get(id);
    const keys = new Set([...oldFields.keys(), ...newFields.keys()]);
    const fields = [...keys].filter(key => oldFields.get(key)?.join("\n") !== newFields.get(key)?.join("\n"));
    return fields.length ? [{ id, fields }] : [];
  });
  const presetConfigurationChanged = before.header !== after.header;
  const contentDrift = Boolean(missingPluginIds.length || addedPluginIds.length || changedPlugins.length
    || orderChanged || presetConfigurationChanged);
  const drift = contentDrift || versionDrift;
  const match = !drift && version === SNAPSHOT_VERSION;
  return {
    ...result, drift: contentDrift || version !== null ? drift : null, missingPluginIds, addedPluginIds,
    changedPlugins, orderChanged, presetConfigurationChanged, status: match ? "matched" : "unknown",
    reason: match ? "matches_snapshot" : drift ? "snapshot_drift" : "host_version_unverified",
  };
}

export function summarizeCapabilities({ profile, hostVersion, drift, present, stages, observed }) {
  const state = (names) => {
    const statuses = names.map(name => stages[name].status);
    if (statuses.includes("fail")) return "unsupported";
    return statuses.every(status => status === "pass") ? "supported" : "unknown";
  };
  const services = {
    skills: state(["entry", "skillProvider"]),
    presetDeclarativeBundle: state(["preset", "persona"]),
    resourceResolution: state(["resources"]),
    sessionController: observed?.sessionController === true ? "supported"
      : observed?.sessionController === false ? "unsupported" : "unknown",
  };
  let overall = "unknown";
  if (profile.confidence === "high" && drift.status === "matched") {
    overall = state(Object.keys(stages));
    if (services.sessionController !== "supported" && overall === "supported") {
      overall = services.sessionController;
    }
  }
  return {
    hostVersion: versionOrNull(hostVersion), profile, services,
    generatedPreset: { present, snapshotVersion: SNAPSHOT_VERSION, drift: drift.drift },
    overall,
  };
}
