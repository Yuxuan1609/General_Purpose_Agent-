from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field


@dataclass
class FunctionCall:
    name: str
    arguments: str = "{}"


@dataclass
class ToolCall:
    id: str
    function: FunctionCall


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    def __init__(self, client, model: str):
        self._client = client
        self.model = model
        self.thinking_enabled = False
        self._prompt_tokens = 0
        self._completion_tokens = 0

    @property
    def total_tokens(self) -> int:
        return self._prompt_tokens + self._completion_tokens

    def reset_token_counts(self) -> None:
        self._prompt_tokens = 0
        self._completion_tokens = 0

    def chat(self, messages: list, tools: list | None = None,
             json_mode: bool = False, **kwargs) -> LLMResponse:
        params = {"model": self.model, "messages": messages}
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        if getattr(self, "thinking_enabled", False):
            extra = params.setdefault("extra_body", {})
            thinking = extra.setdefault("thinking", {})
            thinking["type"] = "enabled"
            if hasattr(self, "thinking_effort"):
                thinking["effort"] = self.thinking_effort
        params.update(kwargs)
        if tools:
            params["tools"] = [
                {"type": "function", "function": fn}
                if isinstance(fn := t.get("function") if isinstance(t, dict) else None, dict)
                else t
                for t in tools
                if isinstance(t, dict)
            ]
        try:
            resp = self._client.chat.completions.create(**params)
        except Exception as e:
            logging.getLogger("llm_client").warning(
                "LLM API call failed: %s", e)
            return LLMResponse(
                text=json.dumps({"error": f"LLM API error: {e}"}),
                tool_calls=[],
            )
        msg = resp.choices[0].message
        usage = getattr(resp, "usage", None)
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        self._prompt_tokens += prompt_tokens
        self._completion_tokens += completion_tokens
        raw_calls = msg.tool_calls or []
        tool_calls = [
            ToolCall(
                id=getattr(tc, "id", ""),
                function=FunctionCall(
                    name=tc.function.name,
                    arguments=getattr(tc.function, "arguments", "{}"),
                ),
            )
            for tc in raw_calls
        ]
        return LLMResponse(
            text=msg.content or "",
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
