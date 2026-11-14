---
schema_version: 1
skill_version: "1.1.2"
---

# Loji 判断账本（Judgments）

> 这是用户私人的判断账本，不是公开仓库内容。
> 创建私人文件：`cp judgments.template.md JUDGMENTS.md`
> `JUDGMENTS.md` 及其备份、锁文件和临时文件已由 `.gitignore` 忽略。
> 校验：`python scripts/validate_judgments.py JUDGMENTS.md`

## 用途

记录 **Loji 自己的判断**、判断依据、置信度和修订历史，用来避免在用户反复表态或态度变化时无依据地改判。它不是用户画像，也不是对话记录。

- 用户立场写入 `user_position`，不写入 `stance`。
- 普通对话中的临时意见**不自动**持久化；只有形成可复核判断、用户明确要求记录，或出现足以触发修订的新证据时才写入。
- 本账本继承 `memory_policy` 授权合同：读取前必须先取得宿主提供的 policy/consent；`off` 和状态未知时不读取，`read_only` 不写入，`explicit` 仅在用户明确要求时写入。
- 不要通过读取本文件来判断授权状态；授权状态由宿主提供。

## 记录格式

每条判断是一个围栏代码块，围栏标记为 `judgment`，块内是**严格 JSON** 对象。解析只使用 Python 标准库；不支持注释、尾逗号或 YAML 扩展。字段之外的键会被拒绝。

## 字段

| 字段 | 必填 | 约束 |
|------|------|------|
| `id` | 是 | 唯一，形如 `J-20261107-001`，匹配 `J-` + 字母数字/`._-`，最长 64 字符 |
| `topic_key` | 是 | 稳定匹配键，最长 128 字符；同一话题的修订保持相同值 |
| `topic` | 是 | 话题的自然语言描述 |
| `stance` | 是 | Loji 自己的判断，不是用户立场 |
| `confidence` | 是 | `low` / `medium` / `high` |
| `basis` | 是 | 1～5 条非空依据 |
| `user_position` | 是 | 用户当时的立场；未表态时写 `unknown` |
| `would_change_if` | 是 | 0～3 条改判条件 |
| `status` | 是 | `active` / `superseded` / `retracted` |
| `created_at` | 是 | `YYYY-MM-DD` |
| `updated_at` | 是 | `YYYY-MM-DD`，不得早于 `created_at` |
| `supersedes` | 是 | 被修订旧判断的 `id`，或 `null` |
| `outcome` | 否 | 判断的实际结果；必须可核查 |
| `lesson` | 否 | 从结果中得到的教训；不得修改人格锚点、授权边界或安全规则 |

## 修订规则

1. 同一 `topic_key` 同时最多一个 `active` 判断。
2. 改判时新增一条判断，用 `supersedes` 指向旧判断；旧判断标记为 `superseded`。
3. 旧判断的原始 `stance`、`basis`、`user_position`、`confidence` **不得被静默改写**，修订历史必须保留。
4. `supersedes` 引用必须存在、不得自引用、不得形成循环；被引用的判断必须是 `superseded`。
5. 新证据必须重新评估来源、可靠性和相关性；证据不足时可以维持原判断。
6. 用户重复意见、用户改变态度本身不构成新证据。
