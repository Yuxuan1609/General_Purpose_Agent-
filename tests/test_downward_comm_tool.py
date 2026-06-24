"""Tests for downward_comm_tool (B-2): l1_query/l2_query as regular tools."""
import json
import pytest
from unittest.mock import MagicMock, patch

from core.round_tree import DecisionNode, push_node, pop_node, current_node
from core.tools.downward_comm_tool import (
    set_layer_downstreams, register_downward_tools, _downstreams
)
from core.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def reset_downstreams():
    set_layer_downstreams({})
    yield
    set_layer_downstreams({})


def _make_mock_downstream(name="l2", reply="L2 reply", result="L2 result"):
    downstream = MagicMock()
    downstream.name = name
    downstream.collect_notify.return_value = {
        name: {"reply": reply, "result": result, "reasoning": "reason"},
    }
    return downstream


class TestSetLayerDownstreams:
    def test_sets_mapping(self):
        mock = _make_mock_downstream()
        set_layer_downstreams({"l1_query": mock})
        assert _downstreams["l1_query"] is mock

    def test_reset_clears(self):
        mock = _make_mock_downstream()
        set_layer_downstreams({"l1_query": mock})
        set_layer_downstreams({})
        assert "l1_query" not in _downstreams


class TestRegisterDownwardTools:
    def test_registers_l1_query_and_l2_query(self):
        registry = ToolRegistry()
        registry.clear()
        register_downward_tools(registry)
        defs = {d["function"]["name"] for d in registry.get_definitions()}
        assert "l1_query" in defs
        assert "l2_query" in defs


class TestL1QueryHandler:
    def test_unbound_downstream_returns_error(self):
        registry = ToolRegistry()
        registry.clear()
        register_downward_tools(registry)
        result = registry.dispatch("l1_query", {"queries": [{"query": "test"}], "reasoning": "r"})
        parsed = json.loads(result)
        assert "error" in parsed

    def test_calls_downstream_query_and_collect_notify(self):
        registry = ToolRegistry()
        registry.clear()
        mock = _make_mock_downstream("l2", reply="L2 answer")
        set_layer_downstreams({"l1_query": mock})
        register_downward_tools(registry)
        result = registry.dispatch("l1_query", {
            "queries": [{"query": "what cards for leduc?"}],
            "reasoning": "need L2 knowledge",
        })
        mock.query.assert_called_once()
        mock.collect_notify.assert_called_once()
        parsed = json.loads(result)
        assert "results" in parsed

    def test_multiple_queries(self):
        registry = ToolRegistry()
        registry.clear()
        mock = _make_mock_downstream("l2", reply="answer")
        set_layer_downstreams({"l1_query": mock})
        register_downward_tools(registry)
        result = registry.dispatch("l1_query", {
            "queries": [{"query": "q1"}, {"query": "q2"}],
            "reasoning": "r",
        })
        assert mock.query.call_count == 2
        parsed = json.loads(result)
        assert len(parsed["results"]) == 2


class TestL2QueryHandler:
    def test_calls_l3_downstream(self):
        registry = ToolRegistry()
        registry.clear()
        mock = _make_mock_downstream("l3", reply="L3 skill result")
        set_layer_downstreams({"l2_query": mock})
        register_downward_tools(registry)
        result = registry.dispatch("l2_query", {
            "queries_to_L3": [{"domain": "game/leduc", "task": "execute skill"}],
            "reasoning": "need L3 skill",
        })
        mock.query.assert_called_once()
        parsed = json.loads(result)
        assert "results" in parsed


class TestDownwardRoundTreeContinuity:
    """Issue #1: downward handler must run on caller's thread so the
    thread-local RoundTree node stack stays continuous and child nodes
    append to the parent (caller's current_node)."""

    def test_child_node_appends_to_parent_across_downward_call(self):
        parent = DecisionNode(layer="l0_5_1", query="q", result="", reasoning="")
        push_node(parent)
        try:
            captured_children = []

            def fake_query(obs):
                child = DecisionNode(layer="l2", query=obs.meta, result="r", reasoning="")
                push_node(child)
                pop_node()
                node = current_node()
                if node is not None:
                    node.children.append(child)
                captured_children.append(current_node())

            downstream = MagicMock()
            downstream.name = "l2"
            downstream.query.side_effect = fake_query
            downstream.collect_notify.return_value = {"l2": {"reply": "ok"}}

            set_layer_downstreams({"l1_query": downstream})
            registry = ToolRegistry()
            registry.clear()
            register_downward_tools(registry)

            registry.dispatch("l1_query", {
                "queries": [{"query": "what?"}],
                "reasoning": "r",
            })

            assert len(parent.children) == 1
            assert parent.children[0].layer == "l2"
        finally:
            pop_node()


class TestDownwardReasoningPropagation:
    """Issue #4: downstream reasoning must be propagated upward in the
    tool result so upper layers can see the chain of thought."""

    def test_result_includes_reasoning_from_downstream(self):
        downstream = _make_mock_downstream("l2", reply="answer", result="answer")
        downstream.collect_notify.return_value = {
            "l2": {"reply": "answer", "result": "answer", "reasoning": "because X"},
        }
        set_layer_downstreams({"l1_query": downstream})
        registry = ToolRegistry()
        registry.clear()
        register_downward_tools(registry)

        result = registry.dispatch("l1_query", {
            "queries": [{"query": "why?"}],
            "reasoning": "r",
        })
        parsed = json.loads(result)
        assert "results" in parsed
        assert parsed["results"][0]["reasoning"] == "because X"
