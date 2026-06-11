# Agent While-Loop 设计

## 动机

当前 V-structure 将每层推理硬编码为固定阶段流水线：

- L1: `stage1`（一次性产出 query）→ propagate L2 → `stage2`（一次性产出决策）
- L2: `stage1`（一次性打分节点）→ `stage2`（一次性选卡片+调L3）→ `stage3`（整合L3结果）

"我需要什么信息"和"我做什幺决策"是同一轮推理的连续过程，不应被切分为两层嵌套 while。
更深层的问题：L1 问一次 L2 后无法追加追问，L2 第一次选卡片后无法修正——隐式 while 不存在。

## 目标

将每层 V-structure 的 stage1/2/3 **合并为单一 while 循环**，循环体内 Agent 交替执行：

1. 判断当前信息是否充分 → `done=True` 则产出 NOTIFY，退出
2. 否则：
   - 通过 `tool_calls` 调用本层可见工具
   - 通过 `queries` 向下层发送子任务（task decomposition）
   - 收集下层 NOTIFY + 工具结果 → 注入下一轮 context → 继续

## Agent 内循环 vs Manager while 循环

当前 `LayerAgent._call_llm()` 内有一个 `MAX_TOOL_TURNS=5` 的内部循环（role:"tool" 消息），
仅在单次 LLM 调用的工具往返内有效。新设计中：

| 循环层级 | 作用 | 嵌套关系 |
|---------|------|---------|
| `_call_llm` 内 MAX_TOOL_TURNS | 单次 LLM 调用的工具往返 | 不变，保留 |
| Manager while（新增） | 多次 LLM 调用 + 工具 + 向下 query 交替 | 包裹 `_call_llm` |

两层嵌套，各有限制：MAX_TOOL_TURNS 限单次 LLM 工具往返；MAX_ROUNDS 限 Manager 整体迭代。

---

## 整体架构

```
Executor.execute()
  └→ L1.query()              [while ≤ MAX_ROUNDS]
       ├→ L1Agent.decide()
       ├→ 工具调用 (todo, knowledge_query)
       ├→ propagate → L2.query()         [while ≤ MAX_ROUNDS]
       │    ├→ L2Agent.decide()
       │    ├→ 工具调用 (todo, terminal, read_file, grep, knowledge_query)
       │    └→ propagate → L3.query()    [while ≤ MAX_ROUNDS]
       │         ├→ L3Agent.decide()
       │         └→ 工具调用 (全部)
       └→ 收集 NOTIFY → 下一轮
```

每层 while 对内完整运行，对外表现为一个 `query()` 调用。嵌套调用关系不变（A1 相邻传递）。

---

## 各层变更

### L1Agent

**删除**: `stage1()`, `stage2()`

**新增**: `decide(meta, state, history, tools, layer) → dict`

**保留**: `_build_system_prompt()`, `_build_user_context()`（decide 内部复用）

`L1_DECISION_SCHEMA`:

```json
{
  "type": "object",
  "properties": {
    "done": {"type": "boolean"},
    "result": {"type": "string", "description": "最终决策文本"},
    "queries": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "向下层 L2 查询的问题"},
          "domains_hint": {"type": "array", "items": {"type": "string"},
                           "description": "建议查询的领域"}
        }
      }
    },
    "reasoning": {"type": "string"}
  },
  "required": ["done", "reasoning"]
}
```

### L1Manager

`query()` 改为 while 循环：

```
while round < MAX_ROUNDS:
    result = L1Agent.decide(meta, state, history, tools, layer="l1")
    if result.done -> self._l1_notify = {done, result, reasoning}, return
    for q in result.queries:
        build sub_obs from q
        propagate to L2 via _downward.wrap_query()
        L2.query() runs its own while loop
        collect L2 NOTIFY -> append to history
    round++
force-terminate if max rounds exhausted
```

### L2Agent

**删除**: `stage1()`, `stage2()`, `stage3()`

**新增**: `decide(query, meta, state, context, tools, layer) → dict`

**保留**: `_build_system_prompt()`, `_build_user_context()`, `_get_cards_for_nodes()`

`L2_DECISION_SCHEMA`:

```json
{
  "type": "object",
  "properties": {
    "done": {"type": "boolean"},
    "reply": {"type": "string", "description": "回复上层查询的结论"},
    "selected_nodes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "score": {"type": "number"}
        }
      }
    },
    "selected_cards": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "domain": {"type": "string"},
          "content": {"type": "string"}
        }
      }
    },
    "queries_to_L3": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "domain": {"type": "string", "description": "目标领域"},
          "task": {"type": "string", "description": "委托 L3 执行的技能任务"}
        }
      }
    },
    "reasoning": {"type": "string"}
  },
  "required": ["done", "reasoning"]
}
```

### L2Manager

`query()` 新增 while 循环触发段，复用存量方法：

```
while round < MAX_ROUNDS:
    result = L2Agent.decide(query, meta, state, context, tools, layer="l2")
    if result.done -> self._l2_notify = {reply, cards, reasoning}, return

    if result.selected_nodes:
        context.selected_nodes = result.selected_nodes
        context.candidate_cards = _get_cards_for_nodes(result.selected_nodes)  # 复用

    for q in result.queries_to_L3:
        build sub_obs from q
        self._propagate(sub_obs, trace_id)  # 复用已有
        collect L3 NOTIFY -> append to context.l3_results
```

**存量不变**: `_upward.receive()` 入口, `_enrich_cards()`, `_propagate()`, `notify()`, `_get_cards_for_nodes()`。

### L3Agent

**删除**: `execute()`

**新增**: `decide(meta, state, context, tools, layer) → dict`

**保留**: `_build_system_prompt()`, `_build_user_context()`，技能匹配逻辑。

`L3_DECISION_SCHEMA`:

```json
{
  "type": "object",
  "properties": {
    "done": {"type": "boolean"},
    "result": {"type": "string", "description": "技能执行结果"},
    "skills_used": {"type": "array", "items": {"type": "string"}},
    "reasoning": {"type": "string"}
  },
  "required": ["done", "reasoning"]
}
```

L3 无下游层，while 循环体仅有工具调用 + 自迭代。

### L3Manager

```
while round < MAX_ROUNDS:
    result = L3Agent.decide(meta, state, context, tools, layer="l3")
    if result.done -> self._l3_notify = {skills_matched, skills_used, result, reasoning}, return
    context.history.append(result)
```

**存量不变**: `_skill_layer.match()` 匹配部分。

---

## 协调协议

### decide() 内部工具处理

`decide()` 内部调用 `_call_llm()`，后者已有 MAX_TOOL_TURNS=5 的多轮工具循环。
因此 `decide()` 返回时所有 tool_calls 已在内部处理完毕，结果已注入最终的 LLM 产出。
Manager while 不需要处理工具调用。

### Manager while 内动作

| `done=False` 时的字段 | Manager 处理 |
|----------------------|-------------|
| `queries`（向下追问） | propagate 到下层 → 下层运行完整 while → 收集 NOTIFY → 注入下一轮 context |
| `queries` 为空且 `done=False` | 视为 done（无下游可追问），产出 NOTIFY |

每轮 decide() 内部可多次调 `_call_llm`（每次含工具往返），Manager 不干预。

### 嵌套调用关系

```
Executor.execute()  ← 单次入口，不变
  └→ L1.query()      [while ≤ MAX_ROUNDS]
       └→ L2.query()  [while ≤ MAX_ROUNDS，L1 每发一个 sub-query 就走一次完整 L2 while]
            └→ L3.query()  [while ≤ MAX_ROUNDS]
```

### 数据传递

上层传下层: `TaskObservation(meta=query_text, state={..., query_context})`
下层回上层: `collect_notify()` → 注入上层 `history` / `context` → 下一轮 decide() 入参

state 字段通过 TaskObservation 传递，L2/L3 NOTIFY 按照现有 `collect_notify()` 机制收集。

---

## 边界与终止

| 约束 | 默认值 | 说明 |
|------|--------|------|
| `MAX_ROUNDS` | 3 | 每层 Manager while 最大迭代次数，可配置 |
| `MAX_TOOL_TURNS` | 5 | 单次 LLM 调用内工具往返限制，不变 |
| 强制终止 | round 耗尽时取最后一轮产出 | LLM 未返回 done=True 但超过 MAX_ROUNDS |
| 空 query | 跳过 | queries 为空且无 tool_calls 时视为 done |

### 防护

- 每层独立 `MAX_ROUNDS`，内层超限不拖垮外层
- `_call_llm` 内 MAX_TOOL_TURNS 不变，工具循环不会因外层 while 而放大
- `Executor.execute()` 入口签名不变，调用方无感

### 不改的部分

- `LayerMessage` 枚举和 Comm Agent 协议
- `Executor.execute()` 入口签名
- `collect_notify()` 链式收集
- `_propagate()`, `_enrich_cards()`, `notify()` 等存量函数体
- 仅使用 QUERY / RESPONSE / NOTIFY 三种 MessageType，不做 PROPOSAL/APPROVAL/REJECTION

---

## 影响范围

### 修改文件

| 文件 | 变更 |
|------|------|
| `core/layers/l0_5_1/manager.py` | `query()` 改 while；删 stage1/stage2 调用 |
| `core/layers/l0_5_1/agent.py` 或同文件内 L1Agent | 删 `stage1()`, `stage2()`；新增 `decide()` |
| `core/layers/l2/manager.py` | `query()` 加 while 触发段；删 stage 调用 |
| `core/layers/l2/agent.py` 或同文件内 L2Agent | 删 `stage1/2/3()`；新增 `decide()` |
| `core/layers/l3/manager.py` | `query()` 加 while；删 execute 调用 |
| `core/layers/l3/agent.py` 或同文件内 L3Agent | 删 `execute()`；新增 `decide()` |
| `core/layers/base.py` | `LayerAgent` 新增 `decide()` 抽象方法 |
| `core/config.py` 或 `config.yaml` | 新增 `MAX_ROUNDS` 配置项 |

### 不受影响的文件

- `core/executor.py` — 入口不变
- `core/layer_message.py` — 协议不变
- `core/layers/comm.py` — Comm Agent 不变
- `core/env/*` — Environment 全部不变
- `capability/*` — 能力系统不变
- `core/tools/*` — 工具系统不变
- `scripts/*` — 脚本层参数不变

---

## 伪代码

### L1Manager.query()

```python
def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
    if isinstance(msg, LayerMessage):
        data = self._upward.receive(msg)
        if not trace_id:
            trace_id = msg.trace_id
    else:
        data = msg

    obs = data if isinstance(data, TaskObservation) else TaskObservation(**data)
    meta = obs.meta
    state = dict(obs.state or {})
    history = []

    for round_idx in range(1, self.max_rounds + 1):
        tools = self._injector.get_tools_for_layer("l1") if self._injector else None
        result = self._agent.decide(
            meta=meta, state=state, history=history,
            tools=tools, layer="l1",
        )

        if result.get("done"):
            self._l1_notify = {
                "done": True,
                "result": result.get("result", ""),
                "reasoning": result.get("reasoning", ""),
            }
            return

        for q in result.get("queries", []):
            sub_obs = TaskObservation(
                meta=q["query"],
                state={
                    **state,
                    "query_context": q,
                    "domains_hint": q.get("domains_hint", []),
                },
            )
            q_msg = self._downward.wrap_query(
                payload=sub_obs,
                source=self.name,
                target=self._downstream.name,
                trace_id=trace_id,
            )
            self._downstream.query(q_msg, trace_id)
            l2_notify = self._downstream.collect_notify()
            history.append({
                "round": round_idx,
                "query": q["query"],
                "l2_reply": l2_notify,
            })
            state[f"l2_round_{round_idx}"] = l2_notify

    # 强制终止
    force = self._agent._call_llm(
        system=self._agent._build_system_prompt("force_terminate", meta),
        user="鉴于已超过最大轮次，基于已有信息给出最终决策。",
        layer="l1",
    )
    self._l1_notify = {"done": True, "result": str(force), "reasoning": "max_rounds"}
```

### L2Manager.query()

```python
def query(self, msg: LayerMessage | Any, trace_id: str = "") -> None:
    if isinstance(msg, LayerMessage):
        data = self._upward.receive(msg)
        if not trace_id:
            trace_id = msg.trace_id
    else:
        data = msg

    obs = data if isinstance(data, TaskObservation) else TaskObservation(**data)
    query_text = obs.meta
    state = dict(obs.state or {})

    context = {
        "history": [],
        "selected_nodes": None,
        "candidate_cards": [],
        "l3_results": [],
    }

    for round_idx in range(1, self.max_rounds + 1):
        tools = self._injector.get_tools_for_layer("l2") if self._injector else None
        result = self._agent.decide(
            query=query_text, meta=obs.meta, state=state,
            context=context, tools=tools, layer="l2",
        )

        if result.get("done"):
            self._l2_notify = {
                "reply": result.get("reply", ""),
                "cards": result.get("selected_cards", []),
                "reasoning": result.get("reasoning", ""),
            }
            return

        if result.get("selected_nodes"):
            context["selected_nodes"] = result["selected_nodes"]
            context["candidate_cards"] = self._agent._get_cards_for_nodes(
                result["selected_nodes"]
            )

        for q in result.get("queries_to_L3", []):
            sub_obs = TaskObservation(
                meta=q["task"],
                state={**state, "domain": q.get("domain", "")},
            )
            self._propagate(sub_obs, trace_id)
            l3_notify = self._downstream.collect_notify()
            context["l3_results"].append(l3_notify)
            context["history"].append({"round": round_idx, "query_to_L3": q})

    # 强制终止
    self._l2_notify = {
        "reply": self._agent._call_llm(
            system=self._agent._build_system_prompt("force_terminate", obs.meta),
            user="基于已有卡片和上下文，给出最终回复。",
            layer="l2",
        ),
        "cards": context["candidate_cards"],
        "reasoning": "max_rounds",
    }
```

---

## 文件影响总结

| 文件 | 删除 | 新增 | 保留 |
|------|------|------|------|
| `core/layers/l0_5_1/manager.py` | stage1/stage2 调用 | while 循环 | upward/downward 入口 |
| L1Agent 所在文件 | `stage1()`, `stage2()` | `decide()` | `_build_system_prompt()`, `_build_user_context()` |
| `core/layers/l2/manager.py` | stage1/2/3 调用 | while 触发段 | `_enrich_cards()`, `_propagate()`, `notify()` |
| L2Agent 所在文件 | `stage1()`, `stage2()`, `stage3()` | `decide()` | `_get_cards_for_nodes()`, build helper |
| `core/layers/l3/manager.py` | execute() 调用 | while 循环 | `_skill_layer.match()` |
| L3Agent 所在文件 | `execute()` | `decide()` | build helper |
| `core/layers/base.py` | — | `decide()` 抽象方法 | 其余不变 |
| `config/layers/*.yaml` / `core/config.py` | — | `max_rounds` 配置 | 其余不变 |

## 与现有 Agent 多轮 Tool Call 的关系

当前 `LayerAgent._call_llm()` 已支持 MAX_TOOL_TURNS=5 的内部工具循环（role:"tool" 消息）。
新设计中 `_call_llm` 不变——它仍是单次 `decide()` 调用中的一部分。
Manager while 在更高一层包裹：`decide()` → 若返回 tool_calls（由 `_call_llm` 内循环处理完）→ Manager 检查 queries → 若有，发往下层 → 下一轮 decide()。

两层循环各有限制和用途，不冲突。
