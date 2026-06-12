# Static Knowledge Base Design

> 基于 txtai 核心代码二次开发的静态知识库系统。解决知识系统空白、domain 索引规则完善、反思段工具重检三个问题。

## 背景

### 当前三个问题

**1. 知识系统空白**

- `data/layers/knowledge/` 下有 `.md`  seed 文件，但 `l2_index.json` chapters 永远为空
- `KnowledgeGraph.spread_activation` 存在但从未被调用，且与 `DomainRegistry` 断开
- L2 的 cards 是纯内存运行时结构，每次启动重新 seed，不跨运行持久化（但 cards 的标注体系——usefulness/misleading 等——已完善，本次不改 cards 持久化）

**2. Domain 系统基本可但 L2 索引规则有缺口**

- `DomainRegistry._reverse_index` 写入但从未被读取。`get_primary_items()` / `get_explore_items()` / `get_items_for_domains()` 是死代码
- L1→L2 的 `selected_nodes` 通道断裂：L1 的 `domains_hint` 埋在 state 中，L2Manager.query() 忽略它，L2 每次从零领域上下文启动
- L2 卡片检索是 O(n) 线性扫描，没用上 reverse_index
- `KnowledgeGraph` 和 `DomainRegistry` 是两套不相连的图结构

**3. 反思段工具需要重检**

- 各层 consolidation 工具（deprecate/create/modify）通过 DictInjector 注入，功能正常但绕过 CapabilityRegistry
- `consolidation_tools.yaml` 成了纯文档，实际不用
- 质量反馈（usefulness/misleading）write-only，Agent 看不到累计统计
- `LearningEnv.build_consolidation_task()` 不把实际卡片/技能内容注入 state，只注入 criteria 文本

### 设计目标

1. **静态知识库**：独立于 cards/rules/skills 的参考文档系统，存 Markdown 文档 + 结构化元数据 + domain 索引
2. **全层可查**：L1/L2/L3 通过 `knowledge_query` tool 按需查询，不走固定链路
3. **独立可管**：CLI 可手动增删改查，Agent 也可通过标准化工具读写
4. **Domain 修复**：利用 txtai 的图能力重建 domain 索引和跨域关联，修复 L1→L2 断链
5. **反思工具备案**：明确 consolidation 工具的重检结论，不在此次改动中动代码

## KB 职责边界

**三层角色对应**：KB = 语法库（基础参考），L3 = 实现路径（标准化流程），L2 = 经验（柔性判断）。

**KB 只做存储+检索，智能全归 Agent**：

```
KB 职责（薄封装层）：
  ├── 增：存储文档 + 自动索引到向量/图/SQL
  ├── 删：移除文档 + 清理索引
  ├── 改：更新文档 + re-index
  ├── 查：语义/关键词/混合搜索，支持 domain 过滤
  └── 轻量维护：LLM 辅助自动打 tag、建议 domain 分类

归 Agent 负责（不在 KB 代码中）：
  ├── 质量评估 → Agent 对比查询结果自行判断
  ├── 知识缺口 → Agent 对比 KB 和 L2/L3 知识自行发现
  ├── 知识合成 → Agent 用 LLM 多轮推理自行总结
  ├── 内容过时检测 → Agent 浏览 timestamp 自行判断
  └── 跨域分析 → Agent 利用搜索结果自行推理关联
```

## 方案：基于 txtai 核心代码二次开发

### 为什么选 txtai

txtai 的核心架构是 **embeddings database = 向量索引 + 图网络 + 关系数据库的联合体**，恰好匹配需求：

| txtai 能力 | 对应需求 |
|-----------|---------|
| Embeddings（向量索引） | 文档语义搜索 |
| Graph（图网络） | domain 聚类、相似 domain 发现、跨域关联 |
| Database（SQL） | 按 domain/tag/source 过滤查询 |
| Archive | 压缩持久化到单文件 |

### 代码规模与定制策略

txtai 核心模块约 **200KB / 5000-6000 行** Python（仅计算 embeddings、graph、database、scoring、vectors、archive、ann 七个模块）。不需要的模块（app、api、models、pipeline、workflow、agent）约 100KB，直接不引入。

**策略**：将 txtai 核心代码 fork 到 `vendor/txtai_core/`，做以下定制：
- 替换默认 embedding 模型为 DeepSeek 兼容模型
- 移除 HuggingFace 依赖（我们不需要本地模型推理）
- 简化 database 层——我们只需要 SQLite，不需要 DuckDB/Postgres 多后端
- 中文分词适配
- 与 `DomainRegistry` 互同步的 API

## 架构位置

```
cognitive-agent
    │
    ├── L1 Agent ──┐
    ├── L2 Agent ──┤── knowledge_query tool ──┐
    └── L3 Agent ──┘                          │
                                              ▼
                                    ┌──────────────────┐
                                    │  KnowledgeBase    │  core/knowledge/
                                    │  (封装 txtai)     │
                                    ├──────────────────┤
                                    │ Embeddings       │  语义搜索
                                    │ Graph            │  domain 聚类
                                    │ Database (SQL)   │  domain/tag 过滤
                                    └──────┬───────────┘
                                           │
                    ┌──────────────────────┤
                    ▼                      ▼
          data/knowledge/          vendor/txtai_core/
          (Markdown 源文件)         (forked txtai modules)
```

- `core/knowledge/` — 新模块，封装 txtai 核心，暴露 `KnowledgeBase` 类
- `vendor/txtai_core/` — fork 的 txtai 源码，只保留需要的那 7 个模块
- 与 `FlexibleKnowledge`（cards）、`SkillLayer`（skills）**半平行**——独立存储但可通过工具同步 domain 名称

## 存储模型

### 文档

```python
@dataclass
class KnowledgeDoc:
    id: str              # UUID 8位 hex
    domain: str          # "coding/python", "game/leduc"
    title: str           # 文档标题
    content: str         # Markdown 正文
    content_type: str    # "markdown"
    source: str          # "manual" | "agent" | "import"
    tags: list[str]      # 标签
    created_at: str      # ISO timestamp
    updated_at: str      # ISO timestamp
```

### Domain 图节点

```python
@dataclass
class KBDomain:
    path: str            # "coding/python"
    parent: str | None   # "coding"
    description: str     # 自然语言描述
    doc_count: int       # 该 domain 下文档数
    neighbors: dict[str, float]  # 相邻 domain → 相似度权重
```

Domain 图由 txtai 的 `Graph` 模块自动构建和更新：
- 新文档加入时自动计算 domain 间相似度
- 支持 `find_similar_domains("coding/python", top_k=5)` 发现相关领域
- 与 Agent 的 `DomainRegistry` 通过 `knowledge_sync_domain` tool 同步

### 持久化

- txtai 默认持久化到 `data/knowledge/` 目录（tar.gz 压缩归档）
- Markdown 源文件可选保留在 `data/knowledge/files/` 供人工阅读和版本控制

## Tool 接口

Agent 通过 4 个标准化 CRUD tool 操作 KB。所有智能判断（质量、缺口、合成、验证）由 Agent 在 while-loop 中自行完成。

### knowledge_query — 查询

```yaml
# 输入
query: "Python 列表推导式的语法"
domain: "coding/python"      # 可选，限定领域
search_type: "hybrid"        # "semantic" | "keyword" | "hybrid"
top_k: 5

# 输出
results:
  - id: "doc_abc123"
    domain: "coding/python"
    title: "列表推导式"
    content: "..."           # 截断至 500 字符
    score: 0.92
    source: "manual"
    tags: ["python", "syntax"]
```

### knowledge_add — 新增文档

```yaml
# 输入
domain: "coding/python"
title: "Python 列表推导式"
content: "# 列表推导式\n\n..."   # Markdown
tags: ["python", "list", "syntax"]  # 可选，KB 会自动 LLM 补 tag

# 输出
status: "ok"
doc_id: "doc_abc123"
```

### knowledge_update — 更新文档

```yaml
# 输入
doc_id: "doc_abc123"
content: "# 列表推导式\n\n..."   # 新内容（Markdown）
title: "Python 列表推导式"       # 可选
tags: ["python", "syntax"]       # 可选

# 输出
status: "ok"
```

### knowledge_delete — 删除文档

```yaml
# 输入
doc_id: "doc_abc123"

# 输出
status: "ok"
```

### 轻量 LLM 维护（非 Agent tool，KB 内部自动触发）

- **自动 tag**：新增文档时，KB 用一次 LLM 调用分析 content，生成 3-5 个 tag
- **domain 建议**：新增文档时，KB 用一次 LLM 调用分析 content，建议 domain 分类（如果未指定）
- **domain 同步**：Agent 调用 `knowledge_sync_domain` 做 domain 重命名/合并

## CLI 管理

```bash
# 添加文档
python -m cognitive_agent.kb add coding/python "Python 列表推导式" file.md

# 搜索
python -m cognitive_agent.kb search "列表推导式" --domain coding/python

# 列出所有 domain
python -m cognitive_agent.kb domains

# 从 Markdown 目录批量导入
python -m cognitive_agent.kb import data/knowledge/files/

# 导出索引
python -m cognitive_agent.kb export
```

## Domain 桥接

`KnowledgeBase` ↔ `DomainRegistry` 的半平行同步机制：

1. **独立存储**：各自维护 domain 树，互不依赖
2. **Agent 主动同步**：Agent 发现两边 domain 名称不一致时，调用 `knowledge_sync_domain` 做 rename/merge（该 tool 操作 KB 的 domain 元数据，不涉及智能判断）
3. **KB 内部域间发现**：txtai Graph 维护 domain 间相似度（文档内容驱动的向量距离），Agent 可通过 `knowledge_query` 的搜索结果中看到相关 domain，自行决定是否进一步探索

## 反思段工具重检结论

本次设计不修改 consolidation 工具代码，但记入三个待改进项：

| 项目 | 现状 | 改进方向 | 优先级 |
|------|------|---------|--------|
| DictInjector vs CapabilityRegistry | consolidation 工具绕过 CapabilityRegistry | 统一到 CapabilityRegistry，让 consolidation 工具和运行时工具走同一个注入通道 | P1（后续） |
| 质量反馈 read-back | usefulness/misleading 只写不读 | `modify_*` tool 调用时注入累计 stats 到 prompt | P1（后续） |
| consolidation task 内容缺失 | build_consolidation_task 不含实际卡片内容 | 在 state 中注入 per-domain 的全量卡片列表（由 L2 取数） | P2（后续） |

## 实施阶段

### Phase 1：txtai 核心定制 + KnowledgeBase 原型 + 4 个 CRUD tool

- fork txtai 需要的 7 个核心模块到 `vendor/txtai_core/`
- 移除 HuggingFace 依赖，适配 DeepSeek embedding API
- 简化 database 到 SQLite-only
- 实现 `core/knowledge/knowledge_base.py`：`add()` / `get()` / `update()` / `delete()` / `search()`
- 实现 4 个 tool handler：`knowledge_query` / `knowledge_add` / `knowledge_update` / `knowledge_delete`
- KB 内部 LLM 自动 tag（加文档时用一次 LLM 调用生成 tags）

### Phase 2：Domain 索引修复 + domain 同步

- 构建 KB 内部 domain 图（基于 txtai Graph）
- 实现 `knowledge_sync_domain` tool（domain 重命名/合并）
- 修复 `DomainRegistry._reverse_index` 读取端：L2Manager 用 indexed 检索替代 O(n) 扫描
- 修复 L1→L2 `selected_nodes` 断链：L2Manager.query() 读取 `domains_hint`
- KB 内部 LLM 辅助 domain 分类建议（新增文档时可选自动推断 domain）

### Phase 3：CLI + 批量导入

- 实现 `python -m cognitive_agent.kb` CLI（add/search/update/delete/list）
- 支持从现有 `data/layers/knowledge/` 的 `.md` 文件批量导入
- 支持导出索引到 JSON

### Phase 4（后续）：反思工具统一

- consolidation 工具迁移到 CapabilityRegistry
- 质量反馈 read-back
- consolidation task 内容注入

## 影响范围

### 新增文件

- `core/knowledge/__init__.py`
- `core/knowledge/knowledge_base.py` — KnowledgeBase 主类（CRUD + search + LLM tag）
- `core/knowledge/tools.py` — knowledge_query/add/update/delete/sync_domain tool handlers
- `core/knowledge/cli.py` — CLI 入口
- `vendor/txtai_core/` — txtai 核心 fork（7 个模块）

### 修改文件

- `core/tools/registry.py` — 注册 5 个 knowledge_* tools
- `core/capability/` — 注册 tool schemas 到 LayerInjector
- `core/layers/l2/manager.py` — 修复 domains_hint 读取；使用 DomainRegistry 索引检索
- `core/domain_registry.py` — 修复 `_reverse_index` 读取端

### 不受影响

- `core/flexible_knowledge.py` — cards 系统本次不改
- `core/philosophy.py` — rules 系统本次不改
- `core/skill_layer.py` — skills 系统本次不改
- `core/env/learning_env.py` — 本次不改（反思工具不在 Phase 1-3）
- `core/layers/base.py` / `core/layers/l0_5_1/` / `core/layers/l3/`
