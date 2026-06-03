from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class FunctionCall:
    name: str
    arguments: str = "{}"


@dataclass
class ToolCall:
    function: FunctionCall


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMClient:
    def __init__(self, client, model: str):
        self._client = client
        self.model = model

    def chat(self, messages: list, tools: list | None = None,
             json_mode: bool = False, **kwargs) -> LLMResponse:
        params = {"model": self.model, "messages": messages}
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        params.update(kwargs)
        if tools:
            params["tools"] = [
                {"type": "function", "function": t["function"]}
                if isinstance(t, dict) and "function" in t else t
                for t in tools
            ]
        resp = self._client.chat.completions.create(**params)
        msg = resp.choices[0].message
        raw_calls = msg.tool_calls or []
        tool_calls = [
            ToolCall(function=FunctionCall(
                name=tc.function.name,
                arguments=getattr(tc.function, "arguments", "{}"),
            ))
            for tc in raw_calls
        ]
        return LLMResponse(
            text=msg.content or "",
            tool_calls=tool_calls,
        )
