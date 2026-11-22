#!/usr/bin/env node
/**
 * Regenerate lib/skill-meta.json from SKILL.md frontmatter.
 * The runtime reads the JSON so a malformed frontmatter never crashes startup;
 * this script is the single place that parses it. Run after editing SKILL.md.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const text = readFileSync(join(ROOT, "SKILL.md"), "utf8");
const m = /^---\r?\n([\s\S]*?)\r?\n---/.exec(text);
if (!m) throw new Error("SKILL.md: missing frontmatter");

const fm = m[1];
const readScalar = (key) => {
  const line = new RegExp("^" + key + ":\\s*(.+)$", "m").exec(fm);
  return line ? line[1].trim().replace(/^["']|["']$/g, "") : "";
};
// description is a YAML folded block (": >") or a single line.
let description = readScalar("description");
if (description === ">" || description === "|" || description === "") {
  const start = fm.indexOf("description:");
  const rest = fm.slice(start).split("\n").slice(1);
  const body = [];
  for (const line of rest) {
    if (/^\S/.test(line)) break;
    body.push(line.trim());
  }
  description = body.filter(Boolean).join(" ");
}

const meta = {
  name: readScalar("name"),
  version: (readScalar("version") || "").trim(),
  description: description.replace(/\s+/g, " ").trim(),
};
if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(meta.name)) throw new Error("invalid skill name: " + meta.name);
writeFileSync(join(ROOT, "lib", "skill-meta.json"), JSON.stringify(meta, null, 2) + "\n");
console.log("wrote lib/skill-meta.json", meta.name, meta.version);
