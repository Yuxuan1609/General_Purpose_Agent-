"""Integration tests for the Capability system (T0-T4).

Tests cover: CapabilityRegistry, ToolCapability, KnowledgeCapability,
LayerInjector, and LearningEnv consolidation monitoring.
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

import pytest

from capability import (
    Capability, CapabilityResult, CapabilityRegistry,
)
from capability.tool_capability import ToolCapability, DEFAULT_TOOL_ALLOWLIST
from capability.knowledge_capability import (
    KnowledgeCapability, InMemoryKnowledgeStore, BaseKnowledgeStore,
    seed_knowledge_stores,
)
from capability.layer_injector import LayerInjector


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def registry():
    return CapabilityRegistry()


@pytest.fixture
def knowledge_store():
    s = InMemoryKnowledgeStore()
    s.add("doc1", "Leduc Hold'em is a 2-player poker variant with K/Q/J cards.")
    s.add("doc2", "Pre-flop strategy: with K always raise, with J usually fold.")
    s.add("doc3", "Post-flop strategy: pair your hand card with the public card.")
    return s


@pytest.fixture
def knowledge_cap(knowledge_store):
    return KnowledgeCapability(stores={
        "game_rules": (knowledge_store, {"l1", "l2", "l3"}),
        "secret": (knowledge_store, {"l3"}),  # l1/l2 can't see this
    })


@pytest.fixture
def tool_registry_with_todo():
    """Minimal ToolRegistry with one registered tool for testing."""
    from core.tools.registry import ToolRegistry
    # Reset singleton to a fresh instance for test isolation
    ToolRegistry._instance = None
    reg = ToolRegistry()

    def todo_handler(args=None, context=None):
        todos = (args or {}).get("todos", [])
        if todos:
            return json.dumps({"success": True, "todos": todos})
        return json.dumps({"todos": []})

    reg.register("todo", {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Track subtasks",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
    }, todo_handler, toolset="core")
    return reg


@pytest.fixture
def injector(registry, knowledge_cap, tool_registry_with_todo):
    tool_cap = ToolCapability(tool_registry_with_todo)
    registry.register(tool_cap)
    registry.register(knowledge_cap)
    return LayerInjector(registry)


# ═══════════════════════════════════════════════════════════════════════════
# T0: CapabilityRegistry
# ═══════════════════════════════════════════════════════════════════════════

class _MockCap(Capability):
    name = "mock"
    visible_layers = {"l2", "l3"}

    def get_schema(self):
        return {"type": "function", "function": {"name": "mock_func"}}

    def is_visible_to(self, layer):
        return layer in self.visible_layers

    def invoke(self, layer, args):
        return CapabilityResult(
            capability_name="mock", layer=layer, success=True,
            data={"echo": args},
        )


class TestCapabilityRegistry:
    def test_register_and_query(self, registry):
        registry.register(_MockCap())
        assert registry.get("mock") is not None

    def test_register_duplicate_raises(self, registry):
        registry.register(_MockCap())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_MockCap())

    def test_get_schemas_for_layer_visible(self, registry):
        cap = _MockCap()
        registry.register(cap)
        schemas = registry.get_schemas_for_layer("l2")
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "mock_func"

    def test_get_schemas_for_layer_hidden(self, registry):
        registry.register(_MockCap())
        schemas = registry.get_schemas_for_layer("l1")
        assert len(schemas) == 0

    def test_invoke_success(self, registry):
        registry.register(_MockCap())
        result = registry.invoke("mock", "l2", {"key": "val"})
        assert result.success
        assert result.data == {"echo": {"key": "val"}}

    def test_invoke_not_found(self, registry):
        result = registry.invoke("nonexistent", "l1", {})
        assert not result.success
        assert "not found" in result.error

    def test_list_for_layer(self, registry):
        registry.register(_MockCap())
        assert registry.list_for_layer("l2") == ["mock"]
        assert registry.list_for_layer("l1") == []


# ═══════════════════════════════════════════════════════════════════════════
# T1: ToolCapability
# ═══════════════════════════════════════════════════════════════════════════

class TestToolCapability:
    def test_is_visible_to_l1(self, tool_registry_with_todo):
        cap = ToolCapability(tool_registry_with_todo)
        assert cap.is_visible_to("l1")  # L1 can see todo

    def test_allowed_l1_only_todo(self, tool_registry_with_todo):
        cap = ToolCapability(tool_registry_with_todo)
        assert cap.allowed_tools("l1") == {"todo"}

    def test_invoke_allowed(self, tool_registry_with_todo):
        cap = ToolCapability(tool_registry_with_todo)
        result = cap.invoke("l1", {"name": "todo", "args": {}})
        assert result.success

    def test_invoke_denied(self, tool_registry_with_todo):
        cap = ToolCapability(tool_registry_with_todo)
        result = cap.invoke("l1", {"name": "terminal", "args": {}})
        assert not result.success
        assert "not allowed" in result.error.lower()

    def test_get_schemas_by_layer_returns_tool_list(self, tool_registry_with_todo):
        cap = ToolCapability(tool_registry_with_todo)
        schemas = cap.get_schemas_by_layer("l1")
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "todo"

    def test_default_allowlist_structure(self, tool_registry_with_todo):
        cap = ToolCapability(tool_registry_with_todo)
        assert "l1" in DEFAULT_TOOL_ALLOWLIST
        assert "l2" in DEFAULT_TOOL_ALLOWLIST
        assert "l3" in DEFAULT_TOOL_ALLOWLIST
        assert "todo" in DEFAULT_TOOL_ALLOWLIST["l1"]


# ═══════════════════════════════════════════════════════════════════════════
# T2: KnowledgeCapability + InMemoryKnowledgeStore
# ═══════════════════════════════════════════════════════════════════════════

class TestInMemoryKnowledgeStore:
    def test_add_and_get(self, knowledge_store):
        doc = knowledge_store.get("doc1")
        assert doc is not None
        assert "Leduc" in doc["content"]

    def test_search_keyword(self, knowledge_store):
        results = knowledge_store.search("pre-flop K raise")
        assert len(results) > 0
        assert any("raise" in r["content"].lower() for r in results)

    def test_search_no_match(self, knowledge_store):
        results = knowledge_store.search("banana monkey nonexistent")
        assert len(results) == 0

    def test_search_top_k(self, knowledge_store):
        results = knowledge_store.search("strategy flop pre", top_k=2)
        assert len(results) <= 2

    def test_remove(self, knowledge_store):
        assert knowledge_store.remove("doc1")
        assert knowledge_store.get("doc1") is None

    def test_remove_nonexistent(self, knowledge_store):
        assert not knowledge_store.remove("nonexistent")

    def test_list_ids(self, knowledge_store):
        ids = knowledge_store.list_ids()
        assert "doc1" in ids
        assert len(ids) == 3

    def test_len(self, knowledge_store):
        assert len(knowledge_store) == 3


class TestKnowledgeCapability:
    def test_invoke_search(self, knowledge_cap):
        result = knowledge_cap.invoke("l2", {
            "store": "game_rules", "query": "pre-flop K raise",
        })
        assert result.success
        assert len(result.data) > 0

    def test_invoke_store_not_visible(self, knowledge_cap):
        result = knowledge_cap.invoke("l2", {
            "store": "secret", "query": "anything",
        })
        assert not result.success
        assert "not visible" in result.error.lower()

    def test_invoke_unknown_store(self, knowledge_cap):
        result = knowledge_cap.invoke("l1", {
            "store": "nonexistent", "query": "anything",
        })
        assert not result.success
        assert "Unknown store" in result.error

    def test_is_visible_to(self, knowledge_cap):
        assert knowledge_cap.is_visible_to("l1")
        assert knowledge_cap.is_visible_to("l3")

    def test_visible_stores(self, knowledge_cap):
        visible = knowledge_cap.visible_stores("l1")
        assert "game_rules" in visible
        assert "secret" not in visible

    def test_get_schema(self, knowledge_cap):
        schema = knowledge_cap.get_schema()
        assert schema["function"]["name"] == "knowledge_query"
        assert "store" in schema["function"]["parameters"]["properties"]


class TestSeedKnowledgeStores:
    def test_returns_stores(self):
        stores = seed_knowledge_stores()
        assert "game_rules" in stores
        assert "design_docs" in stores
        assert len(stores["game_rules"]) == 3
        assert len(stores["design_docs"]) == 4


# ═══════════════════════════════════════════════════════════════════════════
# T3: LayerInjector
# ═══════════════════════════════════════════════════════════════════════════

class TestLayerInjector:
    def test_get_tools_for_layer_l1(self, injector, tool_registry_with_todo):
        tools = injector.get_tools_for_layer("l1")
        tool_names = {t["function"]["name"] for t in tools}
        assert "todo" in tool_names
        assert "knowledge_query" in tool_names

    def test_get_tools_for_layer_l3_has_more(self, injector):
        tools = injector.get_tools_for_layer("l3")
        tool_names = {t["function"]["name"] for t in tools}
        assert "todo" in tool_names
        assert "knowledge_query" in tool_names

    def test_inject_to_agent_adds_tools(self, injector):
        call_kwargs = {"system": "sys", "user": "usr"}
        result = injector.inject_to_agent("l2", call_kwargs)
        assert "tools" in result
        assert len(result["tools"]) > 0

    def test_inject_to_agent_no_tools_for_none_layer(self, injector):
        call_kwargs = {"system": "sys", "user": "usr"}
        result = injector.inject_to_agent("unknown", call_kwargs)
        assert "tools" not in result

    def test_handle_tool_calls_knowledge_query(self, injector):
        tool_calls = [{
            "function": {
                "name": "knowledge_query",
                "arguments": json.dumps({
                    "store": "game_rules",
                    "query": "pre-flop strategy",
                }),
            },
        }]
        results = injector.handle_tool_calls("l2", tool_calls)
        assert len(results) == 1
        assert results[0].success
        assert len(results[0].data) > 0

    def test_handle_tool_calls_todo(self, injector):
        tool_calls = [{
            "function": {
                "name": "todo",
                "arguments": json.dumps({
                    "todos": [{"id": "1", "content": "test task"}],
                }),
            },
        }]
        results = injector.handle_tool_calls("l2", tool_calls)
        assert len(results) == 1
        assert results[0].success

    def test_handle_tool_calls_invalid_json(self, injector):
        tool_calls = [{
            "function": {
                "name": "knowledge_query",
                "arguments": "not valid json {{{",
            },
        }]
        results = injector.handle_tool_calls("l2", tool_calls)
        assert len(results) == 1
        assert not results[0].success
        assert "Invalid JSON" in results[0].error

    def test_format_results_for_prompt(self, injector):
        results = [
            CapabilityResult(
                capability_name="knowledge_query", layer="l2",
                success=True, data=[
                    {"id": "doc1", "content": "strategy tip 1", "score": 2},
                ],
            ),
            CapabilityResult(
                capability_name="todo", layer="l2",
                success=False, error="not allowed",
            ),
        ]
        formatted = injector.format_results_for_prompt(results)
        assert "[工具调用结果]" in formatted
        assert "strategy tip 1" in formatted
        assert "ERROR" in formatted


# ═══════════════════════════════════════════════════════════════════════════
# T4: LearningEnv Consolidation
# ═══════════════════════════════════════════════════════════════════════════

class TestLearningEnvConsolidation:
    def test_needs_consolidation_l2_over_limit(self):
        """When L2 cards exceed limit, needs_consolidation returns True."""
        from unittest.mock import MagicMock
        l2 = MagicMock()
        l2.cards = list(range(35))  # 35 cards, > default 30 limit
        knowledge = {"l2": l2}
        from core.env.learning_env import LearningEnv
        lenv = LearningEnv(Path("."), knowledge, dry_run=True)
        assert lenv.needs_consolidation()

    def test_needs_consolidation_l3_over_limit(self):
        """When L3 skills exceed limit, needs_consolidation returns True."""
        from unittest.mock import MagicMock
        l3 = MagicMock()
        l3.list_all.return_value = list(range(25))  # 25 skills, > default 20
        knowledge = {"l3": l3}
        from core.env.learning_env import LearningEnv
        lenv = LearningEnv(Path("."), knowledge, dry_run=True)
        assert lenv.needs_consolidation()

    def test_needs_consolidation_no(self):
        """When under limits, needs_consolidation returns False."""
        from unittest.mock import MagicMock
        l2 = MagicMock()
        l2.cards = list(range(5))
        l3 = MagicMock()
        l3.list_all.return_value = list(range(5))
        knowledge = {"l2": l2, "l3": l3}
        from core.env.learning_env import LearningEnv
        lenv = LearningEnv(Path("."), knowledge, dry_run=True)
        assert not lenv.needs_consolidation()

    def test_needs_consolidation_custom_limits(self):
        """Custom limits are respected."""
        from unittest.mock import MagicMock
        l2 = MagicMock()
        l2.cards = list(range(15))  # 15 > custom limit 10
        from core.env.learning_env import LearningEnv
        lenv = LearningEnv(
            Path("."), {"l2": l2}, dry_run=True,
            l2_card_limit=10,
        )
        assert lenv.needs_consolidation()

    def test_get_consolidation_level_mild(self):
        """1-5 items over limit → level 1."""
        from unittest.mock import MagicMock
        l2 = MagicMock()
        l2.cards = list(range(33))  # 3 over
        from core.env.learning_env import LearningEnv
        lenv = LearningEnv(Path("."), {"l2": l2}, dry_run=True)
        assert lenv.get_consolidation_level() == 1

    def test_get_consolidation_level_deep(self):
        """>5 items over limit → level 2."""
        from unittest.mock import MagicMock
        l2 = MagicMock()
        l2.cards = list(range(40))  # 10 over
        from core.env.learning_env import LearningEnv
        lenv = LearningEnv(Path("."), {"l2": l2}, dry_run=True)
        assert lenv.get_consolidation_level() == 2

    def test_get_consolidation_level_none(self):
        """No overflow → level 0."""
        from unittest.mock import MagicMock
        l2 = MagicMock()
        l2.cards = list(range(5))
        l3 = MagicMock()
        l3.list_all.return_value = list(range(5))
        from core.env.learning_env import LearningEnv
        lenv = LearningEnv(Path("."), {"l2": l2, "l3": l3}, dry_run=True)
        assert lenv.get_consolidation_level() == 0
