# Knowledge Base Query-Response Mechanism

> Step 3 产出。定义 KB 两阶段检索的完整流程、Stage 2 LLM 精排设计、与 Agent while-loop 的集成方式。
> 之后应用于 L1/L2/L3 内部通信。纯文档，不写代码。

## 原则

- **KB 不调 LLM**。LLM 精排由 Agent 在自己的 while-loop 中完成。
- **对齐 decide() → capture_tool 模式**。与 L1/L2/L3 现有决策模式一致。
- **Agent 自主决定检索深度**。沿 parent/children/related 链探索到哪一步由 Agent 判断。
- **与 Step 2 维护闭环**：检索结果反馈维护需求，维护提升检索质量。

---

## 1. 两阶段检索流程

```
Agent while-loop:
  │
  ├── decide() 输出: { query, domain?, top_k? }
  │     │
  │     ▼  Manager 分发 → knowledge_query()
  │
  ├── Stage 1: 粗筛 (txtai)
  │     │  embeddings.search(query, limit=top_k*4)  → 语义匹配
  │     │  scoring.bm25.search(query, limit=top_k*4) → 关键词匹配
  │     │  合并去重 → SQL domain 过滤 → top 10-20 候选
  │     │
  │     ▼  返回: [{id, domain, title, content[:200], score, meta}]
  │
  ├── Stage 2: 精排 (Agent LLM)
  │     │  Agent 在 while-loop 中拿到 Stage 1 结果
  │     │  用自己的 LLM 读 meta 做精排：
  │     │    - 文档类型 (type) 是否匹配查询意图？
  │     │    - 复杂度 (level) 是否适合当前上下文？
  │     │    - parent/children 链是否可以追溯更相关文档？
  │     │    - related 链是否有比当前结果更好的？
  │     │
  │     ▼  Agent 输出: { selected_docs, ranking_reason, needs_further_search? }
  │
  ├── (可选) 沿链探索
  │     │  如果 meta 中 parent/children/related 有更相关文档
  │     │  → knowledge_get(doc_id) 获取完整内容
  │
  └── 汇总返回 / 继续任务
```

---

## 2. Stage 1: txtai 粗筛（已实现）

### 当前实现

```
knowledge_query(kb, query, domain=None, top_k=5)
    → kb.search(query, domain, top_k)
        → emb.search(query, limit=top_k*4)    # dense + BM25 两路融合
        → domain 过滤 (Python side)
        → 返回 top_k
```

### 返回格式

```json
{
  "results": [
    {
      "id": "abc123",
      "domain": "docs/superpowers/specs",
      "title": "agent communication design",
      "content": "# Agent Communication Design\n\n...",  // 截断 500 字符
      "score": 0.534,
      "source": "import",
      "meta": { "type": "reference", "level": "advanced", "tags": ["agent", "comm"] }
    }
  ]
}
```

### Stage 1 不做的事

- 不做 meta 语义判断（type/level 是否合适）
- 不做关联链探索（parent/children/related）
- 不做最终排序（只看 embedding+BM25 score）
- 不截断到 top_k=5 以外的内容（多取 top_k*4 留给 Stage 2）

---

## 3. Stage 2: Agent LLM 精排（待实现）

### 3.1 输入

Agent 在一次 decide() 调用中拿到 Stage 1 的候选列表（10-20 条），每条含：

- `id`, `domain`, `title`
- `content[:500]` — 截断正文（概览）
- `meta` — 完整 meta（type, level, parent, children, related, tags, 扩展字段）

加上原始查询的上下文（原始问题、Agent 当前任务目标）。

### 3.2 精排 prompt 结构

```
[任务]
你是知识检索Agent。从候选文档中选出最相关的 top-K。

[原始查询]
{user_query}

[当前上下文]
{agent_task_context}  ← Agent 当前在做什么任务

[候选文档]
1. [abc123] docs/superpowers/specs: agent communication design (score=0.53)
   type=reference | level=advanced | tags=[agent, comm]
   parent=xyz789 | children=[def456] | related=[ghi012]
   content: "..."

2. [def456] docs/superpowers/specs: agent comm phase2 (score=0.39)
   ...

[任务要求]
- 选择与查询意图最匹配的文档
- 考虑 type 是否适合（FAQ 还是 reference？）
- 考虑 level 是否适合上下文（beginner 查询不应推 advanced）
- 如果 parent 更宏观或 children 更细节，标注建议探索
- 如果 related 有更好候选，标注

[输出格式]
{format instruction}  → capture_tool: knowledge_select
```

### 3.3 capture_tool: `knowledge_select`

Agent 通过 capture_tool 输出精排结果：

```yaml
# 输入 (来自 Stage 1)
candidates: [...]   # Stage 1 返回的候选列表

# Agent LLM 输出 → capture_tool 捕获
selected:
  - doc_id: "abc123"
    relevance: "direct_match"
    reason: "直接回答查询，type=reference 合适"

explore_suggestions:      # 可选
  - doc_id: "xyz789"
    source: "parent"
    reason: "更宏观的概述，可能提供背景"
  - doc_id: "def456"
    source: "related"
    reason: "补充了 phase2 的细节"

issues:                    # 可选：维护反馈
  - doc_id: "ghi012"
    issue: "missing_level"
  - doc_id: "jkl345"
    issue: "likely_duplicate_of_abc123"
```

### 3.4 Stage 2 职责边界

Stage 2 的职责：
- 相关性重排序
- type/level 适配判断
- 关联链价值评估
- 维护问题标记

Stage 2 **不**做的事：
- 不获取完整文档内容（只读 meta + content[:500]）
- 不修改文档（标记 issues → 后续调 knowledge_maintain）
- 不探索关联链（只建议 → Agent 决定是否 knowledge_get）

---

## 4. Agent while-loop 集成

### 4.1 查询路径

```
L2/L3 Manager.query(obs)
  │
  ├── L2/L3 Agent.decide(meta, state, context)
  │     │
  │     ├── Agent 分析任务 → 决定需要查 KB
  │     │
  │     ├── [LLM turn 1] 输出 knowledge_query(query, domain, top_k)
  │     │       Manager 分发 → KB.search() → Stage 1 结果
  │     │
  │     ├── [LLM turn 2] 收到 Stage 1 候选
  │     │       输出 knowledge_select(candidates, context)
  │     │       → Agent 自己的 LLM 做 Stage 2 精排
  │     │
  │     ├── [LLM turn 3] 拿到 selected docs
  │     │       决定：沿链探索？还是继续任务？
  │     │       输出 knowledge_get(doc_id)  # 如需完整内容
  │     │
  │     └── [LLM turn N] 汇总知识
  │             输出 decide() 最终结果
  │
  └── Manager propagate → L3 (如需下层执行)
```

### 4.2 维护闭环（与 Step 2 联动）

```
Agent.decide():
  │
  ├── 查询 KB → Stage 1 结果 score 普遍 < 0.3
  │     → Agent 判断：domain 内知识不足
  │     → 标记 issues: [{domain, issue: "knowledge_gap"}]
  │     → 后续可能调 knowledge_add 补充
  │
  ├── Stage 2 发现 type/level 缺失
  │     → 标记 issues: [{doc_id, issue: "missing_level"}]
  │     → 后续可能调 knowledge_maintain(action="fill_gaps")
  │
  └── 发现 candidate 之间高度相似
        → 标记 issues: [{doc_id, issue: "likely_duplicate"}]
        → 后续可能调 knowledge_maintain(action="dedup")
```

### 4.3 工具链

| tool | 用途 | 调用方 |
|------|------|--------|
| `knowledge_query` | Stage 1 粗筛 | Agent (while-loop turn 1) |
| `knowledge_select` | Stage 2 精排 (capture_tool) | Agent 自身 LLM 判断 |
| `knowledge_get` | 获取完整文档内容 | Agent (沿链探索) |
| `knowledge_maintain` | 维护 meta (Step 2) | Agent (检测到问题时) |
| `knowledge_add` | 补充缺失文档 | Agent (发现知识缺口时) |

---

## 5. 推广到 L1/L2/L3 内部通信

### 5.1 思路

当前 L2/L3 的 decide() 通过 capture_tool（l2_query/l2_report）输出结构化结果。但层间通信（L2→L3 查询）目前是确定性匹配 + propagate——没有"query → 多候选 → 精排 → 选择"的模式。

将 query-response 模式推广意味着：

- L2 向 L3 查询变成**非确定性的多候选检索**（不仅是精确 domain match）
- L3 返回的不是单个结果而是**候选集**（附 score + meta）
- L2 的 Agent 在 while-loop 中用**自己的 LLM 做精排**（类比 Stage 2）
- 保持 A1（相邻传递）和 A2（LayerMessage 信封）

### 5.2 L3 作为 "类 KB" 的知识检索源

```
当前: L2 → L3Manager.query() → SkillLayer.match(domain) → 精确匹配 → 执行

将来: L2 → L3Manager.query() → SkillLayer.search(domain, query)
        → 返回候选技能列表 [{name, score, meta}]
        → L2 Agent LLM 精排 → 选择最相关技能
        → L3Manager.execute(skill)
```

### 5.3 不做的事

- 不改 L2/L3 的通信协议（仍用 LayerMessage 信封）
- 不改 A1（相邻传递不变）
- 不改 Manager 的 query() 调度（仍是 while-loop → decide() → propagate）
- 只是让 L3 的返回从"确定性单结果"变成"候选集 + score"，精排由上层 Agent 负责

---

## 6. 实现优先级

| 优先级 | 内容 | 依赖 |
|--------|------|------|
| P0 | `knowledge_select` capture_tool 定义 + Agent decide 中接入 | Stage 1 (done) |
| P1 | Agent while-loop 多轮查询路径 (query → select → get → 汇总) | P0 |
| P2 | Stage 2 的 issues 标记 → 触 maintenance (与 Step 2 联动) | P1 + Step 2 |
| P3 | L3.search() 非确定匹配 (候选集替代精确 match) | P1 |
| P4 | L2/L3 通信引入 query-response 模式 (候选集 + LLM 精排) | P3 |
| P5 | 全层统一 query-response 通信模式 | P4 |

---

## 7. 不做的事

- KB 不调 LLM（精排由 Agent 完成）
- 不改变现有 L2/L3 通信协议（A1 + A2 + LayerMessage 保留）
- 不在 Stage 1 做语义判断或关联探索（那是 Stage 2 的职责）
- 不在 `knowledge_query` 中自动触发精排（Agent 自主决定是否调 `knowledge_select`）
