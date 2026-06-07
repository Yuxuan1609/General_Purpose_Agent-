from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from core.layer_message import LayerMessage
from core.layers.comm import UpwardComm, DownwardComm


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return prefix + text.replace("\n", "\n" + prefix)


class LayerAgent(ABC):
    """Common base for all layer LLM agents.

    Provides _call_llm() with DeepSeek JSON mode + full prompt/response logging.
    Supports multi-turn tool calls via DeepSeek-compatible role:"tool" messages.

    Output is always a parsed JSON dict.
    """

    MAX_TOOL_TURNS = 5  # safety limit per _call_llm invocation

    def __init__(self, llm_client, log: logging.Logger):
        self._llm = llm_client
        self._log = log
        self._injector = None  # set externally after construction

    def set_injector(self, injector):
        """Attach a LayerInjector for tool calling capability."""
        self._injector = injector

    def _call_llm(self, system: str, user: str,
                  schema: dict | None = None,
                  tools: list[dict] | None = None,
                  layer: str = "") -> dict:
        """Call LLM, return parsed JSON dict.

        When tools are provided, enables multi-turn tool call loop:
          LLM → tool_calls → execute → role:tool → LLM → ... → final content.

        DeepSeek compatibility:
          - Uses role:"tool" messages for tool results (not text injection)
          - Disables json_mode when tools are present (incompatible)
          - Preserves tool_call_id for result routing

        Args:
            system: System prompt
            user: User prompt
            schema: JSON schema for structured output (via prompt, not json_mode if tools present)
            tools: OpenAI function-calling tool schemas (from LayerInjector)
            layer: Calling layer identifier ("l1"/"l2"/"l3")
        """
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        if schema:
            schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
            if tools:
                # Cannot use json_mode with tools — inject schema into system prompt
                messages[0]["content"] = (
                    f"{system}\n\n"
                    f"请以 JSON 格式输出，严格遵循以下结构：\n"
                    f"```json\n{schema_text}\n```"
                )
            else:
                messages[0]["content"] = (
                    f"{system}\n\n"
                    f"请以 JSON 格式输出，严格遵循以下结构：\n"
                    f"```json\n{schema_text}\n```"
                )

        self._log.debug("  ── system ──\n%s", _indent(str(messages[0]["content"]), 4))
        self._log.debug("  ── user ──\n%s", _indent(str(messages[1]["content"]), 4))

        # Only use json_mode when no tools (DeepSeek incompatibility)
        use_json_mode = bool(schema) and not tools

        for turn in range(1, self.MAX_TOOL_TURNS + 1):
            resp = self._llm.chat(
                messages=messages,
                json_mode=use_json_mode,
                tools=tools,  # send tools every turn (DeepSeek supports multi-turn tools)
            )

            if resp.has_tool_calls and self._injector and layer:
                # Append assistant message with tool_calls
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": resp.text or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in resp.tool_calls
                    ],
                }
                messages.append(assistant_msg)

                # Execute tools and append role:"tool" messages
                for tc in resp.tool_calls:
                    raw = self._injector.execute_tool_call(
                        layer, tc.function.name,
                        tc.function.arguments,
                    )
                    self._log.debug("  tool %s → %s", tc.function.name,
                                   str(raw)[:120])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(
                            raw.data if raw.success else {"error": raw.error},
                            ensure_ascii=False,
                        ),
                    })
                continue  # next turn

            # No tool calls → final answer
            text = resp.text if hasattr(resp, 'text') else str(resp)
            self._log.debug("  response (turn %d):\n%s", turn, _indent(text, 4))

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                self._log.warning("JSON parse failed, raw text returned")
                return {"_raw": text}

        # Max turns exceeded
        self._log.warning("Max tool call turns (%d) exceeded", self.MAX_TOOL_TURNS)
        return {"_raw": "max_tool_turns", "_error": "tool call loop exceeded"}


class LayerManager(ABC):
    """Abstract base for all layer Manager agents.

    Each Manager:
      - process(data) → enriches data with its layer's information → returns status
      - notify() → returns this layer's NOTIFY payload (business dict)
      - query() → handles LayerMessage QUERY chain top-down (uses Comm Agents)
      - collect_notify() → gathers NOTIFY payloads bottom-up

    Manager only deals with business dicts. Comm Agents handle LayerMessage wrapping.
    """

    def __init__(self, name: str, downstream: LayerManager | None = None,
                 upward: UpwardComm | None = None,
                 downward: DownwardComm | None = None):
        self.name = name
        self._downstream = downstream
        self._upward = upward or UpwardComm()
        self._downward = downward or DownwardComm()

    @abstractmethod
    def process(self, data: Any) -> dict:
        """Enrich data with this layer's information.

        Returns a dict with status info.
        Must update `data` in-place with layer-specific fields.
        """
        ...

    @abstractmethod
    def notify(self) -> Any:
        """Return the payload for this layer's NOTIFY to the Executor."""
        ...

    def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
        """Entry point: unpack LayerMessage, process, propagate downstream.

        Accepts LayerMessage (from Executor or upper layer) or raw dict
        (backward compat). If LayerMessage, unpacks via UpwardComm.
        """
        if isinstance(msg, LayerMessage):
            data = self._upward.receive(msg)
            if not trace_id:
                trace_id = msg.trace_id
        else:
            data = msg

        self.process(data)

        if self._downstream:
            q_msg = self._downward.wrap_query(
                payload=data,
                source=self.name,
                target=self._downstream.name,
                trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)

    def collect_notify(self) -> dict:
        """Collect NOTIFY payloads from this layer and all downstream.

        Returns business dicts: {layer_name: notify_payload, ...}
        """
        result: dict = {}
        result[self.name] = self.notify()
        if self._downstream:
            result.update(self._downstream.collect_notify())
        return result
