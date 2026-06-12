import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.models import KnowledgeDoc
from core.knowledge.tools import (
    knowledge_query, knowledge_add, knowledge_update,
    knowledge_delete, knowledge_sync_domain,
)


class TestKnowledgeIntegration:
    @classmethod
    def setup_class(cls):
        cls.kb = KnowledgeBase(":memory:")

    def test_agent_workflow_add_query_update_delete(self):
        r = json.loads(knowledge_add(self.kb, domain="game/leduc",
            title="Leduc Preflop Strategy",
            content="With a King (K), always raise. With a Jack (J), fold unless in position.",
            tags=["preflop", "strategy"]))
        assert r["status"] == "ok"
        doc_id = r["doc_id"]

        r = json.loads(knowledge_query(self.kb, query="King", domain="game/leduc"))
        assert len(r["results"]) >= 1
        assert "raise" in r["results"][0]["content"].lower()

        r = json.loads(knowledge_update(self.kb, doc_id=doc_id,
            content="With a King (K), always raise. With a Jack (J), fold. With a Queen (Q), call if pot is small."))
        assert r["status"] == "ok"

        doc = self.kb.get(doc_id)
        assert "Queen" in doc.content

        r = json.loads(knowledge_delete(self.kb, doc_id=doc_id))
        assert r["status"] == "ok"
        assert self.kb.get(doc_id) is None

    def test_domain_sync_during_agent_workflow(self):
        knowledge_add(self.kb, domain="coding/python", title="T1", content="C1")
        knowledge_add(self.kb, domain="coding/python", title="T2", content="C2")

        r = json.loads(knowledge_sync_domain(self.kb, action="rename",
            source_domain="coding/python", target_domain="coding/python_programming"))
        assert r["status"] == "ok"

        domains = self.kb.list_domains()
        paths = [d["path"] for d in domains]
        assert "coding/python_programming" in paths
        assert "coding/python" not in paths
