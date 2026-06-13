import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.registry import ToolRegistry
from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.tools import knowledge_query, knowledge_add, knowledge_update, knowledge_delete, knowledge_get


class TestKnowledgeToolRegistration:
    @classmethod
    def setup_class(cls):
        ToolRegistry().clear()
        cls.kb = KnowledgeBase(":memory:")

    def setup_method(self):
        ToolRegistry().clear()
        ToolRegistry().register(
            name="knowledge_query",
            schema={
                "name": "knowledge_query",
                "description": "搜索静态知识库。语义/关键词搜索文档。",
            },
            handler=lambda args, context: knowledge_query(self.kb, **args),
            toolset="knowledge",
        )
        ToolRegistry().register(
            name="knowledge_add",
            schema={
                "name": "knowledge_add",
                "description": "新增文档到静态知识库。",
            },
            handler=lambda args, context: knowledge_add(self.kb, **args),
            toolset="knowledge",
        )
        ToolRegistry().register(
            name="knowledge_update",
            schema={
                "name": "knowledge_update",
                "description": "更新静态知识库文档。",
            },
            handler=lambda args, context: knowledge_update(self.kb, **args),
            toolset="knowledge",
        )
        ToolRegistry().register(
            name="knowledge_delete",
            schema={
                "name": "knowledge_delete",
                "description": "删除静态知识库文档。",
            },
            handler=lambda args, context: knowledge_delete(self.kb, **args),
            toolset="knowledge",
        )
        ToolRegistry().register(
            name="knowledge_get",
            schema={
                "name": "knowledge_get",
                "description": "获取静态知识库文档。",
            },
            handler=lambda args, context: knowledge_get(self.kb, **args),
            toolset="knowledge",
        )

    def test_all_five_knowledge_tools_registered(self):
        definitions = ToolRegistry().get_definitions()
        names = [d["name"] for d in definitions]
        assert "knowledge_query" in names
        assert "knowledge_add" in names
        assert "knowledge_update" in names
        assert "knowledge_delete" in names
        assert "knowledge_get" in names

    def test_dispatch_knowledge_query(self):
        from core.knowledge.models import KnowledgeDoc
        self.kb.add(KnowledgeDoc(domain="test", title="Doc", content="searchable text"))
        result = ToolRegistry().dispatch("knowledge_query", {"query": "searchable"}, context={})
        data = json.loads(result)
        assert len(data["results"]) >= 1

    def test_dispatch_knowledge_add(self):
        result = ToolRegistry().dispatch("knowledge_add",
            {"domain": "x", "title": "T", "content": "C"}, context={})
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "doc_id" in data
