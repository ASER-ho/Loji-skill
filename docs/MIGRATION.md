# 从旧目录 `Loji-skill` 迁移

[← 返回 README](../README.md)

以下步骤仅适用于 Claude Code 的旧安装目录 `~/.claude/skills/Loji-skill`。

> [!NOTE]
> 本指南是旧目录改名与 `memory.md` 备份流程，不是 v1.1.3 / v1.1.4 私人状态迁移工具。此脚本仅自动备份并校验 `memory.md`，其中包含的事件记忆随正文备份。若存在 `JUDGMENTS.md`、`memory.state.json` 及其备份或本地接入配置，必须先另外完成受保护的备份与哈希核对，再执行目录改名；这些私人文件不得上传或提交。新安装不直接导入旧授权状态。新宿主的记忆恢复许可按 [接入指南](../references/CODEX_SETUP.md) 重新确认。

如果已经安装过旧版本，不要直接重新 clone 覆盖。以下步骤按顺序执行；任何一步失败都停止，不移动原目录。

## macOS / Linux

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

## Windows（PowerShell）

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

## 要点

- 同一天重复运行使用时间戳目录，不会覆盖先前备份；`mkdir` / `New-Item` 已存在即失败。
- 复制失败、哈希工具缺失或哈希不一致时立即停止。
- 打印哈希不算校验；必须像上面一样比较并检查退出状态。
- 校验成功前不移动原目录；移动后再次校验。
- POSIX 使用设备号 + inode 判断目录身份；`stat` 不可用时安全停止。
- Windows：两条路径都存在时脚本停止。仅大小写不同的字符串不被当作同一目录的证明；只有你独立确认后，才可把 `$SameDirectoryConfirmed` 改为 `$true` 并重跑。
- 不自动删除旧目录；失败时保留旧目录与外部备份，按备份路径人工恢复。
