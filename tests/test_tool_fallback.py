"""Tests for tool call fallback in LayerInjector.execute_tool_call()."""
import json
import pytest
from unittest.mock import patch, MagicMock

from capability import CapabilityResult, CapabilityRegistry
from capability.layer_injector import LayerInjector, _resolve_capability_name


class TestResolveCapabilityName:
    def test_knowledge_query_returns_knowledge(self):
        assert _resolve_capability_name("knowledge_query") == "knowledge"

    def test_terminal_returns_tool(self):
        assert _resolve_capability_name("terminal") == "tool"

    def test_unknown_returns_tool(self):
        assert _resolve_capability_name("unknown_xyz") == "tool"


class TestExecuteToolCallType2InvalidArgs:
    """Type 2: JSON parse failure in raw_args."""

    def test_invalid_json_returns_fallback(self):
        registry = CapabilityRegistry()
        injector = LayerInjector(registry)
        result = injector.execute_tool_call("l2", "terminal", "{bad json")

        assert result.success is False
        assert "Invalid JSON arguments" in result.error
        assert result.fallback is not None
        assert "retry" in result.fallback
        assert "default" in result.fallback


class TestExecuteToolCallType3ExecError:
    """Type 3: tool execution exception."""

    def test_execution_error_has_default_fallback(self):
        """When registry.invoke returns failure without fallback, a default is added."""
        registry = CapabilityRegistry()
        injector = LayerInjector(registry)

        result = injector.execute_tool_call("l2", "terminal", {"command": "ls"})

        assert result.success is False
        assert result.fallback is not None
        assert "default" in result.fallback

    def test_execution_error_preserves_existing_fallback(self):
        """When registry.invoke already sets fallback, it is preserved."""
        registry = MagicMock()
        existing_fb = {"retry": "\u53ef\u91cd\u8bd5\u6700\u591a 2 \u6b21", "degrade": [], "default": "msg"}
        registry.invoke.return_value = CapabilityResult(
            capability_name="tool", layer="l2", success=False,
            error="timeout", fallback=existing_fb,
        )
        injector = LayerInjector(registry)
        result = injector.execute_tool_call("l2", "terminal", {"command": "ls"})

        assert result.success is False
        assert result.fallback == existing_fb


class TestCapabilityResultFallbackField:
    def test_fallback_is_optional(self):
        r = CapabilityResult(capability_name="x", layer="l1", success=True)
        assert r.fallback is None

    def test_fallback_set_on_construction(self):
        fb = {"default": "msg"}
        r = CapabilityResult(capability_name="x", layer="l1", success=False, error="err", fallback=fb)
        assert r.fallback == fb


class TestBuildFallback:
    def test_build_fallback_with_retry_and_degrade(self):
        from capability.tool_capability import _build_fallback
        cfg = {
            "max_retries": 2,
            "degrade": [{"tool": "read_file", "hint": "try read_file instead"}],
        }
        fb = _build_fallback(cfg)
        assert fb["retry"] == "\u53ef\u91cd\u8bd5\u6700\u591a 2 \u6b21"
        assert len(fb["degrade"]) == 1
        assert fb["degrade"][0]["tool"] == "read_file"
        assert "default" in fb

    def test_build_fallback_no_degrade(self):
        from capability.tool_capability import _build_fallback
        cfg = {"max_retries": 0, "degrade": []}
        fb = _build_fallback(cfg)
        assert "retry" not in fb
        assert "degrade" not in fb
        assert "default" in fb
