# tests/test_knowledge_base.py
import json
import os
import shutil
import sys
import tempfile
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
            meta={"tags": ["python", "syntax"]},
        )
        assert doc.id is not None
        assert len(doc.id) == 8
        assert doc.domain == "coding/python"
        assert doc.title == "列表推导式"
        assert doc.content_type == "markdown"
        assert doc.source == "manual"
        assert doc.meta == {"tags": ["python", "syntax"]}
        assert isinstance(doc.created_at, str)
        assert isinstance(doc.updated_at, str)

    def test_create_doc_with_defaults(self):
        doc = KnowledgeDoc(
            domain="game/leduc",
            title="Preflop Strategy",
            content="Always raise with K.",
        )
        assert doc.source == "manual"
        assert doc.meta == {}
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
            meta={"tags": ["t1"]},
            source="agent",
        )
        d = doc.to_dict()
        assert d["domain"] == "coding/python"
        assert d["content"] == "Content"
        assert d["meta"] == {"tags": ["t1"]}
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


class TestKnowledgeBase:
    def setup_method(self):
        from core.knowledge.knowledge_base import KnowledgeBase
        self._tmpdir = tempfile.mkdtemp()
        self.kb = KnowledgeBase(self._tmpdir)

    def teardown_method(self):
        self.kb.close()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_add_and_get(self):
        from core.knowledge.models import KnowledgeDoc
        doc = KnowledgeDoc(domain="test/d1", title="T1", content="Hello world")
        self.kb.add(doc)
        retrieved = self.kb.get(doc.id)
        assert retrieved is not None
        assert retrieved.title == "T1"
        assert retrieved.content == "Hello world"

    def test_get_nonexistent(self):
        assert self.kb.get("nonexist") is None

    def test_update(self):
        from core.knowledge.models import KnowledgeDoc
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
        from core.knowledge.models import KnowledgeDoc
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

    def test_get_meta_and_update_meta(self):
        from core.knowledge.models import KnowledgeDoc
        doc = KnowledgeDoc(domain="test", title="T", content="C", meta={"type": "reference"})
        self.kb.add(doc)
        m = self.kb.get_meta(doc.id)
        assert m["type"] == "reference"
        assert "id" not in m
        self.kb.update_meta(doc.id, {"level": "beginner", "type": "faq"})
        m2 = self.kb.get_meta(doc.id)
        assert m2["type"] == "faq"
        assert m2["level"] == "beginner"


class TestKnowledgeBasePersistence:
    def setup_method(self):
        from core.knowledge.knowledge_base import KnowledgeBase
        self._tmpdir = tempfile.mkdtemp()
        self.kb = KnowledgeBase(self._tmpdir)

    def teardown_method(self):
        self.kb.close()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        from core.knowledge.models import KnowledgeDoc
        from core.knowledge.knowledge_base import KnowledgeBase
        d1 = KnowledgeDoc(domain="a/b", title="Doc1", content="Content 1", meta={"tags": ["t1"]})
        d2 = KnowledgeDoc(domain="a/c", title="Doc2", content="Content 2", meta={"tags": ["t2"]})
        self.kb.add(d1)
        self.kb.add(d2)
        self.kb.save()

        kb2 = KnowledgeBase(self._tmpdir)
        kb2.load()
        assert kb2.get(d1.id) is not None
        assert kb2.get(d2.id) is not None
        retrieved = kb2.get(d1.id)
        assert retrieved.title == "Doc1"
        assert retrieved.meta == {"tags": ["t1"]}
        domains = kb2.list_domains()
        assert len(domains) == 2
        kb2.close()

    def test_load_nonexistent(self):
        from core.knowledge.knowledge_base import KnowledgeBase
        nonexistent = os.path.join(self._tmpdir, "does_not_exist")
        kb2 = KnowledgeBase(nonexistent)
        kb2.load()
        assert len(kb2.list_domains()) == 0
        kb2.close()


class TestMetaAndChunking:
    def setup_method(self):
        from core.knowledge.knowledge_base import KnowledgeBase
        self._tmpdir = tempfile.mkdtemp()
        self.kb = KnowledgeBase(self._tmpdir)

    def teardown_method(self):
        self.kb.close()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_meta_does_not_contain_id(self):
        from core.knowledge.models import KnowledgeDoc
        doc = KnowledgeDoc(domain="test", title="T", content="Hello world document content", meta={"type": "ref"})
        self.kb.add(doc)
        retrieved = self.kb.get(doc.id)
        assert "id" not in retrieved.meta
        assert retrieved.meta["type"] == "ref"

    def test_meta_roundtrip_through_save_load(self):
        from core.knowledge.models import KnowledgeDoc
        from core.knowledge.knowledge_base import KnowledgeBase
        doc = KnowledgeDoc(domain="t", title="D", content="hello world", meta={"type": "ref", "level": "beginner"})
        self.kb.add(doc)
        self.kb.save()

        kb2 = KnowledgeBase(self._tmpdir)
        kb2.load()
        doc2 = kb2.get(doc.id)
        assert doc2 is not None
        assert doc2.meta == {"type": "ref", "level": "beginner"}
        kb2.close()

    def test_chunking_long_document(self):
        from core.knowledge.models import KnowledgeDoc
        long_text = "hello world " * 5000
        doc = KnowledgeDoc(domain="test", title="Long Doc", content=long_text, meta={"type": "ref"})
        ids = self.kb.add(doc)
        assert len(ids) >= 2
        for i, cid in enumerate(ids):
            chunk = self.kb.get(cid)
            assert chunk is not None
            assert "chunk_of" in chunk.meta
            assert chunk.meta["chunk_index"] == i
            assert chunk.meta["chunk_total"] == len(ids)

    def test_short_document_not_chunked(self):
        from core.knowledge.models import KnowledgeDoc
        doc = KnowledgeDoc(domain="test", title="Short", content="hello world", meta={"type": "ref"})
        ids = self.kb.add(doc)
        assert len(ids) == 1
        chunk = self.kb.get(ids[0])
        assert "chunk_of" not in chunk.meta

    def test_knowledge_add_tool_handles_chunking(self):
        from core.knowledge.tools import knowledge_add
        import json
        long_text = "hello world " * 5000
        result = json.loads(knowledge_add(self.kb, domain="test", title="Long", content=long_text, meta={"type": "ref"}))
        assert result["status"] == "ok"
        assert "doc_ids" in result
        assert len(result["doc_ids"]) >= 2
