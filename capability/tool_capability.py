from __future__ import annotations
import json
import yaml
from typing import Any
from pathlib import Path

from capability import Capability, CapabilityResult

_TOOL_CONFIG: dict | None = None
_TOOL_CONFIG_PATH = Path(__file__).parent.parent / "config" / "tools.yaml"


def _load_tool_config() -> dict:
    global _TOOL_CONFIG
    if _TOOL_CONFIG is None:
        try:
            with open(_TOOL_CONFIG_PATH, encoding="utf-8") as f:
                _TOOL_CONFIG = yaml.safe_load(f)
        except (FileNotFoundError, yaml.YAMLError) as e:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to load %s: %s. Using empty config.", _TOOL_CONFIG_PATH, e
            )
            _TOOL_CONFIG = {}
    if _TOOL_CONFIG is None:
        _TOOL_CONFIG = {}
    return _TOOL_CONFIG


def _load_fallback_config(name: str) -> dict | None:
    cfg = _load_tool_config()
    tool = cfg.get("tools", {}).get(name)
    if tool:
        return tool.get("fallback")
    return None


def _get_tool_timeout(name: str) -> int:
    cfg = _load_tool_config()
    default = cfg.get("default_timeout", 300)
    return cfg.get("tools", {}).get(name, {}).get("timeout", default)


def _get_allowlist() -> dict[str, set[str]]:
    cfg = _load_tool_config()
    allowlist: dict[str, set[str]] = {}
    for name, tool in cfg.get("tools", {}).items():
        for layer in tool.get("allowlist", []):
            allowlist.setdefault(layer, set()).add(name)
    return allowlist


class ToolCapability(Capability):
    """Wraps ToolRegistry as a Capability with per-layer access control.

    Access control granularity: per-tool per-layer.
    Config loaded from config/tools.yaml.
    """

    name = "tool"

    def __init__(self, registry, allowlist: dict[str, set[str]] | None = None):
        self._registry = registry
        self._allowlist = allowlist or _get_allowlist()

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

    def invoke(self, layer: str, args: dict, timeout: int | None = None) -> CapabilityResult:
        tool_name = args.get("name", "")
        tool_args = args.get("args", {})

        allowed = self._allowlist.get(layer, set())
        if tool_name not in allowed:
            return CapabilityResult(
                capability_name="tool", layer=layer, success=False,
                error=f"Tool '{tool_name}' not allowed for layer '{layer}'",
            )

        # Priority: LLM arg.timeout > dispatch timeout > config timeout
        arg_timeout = tool_args.get("timeout") if isinstance(tool_args, dict) else None
        if arg_timeout is not None:
            effective_timeout = arg_timeout
        elif timeout is not None:
            effective_timeout = timeout
        else:
            effective_timeout = _get_tool_timeout(tool_name)

        try:
            raw = self._registry.dispatch(tool_name, tool_args, timeout=effective_timeout)
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

        except Exception as e:
            cfg = _load_fallback_config(tool_name)
            fb = _build_fallback(cfg) if cfg else None
            return CapabilityResult(
                capability_name="tool", layer=layer, success=False,
                error=str(e), fallback=fb,
            )

    # ── public helpers ──────────────────────────────────────────────

    def get_schemas_by_layer(self, layer: str) -> list[dict]:
        """Return per-tool OpenAI function-calling schemas for the given layer.

        Unlike get_schema() which returns a single meta-schema, this returns
        individual tool schemas for direct injection into LLM tools parameter.
        Each schema includes an optional 'timeout' parameter.
        """
        allowed = self._allowlist.get(layer, set())
        schemas = self._registry.get_definitions(requested=allowed)
        for s in schemas:
            params = s.get("function", {}).get("parameters", {}).get("properties", {})
            if "timeout" not in params:
                name = s.get("function", {}).get("name", "")
                default_timeout = _get_tool_timeout(name)
                params["timeout"] = {
                    "type": "integer",
                    "description": f"Optional timeout in seconds (default: {default_timeout})",
                }
        return schemas

    def allowed_tools(self, layer: str) -> set[str]:
        return self._allowlist.get(layer, set())


def _build_fallback(cfg: dict) -> dict:
    fb: dict = {}
    if cfg.get("max_retries", 0) > 0:
        fb["retry"] = f"可重试最多 {cfg['max_retries']} 次"
    degrades = cfg.get("degrade", [])
    if degrades:
        fb["degrade"] = degrades
    fb["default"] = "该工具暂时不可用，请尝试其他可用工具或调整查询方式重试"
    return fb
