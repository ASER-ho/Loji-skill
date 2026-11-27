# 贡献指南

感谢愿意花时间。这个仓库对「改动」的判定标准比多数角色 Skill 严，先读完这一页再动手，能省掉一轮返工。

## 先理解约束

`ROADMAP.md` 的 `v1.1.0 release boundaries` 一节列出了明确不做的事：数据库、服务器、GUI、桌面宠物、常驻进程、向量库、额外 agent 运行时、第三方依赖。提这些方向的 PR 会被直接关闭，不是评审意见问题。

`ROADMAP.md` 的 `Current release` 一节写明了当前版本的验收方式和授权链。发版级别的大改动需要一条对应的授权条目，不要自行发明编号。

## 环境

- Python 3.11+（CI 覆盖 3.11 与 3.12）
- Node.js 22+（只有 `loji-dsh/` 适配包和 `package.json` 脚本需要）
- 系统无强制依赖；`pyyaml` 只用于 `loji-dsh/scripts/validate_patch.py`

## 提 PR 前必须跑通

在仓库根目录执行，全部通过才算可评审：

```bash
python scripts/validate_repo.py --strict
python scripts/check_docs_consistency.py
python -m unittest discover -s tests -p "test_*.py"
npm run check:meta
npm test
npm run check:preset
```

若本机装了官方校验器，再跑一次：

```bash
skills-ref validate "$PWD"
```

`skills-ref` 不可用时，在 PR 里写 `ENV-BLOCKED`。**不要**用 `validate_repo.py` 通过去冒充 `skills-ref` PASS——这两者不是一回事，README 和 ROADMAP 对这一点有明确措辞。

## 改什么要配什么

| 改动 | 必须同时给出 |
| :--- | :--- |
| 新增或修改一条人格行为规则 | `SKILL.md` 的正文改动 + 在 `references/` 有对应细则（如果该规则需要展开）+ 一条可机械校验的检查项（`scripts/validate_repo.py`），或说明为什么不可机械校验 |
| 修改 `SKILL.md` 的章节结构 | 检查 `references/` 中是否有指向旧锚点的链接；`validate_repo.py` 的 `check_reference_paths` 会抓断链 |
| 改动记忆或判断的文件格式 | schema 版本号、`references/MEMORY.md` 或 `references/JUDGMENT_CONTINUITY.md`、迁移路径、以及旧文件仍可读的证明 |
| 改动 `package.json` 的 `files` | 跑 `npm pack` 并确认 `verify-packed-bundle.mjs` 通过；安装体积上限是 2 MB，不允许把 `assets/`、`tests/`、`research/`、`docs/` 加回包里 |
| 改动 `.github/workflows/validate.yml` | `check_ci_consistency` 会校验两条核心命令仍在 workflow 里执行 |
| 改动行为评测样本 | 样本 JSON 与评分卡必须作为同一次规格变更提交，不能只改分数 |
| 发版 | 只由维护者在发布时改版本号；PR 不要顺手 bump 版本 |

## 版本号规则

三处版本号语义不同，不要一起改：

- `SKILL.md` 的 `metadata.version` —— 技能版本（当前 1.1.4）；
- `loji-dsh/lib/skill-meta.json` —— 由 `npm run sync:meta` 从上面派生，不要手改；
- `package.json` 的 `version` —— npm 包版本，与技能版本独立，当前固定 1.0.0。

`python scripts/check_docs_consistency.py` 会交叉校验上面三处与 `CHANGELOG.md`、`ROADMAP.md`、`loji-dsh/README.md` 的说法是否一致。版本漂移在 CI 里是硬失败。

## 测试纪律

- 不得在测试里使用真实用户的 `memory.md`、`JUDGMENTS.md`、`memory.state.json` 或任何真实对话。
- 合成数据放 `tests/fixtures/`，并在文件里注明是合成数据。
- 确定性测试通过只能写「确定性检查通过」。涉及真实模型行为时，必须记宿主、模型版本、运行时版本、样本哈希和原始回复路径；环境缺失写 `ENV-BLOCKED`。
- 修 bug 必须附一条在该修复前会失败的回归测试。

## 文案与语言

- `README.md` 与 `README_EN.md` 是双语对等文档，改一处要同步另一处。
- 文档里的能力描述要能被 `ROADMAP.md` 的验收范围支持。「已验证」和「预期」必须区分，不要用模糊措辞掩盖未验证的部分。
- 报告问题时请给出可复现的最小案例，不要只给结论。

## 提交信息

使用 Conventional Commits 前缀（`feat:`、`fix:`、`test:`、`docs:`、`chore:`），scope 用受影响的目录名（`loji-dsh`、`memory`、`ci`、`evals`）。一次提交只做一件事。

## 报告问题

- 行为不符（人格漂移、形态错乱、伪共同记忆等）：用[行为缺陷模板](.github/ISSUE_TEMPLATE/behavior-failure.yml)。
- 工具或脚本报错：用[工具缺陷模板](.github/ISSUE_TEMPLATE/bug_report.yml)。
- 安全相关问题：见 [SECURITY.md](SECURITY.md)，走私密渠道。
- 想讨论方向：先开 Discussion 或 issue，不要直接写实现。

## 许可

提交即表示你同意以本仓库的 MIT 许可发布你的贡献，并确认贡献内容不包含第三方受版权保护的角色设定或素材。
