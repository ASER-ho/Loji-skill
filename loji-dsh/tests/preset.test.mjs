import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {join} from "node:path";
const root=fileURLToPath(new URL("../../",import.meta.url));
const read=(p)=>readFileSync(join(root,p),"utf8");
test("generated DSH preset declaration contains both independent services",()=>{
  const text=read("loji-dsh/cordis.patch.yml");
  assert.match(text,/id: loji-skill\n      name: loji-dsh/);
  assert.match(text,/id: preset-loji\n      name: '@deepseek-ai\/dsh-agent-preset'/);
  assert.match(text,/id: loji\n        name: 长征机\/逻辑/);
});
test("pinned upstream preset plugin tools are retained bytewise after persona swap",()=>{
  const original=read("loji-dsh/presets/upstream/standard-0.2.2-rc.1.patch.yml");
  const generated=read("loji-dsh/cordis.patch.yml");
  const tail=original.slice(original.indexOf("          - id: agent-instructions"));
  assert.ok(generated.endsWith(tail),"upstream tools differ from snapshot");
});
