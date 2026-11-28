#!/usr/bin/env node
/**
 * Exercise the actual archive produced by npm pack, not just repository files.
 * This checks the relocatable DSH entrypoint and bundled skill in isolation;
 * it is NOT a substitute for the DSH Desktop/Cordis runtime integration test.
 */
import assert from "node:assert/strict";
import { readFile, readdir, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";

const rootArg = process.argv[2];
if (!rootArg) throw new Error("Pass extracted npm package directory");
const root = resolve(rootArg);
const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
assert.equal(manifest.name, "loji-dsh");
assert.equal(manifest.version, "1.0.1");
assert.equal(manifest.main, "loji-dsh/lib/index.js");
assert.equal(manifest.dsh?.bundle?.patch, "./loji-dsh/cordis.patch.yml");
const required = [
  "SKILL.md",
  "references/LORE.md",
  "references/STYLE.md",
  "loji-dsh/lib/index.js",
  "loji-dsh/lib/skill-meta.json",
  "loji-dsh/cordis.patch.yml",
  "loji-dsh/presets/upstream/standard-0.2.2-rc.5.patch.yml",
  "loji-dsh/scripts/gen-preset-patch.mjs",
  "loji-dsh/scripts/verify-install.mjs",
];
for (const path of required) {
  assert.ok(existsSync(join(root, path)), "Missing file from packed archive: " + path);
}

/*
 * Install-size contract. The archive ships the skill, its references, the
 * research notes the skill points at, and the DSH adapter; the banner asset,
 * the test suite and the repository docs stay behind. `research/` has to stay
 * in the archive because manifest.test.mjs asserts it is listed in `files`.
 * Without this assertion the package silently creeps back to multi-megabyte
 * installs, because everything listed in `files` is shipped to every user on
 * every install and update.
 */
const MAX_PACKED_BYTES = 2 * 1024 * 1024;
const FORBIDDEN_DIRS = ["assets", "tests", "docs", "scripts/__pycache__"];
for (const dir of FORBIDDEN_DIRS) {
  assert.ok(
    !existsSync(join(root, dir)),
    "Packed archive must not ship " + dir + "/; keep it repository-only",
  );
}

async function directoryBytes(dir) {
  let total = 0;
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      total += await directoryBytes(path);
    } else if (entry.isFile()) {
      total += (await stat(path)).size;
    }
  }
  return total;
}

const packedBytes = await directoryBytes(root);
assert.ok(
  packedBytes <= MAX_PACKED_BYTES,
  "Packed archive is " +
    (packedBytes / 1024 / 1024).toFixed(2) +
    " MB, over the " +
    MAX_PACKED_BYTES / 1024 / 1024 +
    " MB install-size budget",
);
const plugin = await import(pathToFileURL(join(root, manifest.main)).href);
assert.equal(plugin.name, "loji-skill");
assert.deepEqual(plugin.inject, ["skills"]);
let providerFactory;
plugin.apply({
  skills: {registerProvider: (factory) => {providerFactory = factory;}},
});
assert.equal(typeof providerFactory, "function");
const provider = providerFactory({signal: new AbortController().signal, invalidate(){}});
const candidates = await provider.list();
assert.equal(candidates.length, 1);
assert.equal(candidates[0].name, "loji-skill");
assert.equal(candidates[0].rank, 600);
const loaded = await provider.get(candidates[0]);
assert.equal(resolve(loaded.resourceBase.path), root);
assert.equal(loaded.content, await readFile(join(root, "SKILL.md"), "utf8"));
const metadata = JSON.parse(await readFile(join(root, "loji-dsh/lib/skill-meta.json"), "utf8"));
assert.equal(metadata.name, "loji-skill");
assert.equal(metadata.version, "1.1.5");
const patch = (await readFile(join(root, "loji-dsh/cordis.patch.yml"), "utf8")).replace(/\r\n/g, "\n");
assert.match(patch, /id: loji-skill\n      name: loji-dsh/);
assert.match(patch, /id: preset-loji\n      name: '@deepseek-ai\/dsh-agent-preset'/);
assert.match(patch, /id: loji\n        name: 长征机\/逻辑/);
const diagnostic = spawnSync(process.execPath,
  [join(root, "loji-dsh/scripts/verify-install.mjs"), "--package-root", root],
  { encoding: "utf8", env: { ...process.env, DSH_HOME: "", DSH_PROFILE_DIR: "" } });
assert.equal(diagnostic.status, 2, diagnostic.stderr);
const { stages } = JSON.parse(diagnostic.stdout);
assert.equal(stages.persona.status, "pass");
assert.equal(stages.resources.code, "package_resources_found_resolution_unverified");
console.log(`Packed bundle verified; installed size ${packedBytes} bytes.`);
