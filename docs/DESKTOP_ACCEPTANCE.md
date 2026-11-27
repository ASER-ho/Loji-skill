# DSH Desktop 真机验收记录

本文件记录 `loji-dsh` 插件在真实 Windows DSH Desktop 上的安装、对话、记忆写盘、升级与回滚验收。所有条目来自实际观测，未观测项明确标注为未验收。

## 环境

| 项 | 实测值 |
| --- | --- |
| 宿主 | DSH Desktop `@deepseek-ai/dsh-desktop/0.2.2-rc.5`，Electron `44.7.0`，Chromium `152.0.7977.130` |
| 宿主补丁模板 | `standard.patch.yml` @ `0.2.2-rc.5`（7286 字节，sha256 `e40bb192ed3b835312c2acd2ccd64d3bc4b85f80a7bc95b132cb18fbee190b5d`） |
| 插件 | `loji-dsh` 打包产物，技能版本 `skill 1.1.4`，安装方式 `pnpm add link:`（声明式 bundle） |
| 固定快照 | `0.2.2-rc.5`（官方 commit `9c2670d3bce5275e0d1610272958121af87787bb`），已从 rc.1 迁移 |
| 模型 | `DeepSeek-V4.1-Flash`，reasoning `High` |
| 权限与工作区 | `Workspace Write` / `Downloads` |
| 隔离根 | `output/LOJI-RELIABILITY-01`（`desktop-home`、`desktop-user-data`、`desktop-pnpm-store`） |

## 固定快照迁移（rc.1 → rc.5）

模板来源用两条独立证据钉死：宿主安装里的 `standard.patch.yml`（7286 字节）与 (a) `app.asar` 内嵌副本（偏移 122994248，全文唯一一处 `# Agent preset standard`，字节完全一致）、(b) GitHub tag `dsh-v0.2.2-rc.5` 中的 `packages/bundle/web-app/presets/standard.patch.yml` 完全一致。

rc.1 → rc.5 的真实 diff 只有 3 处，与漂移报告逐项对应：`skill-filesystem` 新增 `config.customSkillDirs`；`tool-subagent-control` 新增 `config.interrupt: false`；`present` 之后新增 `tool-office`（插件数 22 → 23）。迁移后 `loji-dsh/presets/upstream/standard-0.2.2-rc.5.patch.yml` 为上游字节副本，`loji-dsh/lib/preset.js:2` 的 `SNAPSHOT_VERSION` 同步为 `0.2.2-rc.5`，`validate_patch.py` 断言 23 个插件，`cordis.patch.yml` 由 `gen-preset-patch.mjs` 重新生成（+7 行，正是那 3 处差异）。

## 安装与加载

- `desktop-home/profiles/desktop` 内以 `pnpm add link:<隔离根>/tested-package/loji-skill` 安装，`packageDigest` = `d26212f5583b7ceeb1994e0ef3775c6ffb689d363c7bc7ae06b8e9137be9192e`（迁移前为 `5162f9c…`），`SKILL.md` sha256 = `a85a2b928e90c06f62e4d67ff7cade7341b1fe18fa0ada9755f738008c11499a`，`profile.fingerprint` = `fbd7840597c5f85c2e9ab4a5c5ae2901633eddfc19d271b29a93701df5e9b3b0`。
- 首启 New Session 页右下预设按钮即「长征机/逻辑」，说明 `loji-dsh` 的 preset 已在 Desktop 渲染层可见（截图 `desktop-candidate-shot1.png`）；Plugins → Installed plugins 列表出现 `loji-dsh`，启用开关为 checked（`desktop-rc5-plugins.txt:66-72`）。
- 同版本升级曾出现「命令返回成功、宿主仍加载旧目录」，因此本仓库以 `packageDigest` + `profile.fingerprint` 判定实际加载物，而非信任安装命令退出码。
- 链接安装必须带 `--package-root`，否则 `package` stage 报 `external_bundle_root_requires_explicit_path`。

## 真实多轮对话

| 模式 | 轮次 | 结果 |
| --- | --- | --- |
| 长征机/逻辑 | 2 | 完成，第 1 轮 6s、第 2 轮 4s；面板 `2 turns 6 steps`、`97.3K tok · Cache hit 86%` |
| Standard | 2 | 完成，6s / 3s；`2 turns 8 steps`、`134K tok · Cache hit 93%` |

被测内容与包内文件逐字核对一致：

- `references/STYLE.md:14`「幽默方式：逻辑推到极致后自然溢出的荒谬感，不是讲笑话」被正确引用（`desktop-rc5-loji-turn2.txt`、`desktop-rc5-standard-turn2.txt`）。
- 会话代号「青铜松果」在第二轮被正确复述，且只在会话内。
- `research/ANALYSIS_MODELS.md:7`「## 回答工作流」被正确报出。
- 两模式均表明只访问该技能包，未串到其他 provider。

## 记忆合同

- 代号「青铜松果」只存在于会话上下文，回复明确说明未写入记忆。
- 对话结束后在 `desktop-home` 与工作区 `C:/Users/ASUS/Downloads` 执行 `find -newermt '-40 minutes'`，未发现任何 `memory`/`judgments` 文件被创建或修改。

## 记忆写盘与跨会话恢复（真实宿主，隔离目录）

隔离目录 `C:/Users/ASUS/Desktop/测试专用/memory`，验收完成后目录已删除，证据副本留在 `output/LOJI-RELIABILITY-01/desktop-memory-evidence/`（`evidence.json`、`memory-final.md`）。

1. 脚本层 12 用例（`memory-acceptance.py`，真机真文件系统）：state 配置与 1024 字节上限、Episode 写入与读回、有界上下文恢复（`MIN_BYTE_BUDGET=177`，超限退出码 2）、证据指纹（valid/stale/missing、路径遍历拒绝）、并发冲突（同 `expected-digest` 双进程，退出码 `[0,2]`，失败方 `Memory changed since the host inspected it`）、崩溃原子性（子进程写入中 kill，内容仍为完整 A 或 B，无残留 tmp）、防复活（遗忘后用旧备份 `RestorePoint` 还原被拒：`content conflict`）。结果：`passed 12, failed []`（`memory-acceptance-report.json`）。
2. 真实对话写入：新会话在「长征机/逻辑」模式下被明确授权写盘，实际调用 `memory_state.py` 完成写入，`memory.md` 3026 → 3431 字节，`sha256` 写入前 `9d57efc4…` 与写入后 `bf9d562e…` 一致核验，生成唯一备份 `memory.md.bak.20261126T114840Z-9976-a93851c7`。写入落在「用户明确要求记住」（`type: explicit`、`scope: permanent`）与「稳定偏好」（`type: confirmed`、`confidence: high`）。
3. 跨会话恢复：另一个新会话读回「灰鹭」与「先给结论，再给依据」，并报出来源为 `memory.md` 第 21 行与第 39 行。
4. 越界写被宿主拦下：工作区为 `Downloads` 时，写 `测试专用/memory` 属工作区之外，首次 `--write` 报 `PermissionError: memory.state.json.transaction.lock [sandbox: file access denied under workspace-write]`，改用一次 `danger-full-access` 授权后才落地；`memory.md` 在失败那次一个字节都没有变化。

## `verify-install` 结果

带完整观测（`desktop-observations-rc5.json`，11 项 checks 全 true，含 `providerRank 600` 依据 `loji-dsh/lib/index.js:23 BUNDLED_SKILL_RANK=600`）重跑：**退出码 0，`overall: supported`**。

- 7 个 stage 全 `pass`（package / entry / skillProvider / preset / persona / resources / modes）。
- services 全 `supported`（skills / presetDeclarativeBundle / resourceResolution / sessionController）。
- `runtimeEvidence=operator_observation_matches_profile_and_package`。
- drift **`matched`**（`addedPluginIds []`、`changedPlugins []`、`orderChanged false`、`reason matches_snapshot`）。rc.1 时代的 `unknown`/退出码 2 已消除。

结果存 `desktop-verify-rc5.json`。

## 冲突与回滚演练

| 演练 | 操作 | 观测结果 |
| --- | --- | --- |
| A 冲突 | 从 profile `package.json` 的 `dsh.profile.bundles` 移除 `loji-dsh` | `verify-install` 立即 exit 1，`package` fail，code = `bundle_not_enabled_in_profile_manifest`；还原后 pass，digest 回到安装值 |
| B 升级 | 副本改版本 `1.0.1` 后 `pnpm add link:` | package pass，digest `0d39ce60c42cb6af69bdd41e7284feba408bd0c4993f9960292e40e9d6b62898`，`installed_version 1.0.1` |
| B 来源混用 | 用旧路径 `--package-root` 探测 | 正确拒绝：`package_source_conflict` |
| B 回滚 | `pnpm add link:` 回 `tested-package` | 版本回 `1.0.0`，digest 回安装值，`SKILL.md` sha 回 `a85a2b92…`，`same_digest=true` |

演练中的关键教训：用 Python 文本方式改写 profile `package.json` 会把 CRLF 归一成 LF，digest 随之变成 `447b2a24f22f57c875bda4e5eca55e3393ad5c7030d2337ca09a6b5431c63657`；必须按字节还原备份。这正是「文件指纹检查」要防的误判类型。

## 自动化回归

- Python：`python -m unittest discover -s tests -p 'test_*.py'` → `Ran 341 tests`，OK。
- DSH 插件：`node --test loji-dsh/tests/*.test.mjs` → 16 pass / 0 fail。
- `skill_budget.py`：238 行 / 3,597 汉字 / 最长非列表段 118 字符，OK。
- `validate_repo.py --strict`：OK（官方 `skills-ref` 在本机 ENV-BLOCKED，不计 PASS）。
- `gen-preset-patch.mjs --check` 与 `validate_patch.py`：`DSH preset validation OK: provider + preset, 23 plugins, persona matches source`。

## 未验收项

- 初次发布的验收范围为上述 Windows Desktop 配置。后续瘦身包的 Web 和 Desktop 结果见下表。
- 多用户/共享设备场景：插件按单用户本地环境设计，未做共享设备验收。

## 2026-11-27 瘦身包复核（PR #3）

在 Windows 上对提交 `b3f7973` 执行 `npm pack`。压缩包为 241,269 字节，SHA-256 为 `62de369781f936a3950f16b52bed3012d470a61cb24fe22063a7c66058862262`。解包后 80 个文件共 721,646 字节。DSH Web 和 Desktop 均为 `0.2.2-rc.5`，模型为 `DeepSeek-V4.1-Flash`。两个已有的隔离 Profile 均链接到同一份解包目录，启动宿主前已核对安装路径和 80 个文件。这次复核覆盖本地链接安装和升级后的加载。

| 宿主 | 预设 | 对话轮数 | 宿主显示的步骤数 |
| --- | --- | ---: | ---: |
| Web | Standard | 2 | 6 |
| Web | 长征机/逻辑 | 2 | 8 |
| Windows Desktop | Standard | 2 | 5 |
| Windows Desktop | 长征机/逻辑 | 2 | 9 |

四个独立会话均在首轮正确引用 `references/STYLE.md` 的“幽默方式”一行，在第二轮复述临时代号“青铜松果”并从 `research/ANALYSIS_MODELS.md` 返回首个二级标题“回答工作流”。本地原始观测位于 `output/LOJI-PR3-20261127/{web,desktop}-slim-{standard,loji}-turn{1,2}.txt`。

## loji-dsh 1.0.1 首次安装

2026-11-27，Windows 本机复用 DSH Web 和 Desktop 0.2.2-rc.5 宿主程序，两端分别从空的 DSH_HOME、独立的 Agents 目录开始。Desktop 首次启动生成的 Profile 只含基础插件，退出应用后用该 Desktop 自带的 CLI 安装。Web 用其 CLI 创建新 Profile 并安装。两端均直接安装同一份发布归档，随后启动宿主。

| 检查 | Web | Windows Desktop |
| --- | --- | --- |
| Profile 登记适配包 | loji-dsh 1.0.1 | loji-dsh 1.0.1 |
| 插件列表 | 已启用 | 已启用 |
| 新会话选择「长征机/逻辑」 | 成功 | 成功 |
| 安装内容与发布归档逐文件 SHA-256 核对 | 80/80 一致 | 80/80 一致 |

发布文件 `loji-dsh-1.0.1.tgz` 共 241,399 字节，解包后 721,939 字节，SHA-256 为 `1ea1c62309d7b0a9ad17fbb422f409777bafa50301360277f6ac5dd66471cf58`。归档打包自包含最终 README 的提交 `22e245e`。本轮验收覆盖无既有配置时的首次安装、自动登记，以及宿主应用界面中的启用状态及预设选择。Desktop 首次使用另有登录窗口；本轮未登录帐号或发送模型请求。前一节的四组真实模型对话使用 PR #3 产物；逐文件比对确认本版的技能正文、人格预设、提供者实现、记忆恢复逻辑与引用资源均与该产物一致。
