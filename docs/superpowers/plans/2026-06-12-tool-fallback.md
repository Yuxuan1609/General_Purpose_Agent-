# Tool Call Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When tool calls fail, provide structured fallback hints (retry/degrade/default) in the error response so the Agent can autonomously decide next steps.

**Architecture:** `LayerInjector.execute_tool_call()` gains three error branches (Type 2/3/4). Tool config (allowlist, timeout, fallback) moves from `DEFAULT_TOOL_ALLOWLIST` in code to `config/tools.yaml`. `CapabilityResult` gains optional `fallback` dict field. `_call_llm` serializes `fallback` into the `role:"tool"` error message.

**Tech Stack:** Python 3.11+, DeepSeek API, yaml

**Design Spec:** `docs/superpowers/specs/2026-06-12-tool-fallback-design.md`

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `config/tools.yaml` | **New** | Per-tool allowlist, timeout, fallback config |
| `config/consolidation_tools.yaml` | **New** | Consolidation tool config (allowlist only) |
| `capability/__init__.py` | Modify | `CapabilityResult` add `fallback: dict` field |
| `capability/tool_capability.py` | Modify | Load config from yaml; inject timeout into schemas; pass timeout to dispatch |
| `capability/layer_injector.py` | Modify | `execute_tool_call()` — three error branches + `_build_fallback()` |
| `core/tools/registry.py` | Modify | `dispatch()` accepts `timeout` param, passes to handler |
| `core/tools/terminal_tool.py` | Modify | Handler accepts `timeout` kwarg for subprocess.run |
| `core/tools/web_search_tool.py` | Modify | Handler accepts `timeout` kwarg (reserved) |
| `core/tools/file_tools.py` | Modify | Handlers accept `timeout` kwarg (reserved) |
| `core/tools/todo_tool.py` | Modify | Handler accepts `timeout` kwarg (reserved) |
| `core/layers/base.py` | Modify | `_call_llm` error path uses `fallback` dict |
| `tests/test_tool_fallback.py` | **New** | Tests |

---

### Task 1: Create `config/tools.yaml`

**Files:**
- Create: `config/tools.yaml`

- [ ] **Write config file**

```yaml
# Tool system configuration — allowlist, timeout, fallback
# Priority: LLM arg timeout > tool config timeout > default_timeout

default_timeout: 30

tools:
  terminal:
    timeout: 30
    allowlist: [l2, l3]
    fallback:
      max_retries: 2
      degrade:
        - tool: read_file
          hint: "终端不可用时可尝试 read_file 读取目标文件"
        - tool: grep
          hint: "终端不可用时可尝试 grep 搜索文件内容"

  web_search:
    timeout: 15
    allowlist: [l2, l3]
    fallback:
      max_retries: 2
      degrade:
        - tool: knowledge_query
          hint: "网络搜索不可用时可尝试 knowledge_query 查询本地知识库"

  read_file:
    timeout: 10
    allowlist: [l2, l3]
    fallback:
      max_retries: 1
      degrade: []

  grep:
    timeout: 10
    allowlist: [l2, l3]
    fallback:
      max_retries: 1
      degrade: []

  todo:
    timeout: 5
    allowlist: [l1, l2, l3]
    fallback:
      max_retries: 1
      degrade: []

  knowledge_query:
    timeout: 10
    allowlist: [l1, l2, l3]
    fallback:
      max_retries: 1
      degrade: []
```

- [ ] **Verify yaml is valid**

Run: `python -c "import yaml; yaml.safe_load(open('config/tools.yaml')); print('OK')"`

- [ ] **Commit**

```bash
git add config/tools.yaml
git commit -m "feat: add tools.yaml config for allowlist, timeout, fallback"
```

---

### Task 2: Create `config/consolidation_tools.yaml`

**Files:**
- Create: `config/consolidation_tools.yaml`

- [ ] **Write config file**

```yaml
# Consolidation tools — allowlist only (fallback not needed, local DictInjector)

tools:
  deprecate_l1_rule:
    timeout: 5
    allowlist: [l1]
    fallback:
      max_retries: 0
      degrade: []

  create_l1_rule:
    timeout: 5
    allowlist: [l1]
    fallback:
      max_retries: 0
      degrade: []

  modify_l1_rule:
    timeout: 5
    allowlist: [l1]
    fallback:
      max_retries: 0
      degrade: []

  deprecate_l2_card:
    timeout: 5
    allowlist: [l2]
    fallback:
      max_retries: 0
      degrade: []

  create_l2_card:
    timeout: 5
    allowlist: [l2]
    fallback:
      max_retries: 0
      degrade: []

  modify_l2_card:
    timeout: 5
    allowlist: [l2]
    fallback:
      max_retries: 0
      degrade: []

  deprecate_l3_skill:
    timeout: 5
    allowlist: [l3]
    fallback:
      max_retries: 0
      degrade: []

  create_l3_skill:
    timeout: 5
    allowlist: [l3]
    fallback:
      max_retries: 0
      degrade: []

  modify_l3_skill:
    timeout: 5
    allowlist: [l3]
    fallback:
      max_retries: 0
      degrade: []
```

- [ ] **Verify yaml is valid**

Run: `python -c "import yaml; yaml.safe_load(open('config/consolidation_tools.yaml')); print('OK')"`

- [ ] **Commit**

```bash
git add config/consolidation_tools.yaml
git commit -m "feat: add consolidation_tools.yaml config"
```

---

### Task 3: Add `fallback` field to `CapabilityResult`

**Files:**
- Modify: `capability/__init__.py:7-18`

- [ ] **Add fallback field**

In `capability/__init__.py`, find `CapabilityResult` dataclass line 7-18.

Replace:

```python
@dataclass(frozen=True)
class CapabilityResult:
    """Unified return type for all capability invocations.

    Flows through LayerMessage back to the calling layer's user prompt.
    """
    capability_name: str
    layer: str
    success: bool
    data: Any = None
    error: str = ""
    metadata: dict = field(default_factory=dict)
```

With:

```python
@dataclass(frozen=True)
class CapabilityResult:
    """Unified return type for all capability invocations.

    Flows through LayerMessage back to the calling layer's user prompt.
    On failure, fallback dict contains structured hints for the Agent:
      retry: str | None (e.g. "可重试最多 2 次")
      degrade: list[dict] | None (e.g. [{"tool": "...", "hint": "..."}])
      default: str (always present on failure)
    """
    capability_name: str
    layer: str
    success: bool
    data: Any = None
    error: str = ""
    metadata: dict = field(default_factory=dict)
    fallback: dict | None = None
```

- [ ] **Verify import**

Run: `python -c "from capability import CapabilityResult; r = CapabilityResult('x','l1',False,error='err',fallback={'default':'msg'}); print(r.fallback)"`

- [ ] **Commit**

```bash
git add capability/__init__.py
git commit -m "feat: add fallback field to CapabilityResult"
```

---

### Task 4: Load config from yaml in `ToolCapability`

**Files:**
- Modify: `capability/tool_capability.py`

- [ ] **Add yaml config helpers and replace DEFAULT_TOOL_ALLOWLIST**

Read current `capability/tool_capability.py` (116 lines). Replace the full file content:

```python
from __future__ import annotations
import json
import yaml
from typing import Any
from pathlib import Path

from capability import Capability, CapabilityResult

_TOOL_CONFIG: dict | None = None
_TOOL_CONFIG_PATH = Path("config/tools.yaml")


def _load_tool_config() -> dict:
    global _TOOL_CONFIG
    if _TOOL_CONFIG is None:
        with open(_TOOL_CONFIG_PATH) as f:
            _TOOL_CONFIG = yaml.safe_load(f)
    return _TOOL_CONFIG


def _load_fallback_config(name: str) -> dict | None:
    cfg = _load_tool_config()
    tool = cfg.get("tools", {}).get(name)
    if tool:
        return tool.get("fallback")
    return None


def _get_tool_timeout(name: str) -> int:
    cfg = _load_tool_config()
    default = cfg.get("default_timeout", 30)
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

        effective_timeout = timeout or _get_tool_timeout(tool_name)

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
        except json.JSONDecodeError:
            return CapabilityResult(
                capability_name="tool", layer=layer, success=True,
                data={"raw": ""},
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
```

- [ ] **Verify import**

Run: `python -c "from capability.tool_capability import ToolCapability, _get_allowlist; print(_get_allowlist())"`

- [ ] **Commit**

```bash
git add capability/tool_capability.py
git commit -m "feat: load tool allowlist/timeout/fallback from config/tools.yaml"
```

---

### Task 5: Add fallback logic to `LayerInjector.execute_tool_call()`

**Files:**
- Modify: `capability/layer_injector.py:61-89`

- [ ] **Rewrite execute_tool_call with three fallback branches**

In `capability/layer_injector.py`, replace `execute_tool_call` (lines 61-89) with:

```python
    def execute_tool_call(self, layer: str, name: str,
                          raw_args: str | dict) -> CapabilityResult:
        """Execute a single tool call during _call_llm's multi-turn loop.

        Three failure branches:
          Type 4 — tool name unknown → error + available tools list
          Type 2 — invalid JSON arguments → error + retry hint
          Type 3 — execution exception → error + fallback config (retry/degrade/default)

        Args:
            layer: Calling layer.
            name: Function name from LLM tool_call.
            raw_args: JSON string or dict of function arguments.

        Returns:
            CapabilityResult with optional fallback dict on failure.
        """
        cap_name = _resolve_capability_name(name)

        # Type 4: unknown tool
        if cap_name == "tool" and not self._registry.get("tool"):
            return CapabilityResult(
                capability_name=name, layer=layer, success=False,
                error=f"Capability system not initialized",
                fallback={
                    "default": "工具系统未初始化",
                },
            )

        # Parse arguments
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                return CapabilityResult(
                    capability_name=name, layer=layer, success=False,
                    error=f"Invalid JSON arguments: {raw_args[:100]}",
                    fallback={
                        "retry": "请修正 JSON 格式后重试",
                        "default": "参数格式无效，请检查后重试",
                    },
                )
        else:
            args = raw_args

        if cap_name == "tool":
            payload = {"name": name, "args": args}
        else:
            payload = args

        result = self._registry.invoke(cap_name, layer, payload)

        # Type 3: enrich with fallback if not already set
        if not result.success and result.fallback is None:
            return CapabilityResult(
                capability_name=result.capability_name,
                layer=result.layer,
                success=False,
                error=result.error,
                fallback={
                    "default": "该工具暂时不可用，请尝试其他可用工具或调整查询方式重试",
                },
            )

        return result
```

Note: `ToolCapability.invoke()` already sets `fallback` when the tool has a fallback config. `KnowledgeCapability` and unknown capabilities may not — the default fallback in this method covers those cases.

- [ ] **Verify import**

Run: `python -c "from capability.layer_injector import LayerInjector; print('OK')"`

- [ ] **Commit**

```bash
git add capability/layer_injector.py
git commit -m "feat: add three-branch fallback to execute_tool_call"
```

---

### Task 6: Update `ToolRegistry.dispatch()` to accept `timeout`

**Files:**
- Modify: `core/tools/registry.py:67-78`

- [ ] **Update dispatch signature**

In `core/tools/registry.py`, replace `dispatch` method (lines 67-78) with:

```python
    def dispatch(self, name: str, args: dict, context: dict | None = None,
                 timeout: int | None = None) -> str:
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            return json.dumps({"error": f"Tool '{name}' not found"})
        try:
            kwargs = {"args": args}
            if context is not None:
                kwargs["context"] = context
            if timeout is not None:
                kwargs["timeout"] = timeout
            result = entry.handler(**kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})
```

- [ ] **Verify import**

Run: `python -c "from core.tools.registry import ToolRegistry; print('OK')"`

- [ ] **Commit**

```bash
git add core/tools/registry.py
git commit -m "feat: add timeout param to ToolRegistry.dispatch"
```

---

### Task 7: Update tool handlers to accept `timeout`

**Files:**
- Modify: `core/tools/terminal_tool.py`
- Modify: `core/tools/web_search_tool.py`
- Modify: `core/tools/file_tools.py`
- Modify: `core/tools/todo_tool.py`

- [ ] **terminal_tool.py — use timeout from arg**

In `core/tools/terminal_tool.py`, replace the `handler` (lines 10-26) with:

```python
def register_terminal_tool(registry, allowed_commands: list[str] | None = None):
    def handler(args=None, context=None, timeout=30):
        command = (args or {}).get("command", "")
        user_timeout = (args or {}).get("timeout", timeout) if args else timeout
        if not command:
            return json.dumps({"error": "No command provided"})
        if allowed_commands and not any(command.startswith(cmd) for cmd in allowed_commands):
            return json.dumps({"error": f"Command not allowed: {command}"})
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=user_timeout)
            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Command timed out ({user_timeout}s)"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    registry.register("terminal", {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Execute a shell command and capture stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"]
            }
        }
    }, handler, toolset="core")
```

Note: `timeout` is now accepted as a function parameter. The LLM-visible `timeout` is injected by `ToolCapability.get_schemas_by_layer()` at schema level — the handler reads it from the merged `args` dict (priority: LLM args.timeout > dispatch timeout > default 30).

Actually, the priority chain needs clarification. The `dispatch()` receives a `timeout` kwarg from `ToolCapability.invoke()` (which is the config default). The handler should use the LLM's `args.timeout` if present, falling back to the `timeout` kwarg. Let's update:

```python
def register_terminal_tool(registry, allowed_commands: list[str] | None = None):
    def handler(args=None, timeout=30):
        command = (args or {}).get("command", "")
        effective_timeout = (args or {}).get("timeout", timeout) if args else timeout
        if not command:
            return json.dumps({"error": "No command provided"})
        if allowed_commands and not any(command.startswith(cmd) for cmd in allowed_commands):
            return json.dumps({"error": f"Command not allowed: {command}"})
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=effective_timeout)
            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"Command timed out ({effective_timeout}s)"})
        except Exception as e:
            return json.dumps({"error": str(e)})

    registry.register("terminal", {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Execute a shell command and capture stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"]
            }
        }
    }, handler, toolset="core")
```

- [ ] **web_search_tool.py — add timeout param (reserved)**

In `core/tools/web_search_tool.py`, replace the handler signature line 10:

Replace:
```python
    def handler(args=None, context=None):
```

With:
```python
    def handler(args=None, timeout=30):
```

And update the call to remove `context`:

Replace:
```python
    }, handler, toolset="core")
```
No change needed — it already works.

- [ ] **file_tools.py — add timeout param (reserved)**

In `core/tools/file_tools.py`, update both handlers:

`register_read_file` — replace line 44:
```python
    def handler(args=None, context=None):
```
With:
```python
    def handler(args=None, timeout=10):
```

`register_grep` — replace line 113:
```python
    def handler(args=None, context=None):
```
With:
```python
    def handler(args=None, timeout=10):
```

- [ ] **todo_tool.py — add timeout param (reserved)**

In `core/tools/todo_tool.py`, replace line 33:
```python
    def handler(args=None, context=None):
```
With:
```python
    def handler(args=None, timeout=5):
```

- [ ] **Verify all imports**

Run:
```bash
python -c "from core.tools.terminal_tool import register_terminal_tool; print('terminal OK')"
python -c "from core.tools.web_search_tool import register_web_search_tool; print('web_search OK')"
python -c "from core.tools.file_tools import register_read_file, register_grep; print('file_tools OK')"
python -c "from core.tools.todo_tool import register_todo_tool; print('todo OK')"
```

- [ ] **Commit**

```bash
git add core/tools/terminal_tool.py core/tools/web_search_tool.py core/tools/file_tools.py core/tools/todo_tool.py
git commit -m "feat: tool handlers accept timeout param"
```

---

### Task 8: Update `_call_llm` error path to use `fallback` dict

**Files:**
- Modify: `core/layers/base.py:164-183`

- [ ] **Update error role:"tool" message format**

In `core/layers/base.py`, find the `_call_llm` method. Locate the error path (around lines 170-183) where `not raw.success`:

Replace:
```python
                    if raw.success:
                        result_content = raw.data
                        result_str = str(raw.data.get("result", "") if isinstance(raw.data, dict) else raw.data)[:200]
                    else:
                        result_content = {"error": raw.error}
                        result_str = raw.error
                    self._log.debug("  tool %s → %s", tc.function.name,
                                   str(result_str)[:120])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result_content, ensure_ascii=False),
                    })
```

With:
```python
                    if raw.success:
                        result_content = raw.data
                        result_str = str(raw.data.get("result", "") if isinstance(raw.data, dict) else raw.data)[:200]
                    else:
                        result_content = {"error": raw.error}
                        fb = getattr(raw, 'fallback', None)
                        if fb:
                            result_content.update(fb)
                        result_str = raw.error
                    self._log.debug("  tool %s → %s", tc.function.name,
                                   str(result_str)[:120])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result_content, ensure_ascii=False),
                    })
```

- [ ] **Verify import**

Run: `python -c "from core.layers.base import LayerAgent, LayerManager, DictInjector; print('OK')"`

- [ ] **Commit**

```bash
git add core/layers/base.py
git commit -m "feat: _call_llm error messages include fallback dict"
```

---

### Task 9: Write tests

**Files:**
- Create: `tests/test_tool_fallback.py`

- [ ] **Write test file**

```python
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

        # No capabilities registered → invoke returns CapabilityResult(success=False)
        result = injector.execute_tool_call("l2", "terminal", {"command": "ls"})

        assert result.success is False
        assert result.fallback is not None
        assert "default" in result.fallback

    def test_execution_error_preserves_existing_fallback(self):
        """When registry.invoke already sets fallback, it is preserved."""
        registry = MagicMock()
        existing_fb = {"retry": "可重试最多 2 次", "degrade": [], "default": "msg"}
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
        assert fb["retry"] == "可重试最多 2 次"
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
```

- [ ] **Run tests**

Run: `python -m pytest tests/test_tool_fallback.py -v`

- [ ] **Fix any failures, then commit**

```bash
git add tests/test_tool_fallback.py
git commit -m "test: add tool fallback unit tests"
```

---

### Task 10: Run full test suite

- [ ] **Run all tests**

Run: `python -m pytest tests/ -v --tb=short`

Expected: All tests pass. The existing mock-based tests should be unaffected.

- [ ] **If failures, fix and re-run**

---

## Self-Review

**Spec coverage check:**
1. ✅ Config files created — Task 1, 2
2. ✅ `CapabilityResult.fallback` field — Task 3
3. ✅ ToolCapability loads config from yaml — Task 4
4. ✅ `execute_tool_call()` three fallback branches — Task 5
5. ✅ Timeout handling — Tasks 4 (schema injection), 6 (dispatch), 7 (handlers)
6. ✅ `_call_llm` error path — Task 8
7. ✅ Tests — Task 9
8. ✅ Full test suite — Task 10

**Placeholder check:** No TBDs, TODOs, or "add error handling" patterns. All steps contain actual code.

**Type consistency:**
- `CapabilityResult` has `fallback` field (Task 3) → used in `ToolCapability.invoke` (Task 4) → used in `LayerInjector.execute_tool_call` (Task 5) → used in `_call_llm` (Task 8). All consistent.
- `ToolRegistry.dispatch` signature with `timeout` (Task 6) → called by `ToolCapability.invoke` with `timeout` (Task 4) → handlers accept `timeout` kwarg (Task 7). All consistent.
