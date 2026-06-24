import pytest
from pathlib import Path
from unittest.mock import MagicMock

from core.types import TaskObservation
from core.task import Domain
from core.round_tree import DecisionNode, push_node, pop_node


@pytest.fixture
def l3_skill_layer(tmp_path):
    from core.skill_layer import SkillLayer
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return SkillLayer(skills_dir)


class TestL3Manager:
    def test_query_adds_skills_to_state(self, l3_skill_layer, tmp_path):
        from core.layers.l3.manager import L3Manager

        domain = Domain("game/doudizhu", "specific")
        l3_skill_layer.create_skill(
            name="test-skill",
            content="---\nname: test-skill\ndescription: A test skill\ndomain: game/doudizhu\n---\n# Test",
            domain=domain,
        )

        manager = L3Manager(l3_skill_layer)
        obs = TaskObservation(meta="game rules", session={"domain": "game/doudizhu"})
        manager.query(obs)

        assert len(manager._matched_skills) >= 1

    def test_query_handles_no_match(self, l3_skill_layer):
        from core.layers.l3.manager import L3Manager

        manager = L3Manager(l3_skill_layer)
        obs = TaskObservation(meta="game rules", state={}, session={"domain": "game/doudizhu"})
        manager.query(obs)

        assert manager._matched_skills == []

    def test_notify_returns_payload(self, l3_skill_layer):
        from core.layers.l3.manager import L3Manager

        manager = L3Manager(l3_skill_layer)
        payload = manager.notify()
        assert "status" in payload
        assert payload["layer"] == "l3"


from core.layers.l0_5_1.manager import L0_5_1Manager


@pytest.fixture
def l1_philosophy(tmp_path):
    from core.philosophy import Philosophy
    rules_path = tmp_path / "l1_rules.json"
    rules_path.write_text('{"version":1,"rules":[]}')
    return Philosophy(rules_path, max_rules=20, max_rule_length=100)


class TestL0_5_1Manager:
    def test_process_returns_status(self, l1_philosophy):
        manager = L0_5_1Manager(l1_philosophy, auxiliary_llm=None)
        obs = TaskObservation(meta="game rules", state={})
        result = manager.process(obs)
        assert result["status"] == "ok"

    def test_notify_returns_payload(self, l1_philosophy):
        manager = L0_5_1Manager(l1_philosophy, auxiliary_llm=None)
        payload = manager.notify()
        assert "status" in payload
        assert payload["layer"] == "l0_5_1"


from core.layers.l2.manager import L2Manager


@pytest.fixture
def l2_knowledge(tmp_path):
    from core.flexible_knowledge import FlexibleKnowledge
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    index_path = knowledge_dir / "l2_index.json"
    index_path.write_text('{"version":1,"chapters":[],"relations":[]}')
    fk = FlexibleKnowledge(knowledge_dir, index_path)
    return fk


class TestL2Manager:
    def test_process_returns_status(self, l2_knowledge):
        manager = L2Manager(l2_knowledge)
        obs = TaskObservation(meta="game rules", state={})
        result = manager.process(obs)
        assert result["status"] == "ok"

    def test_notify_returns_payload(self, l2_knowledge):
        manager = L2Manager(l2_knowledge)
        payload = manager.notify()
        assert "status" in payload
        assert payload["layer"] == "l2"


class TestL2ManagerRoundTreeAppend:
    """Issue #2: L2Manager.query must append l2_node to the parent
    (current_node) so the decision tree keeps the L1→L2→L3 structure."""

    def test_l2_node_appended_to_parent(self, l2_knowledge):
        manager = L2Manager(l2_knowledge)
        manager._agent = MagicMock()
        manager._agent.decide.return_value = {
            "done": True, "reply": "ans", "reasoning": "r", "selected_cards": [],
        }

        parent = DecisionNode(layer="l0_5_1", query="q", result="", reasoning="")
        push_node(parent)
        try:
            obs = TaskObservation(meta="query", state={})
            manager.query(obs)
            assert len(parent.children) == 1
            assert parent.children[0].layer == "l2"
        finally:
            pop_node()


from core.layers.l3.manager import L3Manager


class TestL3ManagerRoundTreeAppend:
    """Symmetry check: L3 already appends (Issue #2 references it as the
    correct pattern). Verifies it still appends to the parent node."""

    def test_l3_node_appended_to_parent(self, l3_skill_layer):
        manager = L3Manager(l3_skill_layer)
        manager._agent = MagicMock()
        manager._agent.decide.return_value = {
            "done": True, "result": "ans", "reasoning": "r", "skills_used": [],
        }

        parent = DecisionNode(layer="l2", query="q", result="", reasoning="")
        push_node(parent)
        try:
            obs = TaskObservation(meta="task", state={}, session={"domain": "general"})
            manager.query(obs)
            assert len(parent.children) == 1
            assert parent.children[0].layer == "l3"
        finally:
            pop_node()


class TestL3AgentDoneFallback:
    """Issue #6: L3Agent.decide normal mode must wrap a result lacking 'done'
    (e.g. capture-tool JSON parse failure returns {_raw, _capture_tool}) into
    a done=True payload, mirroring L1/L2 fallback."""

    def test_wraps_raw_result_without_done(self, l3_skill_layer):
        from core.layers.l3.manager import L3Agent
        agent = L3Agent(MagicMock(), skill_layer=l3_skill_layer)
        agent._call_llm = MagicMock(
            return_value={"_raw": "raw text", "_capture_tool": "l3_report"})

        result = agent.decide(
            meta="m", state={}, context={"matched_skills": [], "l3_task": ""})

        assert result.get("done") is True
        assert "raw text" in str(result.get("result", ""))

    def test_returns_original_when_done_present(self, l3_skill_layer):
        from core.layers.l3.manager import L3Agent
        agent = L3Agent(MagicMock(), skill_layer=l3_skill_layer)
        agent._call_llm = MagicMock(return_value={
            "done": True, "result": "ok", "reasoning": "r", "skills_used": ["s"]})

        result = agent.decide(
            meta="m", state={}, context={"matched_skills": [], "l3_task": ""})

        assert result["result"] == "ok"
        assert result["skills_used"] == ["s"]
