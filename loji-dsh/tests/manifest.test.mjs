import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync,existsSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {join} from "node:path";
const root=fileURLToPath(new URL("../../",import.meta.url));
const pkg=JSON.parse(readFileSync(join(root,"package.json"),"utf8"));
const meta=JSON.parse(readFileSync(join(root,"loji-dsh/lib/skill-meta.json"),"utf8"));
const skill=readFileSync(join(root,"SKILL.md"),"utf8");
test("package and skill have separate identities and versions",()=>{
  assert.equal(pkg.name,"loji-dsh");
  assert.equal(pkg.version,"1.0.0");
  assert.equal(meta.name,"loji-skill");
  assert.ok(meta.description.includes("长征机"));
  assert.match(skill,/^name: loji-skill$/m);
  const front=skill.match(/^---\r?\n([\s\S]*?)\r?\n---/)[1];
  assert.ok(front.includes('  version: "'+meta.version+'"'));
});
test("DSH entrypoint, patch, and resources survive relocation",()=>{
  assert.equal(pkg.main,"loji-dsh/lib/index.js");
  assert.equal(pkg.dsh.bundle.patch,"./loji-dsh/cordis.patch.yml");
  assert.ok(existsSync(join(root,pkg.main)));
  assert.ok(existsSync(join(root,pkg.dsh.bundle.patch)));
  for(const dir of ["loji-dsh","SKILL.md","references","research"]) assert.ok(pkg.files.includes(dir));
  const patch=readFileSync(join(root,pkg.dsh.bundle.patch),"utf8");
  assert.match(patch,/id: loji-skill/);
  assert.match(patch,/name: loji-dsh/);
  assert.doesNotMatch(patch,/id: preset-loji/);
});
