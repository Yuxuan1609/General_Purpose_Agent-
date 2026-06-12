# Knowledge Base v2 Implementation Plan

> **Goal:** 精简 txtai + meta 化改造 + 定义维护 task + 基础端到端

## Step 0: 精简 txtai

**目标**: 从 17K 行 / 134 文件精简到 ~8K 行 / ~50 文件

### 原理

txtai 8 种向量后端、9 种 ANN 后端、3 种数据库后端全部保留是浪费。我们只需要 DeepSeek embedding API + SQLite + NumPy ANN。

### 任务

**T0.1: 删除不需要的文件**

```bash
# ann/ — 只保留 numpy
rm vendor/txtai_core/ann/dense/faiss.py
rm vendor/txtai_core/ann/dense/ggml.py
rm vendor/txtai_core/ann/dense/hnsw.py
rm vendor/txtai_core/ann/dense/annoy.py
rm vendor/txtai_core/ann/dense/torch.py
rm vendor/txtai_core/ann/dense/pgvector.py
rm vendor/txtai_core/ann/dense/turbovec.py
rm vendor/txtai_core/ann/dense/sqlite.py
rm -rf vendor/txtai_core/ann/sparse/

# vectors/ — 只保留 external + factory
rm vendor/txtai_core/vectors/dense/huggingface.py
rm vendor/txtai_core/vectors/dense/litellm.py
rm vendor/txtai_core/vectors/dense/litert.py
rm vendor/txtai_core/vectors/dense/llama.py
rm vendor/txtai_core/vectors/dense/m2v.py
rm vendor/txtai_core/vectors/dense/sbert.py
rm vendor/txtai_core/vectors/dense/words.py
rm -rf vendor/txtai_core/vectors/sparse/
rm vendor/txtai_core/vectors/recovery.py

# database/ — SQLite only
rm vendor/txtai_core/database/duckdb.py
rm vendor/txtai_core/database/client.py
rm -rf vendor/txtai_core/database/encoder/

# scoring/ — 保留 bm25 + tfidf + terms + normalize
rm vendor/txtai_core/scoring/pgtext.py
rm vendor/txtai_core/scoring/sif.py
rm vendor/txtai_core/scoring/sparse.py

# graph/ — 保留 networkx + topics
rm vendor/txtai_core/graph/rdbms.py

# archive/ — tar.gz only
rm vendor/txtai_core/archive/zip.py

# models/ — 全部换 stub
rm -rf vendor/txtai_core/models/
```

**T0.2: 修复 factory 引用**

删除文件后，factory 文件里的 import 会报错。需要修改：

- `vectors/dense/factory.py` — 删 huggingface/litellm/litert/llama/m2v/sbert/words 分支
- `ann/dense/factory.py` — 删 faiss/hnsw/ggml/annoy/torch/pgvector/turbovec/sqlite 分支
- `scoring/factory.py` — 删 pgtext/sif/sparse 分支
- `graph/factory.py` — 删 rdbms 分支
- `database/factory.py` — 删 duckdb/client 分支
- `archive/factory.py` — 删 zip 分支
- `vectors/dense/__init__.py` — 删被移除模块的 re-export
- `ann/dense/__init__.py` — 同上

**T0.3: 创建 models stub**

```python
# vendor/txtai_core/models/__init__.py
class Models:
    pass

class PoolingFactory:
    pass
```

**T0.4: 验证导入 + 提交**

```bash
python3 -c "from vendor.txtai_core import embeddings, graph, database, scoring, vectors, archive, ann; print('OK')"
pytest tests/ -q
git add vendor/ && git commit -m "strip: txtai minimal set — SQLite + NumPy + external vectors only"
```

---

## Step 1: meta 化改造 + 端到端

### T1.1: KnowledgeDoc 改为 meta dict

```python
# core/knowledge/models.py
@dataclass
class KnowledgeDoc:
    id: str = field(default_factory=_uid)
    domain: str = ""
    title: str = ""
    content: str = ""
    content_type: str = "markdown"
    meta: dict = field(default_factory=lambda: {})  # 替代 tags
    source: str = "manual"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return { ... "meta": self.meta, ... }

    @classmethod
    def from_dict(cls, d: dict) -> KnowledgeDoc:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
```

### T1.2: meta 基本操作

`KnowledgeBase` 新增：

```python
def get_meta(self, doc_id: str) -> dict | None:
    """返回文档的 meta 字段"""

def update_meta(self, doc_id: str, meta: dict) -> bool:
    """合并更新 meta（shallow merge）"""

def set_meta_field(self, doc_id: str, key: str, value) -> bool:
    """设置 meta 的单个字段"""
```

### T1.3: 更新 tool handlers

```python
def knowledge_add(kb, domain, title, content, meta=None, source="agent") -> str:
    doc = KnowledgeDoc(domain=domain, title=title, content=content,
                       meta=meta or {}, source=source)
    kb.add(doc)
    kb.save()
    return json.dumps({"status": "ok", "doc_id": doc.id})

def knowledge_get(kb, doc_id: str) -> str:
    doc = kb.get(doc_id)
    if doc is None:
        return json.dumps({"status": "not_found"})
    return json.dumps({"status": "ok", "doc": doc.to_dict()})
```

### T1.4: knowledge_list_domains

新增 tool，返回 KB 的 domain 目录：

```python
def knowledge_list_domains(kb, parent: str | None = None) -> str:
    domains = kb.list_domains(parent=parent)
    return json.dumps({"domains": domains})
```

### T1.5: 端到端测试

写一个测试覆盖 agent 完整工作流：

```
1. knowledge_list_domains → 浏览域
2. knowledge_add → 加文档（含 meta）
3. knowledge_get → 读文档
4. knowledge_query → 搜索
5. knowledge_update → 更新 meta
6. knowledge_delete → 删除
```

### T1.6: 回跑全部测试 + 提交

```bash
pytest tests/ -q
git commit -m "feat: meta-based KnowledgeDoc, knowledge_get, knowledge_list_domains"
```

---

## Step 2: 数据库整理 task 定义

不写代码，只定义 task。写一个 Markdown 文档描述：

### 2.1 整理 task 类型

| task | 触发条件 | 输入 | 输出 |
|------|---------|------|------|
| **cleanup** | 某 domain 下文档 > N 条，或 Agent 主动调用 | domain | 标准化 type/level 值、删除无用扩展字段 |
| **fill_gaps** | 某 domain 下缺失 meta 的文档 > M% | domain | 自动补全 type/level/tags |
| **link_related** | 某 domain 下 related 链覆盖率 < P% | domain | 自动建议 parent/children/related 关系 |
| **dedup** | 某 domain 内 embeddings 相似度 > 阈值 | domain | 标记疑似重复文档 |

### 2.2 维护触发机制

- Agent 被动触发：任务中查询发现 meta 质量差 → 主动调 `knowledge_maintain`
- 系统触发：`knowledge_maintain` tool 被调用时，内部统计 domain 健康度 → 返回待维护项列表 → Agent 决定执行哪些

### 2.3 质量指标

- meta 完整度：有 type+level+tags 的文档占比
- 关联密度：有 parent/children/related 链的文档占比
- domain 深度：路径层级数分布

---

## Step 3: query-response 系统（待细化）

> 和 L2/L3 一起做，Step 3 届时重新出 plan。

核心 idea:
- KB 的 query-response = Stage 2 精排接入 Agent 自身的 LLM
- 与 L2/L3 的 decide() → capture_tool 模式对齐
- KB 不自己调 LLM——Agent 在 while-loop 中拿到粗筛结果后，用自己的 LLM 做精排
- Meta 的 response-to-query 接口设计（将来写）
