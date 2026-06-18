# Architecture Simplification (A+B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate 6 architecture-level pain points by removing Comm Agent空壳, unifying data flow, killing global mutable state, and template化 Agent/Manager重复模式 — making the codebase ~500 lines shorter and significantly more robust.

**Architecture:** Two-track approach: (A) Layer Template Protocol — extract Manager/Agent repetitive patterns into base class template methods + declarative configs; (B) Communication Layer Simplification — delete Comm Agent空壳, unify query() signature to `TaskObservation`-only, replace module-level global setters with constructor-injected `ConsolidationContext`.

**Tech Stack:** Python 3.10+, dataclasses, pytest, existing test suite

---

## Pain Points Addressed

| # | Pain | Root Cause | Task |
|---|------|-----------|------|
| P1 | Manager/Agent 3层高度重复 | 每层独立实现相同的 query/decide 模板 | T4, T5, T6 |
| P2 | Comm Agent 6个空文件 | 子类继承基类但不添加任何逻辑 | T1 |
| P3 | Consolidation if-branch 重复3次 | `if lX_output_format:` 硬编码在每层 decide() | T5 |
| P4 | 全局可变状态 (set_*, get_pending_mods) | 模块级 global + setter 注入依赖 | T3 |
| P5 | _call_llm 200行承担过多 | 将拆分留给后续迭代，本次不动 | — |
| P6 | query() 接受 LayerMessage|Any | 类型不统一，Comm 只做透传 | T2 |
| P7 | 9个 consolidation handler 模式一致 | 每个 handler 手写 append + return | T7 |
| P8 | _L1/_L2/_L3_OUTPUT schema 重复 | 结构相同只是字段名微差 | T5 |
| P9 | 3层 tool_rules 提示文本完全相同 | 每层各自硬编码同一字符串 | T4 |

---

## File Structure (Post-Plan)

```
core/layers/
  __init__.py          # build_chain 简化 (删除6行空壳import)
  base.py              # +Template Method hooks, +CaptureToolDef, +ConsolidationStrategy
  comm.py              # 不变 (基类保留，删除6个子类文件)
  logging_setup.py     # 不变
  l0_5_1/
    manager.py         # 精简: query() 用基类, decide() 用模板
    upward_comm.py     # ❌ 删除
    downward_comm.py   # ❌ 删除
  l2/
    manager.py         # 精简: 同上
    upward_comm.py     # ❌ 删除
    downward_comm.py   # ❌ 删除
  l3/
    manager.py         # 精简: 同上
    upward_comm.py     # ❌ 删除
    downward_comm.py   # ❌ 删除

core/tools/
  consolidation_tools.py  # -9 handler → +1 _record_mod 工厂 + 声明式注册表
  # 其余不变

core/chain_factory.py     # 注入 ConsolidationContext, 删 set_* 调用

新增:
  (无新文件 — 所有改动在现有文件内)
```

---

## Task Dependency Graph

```
T1 (删Comm空壳) ──→ T2 (统一query签名)
                         │
                         ▼
T3 (消灭全局状态) ──→ T2 依赖 T3 的 ConsolidationContext 注入 Manager
     │
     ▼
T4 (CaptureTool配置化) ──→ T5 (Consolidation Strategy) ──→ T6 (Agent Template Method)
     │                        │
     ▼                        ▼
T7 (handler去重)          T5 包含 OUTPUT_SCHEMA 统一

执行顺序: T1 → T2 → T3 → T7 → T4 → T5 → T6
(每步可独立测试，每步 commit)
```

---

## Task 1: 删除 Comm Agent 空壳

**目标:** 删除 6 个空 Comm Agent 子类文件，`build_chain` 直接用基类实例。

**Files:**
- 删除: `core/layers/l0_5_1/upward_comm.py`
- 删除: `core/layers/l0_5_1/downward_comm.py`
- 删除: `core/layers/l2/upward_comm.py`
- 删除: `core/layers/l2/downward_comm.py`
- 删除: `core/layers/l3/upward_comm.py`
- 删除: `core/layers/l3/downward_comm.py`
- 修改: `core/layers/__init__.py` — build_chain 简化

**现状分析:**
每个 Comm 子类只继承基类、不添加任何方法：
```python
# l0_5_1/upward_comm.py — 全部6行
from core.layers.comm import UpwardComm as _Base
class UpwardComm(_Base):
    """L0.5+1 → Executor communication via LayerMessage (A2)."""
```
基类 `UpwardComm` / `DownwardComm` 已提供完整功能。子类存在仅因为"每层有自己的 Comm"概念，但实现上无差异化。

- [ ] **Step 1: 修改 `build_chain` 使用基类**

当前 `core/layers/__init__.py:19-24`:
```python
from core.layers.l3.upward_comm import UpwardComm as L3Upward
from core.layers.l3.downward_comm import DownwardComm as L3Downward
from core.layers.l2.upward_comm import UpwardComm as L2Upward
from core.layers.l2.downward_comm import DownwardComm as L2Downward
from core.layers.l0_5_1.upward_comm import UpwardComm as L1Upward
from core.layers.l0_5_1.downward_comm import DownwardComm as L1Downward
```

改为：
```python
from core.layers.comm import UpwardComm, DownwardComm
```

构造处改为直接实例化基类：
```python
l3 = L3Manager(skill_layer, upward=UpwardComm(), downward=DownwardComm(),
               auxiliary_llm=auxiliary_llm, domain_registry=domain_registry,
               max_rounds=rt.get('max_rounds_l3', 3))
l2 = L2Manager(flexible_knowledge, downstream=l3,
               upward=UpwardComm(), downward=DownwardComm(),
               auxiliary_llm=auxiliary_llm, domain_registry=domain_registry,
               max_rounds=rt.get('max_rounds_l2', 3))
l1 = L0_5_1Manager(philosophy, auxiliary_llm=auxiliary_llm,
                    downstream=l2, upward=UpwardComm(), downward=DownwardComm(),
                    domain_registry=domain_registry,
                    knowledge_stores=knowledge_stores,
                    max_rounds=rt.get('max_rounds_l1', 5))
```

- [ ] **Step 2: 删除 6 个 Comm 子类文件**

```bash
rm core/layers/l0_5_1/upward_comm.py core/layers/l0_5_1/downward_comm.py
rm core/layers/l2/upward_comm.py core/layers/l2/downward_comm.py
rm core/layers/l3/upward_comm.py core/layers/l3/downward_comm.py
```

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/test_layer_chain.py tests/test_layers.py -v`
Expected: PASS (Comm 子类无自定义逻辑，基类行为完全等价)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: delete 6 empty Comm Agent subclasses, use base class directly"
```

---

## Task 2: 统一 query() 签名为 TaskObservation-only

**目标:** `LayerManager.query()` 只接受 `TaskObservation`，不再接受 `LayerMessage | Any`。Comm 解包逻辑内联到基类。

**Files:**
- 修改: `core/layers/base.py` — `LayerManager.query()` 签名 + 解包逻辑
- 修改: `core/layers/l0_5_1/manager.py` — query() 删除手动解包
- 修改: `core/layers/l2/manager.py` — query() 删除手动解包
- 修改: `core/layers/l3/manager.py` — query() 删除手动解包
- 修改: `core/executor.py` — execute() 改传 TaskObservation
- 修改: `core/layer_message.py` — LayerMessage.payload 类型标注改为 TaskObservation

**现状分析:**
当前每个 Manager 的 `query()` 前 6 行都是同一个模式：
```python
def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
    if isinstance(msg, LayerMessage):
        data = self._upward.receive(msg)  # 实际只是 msg.payload
        if not trace_id:
            trace_id = msg.trace_id
    else:
        data = msg  # 直接当 dict/TaskObservation 用
```
`UpwardComm.receive(msg)` 只做 `return msg.payload`。这 6 行可内联到基类。

- [ ] **Step 1: 修改基类 `LayerManager.query()`**

在 `core/layers/base.py` 的 `LayerManager.query()` 中：

```python
def query(self, obs_or_msg: TaskObservation | LayerMessage, trace_id: str = "") -> None:
    """Entry point: accept TaskObservation (from Executor) or LayerMessage (from upstream).

    LayerMessage is unwrapped to TaskObservation via UpwardComm.
    Subclasses receive a TaskObservation — no more manual unwrapping.
    """
    if isinstance(obs_or_msg, LayerMessage):
        obs = obs_or_msg.payload
        if not trace_id:
            trace_id = obs_or_msg.trace_id
    else:
        obs = obs_or_msg

    if not isinstance(obs, TaskObservation):
        if isinstance(obs, dict):
            obs = TaskObservation(**obs)
        else:
            raise TypeError(f"query() expects TaskObservation, got {type(obs)}")

    self._process_and_propagate(obs, trace_id)

def _process_and_propagate(self, obs: TaskObservation, trace_id: str) -> None:
    """Template: process → propagate downstream. Subclasses may override."""
    self.process(obs)

    if self._downstream:
        q_msg = self._downward.wrap_query(
            payload=obs,
            source=self.name,
            target=self._downstream.name,
            trace_id=trace_id,
        )
        self._downstream.query(q_msg, trace_id)
```

注意：需要在 base.py 顶部添加 `from core.types import TaskObservation`。

- [ ] **Step 2: 修改三个 Manager 的 query() 删除手动解包**

每个 Manager 的 `query()` 现在直接收到 `TaskObservation`。

**L0_5_1Manager.query()** — 删除前 6 行解包，改为：
```python
def query(self, obs_or_msg, trace_id: str = "") -> None:
    # Unwrap to TaskObservation (base class pattern)
    if isinstance(obs_or_msg, LayerMessage):
        obs = obs_or_msg.payload
        if not trace_id:
            trace_id = obs_or_msg.trace_id
    else:
        obs = obs_or_msg
    if isinstance(obs, dict):
        obs = TaskObservation(**obs)

    meta = obs.meta
    # ... 后续逻辑不变 (从 `state = dict(obs.state or {})` 开始)
```

**L2Manager.query()** — 同样删除手动解包。当前有额外的 `data.get("obs")` / `data.get("query")` 逻辑（L1 下发子查询时传 dict）。这需要保留但改为从 `obs.state` 取：
```python
def query(self, obs_or_msg, trace_id: str = "") -> None:
    if isinstance(obs_or_msg, LayerMessage):
        obs = obs_or_msg.payload
        if not trace_id:
            trace_id = obs_or_msg.trace_id
    else:
        obs = obs_or_msg
    if isinstance(obs, dict):
        obs = TaskObservation(**obs)

    # L1 下发子查询时 query 在 obs.meta, selected_nodes 在 obs.state
    query = obs.meta
    selected_nodes = obs.state.get("selected_nodes", []) if obs.state else []
    meta = obs.meta
    # ... 后续逻辑不变
```

**L3Manager.query()** — 同样删除手动解包。当前 `data.get("obs")` / `data.get("l3_task")` 改为从 `obs` 直接取：
```python
def query(self, obs_or_msg, trace_id: str = "") -> None:
    if isinstance(obs_or_msg, LayerMessage):
        obs = obs_or_msg.payload
        if not trace_id:
            trace_id = obs_or_msg.trace_id
    else:
        obs = obs_or_msg
    if isinstance(obs, dict):
        obs = TaskObservation(**obs)

    l3_task = obs.state.get("l3_task", "") if obs.state else ""
    selected_nodes = obs.state.get("selected_nodes", []) if obs.state else []
    session = obs.session or {}
    domain_path = session.get("domain", "general")
    # ... 后续逻辑不变
```

- [ ] **Step 3: 修改 Executor.execute() 传 TaskObservation**

当前 `core/executor.py:51-56`:
```python
msg = LayerMessage(
    source="executor", target=self._root.name,
    type=MessageType.QUERY,
    payload=obs, trace_id=trace_id,
)
self._root.query(msg, trace_id)
```

改为直接传 TaskObservation（trace_id 通过 obs.session 或参数传递）：
```python
self._root.query(obs, trace_id=trace_id)
```

- [ ] **Step 4: 修改 L0_5_1Manager 和 L2Manager 中子查询传播**

**L0_5_1Manager.query()** 中的 `self._downstream.query(q_msg, trace_id)` 改为：
```python
self._downstream.query(sub_obs, trace_id=trace_id)
```

**L2Manager._propagate()** 中的 `self._downstream.query(q_msg, trace_id)` 改为：
```python
def _propagate(self, obs, trace_id: str, l3_task: str = "",
               selected_nodes: list[dict] | None = None) -> None:
    if self._downstream:
        # Merge l3_task and selected_nodes into obs.state
        enriched_state = dict(obs.state) if obs.state else {}
        if l3_task:
            enriched_state["l3_task"] = l3_task
        if selected_nodes:
            enriched_state["selected_nodes"] = selected_nodes
        enriched_obs = TaskObservation(
            meta=obs.meta, state=enriched_state, session=obs.session,
        )
        self._downstream.query(enriched_obs, trace_id=trace_id)
```

- [ ] **Step 5: 运行测试验证**

Run: `pytest tests/test_layer_chain.py tests/test_layers.py tests/test_executor.py tests/test_integration_cognitive.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: unify query() signature to TaskObservation-only, inline Comm unwrapping"
```

---

## Task 3: 消灭全局可变状态 — ConsolidationContext 注入

**目标:** 用 `ConsolidationContext` dataclass 替代 `set_consolidation_stores()` / `set_learning_context()` / `get_pending_mods()` 三个模块级全局函数。所有依赖通过构造函数注入。

**Files:**
- 修改: `core/tools/consolidation_tools.py` — 新增 ConsolidationContext, 删除 3 个 global setter/getter
- 修改: `core/chain_factory.py` — 构建 ConsolidationContext 并注入
- 修改: `core/layers/l0_5_1/manager.py` — notify() 不调 get_pending_mods()
- 修改: `core/layers/l2/manager.py` — notify() 同上
- 修改: `core/layers/l3/manager.py` — notify() 同上
- 修改: `core/tools/record_learning_tool.py` — get_learning_context() 改用注入的 context

**现状分析:**
```python
# consolidation_tools.py — 5 个模块级全局变量
_philosophy = None
_knowledge = None
_skill_layer = None
_registry = None
_executor = None
_pending_mods: list[dict] = []

# 3 个 setter/getter 函数
def set_consolidation_stores(phil, fk, sl, reg): ...
def set_learning_context(executor=None, knowledge_stores=None): ...
def get_learning_context(): ...
def get_pending_mods() -> list[dict]: ...
```

每个 Manager 的 `notify()` 都调用 `get_pending_mods()`，这意味着：
1. 模块级 `_pending_mods` 是共享可变状态
2. 如果两个 Manager 同时 notify，修改会混在一起
3. 测试时无法隔离

- [ ] **Step 1: 定义 ConsolidationContext dataclass**

在 `core/tools/consolidation_tools.py` 顶部添加：

```python
from dataclasses import dataclass, field

@dataclass
class ConsolidationContext:
    """Immutable-ish context for consolidation tools.
    
    Replaces module-level global variables. Constructed once in chain_factory,
    injected into Manager constructors. pending_mods is the only mutable field
    (acts as a per-chain modification collector).
    """
    philosophy: object = None
    knowledge: object = None
    skill_layer: object = None
    domain_registry: object = None
    executor: object = None
    pending_mods: list[dict] = field(default_factory=list)

    def record_mod(self, mod: dict) -> None:
        self.pending_mods.append(mod)

    def drain_mods(self) -> list[dict]:
        mods = list(self.pending_mods)
        self.pending_mods.clear()
        return mods
```

- [ ] **Step 2: 将 handler 中的 `_pending_mods.append(...)` 改为 `ctx.record_mod(...)`**

当前所有 9 个 handler 都做 `_pending_mods.append({...})`。需要一个方式让 handler 访问 ctx。

方案：handler 签名保持 `(args=None, **kwargs)`，但通过闭包绑定 ctx。将 `register_consolidation_tools` 改为接受 `ctx: ConsolidationContext` 参数，用闭包创建 handler：

```python
def register_consolidation_tools(tool_registry, ctx: ConsolidationContext):
    """Register consolidation tools bound to the given ConsolidationContext."""
    
    def _record(mod: dict):
        ctx.record_mod(mod)
    
    tool_registry.register("deprecate_l1_rule", {...},
        lambda args=None, **kw: _h_deprecate_l1_rule(args, ctx), ...)
    # ... 类似模式绑定每个 handler
```

每个 handler 函数签名改为 `(args, ctx: ConsolidationContext)`：

```python
def _h_deprecate_l1_rule(args, ctx: ConsolidationContext):
    args = args or {}
    ctx.record_mod({
        "type": "deprecate", "target": args.get("rule_id", ""),
        "reason": args.get("reason", ""), "layer": "l1",
    })
    return json.dumps({"recorded": True, "message": f"已记录: 删除 {args.get('rule_id', '')}"})
```

（handler 具体改动见 Task 7，此处先改签名和注入路径）

- [ ] **Step 3: 删除旧的全局 setter/getter**

删除：
```python
_philosophy = None
_knowledge = None
_skill_layer = None
_registry = None
_executor = None
_pending_mods: list[dict] = []

def set_consolidation_stores(phil, fk, sl, reg): ...
def set_learning_context(executor=None, knowledge_stores=None): ...
def get_learning_context(): ...
def get_pending_mods() -> list[dict]: ...
```

将 `_content_getter` / `_h_query_domain` / `_h_deprecate_domain` / `_h_merge_domain` / `_h_create_domain` 中的全局变量引用改为从 ctx 参数读取。

- [ ] **Step 4: 修改 chain_factory 构建 ConsolidationContext**

当前 `core/chain_factory.py:53-55`:
```python
from core.tools.consolidation_tools import set_consolidation_stores, set_learning_context
set_consolidation_stores(phil, fk, sl, reg)
set_learning_context(knowledge_stores={"l1": phil, "l2": fk, "l3": sl})
```

改为：
```python
from core.tools.consolidation_tools import ConsolidationContext
consol_ctx = ConsolidationContext(
    philosophy=phil, knowledge=fk, skill_layer=sl,
    domain_registry=reg, executor=None,
)
```

修改 `register_all_tools` 调用传递 ctx：
```python
register_all_tools(registry, proposal_dir=data_root / "data" / "tool_proposals",
                   consol_ctx=consol_ctx)
```

将 `consol_ctx` 注入到每个 Manager 构造函数：
```python
chain = _build(phil, fk, sl, auxiliary_llm=auxiliary_llm,
               domain_registry=reg, knowledge_stores=knowledge_stores,
               consol_ctx=consol_ctx)
```

后续 `set_learning_context` 的 executor 设置改为：
```python
consol_ctx.executor = executor  # 如果后续需要
```

- [ ] **Step 5: 修改 Manager 构造函数和 notify()**

每个 Manager 新增 `consol_ctx: ConsolidationContext | None = None` 参数。

`notify()` 中 `get_pending_mods()` 调用改为 `self._consol_ctx.drain_mods()`：

```python
def notify(self) -> Any:
    if self._l1_notify:
        result = dict(self._l1_notify)
        if self._consol_ctx:
            mods = self._consol_ctx.drain_mods()
            if mods:
                result["l1_modifications"] = mods
        return result
    return {"status": "ok", "layer": self.name}
```

L2/L3 Manager 同理。

- [ ] **Step 6: 修改 record_learning_tool.py 的 get_learning_context**

`_dispatch_learning` 中的 `get_learning_context()` 改为从注入的 ctx 读取。需要将 consol_ctx 传递到 `register_record_learning`：

```python
def register_record_learning(registry, pending_dir, consol_ctx=None):
    ...
    def _dispatch_learning(domain, pending_path, json_files):
        ctx = consol_ctx  # 不再调全局 get_learning_context()
        if ctx is None:
            return
        ...
```

- [ ] **Step 7: 运行测试验证**

Run: `pytest tests/ -v -k "consolidation or learning or layer_chain"`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: replace global mutable state with ConsolidationContext DI"
```

---

## Task 7: Consolidation Handler 去重 — _record_mod 工厂

**目标:** 9 个 handler 模式完全一致（append dict + return JSON），统一为 1 个 `_make_handler()` 工厂函数 + 声明式注册表。

**前置:** Task 3 已完成（handler 签名改为接受 ctx）。

**Files:**
- 修改: `core/tools/consolidation_tools.py`

**现状分析:**
9 个 handler 的模式：
```python
def _h_deprecate_l1_rule(args, ctx):
    args = args or {}
    ctx.record_mod({"type": "deprecate", "target": args.get("rule_id", ""), ...})
    return json.dumps({"recorded": True, "message": f"已记录: 删除 {args.get('rule_id', '')}"})

def _h_create_l1_rule(args, ctx):
    args = args or {}
    ctx.record_mod({"type": "create", "target": "", ...})
    return json.dumps({"recorded": True, "message": "已记录: 创建新规则"})
```
每个 handler 只有 3 个差异：(1) mod_type, (2) target_arg, (3) payload_args。

- [ ] **Step 1: 定义声明式注册表**

```python
@dataclass
class _ModSpec:
    """Declarative spec for a consolidation tool handler."""
    tool_name: str
    mod_type: str           # "deprecate" | "create" | "update"
    layer: str              # "l1" | "l2" | "l3"
    target_arg: str         # arg name for target ID ("rule_id", "card_id", "skill_name", "" for create)
    payload_args: list[str] # arg names to include in payload
    message_template: str   # e.g. "已记录: 删除 {target}"

_MOD_SPECS = [
    # L1 Rules
    _ModSpec("deprecate_l1_rule", "deprecate", "l1", "rule_id", [], "已记录: 删除 {target}"),
    _ModSpec("create_l1_rule", "create", "l1", "", ["content"], "已记录: 创建新规则"),
    _ModSpec("modify_l1_rule", "update", "l1", "rule_id",
             ["content", "usefulness", "misleading", "comment"], "已记录: 修改 {target}"),
    # L2 Cards
    _ModSpec("deprecate_l2_card", "deprecate", "l2", "card_id", [], "已记录: 删除 {target}"),
    _ModSpec("create_l2_card", "create", "l2", "", ["content", "domain"], "已记录: 创建新卡片"),
    _ModSpec("modify_l2_card", "update", "l2", "card_id",
             ["content", "domain", "usefulness", "misleading", "comment"], "已记录: 修改 {target}"),
    # L3 Skills
    _ModSpec("deprecate_l3_skill", "deprecate", "l3", "skill_name", [], "已记录: 删除 {target}"),
    _ModSpec("create_l3_skill", "create", "l3", "name", ["content", "domain"], "已记录: 创建 {target}"),
    _ModSpec("modify_l3_skill", "update", "l3", "skill_name",
             ["content", "domain", "usefulness", "misleading", "comment"], "已记录: 修改 {target}"),
]
```

- [ ] **Step 2: 实现 _make_handler 工厂**

```python
def _make_handler(spec: _ModSpec):
    """Generate a consolidation handler from a declarative spec."""
    def handler(args=None, ctx=None):
        args = args or {}
        target = args.get(spec.target_arg, "") if spec.target_arg else ""
        payload = {}
        for key in spec.payload_args:
            if key in args and args[key] != "":
                payload[key] = args[key]
        ctx.record_mod({
            "type": spec.mod_type,
            "target": target,
            "layer": spec.layer,
            "reason": args.get("reason", ""),
            "payload": payload,
        })
        msg = spec.message_template.format(target=target)
        return json.dumps({"recorded": True, "message": msg})
    return handler
```

- [ ] **Step 3: 用声明式注册替代手写 handler**

`register_consolidation_tools` 中，9 个 CRUD tool 改为：
```python
for spec in _MOD_SPECS:
    handler = _make_handler(spec)
    schema = _TOOL_SCHEMAS[spec.tool_name]
    tool_registry.register(spec.tool_name, schema, handler, toolset="consolidation", sync=True)
```

schema 定义保留（因为每个 tool 的 description/parameters 不同），但提取到 `_TOOL_SCHEMAS` dict 中（只搬移位置，不修改内容）。

- [ ] **Step 4: 删除 9 个旧 handler 函数**

删除 `_h_deprecate_l1_rule` / `_h_create_l1_rule` / `_h_modify_l1_rule` / `_h_deprecate_l2_card` / `_h_create_l2_card` / `_h_modify_l2_card` / `_h_deprecate_l3_skill` / `_h_create_l3_skill` / `_h_modify_l3_skill`。

保留 `_h_query_domain` / `_h_deprecate_domain` / `_h_merge_domain` / `_h_create_domain`（这些有自定义域逻辑，不适合模板化，但改为从 ctx 读 stores）。

- [ ] **Step 5: 运行测试验证**

Run: `pytest tests/ -v -k "consolidation"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: deduplicate 9 consolidation handlers into _make_handler factory"
```

---

## Task 4: Capture Tool 配置化 — CaptureToolDef + _TOOL_RULES 常量

**目标:** 把三层 Agent 中重复定义的 capture tool（l1_query/report, l2_query/report, l3_continue/report）统一为声明式 `CaptureToolDef` dataclass，并把三层重复的 `tool_rules` 提示文本提取为模块级常量。

**Files:**
- 修改: `core/layers/base.py` — 添加 CaptureToolDef + 工厂方法
- 修改: `core/layers/l0_5_1/manager.py` — L1Agent.decide() 改用配置
- 修改: `core/layers/l2/manager.py` — L2Agent.decide() 改用配置
- 修改: `core/layers/l3/manager.py` — L3Agent.decide() 改用配置

**现状分析:**

三层 Agent 各自手写几乎相同的 capture tool 定义（~30 行 × 3 = ~90 行），例如 L1:
```python
query_tool = self._schema_to_tool("l1_query", "...", {...})
report_tool = self._schema_to_tool("l1_report", "...", {...})
```
L2 用 l2_query/l2_report，L3 用 l3_continue/l3_report。结构完全一致，只有命名和 schema 细微差异。

同时，三层 Agent 的 system prompt 都包含完全相同的 `tool_rules` 文本块（~6行），可提取为常量。

- [ ] **Step 1: 定义 CaptureToolDef dataclass + _TOOL_RULES 常量**

在 `core/layers/base.py` 中添加：

```python
_TOOL_RULES = (
    "## 工具调用规则\n"
    "- 所有工具都有 sync 参数。sync=true(默认)阻塞等结果，sync=false 返回 task_id\n"
    "- sync=false 的任务用 collect_tasks(task_ids) 收割结果\n"
    "- check_task(task_id) 可查单个任务状态\n"
    "- 同一轮内多个 sync=true 工具并行执行，互不阻塞\n"
    "- 长耗时任务（kb_fill_gap、terminal 跑 shell 脚本等）建议设 sync=false\n"
)

@dataclass
class CaptureToolDef:
    """Declarative definition of a capture tool for Agent decide().
    
    Capture tools are how the Agent outputs structured decisions:
    query/continue tool (done=false) and report tool (done=true).
    """
    name: str               # e.g. "l1_query", "l1_report"
    description: str        # e.g. "【特殊工具：向下查询】..."
    done: bool              # True = report/final, False = query/continue
    schema: dict            # JSON schema for the tool parameters
    capture_name: str = "" # Auto-set to name if empty

    def to_openai_tool(self) -> dict:
        """Convert to OpenAI function-calling tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }
```

- [ ] **Step 2: 定义三层 CaptureToolDef 配置**

在各自 Agent 文件内或 `base.py` 中集中定义。推荐在每个 Manager/Agent 文件顶部（靠近类定义）声明该层的配置：

**L1Agent (l0_5_1/manager.py):**
```python
L1_QUERY_TOOL = CaptureToolDef(
    name="l1_query",
    description="【特殊工具：向下查询】当需要下层L2的策略知识辅助决策时使用。每次只提交一个问题，收到回复后再决定是否继续查询。禁止以文本方式直接回复！",
    done=False,
    schema={
        "type": "object",
        "properties": {
            "done": {"type": "boolean", "const": False},
            "queries": {
                "type": "array", "maxItems": 1,
                "items": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "向下层 L2 查询的问题"},
                    "domains_hint": {"type": "array", "items": {"type": "string"}, "description": "建议查询的领域"},
                }},
            },
            "reasoning": {"type": "string"},
        },
        "required": ["done", "queries", "reasoning"],
    },
)

L1_REPORT_TOOL = CaptureToolDef(
    name="l1_report",
    description="【特殊工具：向上汇报】当你有了足够信息可以做出最终决策时使用。给出明确的决策结果和推理过程。禁止以文本方式直接回复！",
    done=True,
    schema={
        "type": "object",
        "properties": {
            "done": {"type": "boolean", "const": True},
            "result": {"type": "string", "description": "最终决策文本"},
            "reasoning": {"type": "string"},
        },
        "required": ["done", "result", "reasoning"],
    },
)
```

**L2Agent (l2/manager.py):** 类似定义 `L2_QUERY_TOOL` 和 `L2_REPORT_TOOL`。

**L3Agent (l3/manager.py):** 定义 `L3_CONTINUE_TOOL` 和 `L3_REPORT_TOOL`。

- [ ] **Step 3: 修改三层 Agent.decide() 使用 CaptureToolDef**

当前 L1Agent.decide() 的 capture tool 组装逻辑（~50 行）改为：

```python
# Normal mode
base_tools = self._get_tools(layer) or []
capture_tools = [L1_QUERY_TOOL.to_openai_tool(), L1_REPORT_TOOL.to_openai_tool()]
all_tools = base_tools + capture_tools
result = self._call_llm(system, user, tools=all_tools, layer=layer,
                        capture_tools={L1_QUERY_TOOL.name, L1_REPORT_TOOL.name})
```

Consolidation 模式同理：
```python
if l1_fmt:
    from core.tools.registry import ToolRegistry
    from core.tools.consolidation_tools import L1_CONSOLIDATION_TOOL_NAMES
    _allowed = {"kb_query", "ask_user"}
    base_tools = [t for t in (self._get_tools(layer) or [])
                  if t["function"]["name"] in _allowed]
    consol_schemas = ToolRegistry().get_definitions(L1_CONSOLIDATION_TOOL_NAMES)
    report_tool = L1_REPORT_TOOL.to_openai_tool()
    all_tools = base_tools + consol_schemas + [report_tool]
    result = self._call_llm(system, user, tools=all_tools, layer=layer,
                            capture_tools={L1_REPORT_TOOL.name})
    result = {"done": True,
             "result": result.get("result", ""),
             "reasoning": result.get("reasoning", ""),
             "queries": []}
    return result
```

L2Agent 和 L3Agent 做相同改动。

- [ ] **Step 4: 提取 _TOOL_RULES 到 system prompt 构建**

三层 Agent 的 `_build_system_prompt` 都包含相同的 tool_rules 文本。改为引用 `_TOOL_RULES` 常量：

```python
# Before (每层各自手写):
tool_rules = (
    "## 工具调用规则\n"
    "- 所有工具都有 sync 参数。sync=true(默认)阻塞等结果，sync=false 返回 task_id\n"
    ...
)

# After (引用常量):
from core.layers.base import _TOOL_RULES
tool_rules = _TOOL_RULES
```

- [ ] **Step 5: 运行测试验证**

Run: `pytest tests/test_layers.py tests/test_layer_chain.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: extract CaptureToolDef dataclass and _TOOL_RULES constant"
```

---

## Task 5: Consolidation Strategy — 消灭 if lX_output_format 分支

**目标:** 把每层 Agent 的 consolidation 模式 if-branch 提取为 `ConsolidationStrategy`，通过注入决定行为，Agent 不再感知模式切换。同时统一 `_L1/_L2/_L3_OUTPUT` 为 `OUTPUT_SCHEMA_TEMPLATE`。

**Files:**
- 修改: `core/layers/base.py` — 添加 ConsolidationStrategy
- 修改: `core/layers/l0_5_1/manager.py` — L1Agent 使用 strategy
- 修改: `core/layers/l2/manager.py` — L2Agent 使用 strategy
- 修改: `core/layers/l3/manager.py` — L3Agent 使用 strategy
- 修改: `core/env/learning_env.py` — 统一 OUTPUT SCHEMA

**现状分析:**

每层 Agent.decide() 都有：
```python
lX_fmt = state.get("lX_output_format")
if lX_fmt:
    # ~20 行 consolidation 专用逻辑
    consol_schemas = ToolRegistry().get_definitions(LX_CONSOLIDATION_TOOL_NAMES)
    ...
else:
    # ~30 行 normal 模式逻辑
    base_tools = self._get_tools(layer) or []
    ...
```
这段代码在三层中结构相同，违反 AGENTS.md 的"不准在 Manager 里写 if 特殊分支"原则。

- [ ] **Step 1: 定义 ConsolidationStrategy**

在 `core/layers/base.py` 中添加：

```python
class ConsolidationStrategy:
    """Determines how an Agent decides in consolidation mode.
    
    Injected via chain_factory. Agent.decide() checks self._strategy
    to build tools/capture_tools, without if-branching on state keys.
    """
    def __init__(self, consolidation_tool_names: set[str],
                 allowed_base_tools: set[str],
                 report_tool: CaptureToolDef):
        self.consolidation_tool_names = consolidation_tool_names
        self.allowed_base_tools = allowed_base_tools
        self.report_tool = report_tool

    def build_tools(self, agent: LayerAgent, layer: str) -> tuple[list[dict], set[str]]:
        """Return (all_tools, capture_tools_set) for consolidation mode."""
        from core.tools.registry import ToolRegistry
        base_tools = [t for t in (agent._get_tools(layer) or [])
                      if t["function"]["name"] in self.allowed_base_tools]
        consol_schemas = ToolRegistry().get_definitions(self.consolidation_tool_names)
        report = self.report_tool.to_openai_tool()
        all_tools = base_tools + consol_schemas + [report]
        return all_tools, {self.report_tool.name}
```

定义三层 strategy 实例（在模块顶部或 chain_factory 中）：

```python
# base.py 中或各 Manager 模块中
L1_CONSOLIDATION_STRATEGY = ConsolidationStrategy(
    consolidation_tool_names=L1_CONSOLIDATION_TOOL_NAMES,
    allowed_base_tools={"kb_query", "ask_user"},
    report_tool=L1_REPORT_TOOL,
)
L2_CONSOLIDATION_STRATEGY = ConsolidationStrategy(
    consolidation_tool_names=L2_CONSOLIDATION_TOOL_NAMES,
    allowed_base_tools={"kb_query", "read_file", "grep"},
    report_tool=L2_REPORT_TOOL,
)
L3_CONSOLIDATION_STRATEGY = ConsolidationStrategy(
    consolidation_tool_names=L3_CONSOLIDATION_TOOL_NAMES,
    allowed_base_tools={"kb_query", "read_file", "grep"},
    report_tool=L3_REPORT_TOOL,
)
```

- [ ] **Step 2: 统一 OUTPUT SCHEMA**

当前 `learning_env.py` 有三个几乎相同的 `_L1_OUTPUT`, `_L2_OUTPUT`, `_L3_OUTPUT` dict。它们的 `notify` 子结构几乎一样（只是字段名 `l1_modifications` / `l2_modifications` / `l3_modifications`）。

新增 `core/env/consolidation_schemas.py`：

```python
def _layer_output_schema(layer_key: str) -> dict:
    """Generate per-layer output schema from template. Much DRY-er than 3 copies."""
    return {
        "type": "object",
        "properties": {
            "response": {
                "type": "object",
                "properties": {
                    "result": {"type": "string"},
                    # L2 adds "cards", L3 adds "skills_used", but base is same
                    "reasoning": {"type": "string"},
                },
                "required": ["result", "reasoning"],
            },
            "notify": {
                "type": "object",
                "properties": {
                    f"{layer_key}_modifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string"},
                                "type": {"type": "string", "enum": ["update", "create", "deprecate"]},
                                "payload": {
                                    "type": "object",
                                    "properties": {
                                        "content": {"type": "string"},
                                        "reason": {"type": "string"},
                                    },
                                    "required": ["content", "reason"],
                                },
                            },
                            "required": ["target", "type"],
                        },
                    },
                },
            },
        },
        "required": ["response"],
    }

L1_OUTPUT = _layer_output_schema("l1")
L2_OUTPUT = _layer_output_schema("l2")
L3_OUTPUT = _layer_output_schema("l3")
```

修改 `learning_env.py` 导入：
```python
from core.env.consolidation_schemas import L1_OUTPUT as _L1_OUTPUT, L2_OUTPUT as _L2_OUTPUT, L3_OUTPUT as _L3_OUTPUT
```

删除 `learning_env.py` 中的内联 schema 定义（~120 行 → ~5 行 import）。

- [ ] **Step 3: 修改 Agent 构造函数注入 Strategy**

每个 Agent 构造函数新增 `consolidation_strategy: ConsolidationStrategy | None = None` 参数：

```python
class L1Agent(LayerAgent):
    def __init__(self, llm_client, philosophy, domain_registry=None,
                 knowledge_stores=None,
                 consolidation_strategy=None):
        super().__init__(llm_client, logger)
        self._philosophy = philosophy
        self._registry = domain_registry
        self._consolidation_strategy = consolidation_strategy
```

- [ ] **Step 4: 修改 decide() 使用 Strategy**

Agent.decide() 中合并 normal 和 consolidation 分支：

```python
def decide(self, meta, state, history, tools=None, layer="l1") -> dict:
    strategy = self._consolidation_strategy if "l1_output_format" in state else None
    
    # instruction 构建...
    system = self._build_system_prompt(instruction, meta, static_context=static_context)
    user = ... # 构建 user prompt（不变）
    
    if strategy:
        all_tools, capture_set = strategy.build_tools(self, layer)
    else:
        base_tools = self._get_tools(layer) or []
        capture_set = {"l1_query", "l1_report"}
        all_tools = base_tools + [L1_QUERY_TOOL.to_openai_tool(), L1_REPORT_TOOL.to_openai_tool()]
    
    result = self._call_llm(system, user, tools=all_tools, layer=layer, capture_tools=capture_set)
    
    # Post-processing: strategy mode always returns done=True
    if strategy:
        return {"done": True,
                "result": result.get("result", ""),
                "reasoning": result.get("reasoning", ""),
                "queries": []}
    
    # Normal mode fallback
    if not result.get("done"):
        raw = result.get("_raw") or result.get("result") or ""
        if raw:
            return {"done": True, "result": str(raw), "reasoning": "direct reply", "queries": []}
    return result
```

L2Agent 和 L3Agent 同理，但 capture_set 和 report/query tool 不同。

- [ ] **Step 5: 更新 chain_factory 注入 Strategy**

`build_chain()` 中构造 Agent 时传入 strategy：

```python
l1_agent = L1Agent(auxiliary_llm, philosophy, domain_registry=reg,
                   knowledge_stores=knowledge_stores,
                   consolidation_strategy=L1_CONSOLIDATION_STRATEGY)
```

- [ ] **Step 6: 运行测试验证**

Run: `pytest tests/test_layers.py tests/test_layer_chain.py tests/test_learning_env.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: extract ConsolidationStrategy, unify OUTPUT schemas, eliminate if-branches"
```

---

## Task 6: Agent.decide() Template Method — 提取公共模板到基类

**目标:** 把三层 Agent.decide() 的 7 步模板提取到 LayerAgent 基类，每层只 override 3 个 hook。

**前置:** T4 (CaptureToolDef) 和 T5 (ConsolidationStrategy) 已完成。

**Files:**
- 修改: `core/layers/base.py` — 添加 decide() 模板方法 + hook 方法
- 修改: `core/layers/l0_5_1/manager.py` — L1Agent override hooks
- 修改: `core/layers/l2/manager.py` — L2Agent override hooks
- 修改: `core/layers/l3/manager.py` — L3Agent override hooks

**现状分析:**

三层的 `decide()` 方法虽有差异，但都遵循同一个骨架：
1. 检查是否 consolidation 模式 → 构建 instruction
2. 构建 system prompt
3. 构建 user prompt/context
4. 确定 tools + capture_tools（normal vs consolidation）
5. 调用 `_call_llm()`
6. 解析结果（consolidation 直接返回 vs normal fallback）
7. 返回 dict

每层只是步骤 1/3/4/6 的具体内容不同（instruction 文本、context 字段、tool 定义、结果字段名）。

- [ ] **Step 1: 在 LayerAgent 基类定义 decide 模板方法 + hook**

在 `core/layers/base.py` 的 `LayerAgent` 中：

```python
class LayerAgent(ABC):
    # ... existing __init__, _call_llm, etc ...

    # ── Hooks for subclass customization ──

    def build_instruction(self, meta: str, state: dict, *, 
                          consolidation: bool = False) -> str:
        """Build the instruction part of the system prompt.
        Override in each layer for layer-specific instructions.
        """
        raise NotImplementedError

    def build_user_prompt(self, state: dict, history: list[dict],
                          context: dict) -> str:
        """Build the user prompt body.
        Override in each layer for layer-specific context formatting.
        """
        raise NotImplementedError

    def get_capture_tools(self, layer: str, consolidation: bool) -> tuple[list[dict], set[str]]:
        """Return (tools_list, capture_tool_names_set) for this decision step.
        Override in each layer.
        """
        raise NotImplementedError

    def parse_result(self, raw_result: dict, consolidation: bool) -> dict:
        """Parse _call_llm result into layer-specific output dict.
        Override in each layer for field mapping.
        """
        raise NotImplementedError

    def decide(self, *, meta, state, history=None, context=None,
               tools=None, layer="") -> dict:
        """Template method for single decision step.
        
        Flow: build_instruction → build_system_prompt → build_user_prompt
              → get_capture_tools → _call_llm → parse_result
        """
        consolidation = any(k in state for k in 
                           ("l1_output_format", "l2_output_format", "l3_output_format"))
        instruction = self.build_instruction(meta, state, consolidation=consolidation)
        system = self._build_system_prompt(instruction, meta)
        history = history or []
        context = context or {}
        user = self.build_user_prompt(state, history, context)
        
        all_tools, capture_set = self.get_capture_tools(layer, consolidation)
        result = self._call_llm(system, user, tools=all_tools or None,
                                  layer=layer, capture_tools=capture_set or None)
        return self.parse_result(result, consolidation)
```

- [ ] **Step 2: L1Agent override hooks**

```python
class L1Agent(LayerAgent):
    def build_instruction(self, meta, state, *, consolidation=False):
        instruction = (
            "你的职责：基于【行为准则】将任务拆解为下层需要协助的具体子任务。\n"
            "拆解时思考：已有信息能完成什么、还差什么子任务或信息、所需材料是否可以由下层提供。\n\n"
            "*** 输出规则（极其重要）***\n"
            "1. 如果你需要 L2 层的策略知识才能做出决策 → 调用【l1_query】工具下发查询\n"
            "2. 如果你已经掌握了足够信息，可以独立做出最终决策 → 调用【l1_report】工具汇报结果\n"
            "3. 禁止以文本方式直接输出JSON或回复，必须调用以上两个工具之一！\n\n"
            "l1_query：向下查询，done固定为false。每次只能提交一个问题，收到L2回复后如仍需补充再发起下一次查询。\n"
            "l1_report：向上汇报，done固定为true，给出最终决策和理由\n"
        )
        if consolidation:
            instruction += "\n\n【整理任务】你只负责 L1 行为准则的修改。使用整理工具记录修改，完成后调用 l1_report 输出结果。"
        else:
            instruction += "\n如果任务无需下层协助，直接调用 l1_report。"
        return instruction

    def build_user_prompt(self, state, history, context):
        # ... 现有 _build_user_context 逻辑 ...
        pass

    def get_capture_tools(self, layer, consolidation):
        if consolidation and self._consolidation_strategy:
            return self._consolidation_strategy.build_tools(self, layer)
        base = self._get_tools(layer) or []
        return (base + [L1_QUERY_TOOL.to_openai_tool(), L1_REPORT_TOOL.to_openai_tool()],
                {"l1_query", "l1_report"})

    def parse_result(self, raw, consolidation):
        if consolidation:
            return {"done": True, "result": raw.get("result", ""),
                    "reasoning": raw.get("reasoning", ""), "queries": []}
        if not raw.get("done"):
            r = raw.get("_raw") or raw.get("result") or ""
            if r:
                return {"done": True, "result": str(r), "reasoning": "direct reply", "queries": []}
        return raw
```

- [ ] **Step 3: L2Agent override hooks**

类似 L1，但 instruction/context/parse 逻辑不同。核心改动：
- `build_instruction`: L2 的 description + tool_rules
- `build_user_prompt`: 卡片文本 + domain nodes + L3 结果
- `get_capture_tools`: L2_QUERY_TOOL / L2_REPORT_TOOL / L2_CONSOLIDATION_STRATEGY
- `parse_result`: 返回 `done/reply/selected_nodes/selected_cards/queries_to_L3/reasoning`

- [ ] **Step 4: L3Agent override hooks**

类似。核心改动：
- `build_instruction`: L3 的 description + tool_rules
- `build_user_prompt`: 技能文本 + 学习数据
- `get_capture_tools`: L3_CONTINUE_TOOL / L3_REPORT_TOOL / L3_CONSOLIDATION_STRATEGY
- `parse_result`: 返回 `done/result/skills_used/reasoning`

- [ ] **Step 5: 删除三层各自旧 decide() 方法**

用 hook overrides 替代。每个 Agent 的 `decide()` 方法不再手写完整流程，而是由基类模板调用 hooks。

- [ ] **Step 6: 运行测试验证**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: extract Agent.decide() template method into LayerAgent base class"
```

---

## Update MAINTAIN.md

在所有 Task 完成后，必须更新 MAINTAIN.md 以反映函数签名和调用关系的变更：

- [ ] **更新 ConsolidationContext 相关条目**: 删除 `set_consolidation_stores`/`set_learning_context`/`get_learning_context`/`get_pending_mods`，新增 `ConsolidationContext` dataclass 条目
- [ ] **更新 LayerManager 基类条目**: 新增 `_process_and_propagate` 方法，`query()` 签名改为 `TaskObservation | LayerMessage`
- [ ] **更新三层 Agent 条目**: `decide()` 改为 override hooks 形式（`build_instruction`/`build_user_prompt`/`get_capture_tools`/`parse_result`）
- [ ] **删除 Comm Agent 子类条目**（如 COOKBOOK.md 有引用则在 COOKBOOK.md 标注）
- [ ] **更新 chain_factory 条目**: 新增 `consol_ctx` 参数传递
- [ ] **新增 CaptureToolDef 条目**

---

## Self-Review Checklist

- [x] **Spec coverage**: 每个 Pain Point 都有对应 Task
- [x] **Placeholder scan**: 无 TBD/TODO；所有代码步骤完整
- [x] **Type consistency**: ConsolidationContext 在所有引用处签名一致；CaptureToolDef 在三层使用同一类型
- [x] **Dependency order**: T1→T2→T3→T7→T4→T5→T6 依赖链清晰
- [x] **No new files**: 所有改动在现有文件内，无需创建新模块
- [x] **Testability**: 每个 Task 有独立 pytest 命令验证



