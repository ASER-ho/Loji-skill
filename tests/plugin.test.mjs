import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const plugin = await import(pathToFileURL(new URL("../lib/index.js", import.meta.url).pathname).href);

test("exports a cordis plugin that injects skills", () => {
  assert.equal(plugin.name, "loji-skill");
  assert.deepEqual(plugin.inject, ["skills"]);
  assert.equal(typeof plugin.apply, "function");
});

test("registers exactly one candidate with a kebab-case name", async () => {
  let captured;
  plugin.apply({ skills: { registerProvider: (create) => { captured = create; } } });
  assert.equal(typeof captured, "function");
  const provider = captured({ signal: new AbortController().signal, invalidate() {} });
  const list = await provider.list();
  assert.equal(list.length, 1);
  const [skill] = list;
  assert.match(skill.name, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
  assert.equal(skill.provider, "loji-skill");
  assert.equal(skill.source, "bundled");
  assert.equal(skill.invocation.modelInvocable, true);
  assert.equal(skill.invocation.userInvocable, true);
});

test("get() returns the SKILL.md body verbatim and a usable resource base", async () => {
  let captured;
  plugin.apply({ skills: { registerProvider: (create) => { captured = create; } } });
  const provider = captured({ signal: new AbortController().signal, invalidate() {} });
  const [candidate] = await provider.list();
  const skill = await provider.get(candidate);
  const body = await readFile(new URL("../SKILL.md", import.meta.url), "utf8");
  assert.equal(skill.content, body);
  assert.equal(skill.resourceBase.kind, "directory");
  assert.ok(skill.name.length > 0 && skill.description.length > 0);
});
