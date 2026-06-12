# Tool Call Fallback Design

> **Date**: 2026-06-12
> **Status**: draft

## Goal

When a tool call fails (execution exception, invalid args, tool not found), provide structured fallback information to the Agent so it can autonomously decide: retry, switch to an alternative tool, or abort. The fallback layer does NOT make decisions — it only enriches the error response with hints the Agent can read.

## Non-Goals

- Non-goal: automatic retry in code (Agent decides)
- Non-goal: DictInjector path (consolidation tools don't need fallback — they only append to `_pending_mods`)
- Non-goal: replacing `ToolRegistry` or `CapabilityRegistry`

## Architecture

```
Agent (LLM) → tool_call → _call_llm (base.py)
                              │
                              ▼
                    injector.execute_tool_call(layer, name, args)
                              │
                    ┌─────────┼──────────┐
                    │         │          │
                   Type 4    Type 2     Type 3
              (not found)  (bad args)  (exec error)
                    │         │          │
                    ▼         ▼          ▼
              error +     error +     error + fallback config
              available   required      ├─ retry hint
              tools       fields        ├─ degrade list
                                        └─ default hint
                              │
                              ▼
                    role:"tool" message → Agent 判断下一步
```

## Config Files

### `config/tools.yaml`

```yaml
# Default timeout for all tools (seconds)
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

### `config/consolidation_tools.yaml`

```yaml
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

## CapabilityResult Extension

```python
@dataclass(frozen=True)
class CapabilityResult:
    capability_name: str
    layer: str
    success: bool
    data: Any = None
    error: str = ""
    metadata: dict = field(default_factory=dict)
    fallback: dict | None = None  # NEW: structured fallback hints
```

`fallback` dict shape:

```python
{
    "retry": "可重试最多 2 次",           # present if max_retries > 0
    "degrade": [                          # present if non-empty
        {"tool": "read_file", "hint": "终端不可用时可尝试 read_file 读取目标文件"},
    ],
    "default": "该工具暂时不可用，请尝试其他可用工具或调整查询方式重试",  # always present on failure
}
```

## LayerInjector.execute_tool_call() — Updated

Three branches after initial dispatch:

### Type 4: Tool Not Found

```python
# Capability name resolution failed or tool name unknown
return CapabilityResult(
    capability_name=name, layer=layer, success=False,
    error=f"Tool '{name}' not registered",
    fallback={
        "available": self._registry.list_for_layer(layer),
        "default": "该工具未注册，请从可用工具列表中选择",
    },
)
```

### Type 2: Invalid Arguments (JSONDecodeError)

```python
# raw_args is not valid JSON
return CapabilityResult(
    capability_name=name, layer=layer, success=False,
    error=f"Invalid JSON arguments: {raw_args[:100]}",
    fallback={
        "retry": "请修正 JSON 格式后重试",
        "default": "参数格式无效，请检查后重试",
    },
)
```

### Type 3: Execution Exception (success=False)

```python
# After CapabilityRegistry.invoke() returns CapabilityResult(success=False)
cfg = _load_fallback_config(name)
if cfg:
    return CapabilityResult(
        capability_name=name, layer=layer, success=False,
        error=result.error,
        fallback=_build_fallback(cfg),
    )
# No config → bare error
```

### _build_fallback(cfg) helper

```python
def _build_fallback(cfg: dict) -> dict:
    fb = {}
    if cfg.get("max_retries", 0) > 0:
        fb["retry"] = f"可重试最多 {cfg['max_retries']} 次"
    degrades = cfg.get("degrade", [])
    if degrades:
        fb["degrade"] = degrades
    fb["default"] = "该工具暂时不可用，请尝试其他可用工具或调整查询方式重试"
    return fb
```

## Timeout Handling

### Tool schemas — add optional `timeout` field

Each tool registered via `ToolRegistry.register()` gets `timeout` appended to its parameters schema:

```python
# In ToolCapability.get_schemas_by_layer() (or during registration):
schema["function"]["parameters"]["properties"]["timeout"] = {
    "type": "integer",
    "description": f"Optional timeout in seconds (default: {tool_timeout})",
}
```

### Priority

```
LLM tool_call args.timeout  >  config/tools.yaml tool.timeout  >  config/tools.yaml default_timeout (30)
```

### Delivery to tool handler

`ToolRegistry.dispatch()` signature changes:

```python
def dispatch(self, name: str, args: dict, timeout: int | None = None) -> str:
    ...
    # Pass timeout to handler as separate arg (handlers that need it can accept it)
    result = entry.handler(args, timeout=timeout)
```

Terminal handler uses it:

```python
def handler(args=None, context=None, timeout=30):
    ...
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
```

Other handlers (web_search, read_file, etc.) accept `timeout` kwarg but may ignore it for now (future-proof).

## Error Response — role:"tool" Message Format

The error message sent to LLM via `role:"tool"` uses the `fallback` dict (not raw error string):

```json
{
  "error": "command timed out after 30s",
  "retry": "可重试最多 2 次",
  "degrade": [
    {"tool": "read_file", "hint": "终端不可用时可尝试 read_file 读取目标文件"},
    {"tool": "grep", "hint": "终端不可用时可尝试 grep 搜索文件内容"}
  ],
  "default": "该工具暂时不可用，请尝试其他可用工具或调整查询方式重试"
}
```

For DictInjector tools, the existing `role:"tool"` message format is unchanged (they don't go through fallback).

## Configuration Loader

`capability/tool_capability.py`:

```python
import yaml
from pathlib import Path

def _load_tool_config(path: str = "config/tools.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

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
    allowlist = {}
    for name, tool in cfg.get("tools", {}).items():
        for layer in tool.get("allowlist", []):
            allowlist.setdefault(layer, set()).add(name)
    return allowlist
```

`ToolCapability.__init__` uses `_get_allowlist()` instead of `DEFAULT_TOOL_ALLOWLIST`.

## Modification Scope

| File | Change |
|------|--------|
| `config/tools.yaml` | **New** — tool allowlist, timeout, fallback config |
| `config/consolidation_tools.yaml` | **New** — consolidation tool fallback config |
| `capability/__init__.py` | `CapabilityResult` add `fallback: dict` field |
| `capability/layer_injector.py` | `execute_tool_call()` — three fallback branches; `_build_fallback()` helper |
| `capability/tool_capability.py` | `__init__` reads allowlist from yaml; `get_schemas_by_layer()` injects timeout into schemas; `invoke()` passes timeout; new helpers `_load_tool_config()`, `_get_tool_timeout()` |
| `core/tools/registry.py` | `dispatch()` accepts optional `timeout` param, passes to handler |
| `core/tools/terminal_tool.py` | Handler accepts `timeout` kwarg, uses for `subprocess.run` |
| `core/tools/web_search_tool.py` | Handler accepts `timeout` kwarg (reserved) |
| `core/tools/file_tools.py` | Handlers accept `timeout` kwarg (reserved) |
| `core/tools/todo_tool.py` | Handler accepts `timeout` kwarg (reserved) |
| `core/layers/base.py` | `_call_llm` — error `role:"tool"` message uses `CapabilityResult.fallback` dict instead of `{"error": raw.error}` |

### NOT Modified

- `DictInjector` — consolidation tools bypass fallback
- `LayerInjector.handle_tool_calls()` — delegates to `execute_tool_call()`, no change needed
- Layer `decide()` methods — unchanged
- `KnowledgeCapability` — unchanged (not a tool)
