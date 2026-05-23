import pytest
from unittest.mock import MagicMock
from core.llm_client import LLMResponse, LLMClient, ToolCall, FunctionCall


class TestLLMResponse:
    def test_response_without_tool_calls(self):
        resp = LLMResponse(text="Hello", tool_calls=[])
        assert resp.has_tool_calls is False
        assert resp.text == "Hello"

    def test_response_with_tool_calls(self):
        tc = ToolCall(function=FunctionCall(name="search", arguments='{"q":"test"}'))
        resp = LLMResponse(text="", tool_calls=[tc])
        assert resp.has_tool_calls is True
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].function.name == "search"
        assert resp.tool_calls[0].function.arguments == '{"q":"test"}'

    def test_response_text_and_tool_calls(self):
        tc = ToolCall(function=FunctionCall(name="search", arguments="{}"))
        resp = LLMResponse(text="Let me search", tool_calls=[tc])
        assert resp.has_tool_calls is True
        assert resp.text == "Let me search"


class TestLLMClient:
    def test_chat_returns_llm_response(self):
        mock_openai = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = "response text"
        mock_msg.tool_calls = None
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=mock_msg)]
        )
        client = LLMClient(client=mock_openai, model="test-model")
        resp = client.chat(messages=[{"role": "user", "content": "hi"}])
        assert isinstance(resp, LLMResponse)
        assert resp.text == "response text"
        assert resp.has_tool_calls is False

    def test_chat_with_tools(self):
        mock_openai = MagicMock()
        mock_tc = MagicMock()
        mock_tc.function.name = "skills_list"
        mock_tc.function.arguments = '{}'
        mock_msg = MagicMock()
        mock_msg.content = ""
        mock_msg.tool_calls = [mock_tc]
        mock_openai.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=mock_msg)]
        )
        client = LLMClient(client=mock_openai, model="test-model")
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        resp = client.chat(messages=[], tools=tools)
        assert resp.has_tool_calls is True
        assert resp.tool_calls[0].function.name == "skills_list"
