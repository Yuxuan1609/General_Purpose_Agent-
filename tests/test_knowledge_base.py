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
