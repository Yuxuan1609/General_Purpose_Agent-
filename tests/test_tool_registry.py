import pytest
from core.tools.registry import ToolRegistry, ToolEntry


def echo_handler(args, context=None):
    return f"echo: {args.get('message', '')}"

def check_always():
    return True

def check_never():
    return False


@pytest.fixture(autouse=True)
def _clear_registry():
    """Clear the singleton registry before each test to ensure isolation."""
    ToolRegistry().clear()


class TestToolRegistry:
    def test_singleton(self):
        a = ToolRegistry()
        b = ToolRegistry()
        assert a is b

    def test_register_and_get(self):
        r = ToolRegistry()
        r.register("echo", {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo a message",
                "parameters": {"type": "object", "properties": {}}
            }
        }, echo_handler, check_fn=check_always)
        defs = r.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "echo"

    def test_get_definitions_filters_by_check_fn(self):
        r = ToolRegistry()
        r.register("always", {
            "type": "function",
            "function": {"name": "always", "description": "", "parameters": {}}
        }, echo_handler, check_fn=check_always)
        r.register("never", {
            "type": "function",
            "function": {"name": "never", "description": "", "parameters": {}}
        }, echo_handler, check_fn=check_never)
        defs = r.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "always" in names
        assert "never" not in names

    def test_dispatch(self):
        r = ToolRegistry()
        r.register("echo", {
            "type": "function",
            "function": {"name": "echo", "description": "", "parameters": {}}
        }, echo_handler, check_fn=check_always)
        result = r.dispatch("echo", {"message": "hello"})
        assert result == "echo: hello"

    def test_dispatch_unknown_tool_returns_error(self):
        r = ToolRegistry()
        result = r.dispatch("nonexistent", {})
        assert "error" in result

    def test_deregister(self):
        r = ToolRegistry()
        r.register("temp", {
            "type": "function",
            "function": {"name": "temp", "description": "", "parameters": {}}
        }, echo_handler, check_fn=check_always)
        assert len(r.get_definitions()) == 1
        r.deregister("temp")
        assert len(r.get_definitions()) == 0

    def test_duplicate_register_same_toolset_is_ok(self):
        r = ToolRegistry()
        schema = {"type": "function", "function": {"name": "dup", "description": "", "parameters": {}}}
        r.register("dup", schema, echo_handler, check_fn=check_always, toolset="core")
        r.register("dup", schema, echo_handler, check_fn=check_always, toolset="core")
        assert len(r.get_definitions()) == 1

    def test_duplicate_register_different_toolset_raises(self):
        r = ToolRegistry()
        schema = {"type": "function", "function": {"name": "dup", "description": "", "parameters": {}}}
        r.register("dup", schema, echo_handler, check_fn=check_always, toolset="A")
        with pytest.raises(ValueError, match="already registered"):
            r.register("dup", schema, echo_handler, check_fn=check_always, toolset="B")
