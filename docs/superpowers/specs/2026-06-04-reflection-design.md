# Reflection Implementation Design — Phase 2a

> 日期: 2026-06-04 | 状态: 设计完成 | 参考: LearingRefiner(已实现), Reflexion, Voyager

## 1. 目标

实现 Execute 段之后的反射学习闭环：识别哪些步骤值得学习 → 每层自我审查 → 提案修复 → 验证整合 → 执行。

不实现：反思效果验证、跨 trial 经验累积(recap)、L2→L3 自动编译。

---

## 2. 全流程

```
Session 结束
  │
  ├─ TaskDecomposer: Session → LearningUnit[]（纯规则，未来 LLM）
  │
  ├─ 每个 LearningUnit:
  │   │
  │   ├─ LearningRefiner(LLM): 选 worth_learning steps
  │   │   输出: {steps: [{index, reasoning}]}
  │   │
  │   └─ per-step:
  │       │
  │       ├─ Coordinator → ReflectPacket 同时发给 L1/L2/L3
  │       │
  │       ├─ L1:
  │       │   ├─ Proposer(LLM): 分析 layer_notify → {self_fixes, dispatch_l2?}
  │       │   ├─ if dispatch_l2 → L2 AgentPacket("reflect_dispatch")
  │       │   └─ Verifier(LLM): proposals + Philosophy.all_rules() → {verified, rejected}
  │       │   └─ Manager.apply_update(verified)
  │       │
  │       ├─ L2:
  │       │   ├─ if dispatch来自L1 → 合并到 input
  │       │   ├─ Proposer(LLM): {self_fixes, dispatch_l3?}
  │       │   ├─ if dispatch_l3 → L3
  │       │   └─ Verifier(LLM): proposals + FK.cards → {verified, rejected}
  │       │   └─ Manager.apply_update(verified)
  │       │
  │       └─ L3:
  │           ├─ if dispatch来自L2 → 合并到 input
  │           ├─ Proposer(LLM): {self_fixes}
  │           └─ Verifier(LLM): proposals + SkillLayer → {verified, rejected}
  │           └─ Manager.apply_update(verified)
  │
  └─ ReflectCoordinator._archive() → pending/ → learned/{domain}/
```

---

## 3. 核心数据结构

### 3.1 NOTIFY 增强（execute 段）

```
L1 NOTIFY:  {done, result, reasoning, rules_applied: [str], l2_received: {reply, cards}}
L2 NOTIFY:  {reply, cards, reasoning, cards_used: [str], l3_received: {skills}}
L3 NOTIFY:  {skills_matched: [str], skills_used: [str], status}
```

- `rules_applied` / `cards_used` / `skills_used`: LLM prompt 控制列出本次实际使用的内容摘要
- `l2_received` / `l3_received`: 下层返回的简化摘要

### 3.2 ReflectPacket（不变）

```python
ReflectPacket(
    record_id, domain, target_layer,
    refiner_reasoning,
    layer_notify,       # 该层 execute 段的完整 NOTIFY（含下层归来）
    issues=()
)
```

### 3.3 ReflectDispatch（L1→L2 / L2→L3）

```
AgentPacket(source_layer="l1", message_type="reflect_dispatch",
            content={task: "L1认为L2的卡片不够充分，请自查", context: {...}})
```

上层发 `LayerMessage(type=QUERY, subtype="REFLECT:DISPATCH")` 包装 `AgentPacket`，走现有 comm 通道。

### 3.4 Proposer 输出

```json
{
  "self_fixes": [
    {"action": "add_rule", "content": "持有弱牌时优先fold", "reason": "当前L1 reasoning 缺乏此准则"}
  ],
  "dispatch_lower": {
    "layer": "l2",
    "task": "L2的reply 未覆盖L1 query中对手手牌范围的计算需求，请自查知识卡片覆盖"
  }
}
```

`dispatch_lower` 为 null 表示不需要下沉。

### 3.5 Verifier 输出

```json
{
  "verified": [
    {"action": "add_rule", "content": "持有弱牌时优先fold", "integrated_with": "已有规则id"}
  ],
  "rejected": [
    {"action": "add_rule", "content": "持有弱牌时优先fold", "reason": "与已有规则#r3语义重复"}
  ]
}
```

---

## 4. 各层 Proposer

| 层 | 输入 | 分析要点 | 输出 actions |
|----|------|---------|-------------|
| L1 | layer_notify + refiner_reasoning + Meta + dispatch(可选) | result 是否匹配 reasoning；rules_applied 是否够用；l2_received 质量 | add_rule, modify_rule, remove_rule |
| L2 | layer_notify + refiner_reasoning + Meta + dispatch(可选) | cards_used 是否覆盖 query；reply 准确性；l3_received 质量 | boost_card, penalize_card, add_card |
| L3 | layer_notify + refiner_reasoning + Meta + dispatch(可选) | skills_used 是否够；是否漏掉可用技能 | update_skill |

Proposer 不访问数据库（Philosophy/FK/SkillLayer），只看 NOTIFY。去重整合留给 Verifier。

### 4.1 Proposer System Prompt 模板

```
你是 {layer} 层的反思 Proposer。分析本层 Execute 段的输出质量。

[执行反思标准]
{criteria}

[任务 Meta]
{meta}

你的任务：
1. 分析本层 NOTIFY，提出对本层内容的修复方案
2. 判断是否需要下层反思（仅在reasoning 显示下层输出不足时）
```

### 4.2 Proposer User Prompt 模板

```
[Refiner 评估]
{refiner_reasoning}

[上层 Dispatch]
{dispatch_task 或 "无"}

[本层 NOTIFY]
{layer_notify}

请输出 JSON 格式的提案。
```

---

## 5. 各层 Verifier

| 层 | 输入 | 已有内容来源 | 验证要点 |
|----|------|------------|---------|
| L1 | proposals + Philosophy.all_rules() | `data/l1_rules.json` | 去重、语义重复、矛盾检测、上限检查 |
| L2 | proposals + FK.cards(by domain) | `FlexibleKnowledge.cards` | 置信度边界(0.1-1.0)、卡片是否已存在、domain 是否有效 |
| L3 | proposals + SkillLayer 匹配结果 | `skills/` 目录 | 技能名唯一性、SKILL.md 格式合法性 |

### 5.1 Verifier System Prompt 模板

```
你是 {layer} 层的反思 Verifier。你的任务是根据已有内容整合 Proposer 的提案。

规则：
1. 如果提案内容与已有内容语义重叠，reject 并说明原因
2. 如果提案可整合但需调整，修改后 verified
3. 如果提案新增独立内容，直接 verified
4. 列出每条 verified/rejected 的理由
```

### 5.2 Verifier User Prompt 模板

```
[Proposer 提案]
{proposals}

[已有内容]
{existing_content}

请输出 JSON 格式的验证结果（verified + rejected）。
```

---

## 6. Manager 执行

复用已实现的 `apply_update()`：

| 层 | key | value | 效果 |
|----|-----|-------|------|
| L1 | add_rule | {content, created_by:"reflect"} | Philosophy.add_rule() |
| L1 | modify_rule | {rule_id, content} | Philosophy.modify_rule() |
| L1 | remove_rule | {rule_id} | Philosophy.remove_rule() |
| L2 | boost_card | {card_id} | KnowledgeCard.boost() |
| L2 | penalize_card | {card_id} | KnowledgeCard.penalize() |
| L2 | add_card | {domain, content, confidence} | FK.add_card(source="reflect") |
| L3 | update_skill | {name, content} | SkillLayer.edit_skill() |

---

## 7. ReflectDispatch 通信

上层 Proposer 决定 dispatch_lower 后，Manager 构建 LayerMessage：

```python
pkt = AgentPacket(source_layer="l1", message_type="reflect_dispatch",
                   content={"task": "请自查知识卡片覆盖", "context": {...}})
msg = self._downward.wrap_query(payload=pkt, source="l1", target="l2", ...)
self._downstream.query(msg, trace_id)
```

L2 Manager.query() 检测 LayerMessage.subtype == "REFLECT:DISPATCH"，与常规 QUERY 区分路径：

- Execute QUERY → L2Agent.stage1/2（当前）
- Reflect DISPATCH → L2 Proposer（新增）

---

## 8. 日志

Proposer + Verifier 日志沿用 execute 段格式：

```
═══ L1 Proposer ═══
  system:
    <system prompt>
  user:
    <user prompt>
  response:
    <LLM JSON output>
═══ L1 Verifier ═══
  system:
    ...
  user:
    ...
  response:
    <verified + rejected>
```

---

## 9. 待实现（文档标注）

| 项目 | 状态 |
|------|------|
| 反思效果验证（回归测试/统计/A/B对比） | 设计完成，待实现 |
| 跨 trial 经验累积(recap) | 待设计 |
| L2→L3 自动编译 | 待设计 |
| 置信度自适应调整 | 待设计 |
