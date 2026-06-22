import json
import pytest
from core.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _clear_registry():
    ToolRegistry().clear()
    ToolRegistry().clear_secondary()


class FakeLLMResponse:
    def __init__(self, text):
        self.text = text


class FakeLLM:
    def __init__(self, response_text):
        self._response_text = response_text

    def chat(self, messages, tools=None, json_mode=False, **kwargs):
        return FakeLLMResponse(self._response_text)


class TestActivateSecondaryTools:
    def test_handler_enables_matching_secondary_tools(self):
        from core.tools.secondary_tool import _activate_secondary_tools_handler, _set_llm_for_test

        r = ToolRegistry()
        r.register("douzero_encode_hand",
                   {"type": "function", "function": {"name": "douzero_encode_hand", "description": "", "parameters": {}}},
                   lambda args, **kw: "{}",
                   tool_spec="secondary",
                   semantic_description="将斗地主手牌编码为 DouZero 模型输入格式")
        r.register("web_fetch",
                   {"type": "function", "function": {"name": "web_fetch", "description": "", "parameters": {}}},
                   lambda args, **kw: "{}",
                   tool_spec="secondary",
                   semantic_description="抓取网页内容")
        r.clear_secondary()

        fake_llm = FakeLLM(json.dumps({"tools": [{"name": "douzero_encode_hand", "reason": "斗地主编码"}]}))
        _set_llm_for_test(fake_llm)

        result = _activate_secondary_tools_handler({"query": "我需要斗地主手牌编码工具"})
        data = json.loads(result)
        assert "douzero_encode_hand" in data["enabled"]
        assert data["total_candidates"] == 2

        defs = r.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "douzero_encode_hand" in names

    def test_handler_no_match_returns_empty(self):
        from core.tools.secondary_tool import _activate_secondary_tools_handler, _set_llm_for_test

        r = ToolRegistry()
        r.register("douzero_encode_hand",
                   {"type": "function", "function": {"name": "douzero_encode_hand", "description": "", "parameters": {}}},
                   lambda args, **kw: "{}",
                   tool_spec="secondary",
                   semantic_description="将斗地主手牌编码为 DouZero 模型输入格式")
        r.clear_secondary()

        fake_llm = FakeLLM(json.dumps({"tools": []}))
        _set_llm_for_test(fake_llm)

        result = _activate_secondary_tools_handler({"query": "我需要一个烹饪工具"})
        data = json.loads(result)
        assert data["enabled"] == []
        assert data["total_candidates"] == 1

    def test_handler_no_secondary_tools_returns_empty(self):
        from core.tools.secondary_tool import _activate_secondary_tools_handler, _set_llm_for_test

        r = ToolRegistry()
        r.clear_secondary()
        _set_llm_for_test(FakeLLM('{"tools": []}'))

        result = _activate_secondary_tools_handler({"query": "anything"})
        data = json.loads(result)
        assert data["enabled"] == []
        assert data["total_candidates"] == 0
