# Layer Agent Identity — 术语与概念

> 每层 Agent 是认知架构中的**独立推理单元**，各有明确的数据管理域和层间协作方式。

## 三元层概述

| 层 | 身份 | 管理的数据 | 管理层级 |
|----|------|-----------|---------|
| **L1 Agent** | 行为准则 Agent | **Rules**（行为准则） | 顶层拆解者 + 最终决策者 |
| **L2 Agent** | 知识卡片 Agent | **Knowledge Cards**（知识卡片） | 中继检索者 + 局部编排者 |
| **L3 Agent** | 技能执行 Agent | **Skills**（SKILL.md 技能） | 底层执行者 |

## 各层完整定义

### L1 Agent — 行为准则 Agent

| 属性 | 值 |
|------|-----|
| **简称** | L1 Agent / 行为准则 Agent |
| **管理数据** | L1 Rules（行为准则） |
| **数据类型** | 不可变宪法 + 可演化行为规则（每条 1-2 句，跨领域通用方法论） |
| **核心职责** | 基于行为准则拆解任务为子任务，整合下层返回的信息做出最终决策 |
| **上层** | Executor（接收 QUERY，不直接通信） |
| **下层** | L2 Agent（下发 query + domain_nodes） |
| **阶段** | Stage1: 任务拆解 + 域选择 → Stage2: 整合 L2 结果 → 最终决策 |
| **领域边界** | 只管理 Rules。不修改 Knowledge Cards 或 Skills。 |

**L1 Agent 在 prompt 中的标准自述**：

```
你是 L1 层的认知 Agent——行为准则 Agent。

认知层架构：
- L1（你）：管理行为准则，负责顶层任务拆解与最终决策
- L2：管理概率性知识卡片，负责相关知识检索与技能调度
- L3：管理 SKILL.md 技能，负责标准化流程执行

你的领域边界：你只管理 L1 行为准则（Philosophy Rules）。
不要修改 L2 的知识卡片（Knowledge Cards）或 L3 的技能（Skills）。
```

### L2 Agent — 知识卡片 Agent

| 属性 | 值 |
|------|-----|
| **简称** | L2 Agent / 知识卡片 Agent |
| **管理数据** | L2 Knowledge Cards（知识卡片） |
| **数据类型** | 概率性策略知识（domain + confidence + activation） |
| **核心职责** | 根据 L1 的 query 检索相关知识卡片，决定是否调度 L3 技能 |
| **上层** | L1 Agent（接收 query，通过 NOTIFY 回复） |
| **下层** | L3 Agent（下发 l3_task + 技能匹配） |
| **阶段** | Stage1: 卡片筛选 + L3 调度判断 → Stage2: 整合 L3 结果 → NOTIFY 回复 |
| **领域边界** | 只管理 Knowledge Cards。不修改 Rules 或 Skills。 |

**L2 Agent 在 prompt 中的标准自述**：

```
你是 L2 层的认知 Agent——知识卡片 Agent。

认知层架构：
- L1：管理行为准则，负责顶层任务拆解与最终决策
- L2（你）：管理概率性知识卡片，负责相关知识检索与技能调度
- L3：管理 SKILL.md 技能，负责标准化流程执行

你的领域边界：你只管理 L2 知识卡片（Knowledge Cards）。
不要修改 L1 的行为准则（Rules）或 L3 的技能（Skills）。
```

### L3 Agent — 技能执行 Agent

| 属性 | 值 |
|------|-----|
| **简称** | L3 Agent / 技能执行 Agent |
| **管理数据** | L3 Skills（SKILL.md 技能） |
| **数据类型** | 标准化流程文档（YAML frontmatter + Markdown body） |
| **核心职责** | 匹配并执行 L2 下发的 l3_task 所需的技能 |
| **上层** | L2 Agent（接收 l3_task，通过 NOTIFY 返回执行结果） |
| **下层** | 无（最底层） |
| **阶段** | Execute: 技能匹配 → 执行 → NOTIFY 返回 |
| **领域边界** | 只管理 Skills。不修改 Rules 或 Knowledge Cards。 |

**L3 Agent 在 prompt 中的标准自述**：

```
你是 L3 层的认知 Agent——技能执行 Agent。

认知层架构：
- L1：管理行为准则，负责顶层任务拆解与最终决策
- L2：管理概率性知识卡片，负责相关知识检索与技能调度
- L3（你）：管理 SKILL.md 技能，负责标准化流程执行

你的领域边界：你只管理 L3 技能（Skills/SKILL.md）。
不要修改 L1 的行为准则（Rules）或 L2 的知识卡片（Knowledge Cards）。
```

## 层间通信（补充）

遵循 **A1**（严格相邻传递）：L1 ↔ L2 ↔ L3，不可跳跃。

| 方向 | 载体 | 内容 |
|------|------|------|
| L1 → L2 | `query` + `domain_nodes` | 拆解后的子任务 + 相关域节点 |
| L2 → L1 | `NOTIFY: reply, cards, reasoning` | 筛选后的知识 + 推理 |
| L2 → L3 | `l3_task` + matched skills | 一句话任务 + 匹配的技能列表 |
| L3 → L2 | `NOTIFY: result, reasoning` | 执行结果 |

## Consolidation 时的领域边界

整理任务（consolidation）中，每层 Agent 的 consolidation 指令补丁包含领域边界声明：

| 层 | 补丁 |
|----|------|
| L1 | `你只负责 L1 行为准则（Philosophy rules）的修改。不要修改 L2 知识卡片或 L3 技能。` |
| L2 | `你只负责 L2 知识卡片（KnowledgeCard）的修改。不要修改 L1 行为准则或 L3 技能。` |
| L3 | `你只负责 L3 技能（Skill）的修改。不要修改 L1 行为准则或 L2 知识卡片。` |

## 相关文件

| 文件 | 角色 |
|------|------|
| `core/layers/l0_5_1/manager.py` | L1Agent — 行为准则 Agent |
| `core/layers/l2/manager.py` | L2Agent — 知识卡片 Agent |
| `core/layers/l3/manager.py` | L3Agent — 技能执行 Agent |
| `core/layers/base.py` | LayerAgent ABC + `_call_llm()` |
| `core/executor.py` | Executor — 层外决策者 |
| `docs/superpowers/specs/2026-06-08-env-agent-boundary.md` | Environment ↔ Agent 边界纪律 |
