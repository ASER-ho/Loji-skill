#!/usr/bin/env node
/** Offline, read-only diagnosis for an explicitly scoped DSH installation. */
import { parseArgs } from "node:util";
import { basename, dirname, isAbsolute } from "node:path";
import { readText, verifyInstallation } from "../lib/diagnostics.js";
import { versionOrNull } from "../lib/host-capabilities.js";

function main() {
  const { values } = parseArgs({
    options: {
      home: { type: "string" },
      profile: { type: "string" },
      "package-root": { type: "string" },
      "host-standard": { type: "string" },
      "host-version": { type: "string" },
      observations: { type: "string" },
      help: { type: "boolean", short: "h" },
    },
  });
  if (values.help) {
    console.log("Usage: verify-install.mjs [--home DSH_HOME] [--profile ID] [--package-root PATH]\n"
      + "       [--host-standard PATH --host-version VERSION] [--observations JSON]");
    return 0;
  }
  if (values["host-version"] !== undefined && !versionOrNull(values["host-version"])) {
    console.log(JSON.stringify({ overall: "unknown", error: "invalid_host_version" }));
    return 2;
  }
  let observation;
  try {
    if (values.observations) observation = JSON.parse(readText(values.observations));
  } catch {
    console.log(JSON.stringify({ overall: "unknown", error: "observations_unreadable_or_invalid" }));
    return 2;
  }
  const { DSH_HOME, DSH_PROFILE, DSH_PROFILE_DIR, DSH_INSTALL_DIR } = process.env;
  const profileParent = DSH_PROFILE_DIR && isAbsolute(DSH_PROFILE_DIR) && dirname(DSH_PROFILE_DIR);
  const launcher = DSH_PROFILE && profileParent && {
    profileId: DSH_PROFILE, directory: DSH_PROFILE_DIR, installDir: DSH_INSTALL_DIR,
  };
  const launcherHome = profileParent && basename(profileParent) === "profiles" ? dirname(profileParent) : undefined;
  const result = verifyInstallation({
    home: values.home ?? (DSH_HOME || launcherHome),
    profileId: values.profile,
    packageRoot: values["package-root"],
    standardPath: values["host-standard"],
    hostVersion: values["host-version"],
    observation,
    launcher,
  });
  console.log(JSON.stringify(result, null, 2));
  if (Object.values(result.stages).some(check => check.status === "fail")) return 1;
  return result.overall === "supported" ? 0 : 2;
}

try {
  process.exitCode = main();
} catch {
  console.log(JSON.stringify({ overall: "unknown", error: "invalid_arguments_or_unavailable_diagnostics" }));
  process.exitCode = 2;
}
