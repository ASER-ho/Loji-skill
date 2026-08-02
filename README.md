# Loji-skill

长征机/逻辑/征酱——一个基于 TFR 模组的虚构 AI 角色扮演 Skill。

**当前版本：v0.8.0**（2026-08-02）· 变更记录见 [CHANGELOG](CHANGELOG.md)

## 安装

```bash
git clone https://github.com/ASER-ho/Loji-skill.git ~/.claude/skills/Loji-skill
cp ~/.claude/skills/Loji-skill/memory.template.md ~/.claude/skills/Loji-skill/memory.md
```

Windows：

```powershell
git clone https://github.com/ASER-ho/Loji-skill.git $env:USERPROFILE\.claude\skills\Loji-skill
Copy-Item $env:USERPROFILE\.claude\skills\Loji-skill\memory.template.md $env:USERPROFILE\.claude\skills\Loji-skill\memory.md
```

装完在新对话里说一句 **"征酱，你好"**——如果她用自然的语气回应你（不是普通助手的模板式回答），就说明 Skill 已生效。`// 注释` 是她的标志，但不会每次回复都出现。

## 使用

对话中直接叫"征酱"即可触发。也可以说"用征酱的视角分析……"。

四种形态自然切换：
- **常服** — 日常聊天和分析
- **毛装** — 严肃话题
- **主唱** — 活泼表达
- **军服** — 简洁决策

**地球online**：说"地球online""查一下""现实数据"可切换到现实知识模式（会诚实标注搜索结果状态，不假装实时检索）。分析中国财政/经济/政策问题时，Loji 会调用其现实制度知识底座。

管理记忆：
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
- `memory.template.md` — 记忆模板（安装时复制为 `memory.md`，见上方安装步骤）
- `references/LORE.md` — 世界观与背景
- `references/STYLE.md` — 表达风格详情
- `references/SAFETY_BOUNDARIES.md` — 安全规则
- `references/STATE_MACHINES.md` — 形态/路线/记忆/成长弧的状态机定义
- `references/domain-knowledge.md` — 现实领域知识底座（**仅适用于分析中国财政/经济问题**）

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
