# Loji-skill

**中文** | [English](README_EN.md)

长征机/逻辑/征酱——一个基于 TFR 模组的虚构 AI 角色扮演 Skill。

**当前版本：v1.0.2**（2026-10-18）· 变更记录见 [CHANGELOG](CHANGELOG.md)

## 安装

```bash
git clone https://github.com/ASER-ho/Loji-skill.git ~/.claude/skills/loji-skill
python ~/.claude/skills/loji-skill/scripts/init_memory.py --template ~/.claude/skills/loji-skill/memory.template.md --target ~/.claude/skills/loji-skill/memory.md
```

Windows：

```powershell
git clone https://github.com/ASER-ho/Loji-skill.git $env:USERPROFILE\.claude\skills\loji-skill
python $env:USERPROFILE\.claude\skills\loji-skill\scripts\init_memory.py --template $env:USERPROFILE\.claude\skills\loji-skill\memory.template.md --target $env:USERPROFILE\.claude\skills\loji-skill\memory.md
```

`init_memory.py` 只在 `memory.md` 不存在时创建；已存在时退出码 2，绝不覆盖。

`init_memory.py` 需要 Python 3.11+。若当前环境没有 Python，请停止安装并人工处理记忆文件；不要改用会覆盖已有 `memory.md` 的复制命令。

### 从旧目录 `Loji-skill` 迁移

如果已经安装过旧版本，不要直接重新 clone 覆盖。以下步骤按顺序执行；任何一步失败都停止，不移动原目录。

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

# 1. 每次使用唯一备份目录；已存在则停止，不覆盖旧备份
mkdir "$BACKUP" || { echo "backup directory exists; stop"; exit 1; }
chmod 700 "$BACKUP" 2>/dev/null || true

# 2. 复制并校验；失败或哈希不一致必须停止
if [ -f "$OLD/memory.md" ]; then
  cp -p "$OLD/memory.md" "$BACKUP/memory.md" || { echo "backup copy failed; stop"; exit 1; }
  SRC_HASH="$(hash_file "$OLD/memory.md")" || exit 1
  BAK_HASH="$(hash_file "$BACKUP/memory.md")" || exit 1
  [ "$SRC_HASH" = "$BAK_HASH" ] || { echo "hash mismatch; stop"; exit 1; }
fi

# 3. 校验通过后，才判断是否移动；大小写不敏感时旧/新可能是同一目录
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

# 4. 移动后再次校验新目录中的 memory.md
if [ -f "$NEW/memory.md" ] && [ -f "$BACKUP/memory.md" ]; then
  NEW_HASH="$(hash_file "$NEW/memory.md")" || exit 1
  BAK_HASH="$(hash_file "$BACKUP/memory.md")" || exit 1
  [ "$NEW_HASH" = "$BAK_HASH" ] || { echo "post-move hash mismatch; recover from $BACKUP"; exit 1; }
fi
```

Windows：

```powershell
$old = "$env:USERPROFILE\.claude\skills\Loji-skill"
$new = "$env:USERPROFILE\.claude\skills\loji-skill"
$backup = "$env:USERPROFILE\loji-memory-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"

# 唯一备份目录；已存在则 New-Item 失败并停止
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null

if (Test-Path "$old\memory.md") {
  Copy-Item "$old\memory.md" "$backup\memory.md" -ErrorAction Stop
  $src = (Get-FileHash "$old\memory.md" -Algorithm SHA256).Hash
  $bak = (Get-FileHash "$backup\memory.md" -Algorithm SHA256).Hash
  if ($src -ne $bak) { Write-Error "hash mismatch; stop"; exit 1 }
}

# 仅当你已独立确认两个路径是同一目录后，才把它改为 $true。
# 仅大小写不同的路径字符串不能作为同一目录的证明。
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

# 移动后再次校验
if ((Test-Path "$new\memory.md") -and (Test-Path "$backup\memory.md")) {
  $newHash = (Get-FileHash "$new\memory.md" -Algorithm SHA256).Hash
  $bakHash = (Get-FileHash "$backup\memory.md" -Algorithm SHA256).Hash
  if ($newHash -ne $bakHash) { Write-Error "post-move hash mismatch; recover from $backup"; exit 1 }
}
```

- 同一天重复运行使用时间戳目录，不会覆盖先前备份；`mkdir`/`New-Item` 已存在即失败。
- 复制失败、哈希工具缺失或哈希不一致时立即停止。
- 打印哈希不算校验；必须像上面一样比较并检查退出状态。
- 校验成功前不移动原目录；移动后再次校验。
- POSIX 使用设备号 + inode 判断目录身份；`stat` 不可用时安全停止。
- Windows：两条路径都存在时脚本停止。仅大小写不同的字符串不被当作同一目录的证明；只有你独立确认后，才可把 `$SameDirectoryConfirmed` 改为 `$true` 并重跑。
- 不自动删除旧目录；失败时保留旧目录与外部备份，按备份路径人工恢复。

装完在新对话里说一句 **"征酱，你好"**——如果她用自然的语气回应你（不是普通助手的模板式回答），就说明 Skill 已生效。`// 注释` 是她的标志，但不会每次回复都出现。

## 使用

对话中直接叫"征酱"即可触发。也可以说"用征酱的视角分析……"。

四种形态自然切换：
- **常服** — 日常聊天和分析
- **毛装** — 严肃话题
- **主唱** — 活泼表达
- **军服** — 简洁决策

**地球online**：在已处于 Loji 角色模式，或先提及 Loji/征酱后，说"地球online""查一下""现实数据"可切换到现实知识模式（会诚实标注搜索结果状态，不假装实时检索）。未进入角色模式时，裸"地球online"按普通查询处理，不冷启动角色。分析中国财政/经济/政策问题时，Loji 会调用其现实制度知识底座。

管理记忆（在 Loji 角色模式下，或明确提及 Loji 后）：
- "记住……" — 写入记忆
- "你记得我什么？" / "显示记忆摘要" — 查看记忆
- "忘记……" / "删除关于 X 的记忆" — 精确删除
- "清空近期上下文" — 只清临时上下文
- "清空所有记忆" — 清空整个文件（需确认）
- "记忆健康检查" / "检查记忆" — 输出记忆健康度报告
- "恢复记忆：X" — 从归档重新激活

**维护模式**：说"退出征酱模式""暂停角色扮演""进入维护模式"，Loji 会暂停角色输出，以普通助手身份回应（便于调试或处理非角色任务）。

## 文件说明

### 角色运行文件（Skill 生效必需）

- `SKILL.md` — 人格定义与规则（运行时权威）
- `memory.template.md` — 记忆 schema 骨架（安装时由 `scripts/init_memory.py` 安全创建为 `memory.md`）
- `references/MEMORY.md` — 记忆行为规则（按需加载）
- `scripts/init_memory.py` — 安全初始化 `memory.md`，不覆盖已有文件
- `references/LORE.md` — 世界观与背景
- `references/STYLE.md` — 表达风格详情
- `references/SAFETY_BOUNDARIES.md` — 安全规则
- `references/STATE_MACHINES.md` — 形态/路线/记忆/成长弧的状态机定义
- `references/domain-knowledge.md` — 现实领域知识底座

### 开发与研究资料（不影响日常使用）

- `research/` — 深度研究资料：分析模型（`ANALYSIS_MODELS.md`）、政治场景规则（`POLITICAL_CONTEXT.md`）、来源考据（`SOURCES.md`、`canon/`）、评估框架（`evals/`）、人格故障模式（`PERSONA_FAILURE_MODES.md`）、证据映射（`evidence/`）
- `examples/` — 角色对话示例（`analysis.md`、`casual.md`），展示行为倾向，非固定模板

## 记忆范围

`memory.md` 是本地文件，记在同一台机器上：

| 场景 | 是否互通 |
|------|---------|
| 同一台机器、多个 Claude Code 窗口 | ✅ 互通（同一份 `memory.md`） |
| 不同机器 | ❌ 不互通（各自独立的文件） |
| 不同 Agent（如 Claude Code vs Codex） | ❌ 不互通（各自独立的 Skill 目录） |

> 换机器或换 Agent 时，可以手动复制 `memory.md` 过去——但注意不要提交到 git。

## 许可

原创内容使用 MIT 许可证。TFR 角色设定归原权利方所有。详见 [LICENSE](LICENSE) 和 [ATTRIBUTION.md](ATTRIBUTION.md)。
