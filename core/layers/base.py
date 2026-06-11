from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from core.layer_message import LayerMessage
from core.layers.comm import UpwardComm, DownwardComm


class DictInjector:
    """Lightweight tool injector — maps function names to handler callables."""

    def __init__(self, handlers: dict[str, callable]):
        self._handlers = handlers

    def execute_tool_call(self, layer: str, name: str, arguments_json: str):
        from dataclasses import dataclass

        @dataclass
        class _TR:
            success: bool
            data: dict
            error: str = ""

        handler = self._handlers.get(name)
        if handler is None:
            return _TR(success=False, data={}, error=f"Unknown: {name}")
        try:
            args = json.loads(arguments_json) if arguments_json else {}
            result = handler(args)
            return _TR(success=True, data={"result": result})
        except Exception as e:
            return _TR(success=False, data={}, error=str(e))


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
        self._pending_mods: list[dict] = []

    def get_pending_mods(self) -> list[dict]:
        mods = self._pending_mods.copy()
        self._pending_mods.clear()
        return mods

    def set_injector(self, injector):
        """Attach a LayerInjector for tool calling capability."""
        self._injector = injector

    def _get_tools(self, layer: str) -> list[dict] | None:
        """Return tools from injector for the given layer, if available."""
        if self._injector is None:
            return None
        getter = getattr(self._injector, "get_tools_for_layer", None)
        if getter is None:
            return None
        tools = getter(layer)
        return tools if tools else None

    def _call_llm(self, system: str, user: str,
                  schema: dict | None = None,
                  tools: list[dict] | None = None,
                  layer: str = "",
                  capture_tools: set[str] | None = None) -> dict:
        """Call LLM, return parsed JSON dict.

        When tools are provided, enables multi-turn tool call loop:
          LLM → tool_calls → execute → role:tool → LLM → ... → final content.

        capture_tools: Set of tool names treated as structured-output markers.
          When the LLM calls any of these tools, its arguments are returned
          directly as the result (with _capture_tool field), instead of
          executing the tool. Eliminates JSON-in-prompt schema injection.

        DeepSeek compatibility:
          - Uses role:"tool" messages for tool results (not text injection)
          - Disables json_mode when tools are present (incompatible)
          - Preserves tool_call_id for result routing
        """
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        if schema and not capture_tools:
            schema_text = json.dumps(schema, ensure_ascii=False, indent=2)
            messages[0]["content"] = (
                f"{system}\n\n"
                f"请以 JSON 格式输出，严格遵循以下结构：\n"
                f"```json\n{schema_text}\n```"
            )

        self._log.debug("  ── system ──\n%s", _indent(str(messages[0]["content"]), 4))
        self._log.debug("  ── user ──\n%s", _indent(str(messages[1]["content"]), 4))
        if tools:
            tool_names = [t["function"]["name"] for t in tools]
            self._log.debug("  ── tools: %s ──", ", ".join(tool_names))

        # json_mode only when no tools (DeepSeek incompatibility) and no capture_tools
        use_json_mode = bool(schema) and not tools and not capture_tools

        for turn in range(1, self.MAX_TOOL_TURNS + 1):
            resp = self._llm.chat(
                messages=messages,
                json_mode=use_json_mode,
                tools=tools,
            )

            if resp.has_tool_calls and self._injector and layer:
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

                # Split: capture tools vs executable tools
                executable_calls = []
                for tc in resp.tool_calls:
                    if capture_tools and tc.function.name in capture_tools:
                        self._log.debug("  ═══ capture tool '%s' (turn %d) ═══\n%s",
                                       tc.function.name, turn,
                                       _indent(tc.function.arguments, 4))
                        try:
                            parsed = json.loads(tc.function.arguments)
                            if isinstance(parsed, dict):
                                parsed["_capture_tool"] = tc.function.name
                                return parsed
                        except json.JSONDecodeError:
                            self._log.warning("capture_tool arguments not valid JSON")
                        return {"_raw": tc.function.arguments, "_capture_tool": tc.function.name}
                    executable_calls.append(tc)

                if not executable_calls:
                    continue  # all calls were captured

                # Execute remaining tools
                for tc in executable_calls:
                    raw = self._injector.execute_tool_call(
                        layer, tc.function.name,
                        tc.function.arguments,
                    )
                    # Defensive: raw.data may be dict or list depending on tool
                    result_str = ""
                    if raw.success:
                        if isinstance(raw.data, dict):
                            result_str = raw.data.get("result", "")
                        elif isinstance(raw.data, list):
                            result_str = json.dumps(raw.data, ensure_ascii=False)[:500]
                        else:
                            result_str = str(raw.data)
                    else:
                        result_str = raw.error
                    self._log.debug("  tool %s → %s", tc.function.name,
                                   str(result_str)[:120])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(
                            raw.data if raw.success else {"error": raw.error},
                            ensure_ascii=False,
                        ),
                    })
                continue  # next turn

            # No tool calls → final answer (fallback — shouldn't fire when capture_tools is set)
            text = resp.text if hasattr(resp, 'text') else str(resp)
            self._log.debug("  ═══ response (turn %d) ═══\n%s", turn, _indent(text, 4))

            if capture_tools or schema is None:
                return {"reply": text, "reasoning": ""}
            try:
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    self._log.warning("Expected JSON object, got %s", type(parsed).__name__)
                    return {"_raw": text, "_type": type(parsed).__name__}
                return parsed
            except json.JSONDecodeError:
                from core.json_repair import robust_parse
                self._log.debug("JSON parse failed, trying robust_parse")
                repaired = robust_parse(text, schema)
                if repaired:
                    return repaired
                self._log.warning("robust_parse also failed, returning raw")
                return {"_raw": text}

        # Max turns exceeded
        self._log.warning("Max tool call turns (%d) exceeded", self.MAX_TOOL_TURNS)
        return {"_raw": "max_tool_turns", "_error": "tool call loop exceeded"}


    @staticmethod
    def _schema_to_tool(name: str, description: str, schema: dict) -> dict:
        """Convert a JSON Schema dict to an OpenAI function-calling tool definition.

        The resulting tool can be passed to _call_llm with capture_tool=name
        so the LLM outputs structured data via tool_call arguments instead of
        raw JSON text embedded in markdown.
        """
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema,
            },
        }

    @abstractmethod
    def decide(self, **kwargs) -> dict:
        """Single decision step for Manager while-loop.

        Each layer Agent implements this with its own schema.
        Manager calls this in a while loop, checking `done` in return value.
        """
        ...


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
