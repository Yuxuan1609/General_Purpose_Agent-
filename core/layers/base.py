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

    def __init__(self, llm_client, log: logging.Logger):
        self._llm = llm_client
        self._log = log
        self._injector = None  # set externally after construction
        from core.config_loader import get_section
        self._max_tool_turns = get_section('runtime', default={}).get('max_tool_turns', 5)

    def set_injector(self, injector):
        """Attach a LayerInjector for tool calling capability."""
        self._injector = injector

    def set_context(self, ctx) -> None:
        self._context = ctx

    def _get_tools(self, layer: str) -> list[dict] | None:
        """Return tools for the given layer, filtered by per-layer allowlist
        (tools.yaml → injector) then per-env policy (ctx → AgentContext)."""
        if self._injector is None:
            return None
        getter = getattr(self._injector, "get_tools_for_layer", None)
        if getter is None:
            return None
        tools = getter(layer)
        if not tools:
            return None
        ctx = getattr(self, '_context', None)
        if ctx is not None:
            tools = ctx.resolve(tools)
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

        for turn in range(1, self._max_tool_turns + 1):
            self._log.debug("  ── turn %d/%d (messages=%d) ──", turn, self._max_tool_turns, len(messages))
            resp = self._llm.chat(
                messages=messages,
                json_mode=use_json_mode,
                tools=tools,
            )

            if resp.has_tool_calls and self._injector and layer:
                tool_names = [tc.function.name for tc in resp.tool_calls]
                self._log.debug("  ├─ tool_calls (%d): %s", len(tool_names), ", ".join(tool_names))
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

                # Split by sync param
                sync_batch = []
                async_calls = []
                for tc in executable_calls:
                    try:
                        raw_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        raw_args = {}
                    sync = raw_args.get("sync", True)
                    if sync:
                        sync_batch.append(tc)
                    else:
                        async_calls.append(tc)

                # Process async calls — submit to TaskRunner
                if async_calls:
                    from core.task_runner import get_task_runner
                    runner = get_task_runner()
                    for tc in async_calls:
                        name = tc.function.name
                        args_json = tc.function.arguments
                        self._log.debug("  ├─ async : %s(%s) id=%s",
                                       name, args_json[:400], tc.id)
                        def _make_async_exec(_inj, _l, _n, _a):
                            def _exec():
                                return _inj.execute_tool_call(_l, _n, _a)
                            return _exec
                        exec_fn = _make_async_exec(self._injector, layer, name, args_json)
                        tid = runner.submit(name, exec_fn)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({"task_id": tid, "status": "running"}),
                        })

                # Process sync calls — parallel batch
                if sync_batch:
                    from core.task_runner import get_task_runner
                    runner = get_task_runner()
                    batch = []
                    batch_timeout = 30
                    for tc in sync_batch:
                        inj = self._injector
                        l = layer
                        n = tc.function.name
                        a = tc.function.arguments
                        try:
                            call_args = json.loads(a) if a else {}
                        except json.JSONDecodeError:
                            call_args = {}
                        call_timeout = call_args.get("timeout", 0)
                        if call_timeout > batch_timeout:
                            batch_timeout = call_timeout
                        self._log.debug("  ├─ call  : %s(%s) id=%s",
                                       n, a[:400], tc.id)
                        def _make_exec(_inj, _l, _n, _a):
                            def _exec():
                                return _inj.execute_tool_call(_l, _n, _a)
                            return _exec
                        batch.append({
                            "id": tc.id,
                            "tool": n,
                            "exec": _make_exec(inj, l, n, a),
                        })

                    outcomes = runner.run_sync_batch(batch, timeout=batch_timeout)
                    for outcome in outcomes:
                        tc_id = outcome["id"]
                        if outcome["success"]:
                            raw = outcome["data"]
                            result_content = raw.data
                            result_str = str(raw.data.get("result", "")
                                             if isinstance(raw.data, dict)
                                             else raw.data)[:800]
                            self._log.debug("  └─ result (success=%s, id=%s): %s",
                                           raw.success, tc_id, str(result_str)[:800])
                        else:
                            result_content = outcome["data"]
                            result_str = outcome.get("error", "unknown error")
                            self._log.warning("  └─ result (error, id=%s): %s",
                                             tc_id, result_str)
                        serialized = json.dumps(result_content, ensure_ascii=False)
                        self._log.debug("     → role:tool content (%d chars): %s",
                                       len(serialized), serialized[:500])
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": serialized,
                        })

                if async_calls:
                    pending_text = f"[Pending async tasks: {len(async_calls)}. Use collect_tasks to retrieve results.]"
                    messages.append({"role": "system", "content": pending_text})

                continue  # next turn

            # No tool calls → final answer
            text = resp.text if hasattr(resp, 'text') else str(resp)
            self._log.debug("  ── final answer (turn %d, messages=%d) ──\n%s",
                           turn, len(messages), _indent(text[:500], 4))

            if capture_tools or schema is None:
                return {"done": True, "reply": text, "result": text, "reasoning": "", "_raw": text}
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

        # Max turns exceeded — give LLM one final chance to summarize from accumulated tool results
        self._log.warning("Max tool call turns (%d) exceeded, messages=%d — asking for summary",
                         self._max_tool_turns, len(messages))
        try:
            messages.append({"role": "user", "content": "[系统] 你已达到工具调用次数上限，不可以再调用工具。请基于对话中已获取的信息，直接以纯文本形式给出最终答案。"})
            resp = self._llm.chat(messages=messages, json_mode=False, tools=None)
            text = resp.text if hasattr(resp, 'text') else str(resp)
            self._log.debug("  ── forced summary (messages=%d) ──\n%s",
                           len(messages), _indent(text[:800], 4))
            if capture_tools:
                return {"done": True, "reply": text, "result": text, "reasoning": ""}
            if schema is None:
                return {"reply": text, "reasoning": ""}
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
                return {"_raw": text, "_type": type(parsed).__name__}
            except json.JSONDecodeError:
                from core.json_repair import robust_parse
                repaired = robust_parse(text, schema)
                if repaired:
                    return repaired
                return {"_raw": text}
        except Exception as e:
            self._log.warning("Final summary call also failed: %s", e)
            return {"_raw": "max_tool_turns", "_error": f"tool call loop exceeded: {e}"}


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
