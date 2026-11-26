#!/usr/bin/env node
/** Generate from canonical SKILL.md and the pinned template. --check is read-only. */
import { writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { readText } from "../lib/diagnostics.js";
import { compareStandard, versionOrNull } from "../lib/host-capabilities.js";
import { normalizeNewlines, PATCH_PATH, renderPreset, SNAPSHOT_PATH } from "../lib/preset.js";

function main() {
  const { values } = parseArgs({
    options: {
      check: { type: "boolean" },
      "host-standard": { type: "string" },
      "host-version": { type: "string" },
    },
  });
  const path = values["host-standard"];
  const version = versionOrNull(values["host-version"]);
  if ((path || values["host-version"]) && (!values.check || !path || !version)) {
    console.error("Pass --host-standard PATH and --host-version VERSION together with --check");
    return 2;
  }
  const repository = new URL("../../", import.meta.url);
  const snapshot = readText(new URL(SNAPSHOT_PATH, repository));
  const output = renderPreset(readText(new URL("SKILL.md", repository)), snapshot);
  const destination = new URL(PATCH_PATH, repository);
  if (!values.check) {
    writeFileSync(destination, output, "utf8");
    console.log("Generated loji-dsh/cordis.patch.yml");
    return 0;
  }
  const matches = normalizeNewlines(readText(destination)) === output;
  let drift;
  if (path) {
    let installed;
    try {
      installed = readText(path);
    } catch {
      // Report an unavailable template without exposing the path or OS error.
    }
    drift = compareStandard(snapshot, installed, version);
    console.log(JSON.stringify({ generatedPresetMatches: matches, drift }, null, 2));
  } else if (matches) {
    console.log("Preset patch matches pinned template and canonical SKILL.md");
  } else {
    console.error("Preset patch stale; run npm run gen:preset");
  }
  if (!matches) return 1;
  return drift && drift.status !== "matched" ? 2 : 0;
}

try {
  process.exitCode = main();
} catch {
  console.error("Preset check or generation failed. Check arguments and canonical source files.");
  process.exitCode = 1;
}
