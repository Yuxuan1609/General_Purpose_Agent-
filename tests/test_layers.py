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
