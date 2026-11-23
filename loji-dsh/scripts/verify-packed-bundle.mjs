#!/usr/bin/env node
/**
 * Exercise the actual archive produced by npm pack, not just repository files.
 * This checks the relocatable DSH entrypoint and bundled skill in isolation;
 * it is NOT a substitute for the DSH Desktop/Cordis runtime integration test.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

const rootArg = process.argv[2];
if (!rootArg) throw new Error("Pass extracted npm package directory");
const root = resolve(rootArg);
const manifest = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
assert.equal(manifest.name, "loji-dsh");
assert.equal(manifest.version, "1.0.0");
assert.equal(manifest.main, "loji-dsh/lib/index.js");
assert.equal(manifest.dsh?.bundle?.patch, "./loji-dsh/cordis.patch.yml");
const required = [
  "SKILL.md",
  "references/LORE.md",
  "references/STYLE.md",
  "loji-dsh/lib/index.js",
  "loji-dsh/lib/skill-meta.json",
  "loji-dsh/cordis.patch.yml",
  "loji-dsh/presets/upstream/standard-0.2.3-alpha.2.patch.yml",
  "loji-dsh/scripts/gen-preset-patch.mjs",
];
for (const path of required) {
  assert.ok(existsSync(join(root, path)), "Missing file from packed archive: " + path);
}
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
assert.equal(metadata.version, "1.1.4");
const patch = await readFile(join(root, "loji-dsh/cordis.patch.yml"), "utf8");
assert.match(patch, /id: loji-skill\n      name: loji-dsh/);
assert.match(patch, /id: preset-loji\n      name: '@deepseek-ai\/dsh-agent-preset'/);
assert.match(patch, /id: loji\n        name: 长征机\/逻辑/);
console.log("Packed loji-dsh bundle: manifest, resources, provider, and preset declaration OK");
