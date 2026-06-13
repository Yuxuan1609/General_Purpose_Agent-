# KB Agent Interaction Design v3

> 统合 Step 2/3 讨论结论。定义主 agent ↔ KB sub-agent 交互模型、两个 sub-agent 职责、主 agent 决策链路。

## 核心原则

- **KB 不会"错"或"过时"**（操作上难免有，但非核心逻辑）。与 L2/L3 不同，知识库不随任务进行发生评价变化。
- **维护全部日常顺手做**，无专门 review session。
- **Sub-agent 自主执行，不中途和主 agent 确认**。

---

## 1. KB query sub-agent

### 1.1 触发

主 agent (L2/L3) 需要查知识库时：

```
主 agent decide():
  → knowledge_query(query, context)
  → Manager dispatch KB query sub-agent
```

### 1.2 工具集

| tool | 说明 | 限制 |
|------|------|------|
| `kb_search` | embeddings+BM25 搜索，返回候选 + 完整 meta | domain 可选过滤 |
| `kb_get` | 获取单个文档完整内容（用于跟 parent/children/related 链） | **硬上限 3 次**（含初始，即最多 2 层拓展）|
| `kb_update_meta` | 修正文档 meta 字段（type/level/tags/related 等） | 顺手改，不删不改 content |
| `kb_report` | 结束信号，汇总 findings + suggestions | 必须调 |

### 1.3 工作流

```
kb_search(query, domain?) 
  → 返回 top-10 候选，每条含 id, title, content[:500], score, meta
  │
  ├── sub-agent LLM 读每条 meta：
  │     检查 type/level 是否合理？content 截断看起来匹配意图吗？
  │     有 parent/children/related 链路值得追吗？
  │     有 meta 需要修正的吗？
  │
  ├── [可选] kb_get(doc_id) 
  │     追 parent 或 children 或 related 链（≤3 次 kb_get）
  │
  ├── [可选] 基于 meta 理解做 refine 搜索
  │     kb_search(refined_query, ...)
  │     不同措辞、不同 domain、跟发现的新关键词
  │
  ├── [顺手] kb_update_meta(doc_id, meta_patch)
  │     补 level、标准化 type、加 tags、补 related 链
  │
  └── kb_report(findings, suggestions, exhausted)
```

### 1.4 kb_report 输出格式

```python
{
  "findings": [
    {
      "doc_id": "...",
      "title": "...",
      "content": "...",       # 完整内容（如果是 kb_get 来的）
      "relevance": "direct",  # direct | partial | background
      "confidence": "high"    # high | medium | low
    }
  ],
  "exhausted": True,           # 删除字段，always true
  "coverage": {
    "match_level": "direct",   # direct | partial | none
    "gaps": ["topic_X"]        # 明确缺失的子话题
  },
  "suggestions": [             # 给主 agent 的决策建议
    {
      "action": "add",         # add | delete | fix_meta | flag_outdated
      "domain": "...",
      "topic": "...",
      "reason": "...",
      "priority": "high"       # high | medium | low
    }
  ],
  "meta_changes": [            # 本 sub-agent 改了什么 meta
    {"doc_id": "...", "field": "level", "old": null, "new": "intermediate"}
  ]
}
```

### 1.5 配置

| 参数 | 值 |
|------|-----|
| LLM | 独立实例（可与主 agent 不同模型） |
| 轮次上限 | kb_get ≤ 3；kb_search 不限（由 kb_report 自然结束） |
| content 截断 | kb_search 返回 content[:500]；kb_get 返回完整 |

---

## 2. 主 agent 决策链路

### 2.1 拿到 kb_report 后

```
主 agent decide() 收到 kb_report:

  findings                          ← 直接用于当前任务
  suggestions:
    ├── action == "add"
    │     │
    │     ├── 本轮的 tool 调用中有相关信息？
    │     │     → knowledge_add (即时落库)
    │     │
    │     └── 本轮没有相关信息？
    │           → 回复当前任务（标注缺失）
    │           → deferred.add = True (延后)
    │
    ├── action == "delete"
    │     │
    │     ├── agent 能验证这条确实错/重复？
    │     │     → knowledge_delete
    │     │
    │     └── agent 不确定？
    │           → 不删，kb_update_meta(status="needs_verification")
    │
    └── action == "flag_outdated"
          → kb_update_meta(status="outdated", flagged_by=agent_id)
```

### 2.2 新增信息来源

只有 **通过外部 tool 获取的信息** 可以落库：

| 来源 | 示例 |
|------|------|
| web_search 结果 | 联网搜到的文档/API用法/方案 |
| terminal 输出 | 命令执行结果、配置、脚本经验 |
| read_file 产出 | 项目代码阅读总结 |
| 用户直接提供 | 当前 session 用户明确告知的信息 |

**不落库**：agent 训练数据里的静态知识（已经在模型里）、任务上下文推导的规律（去 L2/L3）。

### 2.3 decide() 输出格式

```python
# 主 agent 的 decide() 输出
{
  "answer": "...",              # 给当前任务的回复/action
  "kb_actions": [               # 本轮即时执行
    {"action": "add", "domain": "...", "title": "...", "content": "...", "source": "web_search"},
    {"action": "delete", "doc_id": "..."},
  ],
  "deferred": [                 # 延后执行（汇总到独立机制）
    {"action": "fill_gap", "domain": "...", "topic": "...", "reason": "..."}
  ]
}
```

### 2.4 回复策略

如果 findings 不充分且本轮无法 fill：

- **先回复当前任务**：基于已有 findings + 标注"我未找到 X，可能需补充"
- **落库不阻塞回复**：deferred.add 标记缺口，不等待
- **如果 agent 通过其他 tool 找到了知识**：用那知识回复 + 同时 knowledge_add

---

## 3. Fill-gap sub-agent（延后，独立脚本先验证）

### 3.1 职责

异步调度，填补 deferred 中标记的知识缺口。

### 3.2 工具集

| tool | 说明 |
|------|------|
| `web_search` | 联网搜索（主信息来源） |
| `terminal` | 执行命令获取信息 |
| `read_file` | 读项目文件 |
| `knowledge_add` | 整理后落库 |

### 3.3 触发

延期机制（后续统一搞，当前不做）。独立脚本先做初步验证：

```
fill_gap_subagent(domain="X", topic="Y") → knowledge_add(...)
```

---

## 4. 与 L2/L3 的关系

| 对比维度 | KB | L2 (FlexibleKnowledge) | L3 (SkillLayer) |
|---------|-----|-----------------------|-----------------|
| 内容变化 | 不变（只增不减或删旧） | 随任务评价动态调整 | 随任务动态编译 |
| 维护方式 | sub-agent 查询中顺手改 meta | consolidation 整理 | consolidation 整理 |
| 检索 | embeddings+BM25→LLM 读 meta | domain match→activation 排序 | domain match→确定性匹配 |
| 精排 | sub-agent LLM 自主判断 | activation 衰减曲线 | 确定性匹配（不改） |

---

## 5. 实现优先级

| 优先级 | 内容 | 状态 |
|--------|------|------|
| P0 | Stage 1 粗筛 (txtai embeddings+BM25) | ✅ 完成 |
| P0 | KB sub-agent 核心逻辑 | 🔲 文档完成，代码待写 |
| P0 | 独立测试脚本 | 🔲 待写 |
| P1 | 主 agent decide() 接入 knowledge_query | 🔲 待写 |
| P1 | 主 agent decide() 接入 knowledge_add/delete | 🔲 待写 |
| P2 | Fill-gap sub-agent | 🔲 延后 |
| P2 | 异步 deferred 调度 | 🔲 延后 |
| P3 | 多实例并行 | 🔲 延后 |
