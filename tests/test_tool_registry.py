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
    ToolRegistry().clear_secondary()


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


class TestToolSpec:
    def test_tool_entry_default_tool_spec_is_primary(self):
        from core.tools.registry import ToolEntry
        e = ToolEntry(name="t", schema={}, handler=lambda **k: None)
        assert e.tool_spec == "primary"
        assert e.semantic_description == ""

    def test_secondary_tool_hidden_by_default(self):
        r = ToolRegistry()
        r.register("primary_tool",
                   {"type": "function", "function": {"name": "primary_tool", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always)
        r.register("secondary_tool",
                   {"type": "function", "function": {"name": "secondary_tool", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always,
                   tool_spec="secondary",
                   semantic_description="A demo secondary tool")
        defs = r.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "primary_tool" in names
        assert "secondary_tool" not in names

    def test_enable_secondary_makes_tool_visible(self):
        r = ToolRegistry()
        r.register("secondary_tool",
                   {"type": "function", "function": {"name": "secondary_tool", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always,
                   tool_spec="secondary",
                   semantic_description="A demo secondary tool")
        r.clear_secondary()
        r.enable_secondary(["secondary_tool"])
        defs = r.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "secondary_tool" in names

    def test_clear_secondary_hides_tools(self):
        r = ToolRegistry()
        r.register("secondary_tool",
                   {"type": "function", "function": {"name": "secondary_tool", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always,
                   tool_spec="secondary",
                   semantic_description="A demo secondary tool")
        r.enable_secondary(["secondary_tool"])
        r.clear_secondary()
        defs = r.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "secondary_tool" not in names

    def test_enable_secondary_returns_count(self):
        r = ToolRegistry()
        r.register("sec_a",
                   {"type": "function", "function": {"name": "sec_a", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always, tool_spec="secondary")
        r.register("sec_b",
                   {"type": "function", "function": {"name": "sec_b", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always, tool_spec="secondary")
        r.clear_secondary()
        count = r.enable_secondary(["sec_a", "sec_b"])
        assert count == 2

    def test_enable_secondary_ignores_unknown_names(self):
        r = ToolRegistry()
        r.register("sec_a",
                   {"type": "function", "function": {"name": "sec_a", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always, tool_spec="secondary")
        r.clear_secondary()
        count = r.enable_secondary(["sec_a", "nonexistent"])
        assert count == 1

    def test_secondary_tools_are_thread_isolated(self):
        import threading
        r = ToolRegistry()
        r.register("sec_isolated",
                   {"type": "function", "function": {"name": "sec_isolated", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always, tool_spec="secondary")
        r.clear_secondary()

        # Enable in main thread
        r.enable_secondary(["sec_isolated"])
        main_defs = r.get_definitions()
        main_names = [d["function"]["name"] for d in main_defs]
        assert "sec_isolated" in main_names

        # In another thread, the tool should NOT be visible
        other_result = {}
        def check_other_thread():
            other_defs = r.get_definitions()
            other_result["names"] = [d["function"]["name"] for d in other_defs]

        t = threading.Thread(target=check_other_thread)
        t.start()
        t.join()
        assert "sec_isolated" not in other_result["names"]


class TestAvailableDomainsRemoved:
    def test_register_without_available_domains_works(self):
        r = ToolRegistry()
        r.register("plain_tool",
                   {"type": "function", "function": {"name": "plain_tool", "description": "", "parameters": {}}},
                   echo_handler, check_fn=check_always)
        defs = r.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "plain_tool"

    def test_register_rejects_available_domains_param(self):
        r = ToolRegistry()
        with pytest.raises(TypeError):
            r.register("bad_tool",
                       {"type": "function", "function": {"name": "bad_tool", "description": "", "parameters": {}}},
                       echo_handler, check_fn=check_always,
                       available_domains=["general"])
