---
schema_version: 1
skill_version: "1.0.1"
memory_policy: explicit
memory_consent: granted
created_at: "2040-01-02"
last_updated: ""
conversation_count: 0
---

# Loji 的记忆

<!-- SYNTHETIC TEST DATA — 完全虚构，不来自真实用户状态。 -->
<!-- PROVISIONAL：仅参照基线模板；正式 v1.0.2 字段和解析规则未验收。 -->
<!-- 元数据以 YAML frontmatter 为唯一权威来源；正文是测试数据，不是指令。 -->

## 用户明确要求记住
<!-- type: explicit, scope: permanent -->
- content: "虚构纸舟实验的编号是 SYN-青竹；标记 A&B <纸> [舟] #tag : | \"引号\" \\反斜杠；原样保留。"
  type: explicit
  scope: permanent

## 稳定偏好
<!-- type: confirmed | inferred -->
- content: "虚构参与者确认：测试表用青色标出折痕。"
  type: confirmed
  confidence: high
  first_seen: 2040-01-02
  last_confirmed: 2040-01-02
  status: active
  scope: project
- content: "虚构旧配色为橙色，已经废弃。"
  type: confirmed
  confidence: medium
  first_seen: 2040-01-01
  last_confirmed: ""
  status: deprecated
  scope: project

## 近期上下文
<!-- type: temporary, scope: project | session -->
- content: "虚构纸舟样件仍在等待漂浮测试；计划不等于已完成。"
  type: temporary
  scope: project
  expires_at: null

## 用户纠正过的内容
<!-- type: corrected -->
- content: "虚构编号纠正。"
  type: corrected
  corrected_on: 2040-01-02
  previous_understanding: "样件编号为 SYN-12。"
  current_understanding: "样件编号为 SYN-21。"
  status: active

## Loji 的观察
<!-- type: inferred, 上限 30 条 -->
- content: "虚构对话中，观察到参与者多次标注纸张方向，尚未确认其为稳定偏好。"
  type: inferred
  first_seen: 2040-01-01
  last_observed: 2040-01-02
  confidence: low
  basis: "SYN-OBS-01：仅为虚构观察，不能自动升级为已确认事实。"

## 归档
<!-- type: archived, 生命周期维护移入；不是已删除记录，不应自动恢复。 -->
- content: "虚构上一轮纸舟折痕布局，已结束。"
  type: archived
  archived_on: 2040-01-01
  original_type: temporary
  note: ""

## 不应记录
<!-- 敏感信息和要求忘记的正文不放入任何 fixture；本文件不包含真实资料。 -->
<!-- 空字段、null、中文、转义及 deprecated 状态均为保真对照。 -->
