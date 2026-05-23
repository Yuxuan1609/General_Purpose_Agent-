import pytest
from unittest.mock import MagicMock
from core.layer_context import LayerContext
from core.task import Task, Domain, TaskResult


@pytest.fixture
def mock_layers():
    meta = MagicMock()
    meta.filter_dangerous.return_value = [MagicMock()]
    meta.evaluate_triggers.return_value = []
    meta.run_reflection.return_value = MagicMock(knowledge_updates=[], l1_proposals=[])
    meta.validate_l1_change.return_value = (True, "")
    meta.check_completion.return_value = "done"
    meta.task_decompose_trigger.return_value = []

    l1 = MagicMock()
    l1.get_active_rules.return_value = ["rule1", "rule2"]
    l1.all_rules.return_value = [MagicMock(content="rule1"), MagicMock(content="rule2")]
    l1.apply.return_value = None

    l2 = MagicMock()
    l2.get_active_cards.return_value = [
        MagicMock(id="card_001", content="test knowledge", domain=Domain("textworld/map_A", "specific"), confidence=0.9, activation=0.85)
    ]
    l2.update_from_tool_results.return_value = None
    l2.apply_updates.return_value = None
    l2.get_domain_cards.return_value = [MagicMock(activation=0.8)]

    l3 = MagicMock()
    l3.match.return_value = [MagicMock(name="test-skill")]
    l3.should_create_skill.return_value = False

    return LayerContext(meta=meta, l1=l1, l2=l2, l3=l3)


class TestLayerContext:
    def test_build_context_includes_l1_rules(self, mock_layers):
        task = Task("test", Domain("textworld/map_A", "specific"))
        context = mock_layers.build_context(task)
        assert "rule1" in context
        assert "rule2" in context

    def test_build_context_includes_l2_cards(self, mock_layers):
        task = Task("test", Domain("textworld/map_A", "specific"))
        context = mock_layers.build_context(task)
        assert "test knowledge" in context

    def test_build_context_includes_l3_skills(self, mock_layers):
        task = Task("test", Domain("textworld/map_A", "specific"))
        context = mock_layers.build_context(task)
        assert "test-skill" in context

    def test_build_context_empty(self, mock_layers):
        mock_layers.l1.get_active_rules.return_value = []
        mock_layers.l2.get_active_cards.return_value = []
        mock_layers.l3.match.return_value = []
        task = Task("test", Domain("general", "general"))
        context = mock_layers.build_context(task)
        assert context == ""

    def test_filter_tool_calls(self, mock_layers):
        calls = [MagicMock(), MagicMock()]
        mock_layers.meta.filter_dangerous.return_value = calls[:1]
        result = mock_layers.filter_tool_calls(calls)
        assert len(result) == 1

    def test_post_task_no_triggers(self, mock_layers):
        task = Task("test", Domain("general", "general"))
        result = mock_layers.post_task(task, [])
        assert isinstance(result, TaskResult)
        assert result.new_knowledge_cards == 0
