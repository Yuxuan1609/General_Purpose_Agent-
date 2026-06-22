"""Test kb_modify / kb_delete handlers via ToolRegistry.dispatch."""
import json
import shutil
import tempfile
import pytest

from core.tools.registry import ToolRegistry
from core.knowledge.knowledge_base import KnowledgeBase
from core.knowledge.models import KnowledgeDoc
import core.tools.kb_tools as kb_tools


class TestKbModify:
    @classmethod
    def setup_class(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cls._kb = KnowledgeBase(cls._tmpdir)
        cls._registry = ToolRegistry()
        cls._registry.clear()
        cls._registry.register(
            "kb_modify",
            kb_tools._KB_SCHEMAS.get("kb_modify", {}),
            kb_tools._kb_modify_handler,
            toolset="core",
        )

    @classmethod
    def teardown_class(cls):
        cls._kb.close()
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setup_method(self):
        kb_tools._kb_instance = self._kb

    def teardown_method(self):
        kb_tools._kb_instance = None

    def test_modify_title(self):
        doc = KnowledgeDoc(domain="test/d", title="Before", content="content")
        self._kb.add(doc)
        self._kb.save()
        result = json.loads(self._registry.dispatch("kb_modify", {
            "doc_id": doc.id, "title": "After",
        }))
        assert result["status"] == "ok"
        assert self._kb.get(doc.id).title == "After"

    def test_modify_content(self):
        doc = KnowledgeDoc(domain="test/d", title="Title", content="old content")
        self._kb.add(doc)
        self._kb.save()
        result = json.loads(self._registry.dispatch("kb_modify", {
            "doc_id": doc.id, "content": "new content",
        }))
        assert result["status"] == "ok"
        assert self._kb.get(doc.id).content == "new content"

    def test_modify_domain(self):
        doc = KnowledgeDoc(domain="test/a", title="Title", content="content")
        self._kb.add(doc)
        self._kb.save()
        result = json.loads(self._registry.dispatch("kb_modify", {
            "doc_id": doc.id, "domain": "test/b",
        }))
        assert result["status"] == "ok"
        assert self._kb.get(doc.id).domain == "test/b"

    def test_modify_multiple_fields(self):
        doc = KnowledgeDoc(domain="test/d", title="Old Title", content="Old")
        self._kb.add(doc)
        self._kb.save()
        result = json.loads(self._registry.dispatch("kb_modify", {
            "doc_id": doc.id,
            "title": "New Title",
            "content": "New",
            "domain": "test/e",
        }))
        assert result["status"] == "ok"
        assert set(result["updated"]) == {"title", "content", "domain"}
        updated = self._kb.get(doc.id)
        assert updated.title == "New Title"
        assert updated.content == "New"
        assert updated.domain == "test/e"

    def test_empty_doc_id_error(self):
        result = json.loads(self._registry.dispatch("kb_modify", {
            "doc_id": "", "title": "X",
        }))
        assert result["status"] == "error"
        assert "empty doc_id" in result["reason"]

    def test_not_found(self):
        result = json.loads(self._registry.dispatch("kb_modify", {
            "doc_id": "nonexistent", "title": "X",
        }))
        assert result["status"] == "not_found"

    def test_no_fields_returns_ok_note(self):
        doc = KnowledgeDoc(domain="test/d", title="Title", content="content")
        self._kb.add(doc)
        self._kb.save()
        result = json.loads(self._registry.dispatch("kb_modify", {
            "doc_id": doc.id,
        }))
        assert result["status"] == "ok"
        assert "no fields" in result["note"]

    def test_empty_strings_ignored(self):
        doc = KnowledgeDoc(domain="test/d", title="Before", content="content")
        self._kb.add(doc)
        self._kb.save()
        result = json.loads(self._registry.dispatch("kb_modify", {
            "doc_id": doc.id, "title": "", "content": "real",
        }))
        assert result["status"] == "ok"
        assert self._kb.get(doc.id).title == "Before"


class TestKbDelete:
    @classmethod
    def setup_class(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cls._kb = KnowledgeBase(cls._tmpdir)
        cls._registry = ToolRegistry()
        cls._registry.clear()
        cls._registry.register(
            "kb_delete",
            kb_tools._KB_SCHEMAS.get("kb_delete", {}),
            kb_tools._kb_delete_handler,
            toolset="core",
        )

    @classmethod
    def teardown_class(cls):
        cls._kb.close()
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setup_method(self):
        kb_tools._kb_instance = self._kb

    def teardown_method(self):
        kb_tools._kb_instance = None

    def test_delete_existing_doc(self):
        doc = KnowledgeDoc(domain="test/d", title="Title", content="content")
        self._kb.add(doc)
        self._kb.save()
        result = json.loads(self._registry.dispatch("kb_delete", {
            "doc_id": doc.id,
        }))
        assert result["status"] == "ok"
        assert self._kb.get(doc.id) is None

    def test_delete_empty_id_error(self):
        result = json.loads(self._registry.dispatch("kb_delete", {
            "doc_id": "",
        }))
        assert result["status"] == "error"
        assert "empty doc_id" in result["reason"]

    def test_delete_not_found(self):
        result = json.loads(self._registry.dispatch("kb_delete", {
            "doc_id": "nonexistent",
        }))
        assert result["status"] == "not_found"

    def test_delete_returns_title(self):
        doc = KnowledgeDoc(domain="test/d", title="My Title", content="content")
        self._kb.add(doc)
        self._kb.save()
        result = json.loads(self._registry.dispatch("kb_delete", {
            "doc_id": doc.id,
        }))
        assert result["status"] == "ok"
        assert result["title"] == "My Title"
