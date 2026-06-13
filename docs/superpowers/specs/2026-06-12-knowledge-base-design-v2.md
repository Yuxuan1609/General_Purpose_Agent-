# Knowledge Base Design v2

> 基于 domain 树 + meta 自维护的静态知识库设计。Agent 通过两阶段检索（embeddings + meta LLM 精排）查找知识，并通过标准化工具自主维护文档 meta。

## 核心理念

- **Meta 由 Agent 自维护**——预定义最小骨架（domain, id），其余字段 Agent 按需演化
- **两阶段检索**——txtai embeddings+BM25 粗筛，LLM 读 meta 精排

## Meta 设计

每条文档的 meta 分三层：

### 必填字段

```yaml
id: "doc_abc123"          # 文档唯一 ID（8 位 hex）
domain: "coding/python"   # 所属 domain 路径（必填）
```

### 预定义字段（存在则填，不存在则空）

```yaml
type: "reference"         # reference | example | faq | guide | tutorial | spec
level: "intermediate"     # beginner | intermediate | advanced
parent: "doc_xyz789"      # 上级文档 ID（层级关系，树形引用）
children:                  # 下级文档 IDs
  - "doc_child1"
  - "doc_child2"
related:                   # 横向关联文档 IDs
  - "doc_related1"
tags:                      # 关键词标签
  - "python"
  - "async"
```

### Agent 扩展字段（自由定义）

```yaml
# Agent 可在维护过程中自由添加任意 key:value
covers: ["list comprehension", "generator expression"]
pitfalls: "nested comprehensions hurt readability"
depends_on: "python>=3.6"
# ... 任意字段
```

设计要点：
- `id` + `domain` 是唯一必填项
- `type` / `level` / `parent` / `children` / `related` / `tags` 是建议填写的预定义字段，但很多文档确实不适合填（如 parent/children 的关系不是总能建立）
- Agent 扩展字段无 schema 限制——Agent 在维护过程中自行定义，后续 reads 时在 meta 中看到之前 Agent 写了什么就延续使用，自然形成约定
- 不必担心跨 Agent 一致性问题——embeddings 搜索不依赖 meta 字段名精确匹配，LLM 精排时能理解语义相近的字段

## 检索流程

```
用户/Agent 查询: "Python 异步编程怎么避免回调地狱"
    │
    ▼
Stage 1: 粗筛 (txtai)
    ├── embeddings.search(query, limit=5)      语义相似 → 5 条
    ├── scoring.bm25.search(query, limit=5)    关键词匹配 → 5 条
    └── 合并去重 → SQL 过滤 (可选: domain 限定)
        输出: top-5 候选文档 (id, title, content[:200], meta)
    │
    ▼
Stage 2: 精排 (Agent LLM)
    输入: [原始查询, top-5 的 meta 摘要]
    LLM 判断:
      - 文档类型是否匹配查询意图？(FAQ 还是 reference？)
      - 复杂度是否适合当前上下文？
      - 是否有 parent/children 关系可追溯更深或更浅的知识？
      - related 链接是否比当前结果更相关？
    输出: top-K 最终结果 (含排序理由)
    │
    ▼
返回结果 + meta 上下文
    Agent 可以:
      - 直接使用 top-K 中的内容
      - 沿 parent/children/related 链继续探索
      - 发现知识缺口后通过 knowledge_add 补充
```

### 为什么 LLM 精排而不是纯向量/关键字

- 向量搜索擅长"语义相近"，但不懂"这个查询需要 example 还是 reference"
- 关键字搜索擅长精确匹配，但对同义表达盲区大
- LLM 读 meta 可以做出语义判断——"查询者看起来是新手，advanced 的文档应该降权"
- parent/children/related 这类复合的类图关系，传统检索无法利用，LLM 可以

### Agent 自主探索路径

Agent 拿到结果后，看到 meta 中有 `parent: "doc_abc"` 和 `children: ["doc_xyz"]`，可以自主决定：
- "这个太细节了，我去看 parent" → `knowledge_get("doc_abc")`
- "这个太抽象了，我去看 children" → `knowledge_get("doc_xyz")`
- "related 里有篇看起来更相关" → `knowledge_get("doc_related1")`

## Domain 集成

### 与 L2/L3 DomainRegistry 的关系

**共享命名规范，独立演进**：

- KB domain 和 Agent DomainRegistry 不合并树、不共享存储
- Domain path 命名规范一致：`game/leduc/preflop`、`coding/python/async`
- Agent 使用 KB domain 时**优先复用已有 domain**——通过 `knowledge_list_domains` 浏览目录，选择最匹配的已有 domain 而非随意新建

```
Agent 任务: "帮我写个 Python asyncio 示例"
    │
    ├── knowledge_list_domains("coding/")
    │       → 看到 coding/python, coding/python/async, ...
    ├── 选择 coding/python/async（已有，直接复用）
    ├── knowledge_query(query, domain="coding/python/async")
    ├── 后续想加新文档也挂在这个 domain 下（不新建 coding/python_asyncio）
    └── 若发现两边 domain 指向同一事物但名称不同
        → knowledge_sync_domain 提示可对齐（非强制）
```



## Agent 维护工具（CRUD + meta）

### knowledge_query — 两阶段检索

```yaml
# 输入
query: "Python 异步编程"
domain: "coding/python"    # 可选
search_type: "hybrid"      # semantic | keyword | hybrid
top_k: 5                   # 最终返回数量（粗筛 top_k*4 然后 LLM 精排到 top_k）

# 输出
results:
  - id: "doc_abc"
    domain: "coding/python"
    title: "asyncio 入门"
    content: "..."         # 截断
    score: 0.92
    meta:                  # 完整 meta（供 LLM 精排和 Agent 后续探索）
      type: "reference"
      level: "beginner"
      parent: "doc_xyz"
      children: ["doc_child1"]
```

### knowledge_add — 新增文档

```yaml
# 输入
domain: "coding/python"    # 必填
title: "asyncio 入门"
content: "# asyncio\n\n..."
meta:
  type: "reference"
  level: "beginner"
  tags: ["python", "async"]

# 输出
status: "ok"
doc_id: "doc_abc123"
```

### knowledge_update — 更新文档（含 meta）

```yaml
# 输入
doc_id: "doc_abc123"
content: "# asyncio\n\n..."  # 可选
meta:                         # 可选，局部更新 meta 字段
  level: "intermediate"
  children: ["doc_new_child"]  # 追加到现有 children

# 输出
status: "ok"
```

### knowledge_get — 获取单个文档完整内容

```yaml
# 输入
doc_id: "doc_abc123"

# 输出
doc:
  id: "doc_abc123"
  domain: "coding/python"
  title: "asyncio 入门"
  content: "# asyncio\n\n...(完整内容)"
  meta: { ... }
```

### knowledge_delete — 删除文档

```yaml
# 输入
doc_id: "doc_abc123"

# 输出
status: "ok"
```

### knowledge_sync_domain — 同步 domain

```yaml
# 输入
action: "rename"
source_domain: "coding/python"
target_domain: "coding/python_programming"

# 输出
status: "ok"
```

### knowledge_maintain — Agent 主动维护 meta（新增 tool）

Agent 定期或按需调用此 tool 来改进 meta 质量：

```yaml
# 输入
domain: "coding/python"       # 目标领域
action: "cleanup"             # cleanup | fill_gaps | link_related

# cleanup: 清理无用的扩展字段、标准化预定义字段值
# fill_gaps: 扫描该 domain 下缺失 type/level 的文档，LLM 自动补全
# link_related: 扫描 domain 内文档，LLM 自动建议 parent/children/related 关系

# 输出
status: "ok"
changes: 12                   # 修改的文档数
details:
  - doc_id: "doc_a"
    added: { level: "beginner" }
  - doc_id: "doc_b"
    added: { parent: "doc_a" }
```

这个 tool 不强制调用——Agent 在任务中自己判断"这个 domain 的 meta 质量太差，我需要清理一下"然后调用。

## 存储模型

### 文档结构

```python
@dataclass
class KnowledgeDoc:
    id: str              # 8 位 hex UUID
    domain: str          # domain 路径
    title: str
    content: str         # Markdown 正文
    meta: dict           # { id, domain, type?, level?, parent?, children?, related?, tags?, ...扩展 }
    source: str          # manual | agent | import
    created_at: str      # ISO timestamp
    updated_at: str      # ISO timestamp
```

### 持久化

所有数据存储在同一个 `storage_path` 目录下：

```
data/knowledge/
  config            ← txtai 配置 (模型路径、scoring 参数等)
  embeddings        ← ANN 向量索引 (NumPy, 768-dim)
  scoring           ← BM25 倒排索引
  documents/        ← SQLite 数据库 (id, content, tags JSON)
  kb.json           ← 文档元数据 (KnowledgeDoc dict) + domain 树 (KBDomain dict)
```

- `config` / `embeddings` / `scoring` / `documents/` 由 txtai `Embeddings.save(path)` 写入，`Embeddings.load(path)` 读取
- `kb.json` 由 `KnowledgeBase.save()` 写入，存储所有文档的完整元数据（domain, title, source, created_at, updated_at）和 domain 图
- 加载时：优先从 txtai 磁盘加载 embeddings + BM25 索引；若磁盘无数据则创建新 Embeddings 并逐文档 upsert 重建
- meta 字段同时存入 txtai 的 SQLite `tags` 列（JSON 序列化，供 SQL 精确过滤）

## 与 txtai 的对接

```
KnowledgeBase (封装层)
    ├── 文档 CRUD + meta 管理
    ├── 两阶段检索 (txtai 粗筛 + LLM 精排)
    └── 对接:
        ├── txtai Embeddings.upsert/search → 向量索引
        ├── txtai Scoring (BM25) → 关键词索引
        ├── txtai Database (SQLite) → meta 精确过滤
        ├── txtai Graph (NetworkX) → domain 间关联
        └── txtai Archive (tar.gz) → 持久化
```

## 与当前代码的改动关系

| 组件 | 当前状态 | v2 改动 |
|------|---------|--------|
| `KnowledgeDoc` | 有 id, domain, title, content, tags, source | 把 tags 并入 meta，新增 meta: dict |
| `KnowledgeBase` | in-memory CRUD + keyword search | 替换 keyword search 为两阶段检索；对接 txtai |
| `tools.py` | query/add/update/delete/sync_domain | 新增 get 和 maintain；query 改为两阶段 |
| `DomainRegistry` | 树 + reverse_index | 不改——L2/L3 这边不在此 scope |
| `vendor/txtai_core/` | 17K 行全量 fork | 精简到 ~50 文件、~8K 行 |

## 实施阶段

### Phase 1: Meta 改造（先不改检索）

- `KnowledgeDoc.meta: dict` 替代 `tags: list[str]`
- 预定义字段验证（type/level 的枚举值）
- knowledge_get tool + knowledge_maintain skeleton
- 现有 243 tests 保持通过

### Phase 2: txtai 精简 + 集成

- 删除 17K 中不需要的后端/模块 → ~8K 行
- DeepSeek embedding API 对接（`vectors/dense/external.py`）
- 替换 keyword search 为 txtai embeddings + BM25
- 两阶段检索：粗筛 (txtai) → 不带 LLM 的直接返回（先不接 LLM 精排）

### Phase 3: LLM 精排

- Stage 2 接入 Agent 的 LLM 做 meta 精排
- knowledge_maintain 的 fill_gaps / link_related action 实现（LLM 自动补 meta）

### Phase 4: CLI + 测试

- CLI 更新（支持 meta 字段）
- 集成测试：Agent 完整 workflow（查询→探索→补充→维护）
