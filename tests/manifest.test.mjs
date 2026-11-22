import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const pkg = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));

test("package.json declares a dsh bundle patch", () => {
  assert.equal(pkg.dsh?.bundle?.patch, "./cordis.patch.yml");
  assert.ok(existsSync(join(ROOT, pkg.dsh.bundle.patch)), "bundle patch file missing");
});

test("cordis.patch.yml inserts this package under the provider id", () => {
  const yaml = readFileSync(join(ROOT, "cordis.patch.yml"), "utf8");
  assert.match(yaml, /- insert:/);
  assert.match(yaml, /id: loji-skill/);
  assert.match(yaml, new RegExp("name: " + pkg.name));
});

test("lib/skill-meta.json matches SKILL.md frontmatter", () => {
  const meta = JSON.parse(readFileSync(join(ROOT, "lib", "skill-meta.json"), "utf8"));
  const skill = readFileSync(join(ROOT, "SKILL.md"), "utf8");
  assert.ok(skill.includes("name: " + meta.name));
  assert.ok(skill.includes('version: "' + meta.version + '"') || skill.includes("version: " + meta.version));
  assert.ok(meta.description.length > 20);
});

test("npm files list ships the runtime pieces", () => {
  for (const entry of ["lib", "cordis.patch.yml", "SKILL.md", "references"]) {
    assert.ok(pkg.files.includes(entry), "files is missing " + entry);
  }
});
