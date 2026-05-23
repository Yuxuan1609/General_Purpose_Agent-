import pytest
from unittest.mock import MagicMock
from core.meta_driver import (
    MetaDriver, ReflectionTrigger, TriggerType, ValidationRule,
    DEFAULT_TRIGGERS, DEFAULT_VALIDATORS,
)
from core.task import Task, TaskContext, Domain
from core.philosophy import L1Proposal


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.chat.return_value.text = '{"completed": true, "efficient": true, "knowledge_to_create": [], "l1_proposals": []}'
    return llm


@pytest.fixture
def meta(mock_llm):
    return MetaDriver(triggers=DEFAULT_TRIGGERS, validation_rules=DEFAULT_VALIDATORS, auxiliary_llm=mock_llm)


class TestReflectionTrigger:
    def test_rule_trigger_fires(self):
        trigger = ReflectionTrigger(
            id="test", trigger_type=TriggerType.RULE, condition_desc="test",
            rule_check=lambda ctx: ctx.consecutive_no_progress >= 3,
            llm_prompt=None, cooldown_rounds=1,
        )
        ctx = TaskContext(task=Task("test"))
        ctx.consecutive_no_progress = 3
        assert trigger.evaluate(ctx) is True

    def test_rule_trigger_does_not_fire(self):
        trigger = ReflectionTrigger(
            id="test", trigger_type=TriggerType.RULE, condition_desc="test",
            rule_check=lambda ctx: ctx.consecutive_no_progress >= 3,
            llm_prompt=None, cooldown_rounds=1,
        )
        ctx = TaskContext(task=Task("test"))
        ctx.consecutive_no_progress = 1
        assert trigger.evaluate(ctx) is False

    def test_cooldown_prevents_firing(self):
        trigger = ReflectionTrigger(
            id="test", trigger_type=TriggerType.RULE, condition_desc="test",
            rule_check=lambda ctx: True, llm_prompt=None, cooldown_rounds=5,
        )
        ctx = TaskContext(task=Task("test"))
        ctx.rounds = 0
        assert trigger.evaluate(ctx) is True
        assert trigger.evaluate(ctx) is False


class TestMetaDriver:
    def test_evaluate_triggers_rule_type(self, meta):
        ctx = TaskContext(task=Task("test"))
        ctx.consecutive_no_progress = 5
        triggered = meta.evaluate_triggers(ctx)
        assert any(t.id == "stagnation" for t in triggered)

    def test_evaluate_triggers_task_failed(self, meta):
        ctx = TaskContext(task=Task("test"))
        ctx.eval_result = "failure"
        triggered = meta.evaluate_triggers(ctx)
        assert any(t.id == "task_failed" for t in triggered)

    def test_validate_l1_change_rejects_duplicate(self):
        meta = MetaDriver(DEFAULT_TRIGGERS, DEFAULT_VALIDATORS, None)
        existing = [MagicMock(content="be careful")]
        proposal = L1Proposal(content="be careful", reason="test")
        approved, reason = meta.validate_l1_change(proposal, existing)
        assert approved is False

    def test_validate_l1_change_rejects_over_limit(self):
        meta = MetaDriver(DEFAULT_TRIGGERS, DEFAULT_VALIDATORS, None, max_rules=2)
        existing = [MagicMock(content="r1"), MagicMock(content="r2")]
        proposal = L1Proposal(content="r3", reason="test")
        approved, reason = meta.validate_l1_change(proposal, existing)
        assert approved is False
        assert "上限" in reason

    def test_filter_dangerous_removes_blocked(self, meta):
        tc1 = MagicMock()
        tc1.function.name = "safe_tool"
        tc2 = MagicMock()
        tc2.function.name = "unsafe_delete_all"
        meta.dangerous_tool_patterns = ["delete_all"]
        filtered = meta.filter_dangerous([tc1, tc2])
        assert len(filtered) == 1
        assert filtered[0].function.name == "safe_tool"

    def test_check_completion_done(self, meta):
        task = Task("test")
        messages = [{"role": "assistant", "content": "done"}]
        assert meta.check_completion(task, messages) == "done"

    def test_check_completion_continue_with_tool_calls(self, meta):
        task = Task("test")
        messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]}]
        assert meta.check_completion(task, messages) == "continue"
