import pytest
import json
from pathlib import Path
from core.philosophy import Philosophy, Rule, L1Proposal
from core.task import LearningUnit, Domain


@pytest.fixture
def rules_path(temp_dir):
    p = temp_dir / "l1_rules.json"
    p.write_text(json.dumps({"version": 1, "rules": []}))
    return p

@pytest.fixture
def philosophy(rules_path):
    return Philosophy(rules_path, max_rules=20, max_rule_length=100)


class TestPhilosophy:
    def test_add_rule(self, philosophy):
        rule = philosophy.add_rule("test rule content", created_by="test")
        assert rule.id is not None
        assert rule.content == "test rule content"
        assert rule.created_by == "test"

    def test_all_rules(self, philosophy):
        philosophy.add_rule("rule 1", created_by="test")
        philosophy.add_rule("rule 2", created_by="test")
        assert len(philosophy.all_rules()) == 2

    def test_get_active_rules_returns_all(self, philosophy):
        philosophy.add_rule("rule A", created_by="test")
        philosophy.add_rule("rule B", created_by="test")
        task = LearningUnit(description="test", domain=Domain("general", "general"))
        active = philosophy.get_active_rules(task)
        assert len(active) == 2

    def test_modify_rule(self, philosophy):
        rule = philosophy.add_rule("original content", created_by="test")
        modified = philosophy.modify_rule(rule.id, "modified content")
        assert modified.version == 2
        assert modified.content == "modified content"

    def test_remove_rule(self, philosophy):
        rule = philosophy.add_rule("to be removed", created_by="test")
        philosophy.remove_rule(rule.id)
        assert len(philosophy.all_rules()) == 0

    def test_apply_proposal(self, philosophy):
        proposal = L1Proposal(content="new rule from reflection", reason="test")
        philosophy.apply(proposal)
        rules = philosophy.all_rules()
        assert any(r.content == "new rule from reflection" for r in rules)

    def test_persists_to_disk(self, rules_path):
        p = Philosophy(rules_path, max_rules=20, max_rule_length=100)
        p.add_rule("persistent rule", created_by="test")
        p2 = Philosophy(rules_path, max_rules=20, max_rule_length=100)
        assert len(p2.all_rules()) == 1
        assert p2.all_rules()[0].content == "persistent rule"

    def test_max_rule_length_enforced(self, philosophy):
        with pytest.raises(ValueError):
            philosophy.add_rule("x" * 101, created_by="test")
