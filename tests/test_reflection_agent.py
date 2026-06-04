"""Tests for per-layer ReflectionAgent implementations."""
import pytest
from core.layers.l3.reflection_agent import L3ReflectionAgent
from core.layers.l2.reflection_agent import L2ReflectionAgent
from core.layers.l0_5_1.reflection_agent import L0_5_1ReflectionAgent
from core.layers.l3.manager import L3Manager
from core.layers.l2.manager import L2Manager
from core.layers.l0_5_1.manager import L0_5_1Manager


class _MockManager:
    """Mock LayerManager for ReflectionAgent tests."""
    def __init__(self, name="mock"):
        self.name = name
        self.updates = []

    def apply_update(self, key, value):
        self.updates.append((key, value))


class TestL3ReflectionAgent:
    def test_investigate_skill_issues_owned_by_l3(self):
        agent = L3ReflectionAgent("l3", _MockManager())
        issues = [
            {"type": "skill_mismatch", "skill_name": "s1"},
            {"type": "skill_missing", "skill_name": "s2"},
        ]
        result = agent.investigate(issues, {})
        assert len(result["my_issues"]) == 2
        assert len(result["downstream_issues"]) == 0

    def test_fix_applies_update(self):
        mgr = _MockManager()
        agent = L3ReflectionAgent("l3", mgr)
        issues = [{"type": "skill_missing", "skill_name": "test_skill",
                   "suggested_content": "new content"}]
        result = agent.fix(issues)
        assert result["fixes_applied"] == 1
        assert len(mgr.updates) == 1


class TestL2ReflectionAgent:
    def test_investigate_card_issues_owned_by_l2(self):
        agent = L2ReflectionAgent("l2", _MockManager())
        issues = [
            {"type": "card_confidence_low", "card_id": "c1"},
            {"type": "skill_mismatch"},
        ]
        result = agent.investigate(issues, {})
        assert len(result["my_issues"]) == 1
        assert len(result["downstream_issues"]) == 1

    def test_fix_penalize_card(self):
        mgr = _MockManager()
        agent = L2ReflectionAgent("l2", mgr)
        issues = [{"type": "card_confidence_low", "card_id": "c1"}]
        result = agent.fix(issues)
        assert result["fixes_applied"] == 1
        assert mgr.updates[0][0] == "penalize_card"

    def test_fix_boost_card(self):
        mgr = _MockManager()
        agent = L2ReflectionAgent("l2", mgr)
        issues = [{"type": "card_confidence_high", "card_id": "c2"}]
        result = agent.fix(issues)
        assert result["fixes_applied"] == 1
        assert mgr.updates[0][0] == "boost_card"


class TestL0_5_1ReflectionAgent:
    def test_investigate_rule_issues_owned_by_l1(self):
        agent = L0_5_1ReflectionAgent("l0_5_1", _MockManager())
        issues = [
            {"type": "rule_wrong", "suggested_content": "fix"},
            {"type": "card_confidence_low", "card_id": "c1"},
            {"type": "skill_mismatch"},
        ]
        result = agent.investigate(issues, {})
        assert len(result["my_issues"]) == 1
        assert len(result["downstream_issues"]) == 2

    def test_query_downstream_cascades(self):
        l3_agent = L3ReflectionAgent("l3", _MockManager())
        l2_agent = L2ReflectionAgent("l2", _MockManager(), downstream=l3_agent)
        l1_agent = L0_5_1ReflectionAgent("l0_5_1", _MockManager(), downstream=l2_agent)

        issues = [{"type": "skill_missing", "skill_name": "s1"}]
        # L1 → L2: L2 sends skill issues to downstream_issues
        l2_result = l2_agent.investigate(issues, {})
        assert len(l2_result["my_issues"]) == 0
        assert len(l2_result["downstream_issues"]) == 1
        # Then L2 → L3: L3 owns the skill issue
        l3_result = l2_agent.query_downstream(l2_result["downstream_issues"], {})
        assert len(l3_result["my_issues"]) == 1
        assert "skill_missing" in str(l3_result["my_issues"])
