from __future__ import annotations
import json
import logging
from typing import Any

from capability import CapabilityRegistry, CapabilityResult

logger = logging.getLogger(__name__)


class LayerInjector:
    """Inject capability schemas into layer Agent LLM calls and handle results.

    Usage pattern per stage:
        injector = LayerInjector(registry)
        tools = injector.get_tools_for_layer("l2")
        result = agent._call_llm(system, user, schema=schema, tools=tools)
        if result.get("_tool_calls"):
            handled = injector.handle_tool_calls("l2", result["_tool_calls"])
            # Merge handled results into next stage's user prompt.
    """

    def __init__(self, registry: CapabilityRegistry):
        self._registry = registry

    # ── schema injection ────────────────────────────────────────────────

    def get_tools_for_layer(self, layer: str) -> list[dict]:
        """Return all tool schemas visible to the given layer.

        Aggregates ToolCapability (per-tool schemas) + KnowledgeCapability
        (single knowledge_query schema).
        """
        tools: list[dict] = []

        tool_cap = self._registry.get("tool")
        if tool_cap is not None and tool_cap.is_visible_to(layer):
            tools.extend(tool_cap.get_schemas_by_layer(layer))

        knowledge_cap = self._registry.get("knowledge")
        if knowledge_cap is not None and knowledge_cap.is_visible_to(layer):
            tools.append(knowledge_cap.get_schema())

        return tools

    def inject_to_agent(self, layer: str, call_kwargs: dict) -> dict:
        """Add 'tools' field to LLM call kwargs for the given layer.

        Called before LayerAgent._call_llm():
            call_kwargs = {"system": ..., "user": ..., "json_mode": True}
            self._injector.inject_to_agent("l2", call_kwargs)
            resp = self._llm.chat(**call_kwargs)
        """
        tools = self.get_tools_for_layer(layer)
        if tools:
            call_kwargs["tools"] = tools
        return call_kwargs

    # ── single tool call execution (for _call_llm multi-turn loop) ───

    def execute_tool_call(self, layer: str, name: str,
                          raw_args: str | dict) -> CapabilityResult:
        """Execute a single tool call during _call_llm's multi-turn loop.

        Args:
            layer: Calling layer.
            name: Function name from LLM tool_call.
            raw_args: JSON string or dict of function arguments.

        Returns:
            CapabilityResult ready for role:"tool" message content.
        """
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                return CapabilityResult(
                    capability_name=name, layer=layer, success=False,
                    error=f"Invalid JSON arguments: {raw_args[:100]}",
                )
        else:
            args = raw_args

        cap_name = _resolve_capability_name(name)
        if cap_name == "tool":
            payload = {"name": name, "args": args}
        else:
            payload = args
        return self._registry.invoke(cap_name, layer, payload)

    def handle_tool_calls(self, layer: str,
                          tool_calls: list[dict]) -> list[CapabilityResult]:
        """Execute tool_calls returned by LLM.

        Delegates to execute_tool_call() for each call.
        """
        results: list[CapabilityResult] = []
        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            raw_args = func.get("arguments", "{}")
            result = self.execute_tool_call(layer, name, raw_args)
            results.append(result)
        return results

    def format_results_for_prompt(self, results: list[CapabilityResult]) -> str:
        """Format CapabilityResult list as user prompt text block.

        Injected into the next stage's user prompt as:
            [工具调用结果]
            tool_name: result_summary
            knowledge_query: found 3 docs...
        """
        if not results:
            return ""

        lines = ["[工具调用结果]"]
        for r in results:
            if r.success:
                data_str = _summarize_data(r.capability_name, r.data)
                lines.append(f"{r.capability_name}: {data_str}")
            else:
                lines.append(f"{r.capability_name}: ERROR - {r.error}")
        return "\n".join(lines)


# ── helpers ──────────────────────────────────────────────────────────────

def _resolve_capability_name(tool_name: str) -> str:
    """Map a tool/function name to its capability name.

    Tool names like 'todo', 'terminal', 'web_search' → capability 'tool'.
    'knowledge_query' → capability 'knowledge'.
    """
    if tool_name == "knowledge_query":
        return "knowledge"
    return "tool"


def _summarize_data(cap_name: str, data: Any) -> str:
    """Create a concise text summary of capability result data."""
    if data is None:
        return "(no data)"

    if isinstance(data, list):
        items = data[:5]
        parts = []
        for item in items:
            if isinstance(item, dict):
                content = str(item.get("content", item.get("snippet", "")))[:120]
                name = item.get("name", item.get("title", item.get("id", "")))
                if name:
                    parts.append(f"[{name}] {content}")
                else:
                    parts.append(content)
            else:
                parts.append(str(item)[:120])
        summary = " | ".join(parts) if parts else f"{len(data)} items"
        if len(data) > 5:
            summary += f" (and {len(data) - 5} more)"
        return summary

    if isinstance(data, dict):
        if "error" in data:
            return f"ERROR: {data['error']}"
        content = str(data.get("content", data.get("result", "")))[:200]
        return content if content else json.dumps(data, ensure_ascii=False)[:200]

    return str(data)[:200]
