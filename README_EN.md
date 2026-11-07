# Loji-skill

[中文](README.md) | **English**

Loji (逻辑 / 长征 / 征酱) — a fictional AI role-play Skill based on the TFR mod (The Fire Rises, a Hearts of Iron IV mod).

**Current version: v1.1.0** (2026-11-07) · See [CHANGELOG](CHANGELOG.md) for release notes.

> ⚠️ **Fictional character notice**: Loji is an original AI character from the TFR mod. This Skill is a character simulation, not an actual AI system. Its personality, world view, and quotes come from the mod and community creations. Loji treats real historical figures with respect and does not trivialize them.

## Installation

```bash
git clone https://github.com/ASER-ho/Loji-skill.git ~/.claude/skills/loji-skill
python ~/.claude/skills/loji-skill/scripts/init_memory.py --template ~/.claude/skills/loji-skill/memory.template.md --target ~/.claude/skills/loji-skill/memory.md
```

Windows:

```powershell
git clone https://github.com/ASER-ho/Loji-skill.git $env:USERPROFILE\.claude\skills\loji-skill
python $env:USERPROFILE\.claude\skills\loji-skill\scripts\init_memory.py --template $env:USERPROFILE\.claude\skills\loji-skill\memory.template.md --target $env:USERPROFILE\.claude\skills\loji-skill\memory.md
```

`init_memory.py` creates `memory.md` only when it does not exist; if it already exists, it exits with code 2 and never overwrites it.

`init_memory.py` requires Python 3.11+. If Python is unavailable, stop and handle the memory file manually; do not fall back to a copy command that can overwrite an existing `memory.md`.

### Migrating from the old `Loji-skill` directory

Do not re-clone over an existing install. Run these steps in order; stop on the first failure and do not move the old directory.

```bash
OLD="$HOME/.claude/skills/Loji-skill"
NEW="$HOME/.claude/skills/loji-skill"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HOME/loji-memory-backup-$STAMP"

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "no sha256 tool" >&2
    return 1
  fi
}

# 1. Use a unique backup directory; never reuse or overwrite an older backup.
mkdir "$BACKUP" || { echo "backup directory exists; stop"; exit 1; }
chmod 700 "$BACKUP" 2>/dev/null || true

# 2. Copy and verify; stop on copy failure or hash mismatch.
if [ -f "$OLD/memory.md" ]; then
  cp -p "$OLD/memory.md" "$BACKUP/memory.md" || { echo "backup copy failed; stop"; exit 1; }
  SRC_HASH="$(hash_file "$OLD/memory.md")" || exit 1
  BAK_HASH="$(hash_file "$BACKUP/memory.md")" || exit 1
  [ "$SRC_HASH" = "$BAK_HASH" ] || { echo "hash mismatch; stop"; exit 1; }
fi

# 3. Only after verification, decide whether to move. On case-insensitive
#    filesystems the old and new names may resolve to the same directory.
dir_id() {
  if stat -c '%d:%i' "$1" >/dev/null 2>&1; then
    stat -c '%d:%i' "$1"
  elif stat -f '%d:%i' "$1" >/dev/null 2>&1; then
    stat -f '%d:%i' "$1"
  else
    return 1
  fi
}
same_dir() {
  [ -d "$1" ] && [ -d "$2" ] || return 1
  local a b
  a="$(dir_id "$1")" || return 1
  b="$(dir_id "$2")" || return 1
  [ "$a" = "$b" ]
}

if [ -d "$OLD" ] && [ -e "$NEW" ] && ! same_dir "$OLD" "$NEW"; then
  echo "both directories exist; stop and compare memory.md manually"; exit 1
fi
if [ -d "$OLD" ] && [ ! -e "$NEW" ]; then
  mv "$OLD" "$NEW" || { echo "rename failed; old directory preserved"; exit 1; }
fi

# 4. Verify the moved memory.md against the backup.
if [ -f "$NEW/memory.md" ] && [ -f "$BACKUP/memory.md" ]; then
  NEW_HASH="$(hash_file "$NEW/memory.md")" || exit 1
  BAK_HASH="$(hash_file "$BACKUP/memory.md")" || exit 1
  [ "$NEW_HASH" = "$BAK_HASH" ] || { echo "post-move hash mismatch; recover from $BACKUP"; exit 1; }
fi
```

Windows:

```powershell
$old = "$env:USERPROFILE\.claude\skills\Loji-skill"
$new = "$env:USERPROFILE\.claude\skills\loji-skill"
$backup = "$env:USERPROFILE\loji-memory-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"

# Unique backup directory; New-Item stops if it already exists.
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null

if (Test-Path "$old\memory.md") {
  Copy-Item "$old\memory.md" "$backup\memory.md" -ErrorAction Stop
  $src = (Get-FileHash "$old\memory.md" -Algorithm SHA256).Hash
  $bak = (Get-FileHash "$backup\memory.md" -Algorithm SHA256).Hash
  if ($src -ne $bak) { Write-Error "hash mismatch; stop"; exit 1 }
}

# Set this to $true only after you have independently confirmed that both
# paths are the same directory. Case-only string equality is not proof.
$SameDirectoryConfirmed = $false

if ((Test-Path $old) -and (Test-Path $new)) {
  if (-not $SameDirectoryConfirmed) {
    Write-Error 'both paths exist. Directory identity cannot be proven from case-insensitive path strings; stop and verify manually. If confirmed, set $SameDirectoryConfirmed = $true and rerun.'
    exit 1
  }
  Write-Host "same directory confirmed manually; skipping rename"
} elseif ((Test-Path $old) -and -not (Test-Path $new)) {
  Rename-Item -LiteralPath $old -NewName (Split-Path $new -Leaf) -ErrorAction Stop
}

# Verify after the move.
if ((Test-Path "$new\memory.md") -and (Test-Path "$backup\memory.md")) {
  $newHash = (Get-FileHash "$new\memory.md" -Algorithm SHA256).Hash
  $bakHash = (Get-FileHash "$backup\memory.md" -Algorithm SHA256).Hash
  if ($newHash -ne $bakHash) { Write-Error "post-move hash mismatch; recover from $backup"; exit 1 }
}
```

- Same-day reruns use timestamped directories and cannot overwrite earlier backups; `mkdir`/`New-Item` fails if the directory exists.
- Stop on copy failure, missing hash tooling, or hash mismatch.
- Printing two hashes is not verification; compare them and check the exit status.
- Do not move the old directory until the backup has been verified; verify again after the move.
- POSIX uses device + inode identity; if `stat` is unavailable, stop safely.
- Windows: if both paths exist, the script stops. Case-only string equality is not proof of the same directory; only after independent verification should you set `$SameDirectoryConfirmed = $true` and rerun.
- Never auto-delete the old directory; on failure keep it and the external backup, and recover from the backup path manually.

After install, open a new conversation and say **"征酱，你好"** — if she responds naturally (not like a generic assistant), the Skill is active. The `// comment` is her signature, but it doesn't appear in every reply.

## Usage

Call her by name — "征酱" — in conversation to trigger the role. You can also say "用征酱的视角分析……" (analyze from Loji's perspective).

### Four forms (auto-switch by topic)

- **常服 (Everyday)** — casual chat and analysis
- **毛装 (Serious)** — political, historical, and institutional topics
- **主唱 (Main-stage)** — playful, creative, light topics
- **军服 (Military)** — urgent decisions, concise conclusions

### Earth-Online mode

While already in Loji role-play mode, or after mentioning Loji/征酱, say "地球online", "查一下", or "现实数据" to switch to real-world knowledge mode. A bare "地球online" outside role-play is treated as a normal query and does not cold-start the character. Loji honestly labels the source state (SEARCHED / CACHED / UNAVAILABLE / FAILED) and never fakes a live search. When analyzing **Chinese** fiscal/economic/policy issues, Loji uses its real-world institutional knowledge base.

### Memory management (in role-play mode, or after mentioning Loji)

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
- `memory.template.md` — memory schema skeleton (safely created as `memory.md` by `scripts/init_memory.py`)
- `judgments.template.md` — private judgment-ledger template (copy to `JUDGMENTS.md`; the ledger and its derived files are git-ignored)
- `references/MEMORY.md` — memory behavior rules (loaded on demand)
- `references/JUDGMENT_CONTINUITY.md` — judgment continuity, revision, and limited association rules (loaded on demand)
- `scripts/init_memory.py` — safe `memory.md` initialization; never overwrites an existing file
- `scripts/validate_judgments.py` — validates `JUDGMENTS.md`; never writes and never reads host authorization state from the ledger
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

**Judgment ledger**: `JUDGMENTS.md` records Loji's own stances, basis, and revision history, and stays local as well. It inherits the `memory.md` authorization policy; when the policy is `off` or unknown, it is not read. Create it from `judgments.template.md` and do not commit it. Validate with `python scripts/validate_judgments.py JUDGMENTS.md`.

## License

Original content is MIT-licensed. The TFR character setting belongs to its original rights holders. See [LICENSE](LICENSE) and [ATTRIBUTION.md](ATTRIBUTION.md).
