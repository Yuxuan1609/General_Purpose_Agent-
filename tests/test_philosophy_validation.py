import pytest
from pathlib import Path
from core.philosophy import Philosophy, L1Proposal


@pytest.fixture
def phil(tmp_path):
    rules_path = tmp_path / "l1_rules.json"
    return Philosophy(rules_path, max_rules=3, max_rule_length=100)


class TestPhilosophyValidation:
    def test_add_rule_rejects_duplicate(self, phil):
        phil.add_rule("be careful", created_by="test", source="l1")
        with pytest.raises(ValueError, match="not_duplicate"):
            phil.add_rule("be careful", created_by="test", source="l1")

    def test_add_rule_rejects_over_limit(self, phil):
        phil.add_rule("rule one", created_by="test", source="l1")
        phil.add_rule("rule two", created_by="test", source="l1")
        phil.add_rule("rule three", created_by="test", source="l1")
        with pytest.raises(ValueError, match="上限"):
            phil.add_rule("rule four", created_by="test", source="l1")

    def test_apply_proposal_adds_rule(self, phil):
        proposal = L1Proposal(content="new rule here", reason="test")
        rule = phil.apply(proposal)
        assert rule.content == "new rule here"
        assert len(phil.all_rules()) == 1

    def test_apply_duplicate_proposal_raises(self, phil):
        phil.add_rule("duplicate rule", created_by="test", source="l1")
        proposal = L1Proposal(content="duplicate rule", reason="test")
        with pytest.raises(ValueError, match="not_duplicate"):
            phil.apply(proposal)
