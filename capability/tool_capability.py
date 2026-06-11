from __future__ import annotations
import json
from typing import Any

from capability import Capability, CapabilityResult

# Default per-layer tool visibility.
# L1:     lightweight tracking only
# L2:     tracking + safe system inspection
# L3:     full tool access (execution-layer privileges)
DEFAULT_TOOL_ALLOWLIST: dict[str, set[str]] = {
    "l1": {"todo"},
    "l2": {"todo", "terminal", "web_search", "read_file", "grep", "tool_proposal"},
    "l3": {"todo", "terminal", "web_search", "read_file", "grep", "tool_proposal"},
}


class ToolCapability(Capability):
    """Wraps ToolRegistry as a Capability with per-layer access control.

    Access control granularity: per-tool per-layer.
    Each tool name in the allowlist is independently checked.

    Example:
        allowlist = {
    "l1": {"todo", "create_domain"},
            "l2": {"todo", "terminal"},
            "l3": {"todo", "terminal", "web_search"},
        }
    """

    name = "tool"

    def __init__(self, registry, allowlist: dict[str, set[str]] | None = None):
        self._registry = registry
        self._allowlist = allowlist or DEFAULT_TOOL_ALLOWLIST

    # ── Capability ABC ──────────────────────────────────────────────

    def is_visible_to(self, layer: str) -> bool:
        return layer in self._allowlist and len(self._allowlist[layer]) > 0

    def get_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "tool_dispatch",
                "description": (
                    "Dispatch a tool call to the registered tool. "
                    "Available tools differ by layer."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the tool to call",
                        },
                        "args": {
                            "type": "object",
                            "description": "Arguments to pass to the tool",
                        },
                    },
                    "required": ["name"],
                },
            },
        }

    def invoke(self, layer: str, args: dict) -> CapabilityResult:
        tool_name = args.get("name", "")
        tool_args = args.get("args", {})

        allowed = self._allowlist.get(layer, set())
        if tool_name not in allowed:
            return CapabilityResult(
                capability_name="tool", layer=layer, success=False,
                error=f"Tool '{tool_name}' not allowed for layer '{layer}'",
            )

        try:
            raw = self._registry.dispatch(tool_name, tool_args)
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = {"raw": raw}
            else:
                parsed = raw
            return CapabilityResult(
                capability_name="tool", layer=layer, success=True,
                data=parsed if isinstance(parsed, dict) else {"result": parsed},
            )
        except json.JSONDecodeError:
            return CapabilityResult(
                capability_name="tool", layer=layer, success=True,
                data={"raw": ""},
            )
        except Exception as e:
            return CapabilityResult(
                capability_name="tool", layer=layer, success=False,
                error=str(e),
            )

    # ── public helpers ──────────────────────────────────────────────

    def get_schemas_by_layer(self, layer: str) -> list[dict]:
        """Return per-tool OpenAI function-calling schemas for the given layer.

        Unlike get_schema() which returns a single meta-schema, this returns
        individual tool schemas for direct injection into LLM tools parameter.
        """
        allowed = self._allowlist.get(layer, set())
        return self._registry.get_definitions(requested=allowed)

    def allowed_tools(self, layer: str) -> set[str]:
        return self._allowlist.get(layer, set())
