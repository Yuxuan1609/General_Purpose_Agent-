# 次工具系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 ToolRegistry 上增加次级工具通道——主工具始终可见，次工具默认不可见、由 Agent 通过 `activate_secondary_tools` 工具按需 LLM 筛选并 thread-local 启用。同时清理 `available_domains` 死代码。

**Architecture:** ToolEntry 加 `tool_spec`/`semantic_description` 字段；ToolRegistry 加 thread-local `_enabled_secondary` 集合 + `enable_secondary`/`clear_secondary` 方法；`get_definitions()` 按确定性逻辑过滤次工具。新增 `activate_secondary_tools` 工具，handler 内部用 LLM subagent 扫描次工具池的 `semantic_description` 做匹配并启用。无新模块、无新类。

**Tech Stack:** Python 3.10+, threading.local, dataclasses, OpenAI function-calling

**Spec:** `docs/superpowers/specs/2026-06-22-secondary-tools-design.md`

---

## File Map

| File | Role | Change |
|------|------|--------|
| `core/tools/registry.py` | ToolEntry + ToolRegistry | 加 `tool_spec`/`semantic_description` 字段；加 thread-local 过滤；删 `available_domains`/`get_tools_for_domain` |
| `core/tools/secondary_tool.py` | `activate_secondary_tools` 工具注册 + handler | Create |
| `core/tools/__init__.py` | `register_all_tools` | 删 `set_domain_registry` 导入；加 `register_secondary_tool` 调用 |
| `core/chain_factory.py` | `_mount_tools` | 删 `set_domain_registry` block (77-81) |
| `core/tools/domain_tool.py` | 死代码 | Delete entire file |
| `config/tools.yaml` | per-layer allowlist | 加 `activate_secondary_tools` 条目 |
| `tests/test_tool_registry.py` | ToolRegistry 单测 | 删 `test_tool_domain_filtering`；加 tool_spec/secondary 测试 |
| `tests/test_secondary_tool.py` | 次工具系统测试 | Create |
| `MAINTAIN.md` | 函数级维护文档 | 更新 ToolRegistry 章节及 Changelog |

---

### Task 1: ToolEntry 字段扩展 — tool_spec + semantic_description

**Files:**
- Modify: `core/tools/registry.py:8-17` (ToolEntry dataclass)
- Test: `tests/test_tool_registry.py`

- [ ] **Step 1: Write failing test for tool_spec default and secondary filtering**

在 `tests/test_tool_registry.py` 末尾追加：

```python
class TestToolSpec:
    def test_tool_entry_default_tool_spec_is_primary(self):
        from core.tools.registry import ToolEntry
        e = ToolEntry(name="t", schema={}, handler=lambda **k: None)
        assert e.tool_spec == "primary"
        assert e.semantic_description == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tool_registry.py::TestToolSpec::test_tool_entry_default_tool_spec_is_primary -v`
Expected: FAIL — `ToolEntry.__init__() got an unexpected keyword argument 'tool_spec'`

- [ ] **Step 3: Extend ToolEntry with tool_spec and semantic_description**

Modify `core/tools/registry.py:8-17`:

```python
@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    tool_spec: str = "primary"
    semantic_description: str = ""
    sync: bool = True
    force_sync: bool = False
    check_fn: Callable | None = None
    toolset: str = "core"
    available_domains: list[str] = field(default_factory=list)
```

（`available_domains` 暂时保留，Task 4 统一删除。）

- [ ] **Step 4: Extend register() to accept tool_spec and semantic_description**

Modify `core/tools/registry.py:36-58`:

```python
    def register(self, name: str, schema: dict, handler: Callable,
                 check_fn: Callable | None = None, toolset: str = "core",
                 available_domains: list[str] | None = None,
                 override: bool = False, sync: bool = True,
                 force_sync: bool = False,
                 tool_spec: str = "primary",
                 semantic_description: str = ""):
        if available_domains is None:
            available_domains = ["general"]
        with self._lock:
            existing = self._entries.get(name)
            if existing and existing.toolset != toolset and not override:
                raise ValueError(
                    f"Tool '{name}' already registered from toolset "
                    f"'{existing.toolset}' (attempted from '{toolset}')"
                )
            tool = ToolEntry(
                name=name, schema=schema, handler=handler,
                sync=sync, force_sync=force_sync, check_fn=check_fn, toolset=toolset,
                available_domains=available_domains,
                tool_spec=tool_spec,
                semantic_description=semantic_description,
            )
            self._entries[name] = tool
            if self._registry:
                for d in tool.available_domains:
                    self._registry.index_item("tool", d, name)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_tool_registry.py::TestToolSpec::test_tool_entry_default_tool_spec_is_primary -v`
Expected: PASS

- [ ] **Step 6: Run full registry test suite to check no regression**

Run: `python -m pytest tests/test_tool_registry.py -v`
Expected: PASS (all tests including pre-existing ones)

- [ ] **Step 7: Commit**

```bash
git add core/tools/registry.py tests/test_tool_registry.py
git commit -m "feat(tools): add tool_spec and semantic_description fields to ToolEntry"
```

---

### Task 2: thread-local secondary filtering in get_definitions()

**Files:**
- Modify: `core/tools/registry.py:60-68` (get_definitions)
- Test: `tests/test_tool_registry.py`

- [ ] **Step 1: Write failing test for enable_secondary + filtering**

在 `tests/test_tool_registry.py` 的 `TestToolSpec` 类中追加（含 Task 1 未写的 hidden-by-default 测试）：

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tool_registry.py::TestToolSpec -v`
Expected: FAIL — `ToolRegistry` has no `enable_secondary`/`clear_secondary` method

- [ ] **Step 3: Add thread-local state and methods to ToolRegistry**

Modify `core/tools/registry.py:20-34` — in `__new__` add thread-local init; add helper + public methods:

```python
class ToolRegistry:
    """Thread-safe singleton tool registry. Adapted from Hermes tools/registry.py."""
    _instance: ToolRegistry | None = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._entries: dict[str, ToolEntry] = {}
                    cls._instance._enabled_secondary = threading.local()
        return cls._instance

    def __init__(self, domain_registry=None):
        self._registry = domain_registry

    def _get_enabled_secondary(self) -> set[str]:
        """Return current thread's enabled secondary set (lazy-init to empty set)."""
        s = getattr(self._enabled_secondary, "set", None)
        if s is None:
            s = set()
            self._enabled_secondary.set = s
        return s

    def enable_secondary(self, names: list[str]) -> int:
        """Add secondary tool names to current thread's enabled set.

        Returns count of names that correspond to actually-registered secondary tools.
        """
        with self._lock:
            valid = {n for n, e in self._entries.items() if e.tool_spec == "secondary"}
        wanted = set(names) & valid
        enabled = self._get_enabled_secondary()
        enabled |= wanted
        return len(wanted)

    def clear_secondary(self) -> None:
        """Clear current thread's enabled secondary set."""
        self._enabled_secondary.set = set()
```

- [ ] **Step 4: Add secondary filter to get_definitions()**

Modify `core/tools/registry.py:60-68`:

```python
    def get_definitions(self, requested: set[str] | None = None) -> list[dict]:
        enabled = self._get_enabled_secondary()
        with self._lock:
            entries = self._entries.values()
            if requested:
                entries = [e for e in entries if e.name in requested]
            return [
                e.schema for e in entries
                if (e.check_fn is None or e.check_fn())
                and not (e.tool_spec == "secondary" and e.name not in enabled)
            ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_tool_registry.py::TestToolSpec -v`
Expected: PASS (all 6 tests)

- [ ] **Step 6: Run full registry test suite to check no regression**

Run: `python -m pytest tests/test_tool_registry.py -v`
Expected: PASS (all tests including pre-existing ones)

- [ ] **Step 7: Commit**

```bash
git add core/tools/registry.py tests/test_tool_registry.py
git commit -m "feat(tools): thread-local secondary tool filtering in get_definitions"
```

---

### Task 3: activate_secondary_tools 工具 — 注册 + handler

**Files:**
- Create: `core/tools/secondary_tool.py`
- Test: `tests/test_secondary_tool.py`

- [ ] **Step 1: Write failing test for handler with mock LLM**

Create `tests/test_secondary_tool.py`:

```python
import json
import pytest
from core.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _clear_registry():
    ToolRegistry().clear()
    ToolRegistry().clear_secondary()


class FakeLLMResponse:
    def __init__(self, text):
        self.text = text


class FakeLLM:
    def __init__(self, response_text):
        self._response_text = response_text

    def chat(self, messages, tools=None, json_mode=False, **kwargs):
        return FakeLLMResponse(self._response_text)


class TestActivateSecondaryTools:
    def test_handler_enables_matching_secondary_tools(self):
        from core.tools.secondary_tool import _activate_secondary_tools_handler, _set_llm_for_test

        r = ToolRegistry()
        r.register("douzero_encode_hand",
                   {"type": "function", "function": {"name": "douzero_encode_hand", "description": "", "parameters": {}}},
                   lambda args, **kw: "{}",
                   tool_spec="secondary",
                   semantic_description="将斗地主手牌编码为 DouZero 模型输入格式")
        r.register("web_fetch",
                   {"type": "function", "function": {"name": "web_fetch", "description": "", "parameters": {}}},
                   lambda args, **kw: "{}",
                   tool_spec="secondary",
                   semantic_description="抓取网页内容")
        r.clear_secondary()

        fake_llm = FakeLLM(json.dumps({"tools": [{"name": "douzero_encode_hand", "reason": "斗地主编码"}]}))
        _set_llm_for_test(fake_llm)

        result = _activate_secondary_tools_handler({"query": "我需要斗地主手牌编码工具"})
        data = json.loads(result)
        assert "douzero_encode_hand" in data["enabled"]
        assert data["total_candidates"] == 2

        defs = r.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "douzero_encode_hand" in names

    def test_handler_no_match_returns_empty(self):
        from core.tools.secondary_tool import _activate_secondary_tools_handler, _set_llm_for_test

        r = ToolRegistry()
        r.register("douzero_encode_hand",
                   {"type": "function", "function": {"name": "douzero_encode_hand", "description": "", "parameters": {}}},
                   lambda args, **kw: "{}",
                   tool_spec="secondary",
                   semantic_description="将斗地主手牌编码为 DouZero 模型输入格式")
        r.clear_secondary()

        fake_llm = FakeLLM(json.dumps({"tools": []}))
        _set_llm_for_test(fake_llm)

        result = _activate_secondary_tools_handler({"query": "我需要一个烹饪工具"})
        data = json.loads(result)
        assert data["enabled"] == []
        assert data["total_candidates"] == 1

    def test_handler_no_secondary_tools_returns_empty(self):
        from core.tools.secondary_tool import _activate_secondary_tools_handler, _set_llm_for_test

        r = ToolRegistry()
        r.clear_secondary()
        _set_llm_for_test(FakeLLM('{"tools": []}'))

        result = _activate_secondary_tools_handler({"query": "anything"})
        data = json.loads(result)
        assert data["enabled"] == []
        assert data["total_candidates"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_secondary_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.tools.secondary_tool'`

- [ ] **Step 3: Create secondary_tool.py with handler + registration**

Create `core/tools/secondary_tool.py`:

```python
"""Secondary tool activation — Agent searches and enables secondary tools on demand."""
from __future__ import annotations
import json
import logging

logger = logging.getLogger(__name__)

_test_llm = None


def _set_llm_for_test(llm):
    """Inject a fake LLM client for testing."""
    global _test_llm
    _test_llm = llm


def _get_llm():
    if _test_llm is not None:
        return _test_llm
    from core.runtime_registry import get_executor
    executor = get_executor()
    if executor is not None:
        return executor._llm
    from core.llm_factory import build_llm_client
    return build_llm_client(temperature=0.1)


def _activate_secondary_tools_handler(args: dict | None = None, **kwargs) -> str:
    from core.tools.registry import ToolRegistry

    args = args or {}
    query = args.get("query", "")
    top_k = args.get("top_k", 10)

    if not query:
        return json.dumps({"error": "query is required"})

    registry = ToolRegistry()
    with registry._lock:
        candidates = [
            {"name": e.name, "semantic_description": e.semantic_description}
            for e in registry._entries.values()
            if e.tool_spec == "secondary"
        ]

    if not candidates:
        return json.dumps({"enabled": [], "total_candidates": 0})

    index_text = "\n".join(
        f"- {c['name']}: {c['semantic_description']}" for c in candidates
    )

    prompt = (
        f"你是一个工具匹配系统。以下是可以用的次级工具列表：\n\n"
        f"{index_text}\n\n"
        f"用户需要以下功能的工具：\n"
        f'"{query}"\n\n'
        f"请从上面的列表中选出最匹配的工具（最多 {top_k} 个），以 JSON 格式返回。\n"
        f"如果所有工具都不匹配，返回空列表。\n\n"
        f'输出格式：\n'
        f'{{"tools": [{{"name": "tool_name", "reason": "为什么匹配"}}]}}'
    )

    messages = [
        {"role": "system", "content": "你是一个工具匹配系统，只输出 JSON。"},
        {"role": "user", "content": prompt},
    ]

    try:
        llm = _get_llm()
        resp = llm.chat(messages=messages, json_mode=True)
        text = resp.text if hasattr(resp, "text") else str(resp)
        parsed = json.loads(text)
        matched_names = [t.get("name", "") for t in parsed.get("tools", [])]
    except Exception as e:
        logger.warning("activate_secondary_tools LLM call failed: %s", e)
        return json.dumps({"error": str(e), "total_candidates": len(candidates)})

    count = registry.enable_secondary(matched_names)
    return json.dumps({
        "enabled": [n for n in matched_names if n],
        "total_candidates": len(candidates),
    }, ensure_ascii=False)


def register_secondary_tool(registry):
    """Register activate_secondary_tools as a primary tool visible to all layers."""
    registry.register(
        "activate_secondary_tools",
        {
            "type": "function",
            "function": {
                "name": "activate_secondary_tools",
                "description": (
                    "搜索并激活可用的次级工具。用自然语言描述需求，系统会匹配并启用合适的次工具。"
                    "激活后的工具在当前 session 内对所有层可见。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "用自然语言描述你需要什么功能的工具",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "最多激活 N 个工具，默认 10",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        _activate_secondary_tools_handler,
        sync=True,
        toolset="core",
        tool_spec="primary",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_secondary_tool.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add core/tools/secondary_tool.py tests/test_secondary_tool.py
git commit -m "feat(tools): add activate_secondary_tools tool with LLM subagent screening"
```

---

### Task 4: 删除 available_domains 死代码 + domain_tool.py

**Files:**
- Modify: `core/tools/registry.py` (remove available_domains from ToolEntry, register, get_tools_for_domain)
- Delete: `core/tools/domain_tool.py`
- Modify: `core/tools/__init__.py:17` (remove import)
- Modify: `core/chain_factory.py:77-81` (remove set_domain_registry block)
- Modify: `tests/test_tool_registry.py` (remove test_tool_domain_filtering)

- [ ] **Step 1: Write test to confirm available_domains removal doesn't break anything**

在 `tests/test_tool_registry.py` 末尾追加一个确认性测试：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tool_registry.py::TestAvailableDomainsRemoved -v`
Expected: FAIL — `test_register_rejects_available_domains_param` fails because param still accepted

- [ ] **Step 3: Remove available_domains from ToolEntry and register()**

Modify `core/tools/registry.py:8-17` — remove `available_domains` line from ToolEntry:

```python
@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    tool_spec: str = "primary"
    semantic_description: str = ""
    sync: bool = True
    force_sync: bool = False
    check_fn: Callable | None = None
    toolset: str = "core"
```

Modify `register()` method — remove `available_domains` parameter, defaulting logic, and DomainRegistry indexing block:

```python
    def register(self, name: str, schema: dict, handler: Callable,
                 check_fn: Callable | None = None, toolset: str = "core",
                 override: bool = False, sync: bool = True,
                 force_sync: bool = False,
                 tool_spec: str = "primary",
                 semantic_description: str = ""):
        with self._lock:
            existing = self._entries.get(name)
            if existing and existing.toolset != toolset and not override:
                raise ValueError(
                    f"Tool '{name}' already registered from toolset "
                    f"'{existing.toolset}' (attempted from '{toolset}')"
                )
            tool = ToolEntry(
                name=name, schema=schema, handler=handler,
                sync=sync, force_sync=force_sync, check_fn=check_fn, toolset=toolset,
                tool_spec=tool_spec,
                semantic_description=semantic_description,
            )
            self._entries[name] = tool
```

- [ ] **Step 4: Remove get_tools_for_domain method**

Delete the entire `get_tools_for_domain` method from `core/tools/registry.py`:

```python
    def get_tools_for_domain(self, domain: str) -> list[ToolEntry]:
        if self._registry:
            ids = self._registry.get_primary_items("tool", domain)
            return [t for t in self._entries.values() if t.name in ids]
        return list(self._entries.values())
```

- [ ] **Step 5: Remove test_tool_domain_filtering test**

Delete `tests/test_tool_registry.py:94-109` (the `test_tool_domain_filtering` method).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_tool_registry.py -v`
Expected: PASS (all tests, including new TestAvailableDomainsRemoved)

- [ ] **Step 7: Delete domain_tool.py and clean up references**

Delete the file `core/tools/domain_tool.py`.

Modify `core/tools/__init__.py:17` — remove the import line:
```python
from core.tools.domain_tool import set_domain_registry
```

Modify `core/chain_factory.py:77-81` — remove the `set_domain_registry` block:

```python
    from core.tools.domain_tool import set_domain_registry
    for layer in _iter_layers(chain):
        if layer._registry:
            set_domain_registry(layer._registry)
            break
```

- [ ] **Step 8: Run full test suite to check no regression**

Run: `python -m pytest tests/ -x --timeout=60 -q`
Expected: PASS (no import errors, no failures referencing removed code)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(tools): remove dead available_domains field and domain_tool.py"
```

---

### Task 5: 注册 activate_secondary_tools 到 register_all_tools + tools.yaml

**Files:**
- Modify: `core/tools/__init__.py`
- Modify: `config/tools.yaml`

- [ ] **Step 1: Add register_secondary_tool call to register_all_tools**

Modify `core/tools/__init__.py` — add import and call after the other tool registrations (before the `if proposal_dir:` block):

```python
    from core.tools.secondary_tool import register_secondary_tool
    register_secondary_tool(registry)
```

完整修改后的 `register_all_tools` 尾部：

```python
    from core.tools.downward_comm_tool import register_downward_tools
    register_downward_tools(registry)

    from core.tools.secondary_tool import register_secondary_tool
    register_secondary_tool(registry)

    if proposal_dir:
        set_proposal_dir(proposal_dir)
```

- [ ] **Step 2: Add activate_secondary_tools entry to tools.yaml**

在 `config/tools.yaml` 末尾（`l2_query:` 条目之后）追加：

```yaml
  # ── Secondary tool activation ──
  activate_secondary_tools:
    sync: true
    timeout: 30
    allowlist: [l1, l2, l3]
    fallback:
      max_retries: 0
      degrade: []
```

- [ ] **Step 3: Write integration test — verify activate_secondary_tools is visible to all layers**

在 `tests/test_secondary_tool.py` 追加：

```python
class TestSecondaryToolRegistration:
    def test_activate_secondary_tools_registered_as_primary_visible(self):
        from core.tools import register_all_tools
        r = ToolRegistry()
        register_all_tools(r)
        defs = r.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "activate_secondary_tools" in names
```

- [ ] **Step 4: Run integration test**

Run: `python -m pytest tests/test_secondary_tool.py::TestSecondaryToolRegistration -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -x --timeout=60 -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/tools/__init__.py config/tools.yaml tests/test_secondary_tool.py
git commit -m "feat(tools): register activate_secondary_tools to all layers"
```

---

### Task 6: 更新 MAINTAIN.md + README.md

**Files:**
- Modify: `MAINTAIN.md`
- Modify: `README.md`

- [ ] **Step 1: Update ToolRegistry section in MAINTAIN.md**

找到 MAINTAIN.md 中 `## core/tools/registry.py` 章节（约 45-57 行），替换为：

```markdown
## core/tools/registry.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `ToolEntry` | `@dataclass(name, schema, handler, tool_spec, semantic_description, sync, force_sync, check_fn, toolset)` | 工具条目数据类，含主/次标记及次工具语义描述 | ToolRegistry | — |
| `ToolRegistry` | `__init__(domain_registry=None)` → singleton | 线程安全工具注册中心，支持主/次工具区分 + thread-local 次工具启用 | setup scripts, LayerAgent | — |
| `ToolRegistry.register` | `(name, schema, handler, check_fn, toolset, override, sync, force_sync, tool_spec, semantic_description)` | 注册工具（主/次统一），次工具默认不可见 | setup scripts | — |
| `ToolRegistry.get_definitions` | `(requested=None) → list[dict]` | 获取可见工具的 OpenAI schema 列表；次工具仅在当前线程已启用时返回 | Executor, LayerInjector | — |
| `ToolRegistry.dispatch` | `(name, args, context=None, timeout=None) → str` | 按名分发工具调用 | ToolCapability | entry.handler() |
| `ToolRegistry.deregister` | `(name)` | 注销工具 | — | — |
| `ToolRegistry.enable_secondary` | `(names: list[str]) → int` | 将次工具加入当前线程的可用集，返回成功数 | activate_secondary_tools handler | — |
| `ToolRegistry.clear_secondary` | `() → None` | 清空当前线程的次工具可用集（Gradio session 切换时调用） | session teardown | — |
| `ToolRegistry.clear` | `()` | 重置所有条目（仅测试用） | test fixtures | — |

## core/tools/secondary_tool.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `register_secondary_tool` | `(registry)` | 注册 activate_secondary_tools 工具（tool_spec="primary"，所有层可见） | register_all_tools() | ToolRegistry.register() |
| `_activate_secondary_tools_handler` | `(args) → str` | 收集次工具 semantic_description → LLM subagent 筛选 → enable_secondary() → 返回启用列表 | ToolRegistry.dispatch | ToolRegistry.enable_secondary(), LLM.chat() |
| `_get_llm` | `() → LLMClient` | 获取 LLM 实例（优先用 test 注入，其次 executor 的 llm，最后 build_llm_client） | _activate_secondary_tools_handler | runtime_registry.get_executor / build_llm_client |
| `_set_llm_for_test` | `(llm) → None` | 测试用：注入 fake LLM 客户端 | test fixtures | — |
```

- [ ] **Step 2: Add Changelog entry to MAINTAIN.md**

在 MAINTAIN.md Changelog 表格顶部（`| 日期 | 变更 |` 表头后第一行）追加：

```markdown
| 2026-06-22 | **次工具系统**：新增 `core/tools/secondary_tool.py` — `activate_secondary_tools` 工具（LLM subagent 筛选次工具池的 `semantic_description` → `ToolRegistry.enable_secondary()` 启用当前线程）。ToolEntry 新增 `tool_spec`（"primary"/"secondary"）+ `semantic_description` 字段；ToolRegistry 新增 thread-local `_enabled_secondary` + `enable_secondary`/`clear_secondary`/`_get_enabled_secondary` 方法；`get_definitions()` 按确定性逻辑过滤次工具（仅已启用返回）。删除死代码：`ToolEntry.available_domains` 字段、`register()` 中 DomainRegistry 索引块、`get_tools_for_domain()` 方法、`core/tools/domain_tool.py` 整个文件、`chain_factory.py` 中 `set_domain_registry` block。config/tools.yaml 新增 `activate_secondary_tools` 条目（allowlist [l1,l2,l3]）。 |
```

- [ ] **Step 3: Update README.md tool table**

在 `README.md` 工具表中 `l1_query`/`l2_query` 行之后追加：

```markdown
| `activate_secondary_tools` | 搜索并激活次级工具（LLM subagent 筛选 + thread-local 启用） | `core/tools/secondary_tool.py` |
```

并在层可见性表格中，L1/L2/L3 行末尾追加 `, activate_secondary_tools`。

- [ ] **Step 4: Add secondary tools section to README.md**

在 `README.md` 的「工具系统」章节之后、「工具调整路线图」之前，插入：

```markdown
## 次级工具系统

主工具数量严格控制在 50 以内，保证 LLM 工具选择精度。次级工具（secondary tools）按场景需要懒加载：

- **注册**：次工具和主工具统一注册到 `ToolRegistry`，仅 `tool_spec="secondary"` 区分
- **默认不可见**：`get_definitions()` 过滤次工具，除非当前线程已启用
- **Agent 自主发现**：Agent 调用 `activate_secondary_tools(query)` 工具，LLM subagent 扫描次工具池的 `semantic_description` 做匹配，匹配结果通过 `ToolRegistry.enable_secondary()` 注入当前线程
- **Session 级隔离**：基于 `threading.local()`，CLI 线程终止自动清零，Gradio session 切换时显式 `clear_secondary()`
- **层可见性**：次工具不区分 L1/L2/L3，对所有层平等可见，由 Agent prompt 和场景语义自然约束

详见 [docs/superpowers/specs/2026-06-22-secondary-tools-design.md](docs/superpowers/specs/2026-06-22-secondary-tools-design.md)。
```

- [ ] **Step 5: Commit**

```bash
git add MAINTAIN.md README.md
git commit -m "docs: update MAINTAIN and README for secondary tools system"
```

---

### Task 7: 全量验证

**Files:** 无修改

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --timeout=120`
Expected: ALL PASS

- [ ] **Step 2: Run lint/typecheck if available**

Run: `python -m py_compile core/tools/registry.py core/tools/secondary_tool.py core/tools/__init__.py core/chain_factory.py`
Expected: No errors

- [ ] **Step 3: Verify no stale references to removed code**

Run: `python -c "import core.tools.domain_tool"`
Expected: `ModuleNotFoundError` (file deleted)

Run grep to confirm no remaining references:
Run: `grep -r "set_domain_registry\|get_tools_for_domain\|available_domains" core/ --include="*.py"`
Expected: Only references in KnowledgeCard/SkillMeta (those are different dataclasses, NOT ToolEntry) — no references in `core/tools/registry.py`

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup after secondary tools implementation" --allow-empty
```
