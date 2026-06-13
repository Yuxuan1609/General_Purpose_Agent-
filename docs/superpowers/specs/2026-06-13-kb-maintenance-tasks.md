# Knowledge Base Maintenance Tasks

> Step 2 产出。定义 KB 维护 task 的类型、触发、质量指标、与 query-response (Step 3) 的关系。
> 不写代码，纯文档。Agent 接入实现在 Step 4+。

## 原则

- **KB 是纯存储 + 统计**。不做 LLM 调用。
- **维护决策由 Agent 做出**。KB 提供工具和统计数据，Agent 在 while-loop 中判断、调用、评估。
- **Agent 管理为主，系统层做最简单维护**（enum 校验、tag 标准化）。
- 维护的目标：提升 Stage 1 粗筛精度 → 提升 Step 3 query-response 的 Stage 2 精排质量。

---

## 1. 维护 action 类型

### 1.1 cleanup — 标准化 + 清理废弃字段

**做什么**：
- 标准化 `type` 字段（reference | example | faq | guide | tutorial | spec）
- 标准化 `level` 字段（beginner | intermediate | advanced）
- 标准化 `tags`（全小写、去空格、去停用词）
- 删除已废弃的 Agent 扩展字段（无 schema 限制，Agent 自判断）

**触发**：
- Agent 发现某 domain 内 type/level 值混乱（"TypeScript" vs "typescript"）
- 系统在 add/update 时自动校验 enum 值（规则驱动，不调 LLM）

**输入**：`domain`（要清理的 domain 路径）

**输出**：`{cleaned: N, changes: [{doc_id, field, old, new}]}`

### 1.2 fill_gaps — 补全缺失 meta

**做什么**：
- 扫描 domain 下缺失 `type` 的文档 → Agent LLM 读 content 推断 type
- 扫描缺失 `level` 的文档 → Agent LLM 读 content 推断 level
- 扫描缺失 `tags` 的文档 → Agent LLM 读 content 提取关键词

**触发**：
- Agent 查询时发现返回结果缺少 type/level → 调 `knowledge_maintain`
- 系统提供 domain 健康统计（meta_completeness < 阈值 → 提示 Agent）

**输入**：`domain`

**输出**：`{filled: N, changes: [{doc_id, added_fields: {type, level, tags}}]}`

### 1.3 link_related — 建立文档间关联

**做什么**：
- 扫描 domain 下文档，Agent LLM 读 meta+content 建议 `parent`/`children`/`related` 关系
- parent/children = 层级关系（如 "asyncio 入门" 的 parent 是 "Python 并发编程"）
- related = 横向关联（如 "asyncio" ← related → "threading"）

**触发**：
- Agent 发现 domain 内文档孤立（无关联链）→ `knowledge_maintain(action="link_related")`
- 系统提供 link_density 统计

**输入**：`domain`

**输出**：`{linked: N, changes: [{doc_id, parent, children_added, related_added}]}`

### 1.4 dedup — 检测重复文档

**做什么**：
- 用 embeddings 余弦相似度 + content 文本重叠度检测重复/高度相似文档
- 标记为疑似重复（不自动删除，Agent 判断）
- Agent 可以 merge 或 delete

**触发**：
- Agent 查询时发现多条高度相似结果
- 系统提供 duplicate_risk 统计（cosine > 0.95 的 doc pair 占比）

**输入**：`domain`

**输出**：`{potential_duplicates: [{doc_a, doc_b, cosine_score, overlap_ratio}]}`

---

## 2. 触发机制

### 2.1 Agent 主动触发（主路径）

```
Agent while-loop:
  ├── 执行任务，调 knowledge_query 查资料
  ├── 发现返回结果 meta 质量差（缺 type、标题不规范）
  ├── 决定调 knowledge_maintain(action="fill_gaps", domain=...)
  ├── KB 返回统计 + 候选
  ├── Agent 用自己的 LLM 读 content 推断 type/level
  ├── 调 knowledge_update 逐条更新 meta
  └── 继续任务
```

### 2.2 系统提示触发（辅助）

系统在 `knowledge_maintain` tool 被调用时不直接执行，而是返回 domain 健康统计：

```json
{
  "domain": "docs/superpowers/specs",
  "stats": {
    "doc_count": 14,
    "meta_completeness": 0.72,
    "tag_coverage": 0.85,
    "link_density": 0.15,
    "duplicate_risk": 0.02,
    "orphan_docs": 3
  },
  "suggestions": ["fill_gaps: 4 docs missing level", "link_related: link_density < 0.3"]
}
```

Agent 读 stats，决定执行哪些 action。

### 2.3 系统自动维护（最小化）

在 `add()` / `update()` 时自动执行纯规则操作（不调 LLM）：

- `type` 不在枚举 → 设 `null` 并记 warning
- `level` 不在枚举 → 设 `null` 并记 warning
- `tags` 全转小写、去首尾空格
- `meta.id` 自动 strip（已有）

---

## 3. 质量指标

KB 对外暴露 `kb.get_domain_stats(domain) → dict`：

| 指标 | 计算方式 | 含义 |
|------|---------|------|
| `doc_count` | domain 下文档数 | 规模 |
| `meta_completeness` | 有 type AND level 的文档 / 总数 | meta 完整度 |
| `tag_coverage` | 有 ≥1 个 tag 的文档 / 总数 | 标签覆盖 |
| `link_density` | 有 parent 或 children 或 related 的文档 / 总数 | 关联密度 |
| `duplicate_risk` | embeddings cosine > 0.95 的 doc pair 占比 | 重复风险 |
| `orphan_docs` | 无任何关联链的文档数 | 孤岛文档 |

---

## 4. 与 Step 3（query-response）的关系

### 4.1 维护 → 提升检索质量

```
维护动作              →  检索效果提升
─────────────────────────────────────
cleanup: type/level 标准化  →  Stage 2 LLM 精排能按类型/难度排序
fill_gaps: 补 meta       →  精排时有更多信息判断相关性
link_related: 建关联     →  Agent 可沿链探索，不只看 top-K
dedup: 去重            →  搜索结果不浪费在重复文档上
```

### 4.2 检索 → 反馈维护需求

```
检索信号              →  维护建议
─────────────────────────────────────
查询 score < 0.3 的结果多 →  该 domain 可能缺文档 (fill_gaps / 需新增)
Agent 频繁跨 domain 查询  →  related 链可能断了 (link_related)
同一查询返回多条高度相似   →  dedup 候选确认
Agent 反复 get 某 parent 文档 →  children 链缺失 (link_related)
```

### 4.3 共享 Agent LLM

维护和精排共用一个 LLM（Agent 自身的 LLM）。不需要额外的 LLM 实例：

```
Agent while-loop:
  ├── decide() → 可能是 "查询 KB" 或 "维护 KB"
  ├── 同一次 decide() 输出可同时包含 queries_to_KB 和 maintenance_actions
  └── Manager 分发：queries → KB.search(), maintenance → knowledge_maintain()
```

---

## 5. 实现优先级

| 优先级 | 内容 | 依赖 |
|--------|------|------|
| P0 | `kb.get_domain_stats(domain)` — 纯统计 API | 无 |
| P1 | `knowledge_maintain` tool 骨架 — 接收 action + domain，返回 stats | P0 |
| P2 | Agent while-loop 接入 maintenance 决策路径 | L2/L3 decide() |
| P3 | cleanup 规则化自动执行（enum 校验、tag 标准化） | P0 |
| P4 | fill_gaps / link_related — Agent LLM 读 content 推断 meta | P1 + P2 |
| P5 | dedup — embeddings 相似度 + Agent LLM 判断合并策略 | P4 |
| P6 | 检索反馈 → 维护需求（score 低 → 建议补文档） | Step 3 |

---

## 6. 不做的事

- KB 内不调 LLM（所有 LLM 判断在 Agent）
- 不自动删除文档（dedup 只标记不删）
- 不强制统一 meta schema（Agent 扩展字段自由）
- 不维护跨 domain 的关联（related 只在同 domain 内）
