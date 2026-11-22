/**
 * dsh-loji — DSH skill provider for the Loji-skill repository.
 *
 * Registers the repository's `SKILL.md` as the `loji-skill` Agent Skill, with the
 * repository root as its resource base so `references/`, `research/` and the other
 * relative paths inside the skill body keep resolving after installation.
 *
 * The shape mirrors the bundled provider in `@deepseek-ai/dsh-skill-badge`.
 */
import { readFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join, resolve } from "node:path";

/** Repository root: lib/index.js -> root. Keeps the bundle relocatable. */
const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SKILL_FILE = join(PACKAGE_ROOT, "SKILL.md");
const META_FILE = join(PACKAGE_ROOT, "lib", "skill-meta.json");

/** Provider id; also the plugin's stable name. */
const PROVIDER_NAME = "loji-skill";
/** @deepseek-ai/dsh-skill BUNDLED_SKILL_RANK — packaged skills outrank user roots. */
const BUNDLED_SKILL_RANK = 600;

const META = JSON.parse(readFileSync(META_FILE, "utf8"));
const RESOURCE_BASE = { kind: "directory", path: PACKAGE_ROOT };
const INVOCATION = { modelInvocable: true, userInvocable: true };

const CANDIDATE = {
  name: META.name,
  description: META.description,
  invocation: INVOCATION,
  provider: PROVIDER_NAME,
  source: "bundled",
  resourceBase: RESOURCE_BASE,
  rank: BUNDLED_SKILL_RANK,
  locator: pathToFileURL(SKILL_FILE),
};

const provider = {
  name: PROVIDER_NAME,
  list: () => Promise.resolve([CANDIDATE]),
  async get(_candidate) {
    return {
      name: CANDIDATE.name,
      description: CANDIDATE.description,
      invocation: INVOCATION,
      provider: PROVIDER_NAME,
      source: "bundled",
      resourceBase: RESOURCE_BASE,
      content: await readFile(SKILL_FILE, "utf8"),
    };
  },
};

/** Cordis plugin name. */
export const name = "loji-skill";
/** Service required by the provider. */
export const inject = ["skills"];
/** Register the bundled Loji skill on `ctx.skills`. */
export function apply(ctx) {
  ctx.skills.registerProvider(() => provider);
}
