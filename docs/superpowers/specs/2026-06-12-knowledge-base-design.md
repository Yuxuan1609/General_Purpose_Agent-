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

### knowledge_query — 查询知识库（已有 schema，替换后端实现）

```yaml
# 输入
query: "Python 列表推导式的语法"
domain: "coding/python"  # 可选，限定领域
search_type: "semantic"  # "semantic" | "keyword" | "hybrid"
top_k: 5

# 输出
results:
  - id: "doc_abc123"
    domain: "coding/python"
    title: "列表推导式"
    content: "..."  # 截断至 500 字符
    score: 0.92
    source: "manual"
```

### knowledge_add — 写入知识（新增 tool）

```yaml
# 输入
domain: "coding/python"
title: "Python 列表推导式"
content: "# 列表推导式\n\n[表达式 for 项 in 可迭代对象 if 条件]\n\n..."
tags: ["python", "list", "syntax"]

# 输出
status: "ok"
doc_id: "doc_abc123"
```

### knowledge_sync_domain — 同步 domain（新增 tool）

```yaml
# 输入
action: "rename"  # "rename" | "merge" | "suggest"
source_domain: "coding/python"
target_domain: "coding/python_programming"
# agent_domain: "coding/pythonprogramming"  # Agent DomainRegistry 侧的名称

# 输出
status: "ok"  # 或 "conflict" 带建议列表
```

### knowledge_list_domains — 列出领域

```yaml
# 输出
domains:
  - path: "coding/python"
    doc_count: 15
    neighbors: { "coding/javascript": 0.7, "coding/golang": 0.5 }
```

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
2. **相似度提示**：txtai Graph 自动发现 `coding/python` 和 `coding/pythonprogramming` 相似度 > 0.8 → 存入 domain 的 `neighbors` 字段
3. **Agent 主动同步**：Agent 发现两边 domain 名称不一致时，调用 `knowledge_sync_domain` 做 rename/merge
4. **索引共享**：KB 的 domain 图可作为 Agent `DomainRegistry` 的参照——`DomainRegistry.retrieve_from_root()` 在领域节点为空时 fallback 到 KB 的 domain 列表

## 反思段工具重检结论

本次设计不修改 consolidation 工具代码，但记入三个待改进项：

| 项目 | 现状 | 改进方向 | 优先级 |
|------|------|---------|--------|
| DictInjector vs CapabilityRegistry | consolidation 工具绕过 CapabilityRegistry | 统一到 CapabilityRegistry，让 consolidation 工具和运行时工具走同一个注入通道 | P1（后续） |
| 质量反馈 read-back | usefulness/misleading 只写不读 | `modify_*` tool 调用时注入累计 stats 到 prompt | P1（后续） |
| consolidation task 内容缺失 | build_consolidation_task 不含实际卡片内容 | 在 state 中注入 per-domain 的全量卡片列表（由 L2 取数） | P2（后续） |

## 实施阶段

### Phase 1：txtai 核心定制 + KnowledgeBase 原型

- fork txtai 需要的 7 个核心模块到 `vendor/txtai_core/`
- 移除 HuggingFace 依赖，适配 DeepSeek embedding API
- 简化 database 到 SQLite-only
- 实现 `core/knowledge/knowledge_base.py` 封装层
- 实现 `knowledge_query` / `knowledge_add` 两个 tool

### Phase 2：Domain 图 + 同步机制

- 构建 KnowledgeBase 内部的 domain 图（基于 txtai Graph）
- 实现 `knowledge_list_domains` / `knowledge_sync_domain` tool
- 修复 `DomainRegistry._reverse_index` 读取端：L2Manager 用 indexed 检索替代 O(n) 扫描
- 修复 L1→L2 `selected_nodes` 断链：L2Manager.query() 读取 `domains_hint`

### Phase 3：CLI + 批量导入

- 实现 `python -m cognitive_agent.kb` CLI
- 支持从现有 `data/layers/knowledge/` 的 `.md` 文件批量导入
- 支持导出索引到 JSON

### Phase 4（后续）：反思工具统一

- consolidation 工具迁移到 CapabilityRegistry
- 质量反馈 read-back
- consolidation task 内容注入

## 影响范围

### 新增文件

- `core/knowledge/__init__.py`
- `core/knowledge/knowledge_base.py` — KnowledgeBase 主类
- `core/knowledge/tools.py` — knowledge_query/add/sync_domain/list_domains tool handlers
- `core/knowledge/cli.py` — CLI 入口
- `vendor/txtai_core/` — txtai 核心 fork（7 个模块）

### 修改文件

- `core/tools/registry.py` — 注册 knowledge_add, knowledge_sync_domain, knowledge_list_domains
- `core/capability/` — 或 `core/knowledge/` 内注册 tool schemas
- `core/layers/l2/manager.py` — 修复 domains_hint 读取；使用 DomainRegistry 索引检索
- `core/domain_registry.py` — 修复 `_reverse_index` 读取端；新增 `retrieve_from_root`

### 不受影响

- `core/flexible_knowledge.py` — cards 系统本次不改
- `core/philosophy.py` — rules 系统本次不改
- `core/skill_layer.py` — skills 系统本次不改
- `core/env/learning_env.py` — 本次不改（反思工具不在 Phase 1-3）
- `core/layers/base.py` / `core/layers/l0_5_1/` / `core/layers/l3/`
