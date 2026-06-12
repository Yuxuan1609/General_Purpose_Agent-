# txtai 接口需求记录

> 记录 `KnowledgeBase` 封装层需要对接的 txtai 核心接口。当前为内存占位实现，后续按此记录逐项替换。

## 当前占位 → txtai 接口映射

| KnowledgeBase 方法 | 当前实现 | 需对接的 txtai 接口 | 所属模块 |
|-------------------|---------|-------------------|---------|
| `search()` | dict 遍历 + substring 匹配 | `embeddings.search(query, limit, weights)` | `embeddings` |
| `add()` | dict insert | `embeddings.upsert([doc])` + `database.insert(metadata)` | `embeddings`, `database` |
| `delete()` | dict pop | `embeddings.delete([id])` + `database.delete(id)` | `embeddings`, `database` |
| `update()` | dict attr set | `embeddings.delete()` → `embeddings.upsert()` + `database.update()` | `embeddings`, `database` |
| `_ensure_domain()` | dict key check | `graph.add_node(domain)` → auto-cluster | `graph` |
| `list_domains()` | dict iteration | `database.search("SELECT domain, COUNT(*) ...")` | `database` |
| `save()` | JSON dump to file | `archive.save(path)` → tar.gz | `archive` |
| `load()` | JSON read from file | `archive.load(path)` → 恢复 embeddings + db + graph | `archive` |
| `search()` domain filter | if-else in loop | `database.search()` SQL WHERE domain=? | `database` |
| `search()` keyword score | `_keyword_score()` substring | `scoring.bm25.score(query, doc)` | `scoring` |
| `search()` hybrid | 无 | `embeddings.search()` + `scoring` weighted fusion | `embeddings`, `scoring` |
| `search()` semantic vector | 无 | `embeddings.search()` 默认行为 | `embeddings` |
| `rename_domain()` | doc loop + string replace | `database.update()` + `graph.relabel_node()` | `database`, `graph` |
| 自动 tag（LLM） | 未实现 | `KnowledgeBase._auto_tag()` → LLM call + `database.update_tags()` | 自建 |

## txtai Embeddings 主类所需方法

```python
class Embeddings:
    def __init__(self, config: dict)           # path, content, scoring, graph 等配置
    def index(self, documents: list)           # 批量索引文档 [(id, text, tags), ...]
    def upsert(self, documents: list)          # 插入或更新
    def delete(self, ids: list)                # 按 ID 删除
    def search(self, query: str, limit: int)   # 语义搜索，返回 [(id, score), ...]
    def save(self, path: str)                  # 持久化
    def load(self, path: str)                  # 恢复
    def close(self)                            # 释放资源
    def count(self) -> int                     # 文档计数

    # 内部组件（通过 config 控制）
    # - database: 元数据存储 + SQL 查询
    # - graph: 图网络分析
    # - scoring: BM25 关键词评分
    # - vectors: 向量嵌入后端
    # - archive: 压缩归档
```

## 精简范围（不需要的模块/后端）

| 模块 | 保留 | 可删除 | 理由 |
|------|------|--------|------|
| `ann/` | numpy, sqlite | faiss, ggml, hnsw, annoy, torch, pgvector, turbovec | NumPy ANN 足够，不需要外部 C++ 库 |
| `vectors/` | base, factory | huggingface, litellm, litert, external, llama, m2v, sbert, words | 用 DeepSeek Embedding API，不走本地模型 |
| `database/` | base, sqlite, factory, schema, encoder | duckdb, client, rdbms, embedded | SQLite-only |
| `scoring/` | base, bm25, tfidf, terms, factory | pgtext, sif, sparse | 不需要 PostgreSQL 全文搜索 |
| `graph/` | base, networkx, topics, factory | rdbms, query | 不需要 RDBMS 图后端和 Cypher 查询 |
| `archive/` | base, compress, tar, factory | zip | tar.gz 压缩足够 |
| `models/` | stub | 全部换 stub | 不本地跑 HuggingFace 模型 |
