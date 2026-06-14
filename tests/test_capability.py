"""Integration tests for Capability, LayerInjector, ToolRegistry."""
import json
import pytest
from capability.tool_capability import ToolCapability
from capability.layer_injector import LayerInjector
from capability import CapabilityRegistry
from core.tools.registry import ToolRegistry


@pytest.fixture
def tool_registry():
    """Registry with terminal tool registered."""
    reg = ToolRegistry()
    import subprocess
    def terminal_handler(args=None, context=None, timeout=None):
        cmd = (args or {}).get("command", "")
        if not cmd:
            return json.dumps({"error": "no command"})
        return json.dumps({"stdout": "", "stderr": "", "rc": 0})
    reg.register("terminal", {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Execute a shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    }, terminal_handler, toolset="core")
    return reg


class TestToolCapability:
    def test_is_visible_to_l2(self, tool_registry):
        cap = ToolCapability(tool_registry)
        assert cap.is_visible_to("l2")

    def test_allowed_l2_includes_terminal(self, tool_registry):
        cap = ToolCapability(tool_registry)
        assert "terminal" in cap.allowed_tools("l2")

    def test_invoke_allowed(self, tool_registry):
        cap = ToolCapability(tool_registry)
        result = cap.invoke("l2", {"name": "terminal", "args": {"command": "echo test"}})
        assert result.success

    def test_invoke_unknown_tool(self, tool_registry):
        cap = ToolCapability(tool_registry)
        result = cap.invoke("l2", {"name": "nonexistent", "args": {}})
        assert not result.success

    def test_allowlist_structure(self, tool_registry):
        cap = ToolCapability(tool_registry)
        assert "terminal" in cap._allowlist["l2"]
        assert "terminal" in cap._allowlist["l3"]


@pytest.fixture
def injector(tool_registry):
    cap_reg = CapabilityRegistry()
    cap_reg.register(ToolCapability(tool_registry))
    return LayerInjector(cap_reg)


class TestLayerInjector:
    def test_get_tools_for_layer_l2(self, injector):
        tools = injector.get_tools_for_layer("l2")
        assert tools
        tool_names = [t["function"]["name"] for t in tools]
        assert "terminal" in tool_names

    def test_get_tools_for_layer_l3_has_more(self, injector):
        tools = injector.get_tools_for_layer("l3")
        tool_names = [t["function"]["name"] for t in tools]
        assert "terminal" in tool_names

    def test_handle_tool_calls_terminal(self, injector):
        results = injector.handle_tool_calls("l2", [{
            "id": "1",
            "function": {
                "name": "terminal",
                "arguments": json.dumps({"command": "echo hello"}),
            },
        }])
        assert len(results) == 1
        assert results[0].success
