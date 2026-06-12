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
