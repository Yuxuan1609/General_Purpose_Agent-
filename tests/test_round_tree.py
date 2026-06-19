"""Tests for RoundTree thread-local node stack (B-1)."""
import pytest
from core.round_tree import DecisionNode, current_node, push_node, pop_node


class TestNodeStack:
    def test_empty_stack_returns_none(self):
        assert current_node() is None

    def test_push_then_current(self):
        node = DecisionNode(layer="l0_5_1", query="q", result="r", reasoning="")
        push_node(node)
        assert current_node() is node
        pop_node()

    def test_pop_returns_pushed(self):
        node = DecisionNode(layer="l2", query="q", result="r", reasoning="")
        push_node(node)
        popped = pop_node()
        assert popped is node
        assert current_node() is None

    def test_nested_push_pop_lifo(self):
        n1 = DecisionNode(layer="l0_5_1", query="q1", result="r1", reasoning="")
        n2 = DecisionNode(layer="l2", query="q2", result="r2", reasoning="")
        push_node(n1)
        push_node(n2)
        assert current_node() is n2
        assert pop_node() is n2
        assert current_node() is n1
        assert pop_node() is n1
        assert current_node() is None

    def test_pop_empty_returns_none(self):
        assert pop_node() is None

    def test_append_child_to_current(self):
        parent = DecisionNode(layer="l0_5_1", query="q", result="r", reasoning="")
        child = DecisionNode(layer="l2", query="cq", result="cr", reasoning="")
        push_node(parent)
        push_node(child)
        pop_node()
        parent.children.append(child)
        assert len(parent.children) == 1
        assert parent.children[0] is child
        pop_node()
