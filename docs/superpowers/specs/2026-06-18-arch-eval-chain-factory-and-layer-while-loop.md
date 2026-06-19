# 执行 spec — decide-once 统一模型（#20 / #12-B）

> **状态**：已定方向，待执行。RoundTree 重建细节由实现者定，核心原则：绑定 decide 建节点。
> **基准**：以实际代码为准（MAINTAIN/README 部分条目已过时）。
> **范围**：仅 B 部分（层间交互模型统一）。A 部分（chain_factory + ConsolidationContext）另行评估。

---

## 1. 目标模型

**每层 Manager 只调一次 `decide()`。所有"多轮"行为发生在 `decide()` 内部的 `_call_llm` tool loop（`MAX_TOOL_TURNS`）里。** 向下层对话（l1_query / l2_query）和工具调用统一算 tool turn，由 Agent 在单次 decide 的同一 LLM 会话内自主调度。

| 层 | decide 次数 | 内部 tool turn 上限 | 可调 downward 工具 |
|----|-----------|-------------------|------------------|
| L1 | 1 | 5 | `l1_query` → L2 |
| L2 | 1 | 5 | `l2_query` → L3 |
| L3 | 1 | 5 | 无下游 |

调用树形状（最坏）：L1 5 turn × L2 5 turn × L3 5 turn = 125 嵌套 LLM 调用，但 l1_query/l2_query 同步阻塞，实际远达不到。L1 初始设计无工具时的 Manager 外层 while 是历史遗留，统一废除。

---

## 2. 改动清单

### 2.1 l1_query / l2_query 从 capture_tool 降级为普通工具

**现状**：`L1_QUERY_TOOL` / `L2_QUERY_TOOL` 是 `CaptureToolDef`（`l0_5_1/manager.py:13-34`、`l2/manager.py:34-58`），Agent 一调即退出 decide（`base.py:186-194` capture 分支），跨层靠 Manager 外层 while 接管。

**改为**：注册为 ToolRegistry 普通工具，handler 内部调 `downstream.query()` + `collect_notify()`，把下游结果作为 `role:"tool"` 回灌 LLM，tool loop 继续（`base.py:287-291`）。

- schema 基本不变（l1_query 的 `queries`、l2_query 的 `queries_to_L3` 保留数组形式，Agent 自决顺序/并行——见 §5）。
- `L1_REPORT_TOOL` / `L2_REPORT_TOOL` / `L3_REPORT_TOOL` 保持 capture_tool（向上汇报 = 退出 decide 信号）。
- `L3_CONTINUE_TOOL` 删除（L3 无下游，"继续思考" = 普通工具调用的默认多轮行为，l3_report 是唯一退出信号）。

### 2.2 downstream 注入（沿用 domain_tool 模式）

**现状范式**：`core/tools/domain_tool.py:10` `set_domain_registry(reg)` 模块级 setter，`chain_factory.py:85-88` `_mount_tools` 里调用。handler 读模块级 `_registry`。

**新增**：`core/tools/downward_comm_tool.py`
```python
_downstreams: dict[str, object] = {}  # tool_name → downstream Manager

def set_layer_downstreams(mapping: dict[str, object]) -> None:
    global _downstreams
    _downstreams = mapping

def register_downward_tools(tool_registry):
    def _make_handler(tool_name):
        def handler(args=None, **kwargs):
            args = args or {}
            downstream = _downstreams.get(tool_name)
            if downstream is None:
                return json.dumps({"error": f"{tool_name}: downstream not bound"})
            # 构造 sub TaskObservation，调 downstream.query + collect_notify
            # 返回下游 notify 作为 tool result（见 §3 handler 细节）
        return handler
    tool_registry.register("l1_query", schema_l1, _make_handler("l1_query"), toolset="core", sync=True)
    tool_registry.register("l2_query", schema_l2, _make_handler("l2_query"), toolset="core", sync=True)
```

**注入点**：`chain_factory._mount_tools` 在 `build_chain` 返回后调用（downstream 链已存在）：
```python
set_layer_downstreams({
    "l1_query": chain._downstream,        # L2Manager
    "l2_query": chain._downstream._downstream,  # L3Manager
})
register_downward_tools(registry)
```

allowlist（`config/tools.yaml`）已保证 l1_query 只 L1 可见、l2_query 只 L2 可见，tool name 唯一映射 downstream，无需把 layer 透传进 dispatch。

### 2.3 Manager 外层 while 全废

- `L0_5_1Manager.query`（`l0_5_1/manager.py:288-431`）：删除 `for round_idx in range(...)` 循环，改为单次 `decide()`。删 `self._l2_history` 累积逻辑（`:268, :398-401`）、force-terminate 块（`:403-431`）。
- `L2Manager.query`（`l2/manager.py:395-486`）：已是单次 decide，删 `_propagate` 里的 `queries_to_L3` 透传（`:457-475`，改由 l2_query handler 调下游）、删 `_l3_history`（`:390, :472-475`）。
- `L3Manager.query`（`l3/manager.py:248-331`）：已是单次 decide，删 `l3_continue` coerce（`l3/manager.py:211-215` 在 Agent.decide 内）。
- `config.yaml:runtime.max_rounds_l1/l2/l3`（`:20-22`）删除，统一 `max_tool_turns:5`（`:23` 保留）。

### 2.4 L2 reply-before-L3 bug 随模型统一消失

现状 `l2/manager.py:442-446` 在 decide 返回后立即定 reply，L3 调度在 `:457` 之后。改后 l2_query 是普通工具，L2 Agent 在 tool loop 内同步拿 L3 结果回灌，同会话内看到 L3 结果再决定 l2_report。Manager.query 只在 decide 返回后收 notify，不再定 reply。

### 2.5 consolidation cascade 整段删除（P4）

**删除**：
- `l0_5_1/manager.py:334-356`（L1 done 后 cascade L2/L3）
- `l2/manager.py:14-29` `cascade_consolidation_to_l3` 函数 + `l2/manager.py:449-455` 调用点

**理由**：record_learning 改造后，学习任务由 L1 主动分发，不再需要 Manager 强行给三层平行派活。consolidation 模式下 Agent 通过 l1_query/l2_query 自驱调度下游。

**配套**：
- `ConsolidationStrategy.allowed_base_tools`（`base.py:56`）加入 downward 工具：
  - L1 strategy：`{"kb_query", "ask_user", "l1_query"}`
  - L2 strategy：`{"kb_query", "read_file", "grep", "l2_query"}`
  - L3 strategy：不加（无下游）
- L1/L2 consolidation instruction（`l0_5_1/manager.py:168-172`、`l2/manager.py:280-283`）从"你只负责本层修改"改为"你负责把整理任务分发给下游"。

### 2.6 mods 回流形状不变（P3 核对结论）

`drain_mods()` 在三层 notify() 把 `pending_mods` 塞进 `lX_modifications`（`l0_5_1/manager.py:437-439`、`l2/manager.py:537-540`、`l3/manager.py:337-339`）。Executor `collect_notify` 链式收集，`LearningEnv._parse_notify_layers`（`learning_env.py:686-703`）按 `l0_5_1/l2/l3` 分拣。cascade 删除后，每层 mods 仍各自经本层 notify drain → Executor 回收，**不受影响**。现状 `l0_5_1/manager.py:354-355` 把 l2/l3 mods 塞进 L1 notify 的逻辑随 cascade 一起删，但它们本来也各自出现在 L2/L3 notify 里，`_parse_notify_layers` 按 layer key 分拣不依赖 L1 notify。

---

## 3. l1_query / l2_query handler 细节

handler 拿到 downstream Manager 引用后：
1. 从 args 解析 `queries`（l1_query）或 `queries_to_L3`（l2_query）数组。
2. 对每个 query 构造 `TaskObservation`（meta=query 文本，state 透传上层 state + domains_hint）。
3. `downstream.query(obs, trace_id)` → `downstream.collect_notify()`。
4. 把下游 notify（提取 reply/result/reasoning）格式化为 tool result 字符串返回。
5. **RoundTree 节点在此建**（见 §4）。

**并行 vs 顺序**：Agent 自决。handler 按 args 里 `sync` 参数走 ToolRegistry 的 sync/async 分流（`base.py:204-215`）：
- sync=true（默认）：handler 同步阻塞，一次 tool call 返回该 query 的结果。
- sync=false：handler submit 到 TaskRunner，返回 task_id，Agent 用 collect_tasks 收割（复用 `async_tools.py` 模式）。
- 数组多 query：Agent 可多次调 l1_query（顺序，每次一条），或单次传多条由 handler 内部 loop（sync 一次性返回合并结果）。形状由 Agent 选，handler 两种都支持。

---

## 4. RoundTree 重建方案（P1）

**核心原则**：绑定 decide 建节点。每次 decide() 对应一个 DecisionNode；downward comm 在 handler 里把下游节点 append 为 children。

### 4.1 节点生命周期

| 事件 | 动作 |
|------|------|
| Manager.query 调 decide() 前 | 建本层 DecisionNode（query=obs.meta，result/reasoning 待填） |
| l1_query / l2_query handler 调完 downstream.collect_notify() | 从下游 notify 提取子节点，append 到当前节点的 children |
| Manager.query 收到 decide() 返回 | 填本层节点的 result/reasoning |
| L1 Manager.query 结束（decide 返回） | push 完整 L1 树（含 L2/L3 子树）到 RoundHistory |

### 4.2 当前节点传递机制

downward comm handler 需要拿到"当前正在建的节点"。方案：**线程局部存储（thread-local）**。

```python
# core/round_tree.py 新增
import threading
_current_node_stack = threading.local()

def current_node() -> DecisionNode | None:
    stack = getattr(_current_node_stack, "stack", None)
    return stack[-1] if stack else None

def push_node(node: DecisionNode) -> None:
    stack = getattr(_current_node_stack, "stack", None)
    if stack is None:
        stack = []
        _current_node_stack.stack = stack
    stack.append(node)

def pop_node() -> DecisionNode | None:
    stack = getattr(_current_node_stack, "stack", None)
    return stack.pop() if stack else None
```

- Manager.query 建 node → `push_node(node)` → 调 decide() → decide 内 tool loop 调 l1_query handler → handler 调 downstream.query()（递归进入 L2 Manager.query，L2 也 push 自己的 node）→ handler 拿 `current_node()`（此时栈顶是 L2 node）的 result 填好后，pop L2 node，append 到 `current_node()`（此时栈顶回到 L1 node）的 children。
- L1 Manager.query 结束 pop L1 node → push 到 RoundHistory。

### 4.3 同步递归兼容

l1_query/l2_query 同步阻塞，downstream.query() 在同一线程同栈递归。thread-local 栈天然匹配调用栈深度。async（sync=false）路径：handler submit 到 TaskRunner 的 worker 线程——worker 线程的 thread-local 栈为空，需在 submit 前把当前 node 传入闭包，worker 内 push 传入的 node 作为起点。实现者注意：async 路径的 RoundTree 子树可能晚于父节点 pop 才完成，需在 collect_tasks 收割时补 append（或标记为 detached 子树）。**建议首版 downward comm 强制 sync=true，async 留作后续**（简化 RoundTree 时序）。

### 4.4 删除的字段

- `L0_5_1Manager._l2_history`（`l0_5_1/manager.py:268`）
- `L2Manager._l3_history`（`l2/manager.py:390`）
- L2 notify 里的 `_l3_children`（`l2/manager.py:478-485`）

---

## 5. queries 数组形状（P3）

`l1_query.queries` 和 `l2_query.queries_to_L3` 保留数组 schema（现状 `l0_5_1/manager.py:23-29`、`l2/manager.py:48-53`）。handler 行为：
- 数组 N 条 → handler 内部 loop，对每条调 downstream，返回合并结果（`{results: [{query, reply, ...}, ...]}`）。
- Agent 也可多次调 l1_query 每次 1 条 → 每次返回单条结果，占 1 turn。

Agent 自决。两种都支持，handler 不强制。

---

## 6. L3 简化

- 删 `L3_CONTINUE_TOOL`（`l3/manager.py:31-45`）。
- `L3Agent.decide` capture_tools 从 `{"l3_continue", "l3_report"}` 改为 `{"l3_report"}`（`l3/manager.py:210`）。
- 删 `l3/manager.py:211-215` 的 `not done` coerce 块（不再有 l3_continue）。
- L3 Agent 在 tool loop 内自然多轮调工具，直到调 l3_report 退出 decide。

---

## 7. 测试策略（TDD）

按改动顺序写失败测试：
1. **l1_query/l2_query 工具化**：注册到 ToolRegistry，handler 拿 downstream 调用并返回结果。
2. **downstream 注入**：`set_layer_downstreams` + `_mount_tools` 时序。
3. **Manager 单次 decide**：L0_5_1/L2/L3 query 只调一次 decide，无循环。
4. **L2 reply 基于 L3 结果**：L2 调 l2_query 后 L3 结果回灌，L2 l2_report 的 reply 引用 L3 内容。
5. **cascade 删除**：consolidation 模式下 Manager 不强行调下游，靠 Agent 自驱 l1_query/l2_query。
6. **RoundTree 节点**：decide 后 RoundHistory 含 L1→L2→L3 树，children 正确。
7. **consolidation downward comm 可见**：L1/L2 consolidation strategy 的 allowed_base_tools 含 l1_query/l2_query。
8. **max_rounds_l* 删除**：config 无这三个 key，Manager 不读。

---

## 8. 受影响文件

| 文件 | 改动 |
|------|------|
| `core/tools/downward_comm_tool.py` | **新建**：l1_query/l2_query 注册 + `set_layer_downstreams` |
| `core/tools/__init__.py` | `register_all_tools` 调 `register_downward_tools` |
| `core/chain_factory.py` | `_mount_tools` 调 `set_layer_downstreams`（downstream 链已存在） |
| `core/layers/l0_5_1/manager.py` | 删 while 循环 + cascade + _l2_history；query 改单次 decide + RoundTree push/pop |
| `core/layers/l2/manager.py` | 删 _propagate queries 透传 + cascade + _l3_history；query 改单次 decide + RoundTree push/pop |
| `core/layers/l3/manager.py` | 删 L3_CONTINUE_TOOL + coerce；capture_tools 改 {l3_report} |
| `core/layers/base.py` | `ConsolidationStrategy` L1/L2 allowed_base_tools 加 downward 工具；`decide` docstring 去 "while-loop" |
| `core/round_tree.py` | 新增 thread-local node stack + `current_node`/`push_node`/`pop_node` |
| `config.yaml` | 删 `runtime.max_rounds_l1/l2/l3` |
| `config/tools.yaml` | l1_query 加 L1 allowlist，l2_query 加 L2 allowlist（若未在） |
| `MAINTAIN.md` | 同步 L0_5_1/L2/L3 Manager query 签名、删 max_rounds_l*、改 capture_tool 描述 |

---

## 9. 不在本 spec 范围

- A 部分（chain_factory + ConsolidationContext 架构）—— 见下方评估稿，另行决策。
- #18（`get_tools_for_domain` 零调用）—— 留后续升级点。
- async downward comm（sync=false 的 RoundTree 时序）—— 首版强制 sync，后续再开。

---

# 执行 spec — A 部分：拆 ConsolidationContext + 直接改库 + auto-learning 解耦（#12）

> **状态**：已定方向，待执行。与 B 段独立可并行，但都改 chain_factory/Manager，建议先 B 后 A 或顺序执行避免文件冲突。
> **基准**：以实际代码为准。

## A.1 目标

**拆掉 ConsolidationContext 这个跨主 agent / learning env 的耦合点。** 三类零交集职责分离，两类运行时靠现有接口（Executor.execute + collect_notify）通信，不共享可变 dataclass。

核心决策：
1. **9 CRUD handler 从"提案"改为"直接改库"**，与 4 domain handler 统一。废 `pending_mods` side-channel。
2. **合法性验证归 store 方法**（L1 已自带，L2/L3 按需补）；**domain 索引层操作（embedding/反向索引/correlation 增量标记）归 handler**——domain 是索引层，与正常 IO（card/skill 内容 CRUD）解耦。
3. **auto-learning 改为 learning env 正常给主 agent 发任务**，不从 ConsolidationContext 反向拿 executor。
4. **correlation 增量重算**：DomainRegistry 加 dirty set，handler 改 domain 时标记，L1 Manager.query 在 decide 返回后 flush（O(n × dirty) 而非 O(n²)）。

---

## A.2 改动清单

### A.2.1 废 ConsolidationContext，拆成独立对象

**删除** `core/tools/consolidation_tools.py:10-32` `ConsolidationContext` dataclass + `record_mod`/`drain_mods`。

**替代**：consolidation handler 的 store DI 改用独立注入（沿用 `domain_tool.set_domain_registry` 模式）。

新建 `core/tools/consolidation_injection.py`：
```python
_stores: dict[str, object] = {}   # "l1"/"l2"/"l3" → Philosophy/FlexibleKnowledge/SkillLayer
_registry: object = None          # DomainRegistry

def set_consolidation_stores(stores: dict, registry) -> None:
    global _stores, _registry
    _stores = stores
    _registry = registry
```

handler 读 `_stores["l1"]` / `_stores["l2"]` / `_stores["l3"]` / `_registry`，不再从闭包 `ctx` 拿。

**注入点**：`chain_factory._mount_tools` 调 `set_consolidation_stores({"l1": phil, "l2": fk, "l3": sl}, reg)`。

### A.2.2 9 CRUD handler 改为直接改库

**现状** `_make_handler`（`consolidation_tools.py:276-295`）只调 `ctx.record_mod()` 返回 `{"recorded": True}`。

**改为**：按 `_ModSpec`（`consolidation_tools.py:241-274`）的 `layer`/`mod_type`/`target_arg`/`payload_args` 直接调 store CRUD：

| mod_type | L1 | L2 | L3 |
|----------|----|----|-----|
| create | `Philosophy.add_rule(content, created_by="agent", source="l1")` | `FlexibleKnowledge.add_card(content, domain, source="agent")` | `SkillLayer.create_skill(name, content, domain, created_by="agent")` |
| update | `Philosophy.modify_rule(rule_id, content)` + quality 字段 | `FlexibleKnowledge.modify_card(card_id, content, **quality)` + domain handler 处理 | `SkillLayer.edit_skill(name, content, **quality)` + domain handler 处理 |
| deprecate | `Philosophy.remove_rule(rule_id)` | `FlexibleKnowledge.remove_card(card_id)` | `SkillLayer.delete_skill(name)` |

**quality 字段**（usefulness/misleading/comment）：L1 **去掉**（见 A.4.3，Rule dataclass + 工具 schema + store 列全删，`modify_rule` 不涉及 quality）。L2/L3 的 `modify_card`/`edit_skill` 已收 quality，统一改为收 quality dict（A.4.2），handler 把 payload 里的 quality 字段作为 dict 传给 store。

### A.2.3 domain 索引层操作归 handler

handler 在调 store CRUD 后，额外做 domain 索引层操作（从 `learning_env._apply_l2/_apply_l3` 搬，`learning_env.py:786-794, 813-823`）：

- **L2/L3 update 含 domain 变更**：
  - `registry.get_node(new_domain)` 校验存在（不存在 raise ValueError）
  - `result.domain = Domain(new_domain, "specific")` + `result.available_domains = [new_domain]`
  - `registry.update_item_domains(layer, item_id, [new_domain])` 同步反向索引
  - `registry.mark_domain_dirty(new_domain)` + `registry.mark_domain_dirty(old_domain)`（增量 correlation 用）
- **L2/L3 create**：`registry.index_item(layer, domain, item_id)` + `registry.mark_domain_dirty(domain)`
- **L2/L3 deprecate**：`registry.unindex_item(layer, domain, item_id)` + `registry.mark_domain_dirty(domain)`

**4 domain handler**（query/deprecate/merge/create_domain）已经直接改库，保持现状，补 `mark_domain_dirty` 调用 + embedding 刷新（见 A.2.5）。

### A.2.4 合法性验证归 store 方法

| 验证 | 现归属 | 改后归属 | 动作 |
|------|--------|---------|------|
| L1 duplicate/contradiction/max_rules/L0.5 不可改/长度 | `Philosophy` 内置（`philosophy.py:86-143`） | 不变 | 无需迁移 |
| L1 content 长度 | learning env 重复检查（`learning_env.py:761-763`） | 删（store 已查） | 删 learning env 重复 |
| L2 card 存在性 | learning env（`:784-796`） | `FlexibleKnowledge.modify_card`/`remove_card` 内置 | store 补：modify 返回 None → handler 报错；remove 返回 False → handler 报错（现状已返回 None/False，handler 改为检查返回值） |
| L3 skill 存在性 | learning env（`:818`） | `SkillLayer.edit_skill`/`delete_skill` 内置 | 同 L2 |
| target layer 前缀匹配 | learning env（`:740-744`） | 废（handler 直接按 layer 调对应 store，无 target 字符串解析） | 删 |
| mod_type 合法性 | learning env（`:745-746`） | 废（handler 按 tool name 分发，无 mod_type 字段） | 删 |

### A.2.5 DomainRegistry 增量 correlation

**新增** `core/domain_registry.py`：
```python
def mark_domain_dirty(self, path: str) -> None:
    """Mark a domain as modified for incremental correlation flush."""
    self._dirty_domains.add(path)

def flush_correlations(self) -> int:
    """Recompute correlations only for dirty domains vs all others.
    O(n × dirty_count) instead of O(n²). Clears dirty set after."""
    dirty = list(self._dirty_domains)
    self._dirty_domains.clear()
    count = 0
    for a in dirty:
        if a not in self._nodes:
            continue
        for b in self._nodes:
            if a == b:
                continue
            corr = self.compute_correlation(a, b)
            self.update_correlation(a, b, corr)
            count += 1
    return count
```

`__init__` 加 `self._dirty_domains: set[str] = set()`。

**调用点**：`L0_5_1Manager.query` 在 decide() 返回后（B 段改后的单次 decide 结束）调 `registry.flush_correlations()`。一次 prompt 最多一次。

**涉及 embedding 的 3 domain handler**（create/merge/deprecate_domain）：改完 domain 树后调 `registry.compute_embedding(path, content_getter)` + `mark_domain_dirty`。embedding 是单 domain O(1)，handler 内直接算无性能问题。

### A.2.6 废 side-channel + learning env 应用层

**删除**：
- `consolidation_tools.py` 的 `record_mod`/`drain_mods`（A.2.1 已删 ConsolidationContext）
- 三层 Manager.notify() 的 `drain_mods` 调用 + `lX_modifications` 字段（`l0_5_1/manager.py:437-439`、`l2/manager.py:537-540`、`l3/manager.py:337-339`）
- 三层 Manager 的 `self._consol_ctx` 字段（`l0_5_1/manager.py:263`、`l2/manager.py:389`、`l3/manager.py:236`）
- `build_chain`（`layers/__init__.py:13-35`）的 `consol_ctx` 参数 + 传递
- `learning_env.py` 的 `_apply_layer_mod`/`_apply_l1`/`_apply_l2`/`_apply_l3`/`_apply_parsed_mods`/`_parse_notify_layers`/`_parse_notify_llm`（`:261-731`）
- `learning_env.py` 的 `_quality_kwargs`（`:159-167`，搬进 handler 或 store）
- `learning_env.py:294-317` 的 embedding 刷新块（搬进 handler + Manager flush，A.2.3/A.2.5）

**learning env `step` 退化**：tool handler 直接改库后，`step` 不再"应用修改"。保留一个轻量 `step` 只记录统计（成功/失败计数给 feedback），或直接废 `step` 改用其他方式生成 feedback。需确认（见 A.4）。

### A.2.7 auto-learning 解耦

**现状** `_dispatch_learning`（`record_learning_tool.py:110-180`）从 `_consol_ctx.executor` 反向调层链。

**改为**：auto-learning 触发后，learning env 作为独立运行入口，走正常 `executor.execute(obs)` 路径。

`record_learning_tool.py` 的 `_consol_ctx` 模块级 global（`:7`）删除。`register_record_learning` 不再收 `consol_ctx` 参数。

**executor 获取方式**（解决循环依赖）：auto-learning 触发时，从全局运行时注册表拿 chain+executor。新建 `core/runtime_registry.py`：
```python
_chain = None
_executor = None

def register_runtime(chain, executor) -> None:
    global _chain, _executor
    _chain = chain
    _executor = executor

def get_executor():
    return _executor
```

`chain_factory.build_default_chain` 返回 chain 后，脚本建完 executor 调 `register_runtime(chain, executor)`（一处，替代 8 处手补）。`_dispatch_learning` 改调 `get_executor()`。

**8 处脚本手补删除**：`run_leduc_cognitive.py:157`、`run_douzero_llm.py:111`、`interactive_agent.py:53`、`run_learning_dryrun.py:176`、`test_consolidation_real.py:225`、`test_learning_e2e.py:187`、`test_learning_restructured.py:242`、`test_learning_interaction.py:226` 的 `chain._consol_ctx.executor = executor` 改为 `register_runtime(chain, executor)`（或由 chain_factory 封装一个 `build_chain_with_executor` 工厂统一做）。

---

## A.3 数据流改后

### consolidation 工具调用（主 agent 运行时）
```
Agent.decide → _call_llm tool loop → LLM 调 consolidation 工具
  → handler 直接调 store CRUD（store 自带合法性验证）
  → handler 调 registry domain 索引层操作（index_item/update_item_domains/mark_domain_dirty）
  → domain handler 额外调 compute_embedding
  → 返回 {"success": True} 给 LLM
L0_5_1Manager.query 在 decide 返回后 → registry.flush_correlations()
```
**无 pending_mods，无 drain_mods，无 learning env 应用层。**

### auto-learning（learning env 运行时）
```
record_learning → _check_auto_trigger (pending 满 5)
  → _dispatch_learning
  → executor = get_executor()  ← 从 runtime_registry，不从 ConsolidationContext
  → LearningEnv.process_in_memory → obs
  → executor.execute(obs)  ← 正常层链路径，主 agent 侧 handler 直接改库
  → （learning env 不再 step 应用修改，handler 已改库）
  → if needs_consolidation: executor.execute(consol_task) 再走一次
```

---

## A.4 已决定（原待确认）

1. **learning env `step` 保留轻量版**：tool handler 直接改库后，step 不再应用修改，只统计 handler 返回的 success/error，生成 `_shared_feedback`/`_layer_feedback` 给下一轮 prompt 注入。
2. **`_quality_kwargs` 归 store**：store 方法收 quality dict，内部解析。handler 只传 payload。L2 `FlexibleKnowledge.modify_card`/L3 `SkillLayer.edit_skill` 已收 quality kwargs，统一为收 dict。
3. **L1 quality 字段去掉**（语义正确优先）：L1 是宪法级行为准则，不适用事后 quality 评估；现状字段已死（`modify_rule` 不收、learning env 丢弃、无消费者）。L1/L2/L3 在 quality 上有意不一致，反映 L1 宪法不可评估、L2/L3 经验可评估的语义差异。
   - `Rule` dataclass 删 `usefulness/misleading/comment`（`philosophy.py:26-28`）
   - `modify_l1_rule` 工具 schema 删这三字段（`consolidation_tools.py:85-91`）
   - `L1SQLiteStore` schema 删三列（`l1_store.py:33-35`）+ insert 删三字段（`:44, :54-56`）
   - `_MOD_SPECS` 里 `modify_l1_rule` 的 `payload_args` 删 `usefulness/misleading/comment`（`consolidation_tools.py:257-259`）

---

## A.5 受影响文件

| 文件 | 改动 |
|------|------|
| `core/tools/consolidation_tools.py` | 删 ConsolidationContext；handler 改直接改库 + domain 索引层操作 + mark_dirty；改读 `_stores`/`_registry` 模块级 |
| `core/tools/consolidation_injection.py` | **新建**：`set_consolidation_stores` |
| `core/runtime_registry.py` | **新建**：`register_runtime`/`get_executor` |
| `core/tools/record_learning_tool.py` | 删 `_consol_ctx` global；`_dispatch_learning` 改调 `get_executor()` |
| `core/tools/__init__.py` | `register_all_tools` 不再传 consol_ctx；调 `register_downward_tools`（B 段）+ `set_consolidation_stores` |
| `core/chain_factory.py` | 删 ConsolidationContext 构造；`_mount_tools` 调 `set_consolidation_stores` + `register_runtime`（或工厂封装） |
| `core/domain_registry.py` | 加 `_dirty_domains` + `mark_domain_dirty` + `flush_correlations` |
| `core/layers/__init__.py` | `build_chain` 删 consol_ctx 参数 |
| `core/layers/l0_5_1/manager.py` | 删 _consol_ctx；query 在 decide 返回后调 `flush_correlations` |
| `core/layers/l2/manager.py` | 删 _consol_ctx + drain_mods |
| `core/layers/l3/manager.py` | 删 _consol_ctx + drain_mods |
| `core/env/learning_env.py` | 删 _apply_* / _parse_* / _quality_kwargs / embedding 刷新块；step 退化或废（待 A.4.1） |
| `core/philosophy.py` | `Rule` 删 usefulness/misleading/comment 字段（A.4.3） |
| `core/storage/l1_store.py` | schema 删三列 + insert 删三字段（A.4.3） |
| `core/flexible_knowledge.py` | modify_card/remove_card 存在性检查（现状已返回 None/False，handler 检查） |
| `core/skill_layer.py` | 同 L2 |
| 8 个脚本 | `chain._consol_ctx.executor = executor` 改 `register_runtime(chain, executor)` |
| `MAINTAIN.md` | 同步：删 ConsolidationContext 条目、改 handler/store/Manager 签名、加 runtime_registry/consolidation_injection |

---

## A.6 与 B 段的关系

- A.2.5 的 `flush_correlations` 调用点在 "L0_5_1Manager.query 在 decide() 返回后"——这是 B 段改后的单次 decide 结束位置。B 段未执行时，调用点在 L1 while 循环的 done 分支（`l0_5_1/manager.py:302-357`）。**建议先执行 B 再执行 A**，或 A 的此点按 B 后状态写、B 未执行时暂不接。
- A.2.6 删 Manager.notify 的 `lX_modifications`——B 段不碰 notify 的 mods 字段，无冲突。
- A.2.7 的 `register_runtime` 与 B 段的 `set_layer_downstreams` 都在 `_mount_tools` 调用，无冲突。
- 其余无依赖。
