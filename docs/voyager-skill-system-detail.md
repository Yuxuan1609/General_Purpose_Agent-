# Voyager 技能系统详解

> **论文**: Voyager: An Open-Ended Embodied Agent with Large Language Models
> **作者**: Guanzhi Wang, Yuqi Xie, Yunfan Jiang, Ajay Mandlekar, Chaowei Xiao, Yuke Zhu, Linxi "Jim" Fan, Anima Anandkumar (NVIDIA / Caltech / UT Austin / Stanford, 2023)
> **链接**: https://arxiv.org/abs/2305.16291
> **代码**: https://github.com/MineDojo/Voyager
> **整理日期**: 2026-06-02
> **优先级**: ⭐⭐⭐ 必读

---

## 一、系统总览

Voyager 是一个 **Minecraft 中的开放式具身 agent**，无需人类干预即可探索、学习技能、做出发现。三个核心组件协同工作：

```
Automatic Curriculum ──→ 提议下一个任务
       │
       ▼
Iterative Prompting ──→ GPT-4 生成/修正代码 (最多 4 轮)
       │
       ▼
Self-Verification ──→ 验证任务是否完成
       │
       ├── 完成 → 存入 Skill Library + 查询新任务
       └── 失败 → 继续修正，4 轮后换任务
```

---

## 二、Skill Library（技能库）— Section 2.2

### 2.1 技能是什么

每个技能是一段**可执行的 JavaScript 代码**（基于 Mineflayer API），封装完成特定任务的时序动作。代码通过 embedding 索引，可检索、可复用、可组合。

原文设计原则：*"Inspired by the generality, interpretability, and universality of programs, we represent each skill with executable code."*

### 2.2 技能创建流程

```
当前任务 → GPT-4 生成初始代码 → 执行 → 获取环境反馈+执行错误
    ↓                                                     ↓
  迭代修正 ← 环境反馈 + 执行错误 + critique 拼入 prompt ←─┘
    ↓
  Self-Verification 检查
    ├── 通过 → 存入 Skill Library（description embedding → code）
    └── 失败 → 回迭代（最多 4 轮，超时换任务）
```

### 2.3 创建时的完整 prompt 结构（12 项组件）

代码生成的输入 prompt 包含：

1. **代码生成指南** — 约束和鼓励
   - *"Your function will be reused for building more complex functions. Therefore, you should make it generic and reusable."*
2. **控制原语 API** — Mineflayer 基础操作（`mineBlock`, `craftItem`, `exploreUntil`, `placeItem`, `killMob` 等 ~15 个函数）
3. **Retrieved skills** — 从技能库检索的 top-5 相关技能
4. **上一轮生成的代码**
5. **Environment feedback** — `bot.chat()` 输出的中间进度（如 "I cannot make stick because I need: 2 more planks"）
6. **Execution errors** — 解释器抛出的错误（如 `throw new Error('No item named acacia_axe')`）
7. **Critique** — Self-Verification 模块的 critique
8. **Agent 当前状态** — 背包、装备、附近方块/实体、群系、时间、血量、饥饿值、位置
9. **当前任务** — Automatic Curriculum 提议的任务
10. **Task context** — GPT-3.5 生成的 general suggestion
11. **Chain-of-thought** — 先解释为什么上次失败，再给出 step-by-step 计划，最后生成代码

### 2.4 技能存储与索引

```
存入：
  key = GPT-3.5 embedding(program_description)
  value = 完整的 JavaScript 代码

检索：
  query = GPT-3.5 embedding(general_suggestion + environment_feedback)
  返回 top-5 最相关技能
```

- 描述由 GPT-3.5 自动生成（非人工编写）
- 使用 GPT-3.5 做 embedding（预算考虑）
- 检索时 **general suggestion 与环境反馈拼接**作为 query

### 2.5 技能的层次化组合

复杂技能通过组合简单技能合成：

```
craftStonePickaxe() {
    mineBlock(bot, "cobblestone", 3);     // 已有简单技能
    craftItem(bot, "stick", 2);           // 已有简单技能
    craftItem(bot, "crafting_table", 1);  // 已有简单技能
    // ... 组合为新技能
}
```

论文强调：*"Complex skills can be synthesized by composing simpler programs, which compounds Voyager's capabilities rapidly over time and alleviates catastrophic forgetting."*

---

## 三、Automatic Curriculum（自动课程）— Section 2.1

### 3.1 工作机制

GPT-4 根据当前状态**自动提议下一个任务**，从简单到复杂渐进：

**prompt 包含**：
1. 行为指导（"我的最终目标是发现尽可能多的不同事物"）
2. Agent 当前状态（背包、装备、附近实体、群系、时间、血量、饥饿值、位置）
3. 已完成和失败的任务列表（反映探索进度和能力边界）
4. Additional context：GPT-3.5 根据当前状态和进度自问自答

### 3.2 输出示例

```
背包有 wooden_pickaxe + stones → "Craft 1 stone pickaxe"
背包有 fishing_rod + 在河边 → "Catch 1 fish"
饥饿值为 0 + 附近有猪 → "Kill 1 pig"
背包有 raw_iron + coal + furnace → "Smelt 4 raw iron"
夜晚 + 附近有僵尸 + 有剑 → "Kill 1 zombie"
```

### 3.3 Warm-up Schedule

预热阶段预置了初始任务序列，从基础开始逐步递进（附录 Table A.1），确保早期就能积累基础技能。

---

## 四、Iterative Prompting Mechanism（迭代提示机制）— Section 2.3

### 4.1 三种反馈

| 反馈类型 | 来源 | 作用 |
|---------|------|------|
| **Environment feedback** | `bot.chat()` 输出 | 展示执行中间进度，如 "I cannot make iron chestplate because I need: 7 more iron ingots" |
| **Execution errors** | 代码解释器 | 暴露无效操作或语法错误，用于 bug fix |
| **Self-verification** | 另一个 GPT-4 实例 | 检查任务是否完成，失败时提供 critique |

### 4.2 迭代终止条件

- **成功**：Self-Verification 验证通过 → 存入 Skill Library → 查询新任务
- **失败超时**：4 轮代码生成仍未通过 → 放弃当前任务，查询新任务

### 4.3 Self-Verification（自验证）— 附录 A.5

不同于 Reflexion 只做失败反思，Voyager 的 Self-Verification **同时检查成功 + 失败反思**。

**prompt 结构**：
1. Agent 状态（排除不相关的 nearby blocks/entities）
2. 当前任务
3. Task context（GPT-3.5 的 general suggestion）
4. Chain-of-thought：先推理成功/失败 → 输出 boolean → 失败时提供 critique
5. Few-shot examples

**输出格式**：
```json
{
  "reasoning": "You have 5 coal in your inventory.",
  "success": true
}
```

失败时：
```json
{
  "reasoning": "To craft a spyglass, you need 2 copper ingots and 1 amethyst shard. You have 3 copper ingots, but you don't have any amethyst shards.",
  "success": false,
  "critique": "Find and mine an amethyst shard underground."
}
```

论文原文对比：*"Our self-verification is more comprehensive than self-reflection [Reflexion] by both checking success and reflecting on mistakes."*

---

## 五、实验结论

### 5.1 核心结果

Voyager 对比 ReAct、Reflexion、AutoGPT 等基线：
- **3.3 倍**更多独特物品
- **15.3 倍**更快解锁科技树里程碑
- **2.3 倍**更远探索距离

### 5.2 消融实验结论

三个组件（Automatic Curriculum, Skill Library, Iterative Prompting）各自独立消融后性能显著下降，**三组件缺一不可**。

---

## 六、与本项目的关系分析

### 6.1 直接对应的组件映射

| Voyager | 本项目 |
|---------|--------|
| **Automatic Curriculum** — GPT-4 自动提议下一个探索任务 | **Task Decomposer** — Orchestrator 中将用户请求分解为 Task 序列 |
| **Skill Library** — embedding 索引的可执行 JavaScript 代码库 | **L3 Skill Layer** — SKILL.md 格式的技能，通过工具注册给 Agent |
| **Iterative Prompting** — 代码生成→执行→反馈→修正循环 | **AgentLoop** — Execute 阶段的 LLM 调用 + 工具调度 + POST-TOOL 跟踪 |
| **Self-Verification** — 另一 GPT-4 实例检查成功+提供 critique | **MetaDriver** — 反射触发器 + 验证器 + Reflect 反思 |
| **Environment feedback** — bot.chat() 输出的中间进展 | **Tool dispatch 结果** — 工具调用返回的原始结果 |
| **Execution errors** — 代码解释器错误 | **工具执行错误** — terminal 超时/异常等 |
| **description embedding** → **code** 的键值存储 | **L3 SKILL.md** 文件 + 通过工具调用执行 |
| GPT-3.5 生成 embedding 做检索 | 你的 L2 KnowledgeGraph + domain 匹配做检索 |

### 6.2 关键差异

#### 差异 1：技能的表现形式

- **Voyager**：每个技能是**完整的 JavaScript 代码**（可执行程序），调用 Mineflayer API 直接控制游戏
- **本项目**：L3 技能是 **SKILL.md 格式的描述文档**，Agent 在 system prompt 中看到后通过工具调用执行

Voyager 的方式**更自动化**（代码直接执行），但受限于 Minecraft 的 Mineflayer 环境。你的方式**更通用**（SKILL.md 适合任意领域），但需要 Agent 理解后主动调用工具。

#### 差异 2：技能创建的粒度

- **Voyager**：每次**完成一个具体任务**后自动创建/更新技能（存入 library）
- **本项目**：L2→L3 编译条件是 **≥3 张同域卡片 + 平均激活 > 0.7**，触发后再调用 LLM 编译

Voyager 更激进（每个任务都存），你的更保守（需要积累充分证据才编译）。

#### 差异 3：检索策略

- **Voyager**：description embedding → top-5 skills，外加 GPT-3.5 生成的 general suggestion 增强 query
- **本项目**：L3 按 domain 精确匹配 > 父级匹配 > general 跨域 > 根域，不使用 embedding

你的 domain 树匹配更高效但缺少语义泛化。Voyager 的 embedding 检索能跨域发现相似技能（如"伐木"和"采矿"都涉及 `mineBlock`），这是值得借鉴的。

### 6.3 可直接借鉴的设计

1. **技能创建 prompt 模板** — 附录 Prompt 4 的完整 system prompt（包括控制原语 API 定义、代码指南、few-shot 示例），可直接用于你 L2→L3 编译的 LLM prompt 参考
2. **Self-Verification 的 critique 输出格式** — `{reasoning, success, critique}` 三元组，可用于改善你 MetaDriver 反射的 JSON schema
3. **代码生成的 CoT 策略** — "先解释为什么上次失败，再给出 step-by-step 计划，最后生成代码" 的三段式 prompt 设计
4. **检索 query 拼接策略** — general suggestion + 当前环境反馈拼接作为 query，这个组合策略也可用于你 L2 检索时的 query 构造
5. **自动课程的分层递进** — 从简单到复杂自动提议任务的模式，可参考用于你 Task Decomposer 的任务排序逻辑
