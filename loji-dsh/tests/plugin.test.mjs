import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import * as plugin from "../lib/index.js";

test("exports a provider with stable skill name", async () => {
  assert.equal(plugin.name, "loji-skill");
  assert.deepEqual(plugin.inject, ["skills"]);
  let factory;
  plugin.apply({skills:{registerProvider: callback => {factory=callback;}}});
  assert.equal(typeof factory, "function");
  const provider = factory({signal: new AbortController().signal, invalidate() {}});
  const list = await provider.list();
  assert.equal(list.length,1);
  assert.equal(list[0].name,"loji-skill");
  assert.equal(list[0].provider,"loji-skill");
  assert.equal(list[0].source,"bundled");
  assert.equal(list[0].rank,600);
  const loaded = await provider.get(list[0]);
  assert.equal(loaded.name,"loji-skill");
  assert.equal(loaded.content,await readFile(new URL("../../SKILL.md",import.meta.url),"utf8"));
  assert.equal(loaded.resourceBase.kind,"directory");
  assert.equal(resolve(loaded.resourceBase.path),resolve(fileURLToPath(new URL("../../",import.meta.url))));
});
