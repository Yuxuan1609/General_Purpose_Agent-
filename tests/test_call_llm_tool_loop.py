"""Tests for LayerAgent._call_llm tool-loop edge cases (Issues #3, #5, #8)."""
import logging
from unittest.mock import MagicMock, patch

import pytest

from capability import CapabilityResult
from core.layers.base import LayerAgent
from core.llm_client import LLMResponse, ToolCall, FunctionCall


class _ConcreteAgent(LayerAgent):
    def decide(self, **kwargs):
        return {}


def _make_agent():
    llm = MagicMock()
    agent = _ConcreteAgent(llm, logging.getLogger("test_call_llm"))
    agent.set_injector(MagicMock())
    agent._drain_pending_async = MagicMock()
    return agent


def _tc(tid, name, args):
    return ToolCall(id=tid, function=FunctionCall(name=name, arguments=args))


class TestCaptureWithExecutable:
    """Issue #3: when LLM emits [executable, capture] in the same turn,
    the executable must be executed (side effects + results recorded) before
    the capture result is returned. Previously capture hit returned early and
    the executable was silently dropped."""

    def test_executable_runs_before_capture_return(self):
        agent = _make_agent()
        agent._llm.chat.return_value = LLMResponse(
            text="",
            tool_calls=[
                _tc("t1", "l1_query",
                    '{"queries":[{"query":"q"}],"reasoning":"r"}'),
                _tc("t2", "l1_report",
                    '{"done":true,"result":"final","reasoning":"rr"}'),
            ],
        )
        agent._injector.execute_tool_call.return_value = CapabilityResult(
            capability_name="tool", layer="l1", success=True,
            data={"result": "query done"},
        )

        result = agent._call_llm(
            system="s", user="u",
            tools=[{"function": {"name": "l1_query"}}],
            layer="l1", capture_tools={"l1_report"},
        )

        executed = [c.args[1] for c in agent._injector.execute_tool_call.call_args_list]
        assert "l1_query" in executed
        assert result.get("_capture_tool") == "l1_report"
        assert result.get("done") is True

    def test_capture_only_still_returns_parsed(self):
        agent = _make_agent()
        agent._llm.chat.return_value = LLMResponse(
            text="",
            tool_calls=[
                _tc("t1", "l1_report",
                    '{"done":true,"result":"final","reasoning":"rr"}'),
            ],
        )

        result = agent._call_llm(
            system="s", user="u",
            tools=[{"function": {"name": "l1_report"}}],
            layer="l1", capture_tools={"l1_report"},
        )

        assert result.get("_capture_tool") == "l1_report"
        assert result.get("done") is True
        agent._injector.execute_tool_call.assert_not_called()


class TestDownwardAsyncPendingReminder:
    """Issue #5: in the downward path, async tasks are dispatched to the
    runner but the 'Pending async tasks / use collect_tasks' system reminder
    was never appended (async_calls list only filled in the non-downward
    branch). LLM never gets reminded to harvest them."""

    def test_downward_async_appends_pending_reminder(self):
        agent = _make_agent()
        runner = MagicMock()
        runner.submit.return_value = "task-1"
        agent._injector.execute_tool_call.return_value = CapabilityResult(
            capability_name="tool", layer="l1", success=True, data={"result": "ok"},
        )
        agent._llm.chat.side_effect = [
            LLMResponse(text="", tool_calls=[
                _tc("t1", "l1_query",
                    '{"queries":[{"query":"q"}],"reasoning":"r"}'),
                _tc("t2", "web_search", '{"query":"x","sync":false}'),
            ]),
            LLMResponse(text="final answer", tool_calls=[]),
        ]

        with patch("core.task_runner.get_shared_runner", return_value=runner):
            agent._call_llm(
                system="s", user="u",
                tools=[{"function": {"name": "l1_query"}},
                       {"function": {"name": "web_search"}}],
                layer="l1",
            )

        runner.submit.assert_called_once()
        second_messages = agent._llm.chat.call_args_list[1].kwargs["messages"]
        reminders = [m for m in second_messages
                     if m.get("role") == "system"
                     and "collect_tasks" in m.get("content", "")]
        assert len(reminders) == 1


class TestCaptureDrainNotDuplicated:
    """Issue #8: on capture-tool JSON parse failure, _drain_pending_async was
    called twice (once before parse, once after). Should be called once."""

    def test_drain_called_once_on_parse_failure(self):
        agent = _make_agent()
        agent._llm.chat.return_value = LLMResponse(
            text="",
            tool_calls=[_tc("t1", "l1_report", "{not valid json")],
        )

        result = agent._call_llm(
            system="s", user="u",
            tools=[{"function": {"name": "l1_report"}}],
            layer="l1", capture_tools={"l1_report"},
        )

        assert agent._drain_pending_async.call_count == 1
        assert result.get("_capture_tool") == "l1_report"

    def test_drain_called_once_on_parse_success(self):
        agent = _make_agent()
        agent._llm.chat.return_value = LLMResponse(
            text="",
            tool_calls=[_tc("t1", "l1_report",
                            '{"done":true,"result":"x","reasoning":"r"}')],
        )

        agent._call_llm(
            system="s", user="u",
            tools=[{"function": {"name": "l1_report"}}],
            layer="l1", capture_tools={"l1_report"},
        )

        assert agent._drain_pending_async.call_count == 1
