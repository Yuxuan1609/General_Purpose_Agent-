import pytest
from unittest.mock import MagicMock
from core.agent_loop import AgentLoop
from core.task import LearningUnit, Domain, TaskResult


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    tool_resp = MagicMock()
    tool_resp.has_tool_calls = True
    tool_resp.tool_calls = [MagicMock(function=MagicMock(name="skills_list"))]
    tool_resp.text = ""
    text_resp = MagicMock()
    text_resp.has_tool_calls = False
    text_resp.text = "Task completed."
    llm.chat.side_effect = [tool_resp, text_resp]
    return llm


@pytest.fixture
def mock_tools():
    registry = MagicMock()
    registry.schemas = []
    registry.dispatch.return_value = '[{"name": "test-skill"}]'
    return registry


@pytest.fixture
def mock_layers():
    layers = MagicMock()
    layers.build_context.return_value = "[L1 rules]\n- rule1"
    layers.filter_tool_calls.side_effect = lambda x: x
    layers.on_tool_results.return_value = None
    layers.check_completion.return_value = "done"
    layers.post_task.return_value = MagicMock(success=True, new_knowledge_cards=2, l1_changes=[], new_skills=[])
    layers.l1 = MagicMock()
    layers.l1.all_rules.return_value = [MagicMock(content="test rule")]
    layers.meta = MagicMock()
    layers.meta.reset_turn_state.return_value = None
    return layers


class TestAgentLoop:
    def test_run_returns_messages_and_result(self, mock_llm, mock_tools, mock_layers):
        mock_layers.check_completion.return_value = "done"
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=10)
        task = LearningUnit("test task", Domain("general", "general"))
        messages, result = loop.run(task)
        assert isinstance(messages, list)
        assert messages[0]["role"] == "system"
        assert result is not None
        assert mock_llm.chat.called
        assert mock_layers.build_context.called
        mock_layers.post_task.assert_not_called()

    def test_reflect_calls_post_task(self, mock_llm, mock_tools, mock_layers):
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=10)
        task = LearningUnit("test task", Domain("general", "general"))
        raw_result = TaskResult(success=True, eval_result="success", eval_score=0.9)
        result = loop.reflect(task, [], raw_result)
        mock_layers.post_task.assert_called_once()
        assert result.eval_result == "success"
        assert result.eval_score == 0.9

    def test_execute_and_reflect_convenience(self, mock_llm, mock_tools, mock_layers):
        mock_layers.check_completion.return_value = "done"
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=10)
        task = LearningUnit("test task", Domain("general", "general"))
        result = loop.execute_and_reflect(task)
        assert result is not None
        assert mock_llm.chat.called
        assert mock_layers.post_task.called

    def test_max_iterations_respected(self, mock_llm, mock_tools, mock_layers):
        tool_resp = MagicMock()
        tool_resp.has_tool_calls = True
        tool_resp.tool_calls = [MagicMock(function=MagicMock(name="skills_list"))]
        tool_resp.text = ""
        mock_llm.chat.return_value = tool_resp
        mock_layers.check_completion.return_value = "continue"

        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=3)
        task = LearningUnit("test", Domain("general", "general"))
        messages, raw_result = loop.run(task)
        assert mock_llm.chat.call_count == 3

    def test_system_prompt_includes_l1_rules(self, mock_llm, mock_tools, mock_layers):
        mock_layers.check_completion.return_value = "done"
        loop = AgentLoop(mock_llm, mock_tools, mock_layers, max_iterations=3)
        task = LearningUnit("test", Domain("general", "general"))
        loop.run(task)
        system_msg = mock_llm.chat.call_args_list[0][1]["messages"][0]
        assert system_msg["role"] == "system"
        assert "test rule" in system_msg["content"]
