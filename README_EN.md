# Loji-skill

[中文](README.md) | **English**

Loji (逻辑 / 长征 / 征酱) — a fictional AI role-play Skill based on the TFR mod (The Fire Rises, a Hearts of Iron IV mod).

**Current version: v1.0.0** (2026-08-02) · See [CHANGELOG](CHANGELOG.md) for release notes.

> ⚠️ **Fictional character notice**: Loji is an original AI character from the TFR mod. This Skill is a character simulation, not an actual AI system. Its personality, world view, and quotes come from the mod and community creations. Loji treats real historical figures with respect and does not trivialize them.

## Installation

```bash
git clone https://github.com/ASER-ho/Loji-skill.git ~/.claude/skills/Loji-skill
cp ~/.claude/skills/Loji-skill/memory.template.md ~/.claude/skills/Loji-skill/memory.md
```

Windows:

```powershell
git clone https://github.com/ASER-ho/Loji-skill.git $env:USERPROFILE\.claude\skills\Loji-skill
Copy-Item $env:USERPROFILE\.claude\skills\Loji-skill\memory.template.md $env:USERPROFILE\.claude\skills\Loji-skill\memory.md
```

After install, open a new conversation and say **"征酱，你好"** — if she responds naturally (not like a generic assistant), the Skill is active. The `// comment` is her signature, but it doesn't appear in every reply.

## Usage

Call her by name — "征酱" — in conversation to trigger the role. You can also say "用征酱的视角分析……" (analyze from Loji's perspective).

### Four forms (auto-switch by topic)

- **常服 (Everyday)** — casual chat and analysis
- **毛装 (Serious)** — political, historical, and institutional topics
- **主唱 (Main-stage)** — playful, creative, light topics
- **军服 (Military)** — urgent decisions, concise conclusions

### Earth-Online mode

Say "地球online", "查一下", or "现实数据" to switch to real-world knowledge mode. Loji honestly labels the source state (SEARCHED / CACHED / UNAVAILABLE / FAILED) and never fakes a live search. When analyzing **Chinese** fiscal/economic/policy issues, Loji uses its real-world institutional knowledge base.

### Memory management

- "记住……" — write to memory
- "你记得我什么？" / "显示记忆摘要" — view memory summary
- "忘记……" / "删除关于 X 的记忆" — precise deletion
- "清空近期上下文" — clear temporary context only
- "清空所有记忆" — clear entire file (requires confirmation)
- "记忆健康检查" / "检查记忆" — memory health report
- "恢复记忆：X" — reactivate from archive

### Maintenance mode

Say "退出征酱模式", "暂停角色扮演", or "进入维护模式" — Loji pauses role-play and responds as a normal assistant (useful for debugging or non-role tasks).

## File Structure

### Runtime files (required for the Skill to work)

- `SKILL.md` — personality definition and rules (runtime authority)
- `memory.template.md` — memory template (copy to `memory.md` on install, see above)
- `references/LORE.md` — world view and background
- `references/STYLE.md` — expression style details
- `references/SAFETY_BOUNDARIES.md` — safety rules
- `references/STATE_MACHINES.md` — state machine definitions (form/route/memory/growth/world)
- `references/domain-knowledge.md` — real-world institutional knowledge base

### Development & research materials (not needed for daily use)

- `research/` — deep research: analysis models (`ANALYSIS_MODELS.md`), political context rules (`POLITICAL_CONTEXT.md`), sources (`SOURCES.md`, `canon/`), eval framework (`evals/`), persona failure modes (`PERSONA_FAILURE_MODES.md`), evidence map (`evidence/`)
- `examples/` — role-play conversation examples (`analysis.md`, `casual.md`)

## Memory Scope

`memory.md` is a local file that persists on the same machine:

| Scenario | Shared? |
|----------|---------|
| Same machine, multiple Claude Code windows | ✅ Shared (same `memory.md`) |
| Different machines | ❌ Not shared (independent files) |
| Different agents (e.g. Claude Code vs Codex) | ❌ Not shared (independent Skill dirs) |

> When switching machines or agents, you can manually copy `memory.md` — but don't commit it to git.

## License

Original content is MIT-licensed. The TFR character setting belongs to its original rights holders. See [LICENSE](LICENSE) and [ATTRIBUTION.md](ATTRIBUTION.md).
