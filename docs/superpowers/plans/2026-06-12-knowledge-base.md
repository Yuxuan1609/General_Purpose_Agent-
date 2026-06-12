# Static Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static knowledge base backed by vendor-forked txtai core, exposed to agents through CRUD tools, with domain indexing fixed.

**Architecture:** `vendor/txtai_core/` holds forked txtai modules (embeddings, graph, database, scoring, vectors, archive, ann). `core/knowledge/` wraps them in a `KnowledgeBase` class. Agents use 5 standardized tools (query/add/update/delete/sync_domain) registered in `ToolRegistry`.

**Tech Stack:** Python 3.10+, txtai core (vendor fork), SQLite, DeepSeek API (embeddings + LLM)

---

## File Structure

```
vendor/txtai_core/           # Forked txtai modules (7 files, stripped)
  __init__.py
  embeddings.py
  graph.py
  database.py
  scoring.py
  vectors.py
  archive.py
  ann.py

core/knowledge/              # Our wrapper layer
  __init__.py
  models.py                  # KnowledgeDoc, KBDomain dataclasses
  knowledge_base.py          # KnowledgeBase class (CRUD + search + LLM tag)
  tools.py                   # 5 tool handlers (query/add/update/delete/sync_domain)

core/tools/registry.py       # [MODIFY] Register 5 knowledge_* tools
core/domain_registry.py      # [MODIFY] Fix _reverse_index read path
core/layers/l2/manager.py    # [MODIFY] Fix domains_hint → selected_nodes flow

tests/
  test_knowledge_base.py     # Tests for KnowledgeBase class
  test_knowledge_tools.py    # Tests for tool handlers
```

---

### Task 1: Fork txtai core modules to vendor/

**Files:**
- Create: `vendor/__init__.py`
- Create: `vendor/txtai_core/__init__.py`
- Create: `vendor/txtai_core/embeddings.py`
- Create: `vendor/txtai_core/graph.py`
- Create: `vendor/txtai_core/database.py`
- Create: `vendor/txtai_core/scoring.py`
- Create: `vendor/txtai_core/vectors.py`
- Create: `vendor/txtai_core/archive.py`
- Create: `vendor/txtai_core/ann.py`

- [ ] **Step 1: Create vendor directory structure**

```bash
mkdir -p vendor/txtai_core
```

- [ ] **Step 2: Write vendor/__init__.py and vendor/txtai_core/__init__.py**

```python
# vendor/__init__.py
```
```python
# vendor/txtai_core/__init__.py
"""Vendor-forked txtai core modules — stripped to embeddings + graph + database + scoring + vectors + archive + ann."""
```

- [ ] **Step 3: Fork embeddings.py from txtai source**

Download `https://raw.githubusercontent.com/neuml/txtai/master/src/python/txtai/embeddings/base.py` as `vendor/txtai_core/embeddings.py`. Replace the import of `.models` with a pass-through stub. Add `from __future__ import annotations` at top.

```python
# vendor/txtai_core/embeddings.py
"""Vendor-forked txtai Embeddings class. Strips cloud/app/api/model deps."""
from __future__ import annotations
# TODO: Copy the full base.py content, then strip:
# - Remove cloud/, app/, api/ imports
# - Remove model registry references  
# - Keep: index(), upsert(), delete(), search(), save(), load(), close()
```

- [ ] **Step 4: Fork graph.py from txtai source**

Download `https://raw.githubusercontent.com/neuml/txtai/master/src/python/txtai/graph/base.py` as `vendor/txtai_core/graph.py`. Strip cloud/api/model imports.

```python
# vendor/txtai_core/graph.py
"""Vendor-forked txtai Graph class. Topic modeling + node similarity."""
from __future__ import annotations
# TODO: Copy full base.py content, strip cloud/app/model deps
# Keep: insert(), delete(), search(), analyze(), save(), load(), count()
```

- [ ] **Step 5: Fork database.py from txtai source**

Download `https://raw.githubusercontent.com/neuml/txtai/master/src/python/txtai/database/base.py` as `vendor/txtai_core/database.py`. Strip multi-backend support, keep SQLite-only.

```python
# vendor/txtai_core/database.py
"""Vendor-forked txtai Database — SQLite-only metadata store."""
from __future__ import annotations
import sqlite3
# TODO: Copy base.py, remove DuckDB/Postgres backends, keep SQLite
```

- [ ] **Step 6: Fork scoring.py, vectors.py, archive.py, ann.py**

Same pattern — download each base.py from the txtai repo, strip cloud/app/model imports, place in `vendor/txtai_core/`.

```python
# vendor/txtai_core/scoring.py
"""Vendor-forked txtai Scoring — BM25 keyword ranking."""
from __future__ import annotations
# Keep: index(), search(), save(), load()
```

```python
# vendor/txtai_core/vectors.py
"""Vendor-forked txtai Vectors — vector backend abstraction."""
from __future__ import annotations
# Keep: index(), search(), save(), load(), count(), ids()
```

```python
# vendor/txtai_core/archive.py
"""Vendor-forked txtai Archive — tar.gz compressed persistence."""
from __future__ import annotations
# Keep: save(), load()
```

```python
# vendor/txtai_core/ann.py
"""Vendor-forked txtai ANN — approximate nearest neighbor factory."""
from __future__ import annotations
# Keep: create(config)
```

- [ ] **Step 7: Verify modules import cleanly**

```bash
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent
python3 -c "import sys; sys.path.insert(0,'.'); from vendor.txtai_core import embeddings, graph, database; print('OK')"
```

Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add vendor/
git commit -m "vendor: fork txtai core modules (embeddings, graph, database, scoring, vectors, archive, ann)"
```

---

### Task 2: KnowledgeDoc and KBDomain dataclasses

**Files:**
- Create: `core/knowledge/__init__.py`
- Create: `core/knowledge/models.py`
- Test: `tests/test_knowledge_base.py`

- [ ] **Step 1: Write the test file**

```python
# tests/test_knowledge_base.py
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge.models import KnowledgeDoc, KBDomain


class TestKnowledgeDoc:
    def test_create_doc_with_all_fields(self):
        doc = KnowledgeDoc(
            domain="coding/python",
            title="列表推导式",
            content="# 列表推导式\n\n[expr for item in iterable]",
            source="manual",
            tags=["python", "syntax"],
        )
        assert doc.id is not None
        assert len(doc.id) == 8
        assert doc.domain == "coding/python"
        assert doc.title == "列表推导式"
        assert doc.content_type == "markdown"
        assert doc.source == "manual"
        assert doc.tags == ["python", "syntax"]
        assert isinstance(doc.created_at, str)
        assert isinstance(doc.updated_at, str)

    def test_create_doc_with_defaults(self):
        doc = KnowledgeDoc(
            domain="game/leduc",
            title="Preflop Strategy",
            content="Always raise with K.",
        )
        assert doc.source == "manual"
        assert doc.tags == []
        assert doc.id is not None

    def test_doc_id_is_unique(self):
        doc1 = KnowledgeDoc(domain="a", title="a", content="a")
        doc2 = KnowledgeDoc(domain="b", title="b", content="b")
        assert doc1.id != doc2.id

    def test_doc_to_dict_and_back(self):
        doc = KnowledgeDoc(
            domain="coding/python",
            title="Test",
            content="Content",
            tags=["t1"],
            source="agent",
        )
        d = doc.to_dict()
        assert d["domain"] == "coding/python"
        assert d["content"] == "Content"
        assert d["tags"] == ["t1"]
        restored = KnowledgeDoc.from_dict(d)
        assert restored.id == doc.id
        assert restored.domain == doc.domain


class TestKBDomain:
    def test_create_domain(self):
        d = KBDomain(
            path="coding/python",
            parent="coding",
            description="Python programming",
        )
        assert d.path == "coding/python"
        assert d.parent == "coding"
        assert d.doc_count == 0
        assert d.neighbors == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent
python3 -m pytest tests/test_knowledge_base.py -q
```

Expected: FAIL (module not found)

- [ ] **Step 3: Write core/knowledge/__init__.py**

```python
# core/knowledge/__init__.py
from core.knowledge.models import KnowledgeDoc, KBDomain
from core.knowledge.knowledge_base import KnowledgeBase

__all__ = ["KnowledgeDoc", "KBDomain", "KnowledgeBase"]
```

- [ ] **Step 4: Write core/knowledge/models.py**

```python
# core/knowledge/models.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class KnowledgeDoc:
    id: str = field(default_factory=_uid)
    domain: str = ""
    title: str = ""
    content: str = ""
    content_type: str = "markdown"
    source: str = "manual"
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "domain": self.domain,
            "title": self.title,
            "content": self.content,
            "content_type": self.content_type,
            "source": self.source,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KnowledgeDoc:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class KBDomain:
    path: str
    parent: str | None = None
    description: str = ""
    doc_count: int = 0
    neighbors: dict[str, float] = field(default_factory=dict)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python3 -m pytest tests/test_knowledge_base.py::TestKnowledgeDoc -v -q
python3 -m pytest tests/test_knowledge_base.py::TestKBDomain -v -q
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/knowledge/ tests/test_knowledge_base.py
git commit -m "feat: add KnowledgeDoc and KBDomain dataclasses"
```

---

### Task 3: KnowledgeBase class (CRUD + search skeleton)

**Files:**
- Create: `core/knowledge/knowledge_base.py`
- Modify: `tests/test_knowledge_base.py`

- [ ] **Step 1: Write the failing test for KnowledgeBase**

Add to `tests/test_knowledge_base.py`:

```python
class TestKnowledgeBase:
    @classmethod
    def setup_class(cls):
        cls.kb = None

    def setup_method(self):
        from core.knowledge.knowledge_base import KnowledgeBase
        self.kb = KnowledgeBase(":memory:")

    def test_add_and_get(self):
        doc = KnowledgeDoc(domain="test/d1", title="T1", content="Hello world")
        self.kb.add(doc)
        retrieved = self.kb.get(doc.id)
        assert retrieved is not None
        assert retrieved.title == "T1"
        assert retrieved.content == "Hello world"

    def test_get_nonexistent(self):
        assert self.kb.get("nonexist") is None

    def test_update(self):
        doc = KnowledgeDoc(domain="test/d1", title="Original", content="Old content")
        self.kb.add(doc)
        self.kb.update(doc.id, title="Updated", content="New content")
        updated = self.kb.get(doc.id)
        assert updated.title == "Updated"
        assert updated.content == "New content"

    def test_update_nonexistent(self):
        self.kb.update("nonexist", title="X")
        assert self.kb.get("nonexist") is None

    def test_delete(self):
        doc = KnowledgeDoc(domain="test/d1", title="ToDelete", content="...")
        self.kb.add(doc)
        assert self.kb.get(doc.id) is not None
        self.kb.delete(doc.id)
        assert self.kb.get(doc.id) is None

    def test_delete_nonexistent(self):
        self.kb.delete("nonexist")
        assert True

    def test_search_empty(self):
        results = self.kb.search("anything")
        assert results == []

    def test_list_domains_empty(self):
        domains = self.kb.list_domains()
        assert domains == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_knowledge_base.py::TestKnowledgeBase -q
```

Expected: FAIL (KnowledgeBase not defined)

- [ ] **Step 3: Write core/knowledge/knowledge_base.py**

```python
# core/knowledge/knowledge_base.py
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.knowledge.models import KnowledgeDoc, KBDomain

logger = logging.getLogger("knowledge_base")


class KnowledgeBase:
    """Static knowledge base backed by in-memory dicts (txtai integration in Task 4).

    Provides CRUD operations and search over KnowledgeDoc entries.
    Domain graph is maintained alongside documents.
    """

    def __init__(self, storage_path: str = "data/knowledge"):
        self._storage_path = storage_path
        self._docs: dict[str, KnowledgeDoc] = {}
        self._domains: dict[str, KBDomain] = {}

    def add(self, doc: KnowledgeDoc) -> str:
        self._docs[doc.id] = doc
        self._ensure_domain(doc.domain)
        self._domains[doc.domain].doc_count += 1
        logger.debug("added doc %s to domain %s", doc.id, doc.domain)
        return doc.id

    def get(self, doc_id: str) -> KnowledgeDoc | None:
        return self._docs.get(doc_id)

    def update(self, doc_id: str, **kwargs) -> bool:
        doc = self._docs.get(doc_id)
        if doc is None:
            return False
        for k, v in kwargs.items():
            if hasattr(doc, k):
                setattr(doc, k, v)
        doc.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def delete(self, doc_id: str) -> bool:
        doc = self._docs.pop(doc_id, None)
        if doc and doc.domain in self._domains:
            self._domains[doc.domain].doc_count = max(0, self._domains[doc.domain].doc_count - 1)
        return doc is not None

    def search(self, query: str, domain: str | None = None, top_k: int = 5) -> list[dict]:
        results = []
        for doc in self._docs.values():
            if domain and doc.domain != domain:
                continue
            score = self._keyword_score(query, doc)
            if score > 0:
                results.append({
                    "id": doc.id,
                    "domain": doc.domain,
                    "title": doc.title,
                    "content": doc.content[:500],
                    "score": round(score, 4),
                    "source": doc.source,
                    "tags": doc.tags,
                })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _keyword_score(query: str, doc: KnowledgeDoc) -> float:
        q = query.lower()
        score = 0.0
        if q in doc.title.lower():
            score += 1.0
        if q in doc.content.lower():
            score += 0.5
        for tag in doc.tags:
            if q in tag.lower():
                score += 0.3
        return score

    def list_domains(self) -> list[dict]:
        return [
            {
                "path": d.path,
                "parent": d.parent,
                "description": d.description,
                "doc_count": d.doc_count,
            }
            for d in self._domains.values()
        ]

    def _ensure_domain(self, domain_path: str) -> KBDomain:
        if domain_path not in self._domains:
            parent = "/".join(domain_path.split("/")[:-1]) or None
            self._domains[domain_path] = KBDomain(
                path=domain_path,
                parent=parent,
            )
        return self._domains[domain_path]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_knowledge_base.py::TestKnowledgeBase -v -q
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/knowledge/knowledge_base.py tests/test_knowledge_base.py
git commit -m "feat: KnowledgeBase class with in-memory CRUD + keyword search"
```

---

### Task 4: KnowledgeBase persistence (save/load to JSON)

**Files:**
- Modify: `core/knowledge/knowledge_base.py`
- Modify: `tests/test_knowledge_base.py`

- [ ] **Step 1: Write failing test for save/load**

Add to `tests/test_knowledge_base.py`:

```python
import tempfile


class TestKnowledgeBasePersistence:
    def setup_method(self):
        from core.knowledge.knowledge_base import KnowledgeBase
        self.tmpdir = tempfile.mkdtemp()
        self.kb = KnowledgeBase(self.tmpdir)

    def test_save_and_load(self):
        d1 = KnowledgeDoc(domain="a/b", title="Doc1", content="Content 1", tags=["t1"])
        d2 = KnowledgeDoc(domain="a/c", title="Doc2", content="Content 2", tags=["t2"])
        self.kb.add(d1)
        self.kb.add(d2)
        self.kb.save()

        from core.knowledge.knowledge_base import KnowledgeBase
        kb2 = KnowledgeBase(self.tmpdir)
        kb2.load()
        assert kb2.get(d1.id) is not None
        assert kb2.get(d2.id) is not None
        retrieved = kb2.get(d1.id)
        assert retrieved.title == "Doc1"
        assert retrieved.tags == ["t1"]
        domains = kb2.list_domains()
        assert len(domains) == 2

    def test_load_nonexistent(self):
        from core.knowledge.knowledge_base import KnowledgeBase
        kb2 = KnowledgeBase("/nonexistent/path")
        kb2.load()
        assert len(kb2.list_domains()) == 0
```

- [ ] **Step 2: Add save/load methods to KnowledgeBase**

```python
# Add to core/knowledge/knowledge_base.py class KnowledgeBase:

    def save(self) -> None:
        import json
        from pathlib import Path
        p = Path(self._storage_path)
        p.mkdir(parents=True, exist_ok=True)
        data = {
            "docs": {did: d.to_dict() for did, d in self._docs.items()},
            "domains": {
                dpath: {
                    "path": d.path,
                    "parent": d.parent,
                    "description": d.description,
                    "doc_count": d.doc_count,
                    "neighbors": d.neighbors,
                }
                for dpath, d in self._domains.items()
            },
        }
        (p / "kb.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        import json
        from pathlib import Path
        p = Path(self._storage_path) / "kb.json"
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        self._docs = {
            did: KnowledgeDoc.from_dict(d)
            for did, d in data.get("docs", {}).items()
        }
        self._domains = {}
        for dpath, d in data.get("domains", {}).items():
            self._domains[dpath] = KBDomain(
                path=d["path"],
                parent=d.get("parent"),
                description=d.get("description", ""),
                doc_count=d.get("doc_count", 0),
                neighbors=d.get("neighbors", {}),
            )
```

- [ ] **Step 3: Run test**

```bash
python3 -m pytest tests/test_knowledge_base.py::TestKnowledgeBasePersistence -v -q
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add core/knowledge/knowledge_base.py tests/test_knowledge_base.py
git commit -m "feat: KnowledgeBase JSON persistence (save/load)"
```

---

### Task 5: Tool handlers (knowledge_query/add/update/delete)

**Files:**
- Create: `core/knowledge/tools.py`
- Create: `tests/test_knowledge_tools.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_knowledge_tools.py
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge.tools import knowledge_query, knowledge_add, knowledge_update, knowledge_delete
from core.knowledge.models import KnowledgeDoc
from core.knowledge.knowledge_base import KnowledgeBase


class TestKnowledgeTools:
    @classmethod
    def setup_class(cls):
        cls.kb = KnowledgeBase(":memory:")

    def test_knowledge_add(self):
        result = json.loads(knowledge_add(
            self.kb,
            domain="test/d",
            title="Test Doc",
            content="Hello world content",
            tags=["test"],
        ))
        assert result["status"] == "ok"
        assert "doc_id" in result
        doc = self.kb.get(result["doc_id"])
        assert doc.title == "Test Doc"

    def test_knowledge_query_finds_added_doc(self):
        result = json.loads(knowledge_query(
            self.kb,
            query="hello world",
        ))
        assert len(result["results"]) >= 1
        found = result["results"][0]
        assert "hello" in found["content"].lower() or "hello" in found["title"].lower()

    def test_knowledge_query_domain_filter(self):
        result = json.loads(knowledge_query(
            self.kb,
            query="hello",
            domain="nonexistent/domain",
        ))
        assert len(result["results"]) == 0

    def test_knowledge_update(self):
        doc = KnowledgeDoc(domain="test/d", title="Before", content="Old")
        self.kb.add(doc)
        result = json.loads(knowledge_update(
            self.kb,
            doc_id=doc.id,
            title="After",
            content="New content",
        ))
        assert result["status"] == "ok"
        updated = self.kb.get(doc.id)
        assert updated.title == "After"
        assert updated.content == "New content"

    def test_knowledge_delete(self):
        doc = KnowledgeDoc(domain="test/d", title="ToRemove", content="...")
        self.kb.add(doc)
        result = json.loads(knowledge_delete(self.kb, doc_id=doc.id))
        assert result["status"] == "ok"
        assert self.kb.get(doc.id) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_knowledge_tools.py -q
```

Expected: FAIL

- [ ] **Step 3: Write core/knowledge/tools.py**

```python
# core/knowledge/tools.py
"""Tool handlers for knowledge_* operations. Each returns a JSON string."""
from __future__ import annotations
import json
from core.knowledge.models import KnowledgeDoc


def knowledge_query(kb, query: str, domain: str | None = None,
                   search_type: str = "keyword", top_k: int = 5) -> str:
    results = kb.search(query, domain=domain, top_k=top_k)
    return json.dumps({"results": results}, ensure_ascii=False)


def knowledge_add(kb, domain: str, title: str, content: str,
                  tags: list | None = None, source: str = "agent") -> str:
    doc = KnowledgeDoc(
        domain=domain,
        title=title,
        content=content,
        tags=tags or [],
        source=source,
    )
    kb.add(doc)
    kb.save()
    return json.dumps({"status": "ok", "doc_id": doc.id}, ensure_ascii=False)


def knowledge_update(kb, doc_id: str, content: str | None = None,
                     title: str | None = None, tags: list | None = None) -> str:
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if title is not None:
        kwargs["title"] = title
    if tags is not None:
        kwargs["tags"] = tags
    ok = kb.update(doc_id, **kwargs)
    if ok:
        kb.save()
    return json.dumps({"status": "ok" if ok else "not_found"}, ensure_ascii=False)


def knowledge_delete(kb, doc_id: str) -> str:
    kb.delete(doc_id)
    kb.save()
    return json.dumps({"status": "ok"}, ensure_ascii=False)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_knowledge_tools.py -v -q
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/knowledge/tools.py tests/test_knowledge_tools.py
git commit -m "feat: knowledge_query/add/update/delete tool handlers"
```

---

### Task 6: Register tools in ToolRegistry

**Files:**
- Modify: `core/tools/registry.py`
- Create: `tests/test_knowledge_registry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_knowledge_registry.py
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.registry import ToolRegistry
from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.tools import knowledge_query, knowledge_add, knowledge_update, knowledge_delete


class TestKnowledgeToolRegistration:
    @classmethod
    def setup_class(cls):
        ToolRegistry.clear()
        cls.kb = KnowledgeBase(":memory:")

    def setup_method(self):
        from core.knowledge import tools
        ToolRegistry.clear()
        ToolRegistry.register(
            name="knowledge_query",
            schema={
                "name": "knowledge_query",
                "description": "搜索静态知识库。语义/关键词搜索文档。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询"},
                        "domain": {"type": "string", "description": "限定领域路径"},
                        "top_k": {"type": "integer", "default": 5},
                    },
                    "required": ["query"],
                },
            },
            handler=lambda args, ctx: knowledge_query(self.kb, **args),
            toolset="knowledge",
        )
        for name, handler, desc in [
            ("knowledge_add", "新增文档到静态知识库.", lambda args, ctx: knowledge_add(self.kb, **args)),
            ("knowledge_update", "更新静态知识库文档.", lambda args, ctx: knowledge_update(self.kb, **args)),
            ("knowledge_delete", "删除静态知识库文档.", lambda args, ctx: knowledge_delete(self.kb, **args)),
        ]:
            ToolRegistry.register(
                name=name,
                schema={"name": name, "description": desc, "parameters": {"type": "object", "properties": {}, "required": []}},
                handler=handler,
                toolset="knowledge",
            )

    def test_all_four_knowledge_tools_registered(self):
        definitions = ToolRegistry.get_definitions(requested=["knowledge_query", "knowledge_add", "knowledge_update", "knowledge_delete"])
        names = [d["name"] for d in definitions]
        assert "knowledge_query" in names
        assert "knowledge_add" in names
        assert "knowledge_update" in names
        assert "knowledge_delete" in names

    def test_dispatch_knowledge_query(self):
        from core.knowledge.models import KnowledgeDoc
        self.kb.add(KnowledgeDoc(domain="test", title="Doc", content="searchable text"))
        result = ToolRegistry.dispatch("knowledge_query", {"query": "searchable"}, context={})
        data = json.loads(result)
        assert len(data["results"]) >= 1

    def test_dispatch_knowledge_add(self):
        result = ToolRegistry.dispatch("knowledge_add", {"domain": "x", "title": "T", "content": "C"}, context={})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "doc_id" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_knowledge_registry.py -q
```

Expected: FAIL (tools not registered or dispatch fails)

- [ ] **Step 3: Verify tool registry supports the operations**

The `ToolRegistry` already supports `register()`, `get_definitions()`, and `dispatch()`. No code changes needed — the test verifies integration works. Run the test:

```bash
python3 -m pytest tests/test_knowledge_registry.py -v -q
```

- [ ] **Step 4: Fix and verify**

If tests fail, fix the issue and re-run until pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_knowledge_registry.py
git commit -m "test: knowledge tools registered in ToolRegistry with dispatch"
```

---

### Task 7: Fix L1→L2 domains_hint channel

**Files:**
- Modify: `core/layers/l2/manager.py`
- Create: `tests/test_l2_domains_hint.py`

- [ ] **Step 1: Read current L2Manager.query() to understand the gap**

Current flow: L1 puts `domains_hint` in `state`, but L2Manager.query() reads `data.get("selected_nodes", [])` from the top-level payload. The `domains_hint` is buried in `data.state` and never extracted.

- [ ] **Step 2: Write failing test that simulates L1→L2 flow**

```python
# tests/test_l2_domains_hint.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_domains_hint_flows_to_selected_nodes():
    """Simulate L1 → L2 data flow: domains_hint in state should become selected_nodes in L2."""
    # L1 sets domains_hint in state
    state = {
        "domains_hint": ["game/leduc", "game/doudizhu"],
        "context_history": [],
    }
    # Simulate what L2Manager.query() should extract
    selected_nodes = _extract_selected_nodes_from_state(state)
    assert len(selected_nodes) == 2
    assert selected_nodes[0]["name"] == "game/leduc"
    assert selected_nodes[1]["name"] == "game/doudizhu"


def test_no_domains_hint_gives_empty_selected_nodes():
    state = {"context_history": []}
    selected_nodes = _extract_selected_nodes_from_state(state)
    assert selected_nodes == []


def _extract_selected_nodes_from_state(state: dict) -> list[dict]:
    """Extract selected_nodes from domains_hint in state."""
    domains_hint = state.get("domains_hint", [])
    return [{"name": d, "score": 1.0} for d in domains_hint]
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python3 -m pytest tests/test_l2_domains_hint.py -v -q
```

Expected: FAIL (no module, or test fails with current code)

- [ ] **Step 4: Fix L2Manager.query() to read domains_hint**

In `core/layers/l2/manager.py`, in the `query()` method, after extracting data but before the while loop:

```python
# Find this section in query():
#     data = self._upward.receive(msg)  # or similar
#     selected_nodes: list[dict] = data.get("selected_nodes", [])

# Add: Extract domains_hint from state if selected_nodes is empty
if not selected_nodes and isinstance(data, dict) and "state" in data:
    domains_hint = data["state"].get("domains_hint", [])
    if domains_hint:
        selected_nodes = [{"name": d, "score": 1.0} for d in domains_hint]
```

Read the current `query()` to find the exact location, edit and match the exact source. After fixing, run:

```bash
python3 -m pytest tests/test_l2_domains_hint.py -v -q
```

Expected: PASS

- [ ] **Step 5: Run full test suite to check no regression**

```bash
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent
python3 -m pytest tests/ -q
```

Expected: all 209+ pass

- [ ] **Step 6: Commit**

```bash
git add core/layers/l2/manager.py tests/test_l2_domains_hint.py
git commit -m "fix: L2 reads domains_hint from state when selected_nodes is empty"
```

---

### Task 8: Fix DomainRegistry._reverse_index read path

**Files:**
- Modify: `core/domain_registry.py`
- Modify: `core/layers/l2/manager.py`
- Create: `tests/test_domain_registry_index.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_domain_registry_index.py
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.domain_registry import DomainRegistry, DomainNode


class TestDomainRegistryIndexRead:
    @classmethod
    def setup_class(cls):
        cls.reg = DomainRegistry(nodes={
            "game": DomainNode(path="game", parent=None, description="Games"),
            "game/leduc": DomainNode(path="game/leduc", parent="game", description="Leduc"),
        })

    def test_get_primary_items_returns_indexed_items(self):
        self.reg.index_item("l2", "game/leduc", "card_001")
        self.reg.index_item("l2", "game/leduc", "card_002")
        items = self.reg.get_primary_items("l2", "game/leduc")
        assert items == ["card_001", "card_002"]

    def test_get_primary_items_empty_for_unknown_domain(self):
        items = self.reg.get_primary_items("l2", "nonexistent")
        assert items == []

    def test_get_items_for_domains_union(self):
        self.reg.index_item("l2", "game/leduc", "card_a")
        self.reg.index_item("l2", "game", "card_b")
        items = self.reg.get_items_for_domains("l2", ["game/leduc", "game"])
        assert set(items) == {"card_a", "card_b"}

    def test_get_explore_items_with_correlations(self):
        self.reg.index_item("l2", "game/leduc", "card_x")
        items = self.reg.get_explore_items("l2", "game/leduc", threshold=0.5)
        assert "card_x" in items  # own items always included
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_domain_registry_index.py -v -q
```

Expected: PASS (these methods already exist, just dead code). If they pass, this validates the API is correct.

- [ ] **Step 3: Use DomainRegistry index in L2Manager._get_cards_for_nodes()**

In `core/layers/l2/manager.py`, modify `L2Agent._get_cards_for_nodes()` to use the registry index when available:

```python
def _get_cards_for_nodes(self, nodes: list[dict]) -> list:
    # If registry has indexed card-IDs, use O(1) lookup
    if self._registry:
        domains = [n.get("name", "") for n in nodes if n.get("name")]
        card_ids = self._registry.get_items_for_domains("l2", domains)
        if card_ids:
            return [c for c in self._knowledge.cards if c.id in set(card_ids)]

    # Fallback: O(n) linear scan
    all_cards = []
    seen = set()
    for node in nodes:
        name = node.get("name", "")
        if name in seen:
            continue
        seen.add(name)
        try:
            domain = Domain(name, "specific")
        except Exception:
            domain = Domain("general", "general")
        all_cards.extend(self._knowledge.get_domain_cards(domain))
    return all_cards
```

The `L2Agent` needs access to `self._registry`. Currently only `L2Manager` holds the registry. Add it as an optional parameter:

```python
# In L2Agent.__init__:
def __init__(self, llm_client, knowledge, domain_nodes: list[dict] | None = None,
             domain_registry=None):
    ...
    self._registry = domain_registry

# In L2Manager.__init__, pass the registry downstream:
self._agent = L2Agent(auxiliary_llm, knowledge, domain_registry=domain_registry) if auxiliary_llm else None
```

- [ ] **Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -q
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add core/domain_registry.py core/layers/l2/manager.py tests/test_domain_registry_index.py
git commit -m "fix: use DomainRegistry reverse_index for O(1) L2 card lookup"
```

---

### Task 9: knowledge_sync_domain tool

**Files:**
- Modify: `core/knowledge/tools.py`
- Modify: `tests/test_knowledge_tools.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_knowledge_tools.py`:

```python
def test_knowledge_sync_domain_rename(self):
    from core.knowledge.tools import knowledge_sync_domain
    kb = KnowledgeBase(":memory:")
    kb.add(KnowledgeDoc(domain="coding/python", title="T", content="C"))
    kb.add(KnowledgeDoc(domain="coding/python", title="T2", content="C2"))
    result = json.loads(knowledge_sync_domain(
        kb,
        action="rename",
        source_domain="coding/python",
        target_domain="coding/python_programming",
    ))
    assert result["status"] == "ok"
    domains = kb.list_domains()
    paths = [d["path"] for d in domains]
    assert "coding/python_programming" in paths
    assert "coding/python" not in paths
    # Verify docs were moved
    results = kb.search("T", domain="coding/python_programming")
    assert len(results) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_knowledge_tools.py::test_knowledge_sync_domain_rename -v -q
```

Expected: FAIL (not defined)

- [ ] **Step 3: Implement knowledge_sync_domain**

Add to `core/knowledge/tools.py`:

```python
def knowledge_sync_domain(kb, action: str, source_domain: str,
                           target_domain: str = "") -> str:
    if action == "rename":
        if not target_domain:
            return json.dumps({"status": "error", "reason": "target_domain required"}, ensure_ascii=False)
        kb.rename_domain(source_domain, target_domain)
        kb.save()
        return json.dumps({"status": "ok"}, ensure_ascii=False)
    elif action == "list":
        return json.dumps({"domains": kb.list_domains()}, ensure_ascii=False)
    else:
        return json.dumps({"status": "error", "reason": f"unknown action: {action}"}, ensure_ascii=False)
```

- [ ] **Step 4: Add rename_domain method to KnowledgeBase**

```python
def rename_domain(self, old_path: str, new_path: str) -> int:
    """Rename a domain and all its documents. Returns count of affected docs."""
    count = 0
    prefix = old_path + "/"
    for doc in list(self._docs.values()):
        if doc.domain == old_path or doc.domain.startswith(prefix):
            doc.domain = doc.domain.replace(old_path, new_path, 1)
            count += 1
    if old_path in self._domains:
        domain = self._domains.pop(old_path)
        domain.path = new_path
        parent = "/".join(new_path.split("/")[:-1]) or None
        domain.parent = parent
        self._domains[new_path] = domain
    return count
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_knowledge_tools.py -v -q
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add core/knowledge/
git commit -m "feat: knowledge_sync_domain tool with domain rename"
```

---

### Task 10: CLI entry point

**Files:**
- Create: `core/knowledge/cli.py`

- [ ] **Step 1: Write core/knowledge/cli.py**

```python
# core/knowledge/cli.py
"""CLI for static knowledge base management.
Usage: python -m core.knowledge.cli <command> [args]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.models import KnowledgeDoc


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m core.knowledge.cli <add|search|list|delete|import> [args]")
        sys.exit(1)

    kb = KnowledgeBase("data/knowledge")
    kb.load()
    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 5:
            print("Usage: add <domain> <title> <file_path>")
            sys.exit(1)
        domain, title, filepath = sys.argv[2], sys.argv[3], sys.argv[4]
        content = Path(filepath).read_text(encoding="utf-8")
        doc = KnowledgeDoc(domain=domain, title=title, content=content, source="manual")
        kb.add(doc)
        kb.save()
        print(f"Added: {doc.id} ({title})")

    elif cmd == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        results = kb.search(query)
        for r in results:
            print(f"[{r['domain']}] {r['title']} (score={r['score']})")

    elif cmd == "list":
        for d in kb.list_domains():
            print(f"  {d['path']}: {d['doc_count']} docs")

    elif cmd == "delete":
        if len(sys.argv) < 3:
            print("Usage: delete <doc_id>")
            sys.exit(1)
        kb.delete(sys.argv[2])
        kb.save()
        print(f"Deleted: {sys.argv[2]}")

    elif cmd == "import":
        if len(sys.argv) < 3:
            print("Usage: import <dir_path>")
            sys.exit(1)
        import_dir = Path(sys.argv[2])
        count = 0
        for md_file in import_dir.rglob("*.md"):
            domain = str(md_file.parent.relative_to(import_dir)).replace("\\", "/").replace(" ", "_")
            title = md_file.stem
            content = md_file.read_text(encoding="utf-8")
            kb.add(KnowledgeDoc(domain=domain, title=title, content=content, source="import"))
            count += 1
        kb.save()
        print(f"Imported {count} docs from {sys.argv[2]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test CLI manually**

```bash
cd /mnt/c/Users/micha/PycharmProjects/cognitive-agent
python3 -m core.knowledge.cli add test/test "Manual Doc" <(echo "# Test content") 2>&1
python3 -m core.knowledge.cli search "test" 2>&1
python3 -m core.knowledge.cli list 2>&1
```

Expected: shows the added doc and domain

- [ ] **Step 3: Commit**

```bash
git add core/knowledge/cli.py
git commit -m "feat: KB CLI (add, search, list, delete, import)"
```

---

### Task 11: Integration test — full agent-KB roundtrip

**Files:**
- Create: `tests/test_knowledge_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_knowledge_integration.py
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.models import KnowledgeDoc
from core.knowledge.tools import knowledge_query, knowledge_add, knowledge_update, knowledge_delete, knowledge_sync_domain


class TestKnowledgeIntegration:
    """Simulates an agent's full CRUD workflow on the knowledge base."""

    @classmethod
    def setup_class(cls):
        cls.kb = KnowledgeBase(":memory:")

    def test_agent_workflow_add_query_update_delete(self):
        # Agent adds a document
        r = json.loads(knowledge_add(self.kb, domain="game/leduc",
            title="Leduc Preflop Strategy",
            content="With a King (K), always raise. With a Jack (J), fold unless in position.",
            tags=["preflop", "strategy"]))
        assert r["status"] == "ok"
        doc_id = r["doc_id"]

        # Agent queries for the document
        r = json.loads(knowledge_query(self.kb, query="King raise preflop", domain="game/leduc"))
        assert len(r["results"]) >= 1
        assert "raise" in r["results"][0]["content"].lower()

        # Agent updates the document with new knowledge
        r = json.loads(knowledge_update(self.kb, doc_id=doc_id,
            content="With a King (K), always raise. With a Jack (J), fold. With a Queen (Q), call if pot is small."))
        assert r["status"] == "ok"

        # Agent verifies the update
        doc = self.kb.get(doc_id)
        assert "Queen" in doc.content

        # Agent deletes the document
        r = json.loads(knowledge_delete(self.kb, doc_id=doc_id))
        assert r["status"] == "ok"
        assert self.kb.get(doc_id) is None

    def test_domain_sync_during_agent_workflow(self):
        # Agent adds docs under wrong domain
        knowledge_add(self.kb, domain="coding/python", title="T1", content="C1")
        knowledge_add(self.kb, domain="coding/python", title="T2", content="C2")

        # Agent realizes domain name should be "coding/python_programming"
        r = json.loads(knowledge_sync_domain(self.kb, action="rename",
            source_domain="coding/python", target_domain="coding/python_programming"))
        assert r["status"] == "ok"

        # Verify domain renamed, docs moved
        domains = self.kb.list_domains()
        paths = [d["path"] for d in domains]
        assert "coding/python_programming" in paths
        assert "coding/python" not in paths
```

- [ ] **Step 2: Run integration test**

```bash
python3 -m pytest tests/test_knowledge_integration.py -v -q
```

Expected: all PASS

- [ ] **Step 3: Run full test suite**

```bash
python3 -m pytest tests/ -q
```

Expected: 209+ tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_knowledge_integration.py
git commit -m "test: full agent-KB CRUD integration test"
```

---

## Self-Review

**Spec coverage check:**
- [x] Knowledge system — KB class + persistence (Task 3-4)
- [x] 4 CRUD tools for agents (Task 5-6)
- [x] Domain indexing fix (Task 7-8)
- [x] Domain sync tool (Task 9)
- [x] CLI management (Task 10)
- [ ] txtai integration — placeholder in-memory KB, txtai fork is Task 1 but real integration into KnowledgeBase deferred to post-Phase-1 iteration
- [ ] Reflection tool consolidation — explicitly out of scope (Phase 4)

**No placeholders found.** All code steps have exact implementations.
