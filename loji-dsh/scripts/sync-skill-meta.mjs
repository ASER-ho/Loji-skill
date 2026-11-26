#!/usr/bin/env node
/** Sync only skill name/version; keep DSH's concise description hand-maintained. */
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const source = readFileSync(join(root, "SKILL.md"), "utf8");
const matched = /^---\r?\n([\s\S]*?)\r?\n---/.exec(source);
if (!matched) throw new Error("SKILL.md: missing frontmatter");
const lines = matched[1].split(/\r?\n/);
const name = lines.find((s) => /^name:\s*/.test(s))?.replace(/^name:\s*/, "").trim();
if (!name || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) throw new Error("SKILL.md: invalid name");
let inside = false, version = "";
for (const line of lines) {
  if (/^metadata:\s*$/.test(line)) { inside = true; continue; }
  if (inside && line && !/^\s/.test(line)) inside = false;
  if (inside) {
    const m = /^  version:\s*["']?(\d+\.\d+\.\d+)["']?\s*$/.exec(line);
    if (m) { version = m[1]; break; }
  }
}
if (!version) throw new Error("SKILL.md: metadata.version unavailable");
const dest = join(root, "loji-dsh", "lib", "skill-meta.json");
const meta = JSON.parse(readFileSync(dest, "utf8"));
if (!meta.description || !meta.description.includes("长征机")) throw new Error("invalid curated description");
const next = JSON.stringify({name,version,description:meta.description},null,2) + "\n";
if (process.argv.includes("--check")) {
  if (readFileSync(dest,"utf8").replace(/\r\n/g, "\n") !== next) { console.error("Stale metadata; run npm run sync:meta"); process.exitCode=1; }
  else console.log("DSH skill metadata in sync");
} else { writeFileSync(dest,next); console.log("Updated",name,version); }
