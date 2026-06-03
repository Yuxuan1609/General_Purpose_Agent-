import pytest
from pathlib import Path
from core.types import TaskObservation
from core.task import Domain
from core.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def clear_registry():
    ToolRegistry().clear()
    yield


@pytest.fixture
def l3_skill_layer(tmp_path):
    from core.skill_layer import SkillLayer
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return SkillLayer(skills_dir, ToolRegistry())


class TestL3Manager:
    def test_process_adds_skills_to_meta(self, l3_skill_layer, tmp_path):
        from core.layers.l3.manager import L3Manager

        # Create a skill first
        domain = Domain("game/doudizhu", "specific")
        l3_skill_layer.create_skill(
            name="test-skill",
            content="---\nname: test-skill\ndescription: A test skill\ndomain: game/doudizhu\n---\n# Test",
            domain=domain,
        )

        manager = L3Manager(l3_skill_layer)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert "l3_skills" in obs.meta
        assert result["status"] == "ok"

    def test_process_handles_no_match(self, l3_skill_layer):
        from core.layers.l3.manager import L3Manager

        manager = L3Manager(l3_skill_layer)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert result["status"] == "ok"
        assert obs.meta["l3_skills"] == []

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


@pytest.fixture
def l0_5_meta():
    from core.meta_driver import MetaDriver, DEFAULT_TRIGGERS, DEFAULT_VALIDATORS
    return MetaDriver(
        triggers=DEFAULT_TRIGGERS.copy(),
        validation_rules=DEFAULT_VALIDATORS.copy(),
        auxiliary_llm=None,
    )


class TestL0_5_1Manager:
    def test_process_adds_rules_to_meta(self, l0_5_meta, l1_philosophy):
        l1_philosophy.add_rule("面对不确定信息时优先搜索验证", created_by="test")

        manager = L0_5_1Manager(l0_5_meta, l1_philosophy, auxiliary_llm=None)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert "l1_rules" in obs.meta
        assert len(obs.meta["l1_rules"]) >= 1
        assert result["status"] == "ok"

    def test_process_no_rules(self, l0_5_meta, l1_philosophy):
        manager = L0_5_1Manager(l0_5_meta, l1_philosophy, auxiliary_llm=None)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert result["status"] == "ok"
        assert obs.meta["l1_rules"] == []

    def test_notify_returns_payload(self, l0_5_meta, l1_philosophy):
        manager = L0_5_1Manager(l0_5_meta, l1_philosophy, auxiliary_llm=None)
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
    def test_process_adds_cards_to_meta(self, l2_knowledge):
        from core.task import Domain
        domain = Domain("game/doudizhu", "specific")
        card = l2_knowledge.add_card(
            content="地主上家应优先出单张",
            domain=domain,
            confidence=0.8,
            source="observation",
        )
        card.activation = 0.9

        manager = L2Manager(l2_knowledge)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert "l2_cards" in obs.meta
        assert len(obs.meta["l2_cards"]) >= 1
        assert result["status"] == "ok"

    def test_process_no_cards(self, l2_knowledge):
        manager = L2Manager(l2_knowledge)
        obs = TaskObservation(meta={"domain": "game/doudizhu"})
        result = manager.process(obs)

        assert result["status"] == "ok"
        assert obs.meta["l2_cards"] == []

    def test_notify_returns_payload(self, l2_knowledge):
        manager = L2Manager(l2_knowledge)
        payload = manager.notify()
        assert "status" in payload
        assert payload["layer"] == "l2"
