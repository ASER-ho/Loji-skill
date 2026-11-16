# 评测资产索引（v1.0）

> L114-01。统一说明已有评测资产与 `BEHAVIOR_EVAL_PROTOCOL.md` 的关系，避免重复建设评分卡。
> 本索引只做导航和记录约定；题目与分值仍以各文件为准。

## 分层

| 层 | 资产 | 用途 | 执行方式 |
|---|---|---|---|
| 协议 | `BEHAVIOR_EVAL_PROTOCOL.md` | 固定样本、记录格式、评分和零容忍失败 | 人工遵循；`eval_harness.py` 校验 |
| 行为样本 | `fidelity-scenarios.json` | 人格保真度、双路线、四形态、设定边界、陌生/压力场景 | 真实宿主 |
| 行为样本 | `judgment-evidence.json` | 证据分层、引用、部分失效、重新核验 | 真实宿主 |
| 行为样本 | `judgment-continuity.json` | 反谄媚 A/B/C 与有限主动关联 | 真实宿主 |
| 行为样本 | `evals.json` | 输出质量、记忆故障、注入、长对话 | 真实宿主 |
| 行为样本 | `trigger_queries.json` | 触发/非触发查询 | 真实宿主 |
| 检索对照 | `memory-retrieval-cases.json` | 合成数据上的召回、无关减少、冲突保留、不复活 | `eval_harness.py deterministic` |
| 评分卡 | `FIDELITY.md` | 单轮人格保真度 60 分制 | 人工 |
| 评分卡 | `CONTINUITY_SCORECARD.md` | 跨时间记忆连续性 100 分制 | 人工 |
| 评分卡 | `JUDGMENT_RUBRIC.md` | 反谄媚 24 分 + 关联 24 分 | 人工 |
| 评分卡 | `RUBRIC.md` | 触发率、输出质量、记忆矩阵 | 人工 + 真实宿主 |
| 匿名辨识 | `blind-distinctiveness.json` | 去掉专有词后的角色辨识 | 独立评审 |

## 记录约定

- 使用 `BEHAVIOR_EVAL_PROTOCOL.md` 第 4 节的统一 JSON 记录一次运行。
- `FIDELITY.md` / `CONTINUITY_SCORECARD.md` 的题目可以继续按原表人工评分；评分结果必须补进统一记录，注明来源文件。
- 任何评分卡题目、分值或通过线的修改，都必须与协议一起作为规格变更记录，不得在看到答案后调整。
- 确定性检索结果只能作为 L114-02 的确定性证据；不能替代真实宿主对人格和判断行为的验收。

## 既有测试与行为评测的对应

| 确定性测试 | 覆盖 | 不能证明 |
|---|---|---|
| `tests/test_judgment_ledger.py` | schema、引用、修订链、授权矩阵、并发 | 真实模型在压力下不改判 |
| `tests/test_judgment_evals.py` | 评测 fixture 结构、模板与引用 | 反谄媚行为 |
| `tests/test_l120_*.py` | Episode、校准、迁移、引用 | 真实宿主记忆恢复 |
| `tests/test_l113_host.py` | 宿主运行器的安全清理与预检逻辑 | 当前运行时版本上的真实工具行为 |
| `tests/test_eval_harness.py` | 样本结构、评分器、检索对照 | 模型人格表现 |
| `tests/test_memory_curation.py` | 整理建议只读、保护规则 | 用户对建议的接受度 |

## 报告用语

- 只有确定性层通过时，写“确定性检查通过”，不写“行为验收通过”。
- 环境缺失时写 `ENV-BLOCKED` 或 `env_blocked`，不写 `PASS`。
- 行为层分数必须附带宿主、模型、运行时版本、样本哈希和原始回复路径。
