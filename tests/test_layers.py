import pytest
from pathlib import Path
from core.types import TaskObservation
from core.task import Domain


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
