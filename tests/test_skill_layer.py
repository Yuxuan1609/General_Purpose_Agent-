import pytest
import json
from pathlib import Path
from core.skill_layer import SkillLayer, SkillMeta
from core.task import Domain
from core.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def clear_registry():
    """Isolate tests from each other since ToolRegistry is a singleton."""
    ToolRegistry().clear()
    yield

@pytest.fixture
def skill_registry():
    return ToolRegistry()

@pytest.fixture
def skill_layer(temp_dir, skill_registry):
    skills_dir = temp_dir / "skills"
    skills_dir.mkdir()
    (skills_dir / "general").mkdir()
    return SkillLayer(skills_dir, skill_registry)


class TestSkillLayer:
    def test_create_skill(self, skill_layer, skill_registry):
        content = """---
name: test-skill
description: "A test skill"
domain: general
cross_domain: true
version: 1.0.0
---
# Test Skill

## Procedure
1. Do something
"""
        meta = skill_layer.create_skill("test-skill", content, Domain("general", "general"))
        assert meta.name == "test-skill"
        assert meta.domain.path == "general"
        assert meta.cross_domain is True

        skill_file = skill_layer.skills_dir / "general" / "test-skill" / "SKILL.md"
        assert skill_file.exists()

    def test_list_all(self, skill_layer):
        content = """---
name: skill-a
description: "Skill A"
domain: general
cross_domain: false
version: 1.0.0
---
# A
"""
        skill_layer.create_skill("skill-a", content, Domain("general", "general"))
        skills = skill_layer.list_all()
        assert len(skills) == 1
        assert skills[0].name == "skill-a"

    def test_match_by_domain(self, skill_layer):
        content_g = """---
name: gen-skill
description: "General"
domain: general
cross_domain: true
version: 1.0.0
---
# G
"""
        skill_layer.create_skill("gen-skill", content_g, Domain("general", "general"))
        matches = skill_layer.match(Domain("textworld/map_A", "specific"))
        assert len(matches) >= 1
        assert any(s.name == "gen-skill" for s in matches)

    def test_match_exact_domain_preferred(self, skill_layer):
        content_tw = """---
name: tw-skill
description: "TextWorld"
domain: textworld
cross_domain: false
version: 1.0.0
---
# TW
"""
        content_gen = """---
name: gen-skill
description: "General"
domain: general
cross_domain: true
version: 1.0.0
---
# G
"""
        skill_layer.create_skill("tw-skill", content_tw, Domain("textworld", "general"))
        skill_layer.create_skill("gen-skill", content_gen, Domain("general", "general"))
        matches = skill_layer.match(Domain("textworld", "general"))
        assert matches[0].name == "tw-skill"

    def test_delete_skill_archives_not_deletes(self, skill_layer):
        content = """---
name: temp-skill
description: "Temp"
domain: general
cross_domain: false
version: 1.0.0
---
# T
"""
        skill_layer.create_skill("temp-skill", content, Domain("general", "general"))
        skill_layer.delete_skill("temp-skill")
        assert len(skill_layer.list_all()) == 0
        archive = skill_layer.skills_dir / ".archive" / "temp-skill"
        assert archive.exists()

    def test_tools_registered(self, skill_layer, skill_registry):
        defs = skill_registry.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "skills_list" in names
        assert "skill_view" in names
        assert "skill_manage" in names

    def test_tools_are_functional(self, skill_layer, skill_registry):
        content = """---
name: hello-skill
description: "Hello"
domain: general
cross_domain: false
version: 1.0.0
---
# Hello
"""
        skill_layer.create_skill("hello-skill", content, Domain("general", "general"))
        # Test skills_list
        list_result = json.loads(skill_registry.dispatch("skills_list", {}))
        assert len(list_result) >= 1
        assert any(s["name"] == "hello-skill" for s in list_result)
        # Test skill_view
        view_result = json.loads(skill_registry.dispatch("skill_view", {"name": "hello-skill"}))
        assert view_result.get("success") is True

    def test_get_skills_by_ids_from_registry(self, tmp_path):
        from core.domain_registry import DomainRegistry
        from core.task import Domain
        reg = DomainRegistry()
        reg.add_node("game/leduc", "game", "Leduc")
        sl = SkillLayer(tmp_path / "skills", ToolRegistry(), domain_registry=reg)
        sl.create_skill("test-skill", "desc", Domain("game/leduc", "specific"))
        ids = reg.get_primary_items("l3", "game/leduc")
        assert "test-skill" in ids
        skills = sl.get_skills_by_ids(ids)
        assert len(skills) == 1
        assert skills[0]["name"] == "test-skill"
