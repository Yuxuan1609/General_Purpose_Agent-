# Capability System — 实现计划

> 对应 spec: `docs/superpowers/specs/2026-06-06-capability-system-design.md`
>
> 核心原则：每个任务**新增文件为主 + 现有代码最小侵入**。不改动的模块完全不受影响。

## 任务总览

| 序号 | 任务 | 新增文件 | 改动文件 | 依赖 |
|------|------|---------|---------|------|
| T0 | Capability ABC + Registry | `capability/__init__.py` | — | 无 |
| T1 | ToolCapability 实现 | `capability/tool_capability.py` | — | T0 |
| T2 | KnowledgeCapability + 基础 Store | `capability/knowledge_capability.py` | — | T0 |
| T3 | LayerInjector | `capability/layer_injector.py` | — | T0, T1, T2 |
| T4 | Consolidation 容量监测 | — | `core/env/learning_env.py`（加 2 个方法） | 无 |
| T5 | 示例工具注册（read_file, grep） | `capability/example_tools.py` | — | T1 |
| T6 | 集成测试 + 烟雾测试 | `tests/test_capability.py` | — | T0-T5 |

## 任务详解

### T0 — Capability ABC + Registry

**文件**: `capability/__init__.py`

**内容**:
- `CapabilityResult` frozen dataclass
- `Capability` ABC：`name` / `get_schema()` / `invoke()` / `is_visible_to()`
- `CapabilityRegistry`：`register()` / `get_schemas_for_layer()` / `invoke()` / `list_for_layer()`

**零依赖**：不 import 任何项目内模块。仅依赖 `abc` / `dataclasses` / `typing`。

**验证**:
```python
# 直接在 capability/__init__.py 底部 if __name__ == "__main__": 做简单的自测
class _MockCap(Capability):
    name = "mock"
    def get_schema(self): return {"name": "mock"}
    def invoke(self, layer, args): return CapabilityResult(capability_name="mock", layer=layer, success=True, data={"ok": True})
    def is_visible_to(self, layer): return layer == "l2"

reg = CapabilityRegistry()
reg.register(_MockCap())
assert len(reg.get_schemas_for_layer("l2")) == 1
assert len(reg.get_schemas_for_layer("l1")) == 0
```

---

### T1 — ToolCapability 实现

**文件**: `capability/tool_capability.py`

**内容**:
- `ToolCapability(Capability)`：包装 `ToolRegistry`，加层可见 allowlist
- `get_schema()`：返回 OpenAI function-calling 格式的工具列表（仅该层可见的工具）
- `invoke(layer, args)`：校验层权限 → 调 `ToolRegistry.dispatch()` → 返回 `CapabilityResult`
- `is_visible_to(layer)`：该层是否至少有一个工具可见

**依赖**: `core/tools/registry.py`（只读引用，不修改）

**示例 allowlist 配置**:
```python
DEFAULT_TOOL_ALLOWLIST = {
    "l1": {"todo"},
    "l2": {"todo", "terminal"},
    "l3": {"todo", "terminal", "web_search", "skills_list", "skill_view", "skill_manage"},
}
```

**接口设计要点**: `ToolCapability` 暴露一个 `get_schemas_by_layer(layer)` 方法供 `LayerInjector` 使用，返回该层可见工具的 OpenAI schema 列表。

---

### T2 — KnowledgeCapability + 基础 Store

**文件**: `capability/knowledge_capability.py`

**内容**:
- `BaseKnowledgeStore` ABC：`search()` / `get()` / `add()` / `remove()` / `list_ids()`
- `InMemoryKnowledgeStore`：内存 dict 实现，简单关键词匹配
- `KnowledgeCapability(Capability)`：管理多个 `(store, visible_layers)` 对
- `get_schema()`：返回单个 `knowledge_query` 工具 schema（store 名作为 enum 参数）
- `invoke(layer, args)`：校验 store 权限 → 调 `store.search()` → 返回 `CapabilityResult`

**零依赖**（不依赖项目内任何模块）

**附带种子数据**（放在 `capability/knowledge_capability.py` 内或 `data/knowledge/` 下）：

```python
# 种子知识 store —— 用于验证 KnowledgeCapability 流程
def seed_knowledge_stores() -> dict[str, InMemoryKnowledgeStore]:
    game_rules = InMemoryKnowledgeStore()
    game_rules.add("leduc_basics", "Leduc Hold'em: 2人，6张牌(K/Q/J)，两轮下注...")
    game_rules.add("leduc_preflop", "翻牌前: K=加注, Q=跟注评估, J=弃牌倾向...")

    design_docs = InMemoryKnowledgeStore()
    design_docs.add("a1", "A1: 层间严格相邻传递，禁止跨层跳跃")
    design_docs.add("a2", "A2: 统一 LayerMessage 信封")

    return {"game_rules": game_rules, "design_docs": design_docs}
```

---

### T3 — LayerInjector

**文件**: `capability/layer_injector.py`

**内容**:
- `LayerInjector.__init__(registry: CapabilityRegistry)`
- `get_tools_for_layer(layer) → list[dict]`：聚合 ToolCapability + KnowledgeCapability 的 schema
- `inject_to_agent(layer, call_kwargs: dict) → dict`：在 `call_kwargs` 中注入 `tools` 字段
- `handle_tool_calls(layer, tool_calls: list[dict]) → list[CapabilityResult]`：执行 LLM 返回的 tool_calls

**关键设计 —— 如何不改 `LayerAgent._call_llm()` 签名**:

当前 `LayerAgent._call_llm()`（`core/layers/base.py:27-60`）:
```python
def _call_llm(self, system: str, user: str, schema: dict | None = None) -> dict:
    resp = self._llm.chat(messages=[...], json_mode=bool(schema))
```

方案：在 `_call_llm` 签名中加一个可选参数 `tools: list[dict] | None = None`，然后传递给 `self._llm.chat()` 的 `tools` 参数。改动范围：`base.py` 一行的函数签名 + 调用处传参。

```python
def _call_llm(self, system: str, user: str,
              schema: dict | None = None,
              tools: list[dict] | None = None) -> dict:
    resp = self._llm.chat(
        messages=[...],
        json_mode=bool(schema),
        tools=tools,                    # 新增
    )
```

对应的 `LLMClient.chat()` 也需要支持 `tools` 参数（当前 `core/llm_client.py` 已有 `json_mode`，加 `tools` 是向前兼容扩展）。

---

### T4 — Consolidation 容量监测

**文件**: `core/env/learning_env.py`（改动）

**新增方法**:
```python
def needs_consolidation(self) -> bool:
    """检查是否有层超过容量上限"""
    ...

def get_consolidation_level(self) -> int:
    """1=例行整理, 2=深度整理"""
    ...
```

**改动**: `LearningEnv.__init__` 增加可选参数 `limits: dict | None = None`。

`build_consolidation_task()` 已有，无需修改。

---

### T5 — 示例工具注册

**文件**: `capability/example_tools.py`

**内容**:
- `read_file` 工具：读取文件，支持 offset/limit
- `grep` 工具：正则搜索文件内容

这些工具使用 `ToolRegistry.register()` 注册，遵循现有模式（OpenAI function-calling schema + handler 函数）。

**为什么放 capability/ 下而不是 core/tools/**: 新工具是 capability 系统的验证手段，不是核心架构的一部分。稳定后可迁到 `core/tools/`。

---

### T6 — 集成测试

**文件**: `tests/test_capability.py`

**测试用例**:

| 用例 | 内容 |
|------|------|
| `test_registry_register_and_query` | CapabilityRegistry 注册 + 按层查询 schema |
| `test_tool_allowlist` | ToolCapability 的层可见性控制正确 |
| `test_tool_invoke_allowed` | 允许的层调用工具成功 |
| `test_tool_invoke_denied` | 不允许的层调用工具被拒绝 |
| `test_knowledge_search` | KnowledgeCapability 搜索返回正确结果 |
| `test_knowledge_layer_visibility` | 层可见性过滤正确 |
| `test_injector_injects_tools` | LayerInjector 正确注入 tools 到 call_kwargs |
| `test_injector_handles_tool_calls` | 处理 tool_calls 返回正确 CapabilityResult |
| `test_learning_env_needs_consolidation` | 超限检测正确触发 |

**Mock 策略**:
- `ToolRegistry` 已有 mock 模板（`tests/conftest.py`）
- `LLMClient` 使用 `scripts/mock_llm.py` 的 `MockLLMClient`
- KnowledgeStore 直接用 `InMemoryKnowledgeStore`，无需 mock

---

## 实施顺序（严格依赖链）

```
T0 (ABC + Registry)
 ├─→ T1 (ToolCapability)
 │    └─→ T5 (example tools)
 ├─→ T2 (KnowledgeCapability)
 └─→ T3 (LayerInjector)  ← 依赖 T1 + T2 的 get_schema()
      └─→ T6 (integration tests)

T4 (consolidation) —— 独立，可并行于 T1-T3
```

## 目录结构（新增）

```
capability/                    # 新模块（与 core/ 平级）
  __init__.py                  # T0: Capability ABC + CapabilityRegistry
  tool_capability.py           # T1: ToolCapability
  knowledge_capability.py      # T2: KnowledgeCapability + BaseKnowledgeStore + InMemoryKnowledgeStore
  layer_injector.py            # T3: LayerInjector
  example_tools.py             # T5: read_file / grep 示例工具

tests/
  test_capability.py           # T6: 集成测试
```

## 代码行数预估

| 文件 | 预估行数 |
|------|---------|
| `capability/__init__.py` | ~80 |
| `capability/tool_capability.py` | ~100 |
| `capability/knowledge_capability.py` | ~160 |
| `capability/layer_injector.py` | ~90 |
| `capability/example_tools.py` | ~80 |
| `tests/test_capability.py` | ~200 |
| `core/env/learning_env.py`（改动） | +30 |
| `core/layers/base.py`（改动） | +5 |
| **总计新增+改动** | ~745 |
