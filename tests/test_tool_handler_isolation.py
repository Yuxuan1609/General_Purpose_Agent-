"""Test tool handlers in isolation via ToolRegistry.dispatch.

Covers: sysinfo, terminal, read_file, grep, create_domain.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from core.tools.registry import ToolRegistry
from core.tools.consolidation_injection import set_consolidation_stores
from core.tools.consolidation_tools import register_consolidation_tools
from core.domain_registry import DomainRegistry
from core.tools.file_tools import set_workspace_root


# ── fixtures ──

@pytest.fixture
def registry():
    r = ToolRegistry()
    r.clear()
    return r


@pytest.fixture
def temp_workspace(tmp_path):
    old = Path.cwd()
    set_workspace_root(tmp_path)
    yield tmp_path
    set_workspace_root(old)


# ── sysinfo ──

class TestSysinfoDispatch:
    def test_dispatch_all(self, registry):
        from core.tools.sysinfo_tool import register_sysinfo_tool
        register_sysinfo_tool(registry)
        result = json.loads(registry.dispatch("sysinfo", {}))
        for key in ("os", "hardware", "env", "network"):
            assert key in result[key if isinstance(result, dict) and key in result else None] or True
        assert "os" in result
        assert "hardware" in result
        assert "env" in result
        assert "network" in result

    def test_dispatch_category_os(self, registry):
        from core.tools.sysinfo_tool import register_sysinfo_tool
        register_sysinfo_tool(registry)
        result = json.loads(registry.dispatch("sysinfo", {"category": "os"}))
        assert "os" in result
        assert "system" in result["os"]
        assert "hardware" not in result

    def test_dispatch_category_env(self, registry):
        from core.tools.sysinfo_tool import register_sysinfo_tool
        register_sysinfo_tool(registry)
        result = json.loads(registry.dispatch("sysinfo", {"category": "env"}))
        assert "env" in result
        assert "python_version" in result["env"]

    def test_dispatch_invalid_category_falls_back_all(self, registry):
        from core.tools.sysinfo_tool import register_sysinfo_tool
        register_sysinfo_tool(registry)
        result = json.loads(registry.dispatch("sysinfo", {"category": "nonsense"}))
        assert "os" in result


# ── terminal ──

class TestTerminalDispatch:
    def test_empty_command_error(self, registry):
        from core.tools.terminal_tool import register_terminal_tool
        register_terminal_tool(registry)
        result = json.loads(registry.dispatch("terminal", {"command": ""}))
        assert "error" in result

    def test_echo_command(self, registry):
        from core.tools.terminal_tool import register_terminal_tool
        register_terminal_tool(registry)
        result = json.loads(registry.dispatch("terminal", {"command": "echo hello_test"}))
        assert "stdout" in result
        assert "hello_test" in result["stdout"]
        assert result.get("returncode") == 0

    def test_python_version(self, registry):
        from core.tools.terminal_tool import register_terminal_tool
        register_terminal_tool(registry)
        result = json.loads(registry.dispatch("terminal", {
            "command": f'{sys.executable} -c "print(42)"'
        }))
        assert "42" in result.get("stdout", "")

    def test_nonexistent_command(self, registry):
        from core.tools.terminal_tool import register_terminal_tool
        register_terminal_tool(registry)
        result = json.loads(registry.dispatch("terminal", {
            "command": "nonexistent_cmd_xyz_123"
        }))
        assert "error" in result or result.get("returncode", 0) != 0


# ── read_file ──

class TestReadFileDispatch:
    def test_read_file_empty_path_error(self, registry):
        from core.tools.file_tools import register_read_file
        register_read_file(registry)
        result = json.loads(registry.dispatch("read_file", {"path": ""}))
        assert "error" in result

    def test_read_file_not_found(self, registry):
        from core.tools.file_tools import register_read_file
        register_read_file(registry)
        result = json.loads(registry.dispatch("read_file", {"path": "/nonexistent/file.txt"}))
        assert "error" in result

    def test_read_file_with_workspace_root(self, registry, temp_workspace):
        from core.tools.file_tools import register_read_file
        register_read_file(registry)
        f = temp_workspace / "test.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = json.loads(registry.dispatch("read_file", {"path": "test.txt"}))
        assert result.get("total_lines") == 3
        assert "line1" in result.get("content", "")

    def test_read_file_offset_limit(self, registry, temp_workspace):
        from core.tools.file_tools import register_read_file
        register_read_file(registry)
        f = temp_workspace / "data.txt"
        f.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
        result = json.loads(registry.dispatch("read_file", {
            "path": "data.txt", "offset": 2, "limit": 2,
        }))
        assert result.get("offset") == 2
        assert "2: b" in result.get("content", "")
        assert "3: c" in result.get("content", "")


# ── grep ──

class TestGrepDispatch:
    def test_grep_empty_pattern_error(self, registry):
        from core.tools.file_tools import register_grep
        register_grep(registry)
        result = json.loads(registry.dispatch("grep", {"pattern": ""}))
        assert "error" in result

    def test_grep_in_temp_workspace(self, registry, temp_workspace):
        from core.tools.file_tools import register_grep
        register_grep(registry)
        f = temp_workspace / "greptest.py"
        f.write_text("def hello():\n    return 42\n", encoding="utf-8")
        result = json.loads(registry.dispatch("grep", {
            "pattern": "def hello", "path": str(temp_workspace),
        }))
        assert result.get("count", 0) >= 1
        matches = result.get("matches", [])
        assert any("hello" in m for m in matches)

    def test_grep_no_match(self, registry, temp_workspace):
        from core.tools.file_tools import register_grep
        register_grep(registry)
        f = temp_workspace / "greptest2.py"
        f.write_text("x = 1\n", encoding="utf-8")
        result = json.loads(registry.dispatch("grep", {
            "pattern": "ZZZNOTFOUND", "path": str(temp_workspace),
        }))
        assert result.get("count", 0) == 0


# ── create_domain ──

class TestCreateDomainDispatch:
    @classmethod
    def setup_class(cls):
        cls._tmpdir = tempfile.mkdtemp()
        cls._reg = DomainRegistry()
        set_consolidation_stores({"l1": None, "l2": None, "l3": None}, registry=cls._reg)

    @classmethod
    def teardown_class(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_create_domain_success(self, registry):
        register_consolidation_tools(registry)
        result = json.loads(registry.dispatch("create_domain", {
            "path": "game/mahjong",
            "description": "Mahjong game domain",
        }))
        assert result.get("success") is True
        node = self._reg.get_node("game/mahjong")
        assert node is not None

    def test_create_domain_empty_path(self, registry):
        register_consolidation_tools(registry)
        result = json.loads(registry.dispatch("create_domain", {
            "path": "", "description": "test",
        }))
        assert "error" in result

    def test_create_domain_idempotent_returns_success(self, registry):
        register_consolidation_tools(registry)
        registry.dispatch("create_domain", {
            "path": "game/chess", "description": "Chess game domain",
        })
        result = json.loads(registry.dispatch("create_domain", {
            "path": "game/chess", "description": "Duplicate overwrite",
        }))
        assert result.get("success") is True
        node = self._reg.get_node("game/chess")
        assert "Duplicate overwrite" in node.description
