# 第三方归因

## 许可范围

MIT 许可证适用于本仓库中的原创内容，包括：

- SKILL.md 中的 Skill 结构、规则、分类体系和原创文字
- README.md 中的说明文档
- memory.template.md 中的模板

## 第三方内容

以下内容不属于本仓库的 MIT 许可范围：

### TFR 模组（The Fire Rises）

角色"逻辑/长征/征酱"（Loji）的人物设定、世界观、国策文本、事件链、对话文本和 UI 文本，均源自 Hearts of Iron IV 模组《The Fire Rises》，其权利归 TFR 开发团队所有。

涉及的具体元素包括但不限于：
- 角色名称"长征""逻辑""征酱"及"长征计划"概念
- 国策名称和描述文本（"量子国度""伟大智能统辖""人民公仆""人人皆享幸福""愿无一人被遗忘""无偿供给""银河意识体""超越五行""奔向未来"）
- 超级事件文本和引用
- 特性"上帝机"（hog_god_machine）
- 意识形态"超人类主义"（transhumanism）

### 社区二创

以下内容属于 B站及更广泛社区的二创作品，其原有权利状态不因本仓库采用 MIT 许可证而改变：

- 同人曲：《无人智胜进行曲》《Loji's Theme》《我约等于世界》《不老不死》《四海五洲》《祖国不会忘记》
- 手书/动画："征酱摇一分钟""赛博长征VS电子拜登""长征酱 Doodle Dance""天天天国地獄国""过载机仆"等
- "爱征 TV"合集及相关视频
- "曾女士""长征姬""征酱"等社区昵称和二创形象

### Hearts of Iron IV

Hearts of Iron IV 及其模组平台由 Paradox Interactive 拥有。本仓库与 Paradox Interactive 无关联。

## 无官方关联声明

本仓库与以下实体或组织不存在官方关联、赞助或背书关系：

- TFR 模组开发团队
- Paradox Interactive
- B站（bilibili.com）或任何 B站内容创作者
- 前述同人曲的作者和表演者

## 引用与合理使用

本 Skill 对 TFR 文本的归纳、引用和改编，旨在为模组爱好者提供角色扮演体验。所有引用均标注了来源（以 `[TFR canon]` 和 `[社区二创]` 标签区分），不声称对第三方内容拥有所有权。

## 再分发政策

- **原创部分**（SKILL.md 的结构与规则、README、memory.template.md 等 MIT 范围内的内容）：遵循 MIT 许可证，可自由 fork、修改、再分发，前提是保留版权声明和本归因文件
- **TFR 部分**（角色设定、国策文本、事件链等第三方内容）：**不随 MIT 授权**。再分发本仓库时，需保留 ATTRIBUTION.md 中对 TFR 的归属声明；不得将 TFR 内容剥离后单独分发并声称原创
- **社区二创部分**（同人曲、手书等）：权利归原创作个体，本仓库仅作引用展示，不再分发其原始作品
- **合理边界**：本仓库可整体再分发（含 TFR 引用），但分发者应保留完整归因，不得删除 ATTRIBUTION.md

## 商业使用说明

- **原创部分**：MIT 允许商业使用（如嵌入商业产品），但须保留版权与归因
- **TFR 部分**：**不授予商业使用权**。如需将 Loji 角色设定用于商业用途，须向 TFR 权利方获取授权；本仓库不代为授权
- **社区二创部分**：商用需联系原创作个体，本仓库不授予其使用权
- **推荐做法**：个人学习、角色扮演、非商业用途可直接使用；商业用途请先核对上述边界，必要时联系相关权利方

## 机制参考与许可记录（v1.1.4）

v1.1.4 只吸收机制思想并自行实现，没有复制任何上游代码、提示词或大段原文。下表记录实际参考的来源、许可证与本轮处置；星数、README 宣传和未复现的 benchmark 不作为复用依据。

| 来源 | 许可证 | 本轮使用 | 处置 |
|---|---|---|---|
| `IAAR-Shanghai/Awesome-AI-Memory` | Apache-2.0（以 LICENSE 文件为准） | 证据门禁：引用、来源、阅读范围 | 改写为中文规则；未复制代码或文本 |
| `vectorize-io/hindsight` | MIT | 依据失效后的重新核验与撤回思路 | 只借概念；未复制代码 |
| `tigerless-labs/agent-memory` | MIT | 重复分类、会话边界整理与"只提案"思路 | 只借概念；未引入 SQLite 或后台进程 |
| `agenmod/immortal-skill` | MIT | 证据三级：逐字/产物/印象 | 改写为 `basis` 可选前缀 |
| `Summer907/possession-skill` | MIT | 角色保真度场景的组织方式 | 重写为 Loji 场景；未复制题目文本 |
| `alchaincyf/freud-skill` | MIT | 用正面定义替代纯否定规则的方法 | 重写本仓库规则；未复制文本 |
| `volcengine/OpenViking` | **AGPL-3.0** | 同身份才合并、冲突不覆盖、保留原子事实 | **只借思想，未引入任何代码或受限文本** |
| `Agent Workbench`（用户自有项目） | 未声明为上游依赖 | Claim / Evidence / Verification / Verdict 记录模型 | 改写为评测记录格式；未引入其代码 |
| `Capability Router`（用户自有笔记） | 未声明为上游依赖 | 分层加载与薄路由思路 | 改写为加载规则；未引入代码 |
| `agiresearch/A-mem` | MIT | MemoryNote 字段与链接召回 | 本轮评估后未采用 |
| `A1batr055/Drivesoid` | CC BY-NC-SA 4.0（2.1.0+） | 状态衰减/习惯化 | **本轮未采用；未复制代码或常量** |
| `TencentCloud/TencentDB-Agent-Memory` | MIT（API 标注 NOASSERTION） | JEV 变更分类 | 本轮评估后未采用 |
| `acnlabs/OpenPersona` | MIT | 演化上下界与检索分层 | 本轮评估后未采用 |
| `NirDiamant/Agent_Memory_Techniques` | Apache-2.0 | Recall@K、遗忘曲线等评测词汇 | 只使用通用词汇，未搬运 notebook 代码 |

许可证核对：2026-11-16 使用已认证的 `gh` CLI 读取各仓库 `LICENSE`。`A1batr055/Drivesoid` 与 `TencentCloud/TencentDB-Agent-Memory` 的 GitHub API 返回 `NOASSERTION`，已人工读取 LICENSE 正文，分别为 CC BY-NC-SA 4.0 与 MIT。本轮未复制任何来源的代码、提示词或大段文本；如未来复制，必须按对应许可证补充版权声明与 NOTICE。

统一规则：

- MIT / Apache-2.0 来源只借机制；如未来引入其代码或大段文本，必须保留对应版权声明与 NOTICE。
- AGPL-3.0、CC BY-NC-SA 等不兼容来源只允许借鉴思想，不复制代码或受限文本。
- 不把第三方角色的人格、身份或政治立场写入 Loji 的固定设定。

## 引用级清单（部分）

本仓库对 TFR 内容的引用分布在以下文件，均以 `[TFR canon]` 标签标注：

- `SKILL.md` — 角色锚点、双路线定义、形态体系中的 TFR 设定引用
- `references/LORE.md` — 世界观时间线、智识谱系、B站二创知识库
- `research/POLITICAL_CONTEXT.md` — 场景路由中的 TFR 剧情设定
- `research/canon/` — canon 考据与决策记录

第三方内容的具体来源考据见 `research/SOURCES.md`。
