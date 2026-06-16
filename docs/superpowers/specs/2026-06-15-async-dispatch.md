# Async Dispatch — Design Spec

**Goal:** Agent 工具调用支持 sync/async 两种模式，同轮工具互不阻塞，async 任务后台执行后通过 collect 收割。

**Status:** Draft v1

---

## 1. 核心语义

### 工具分类

每个工具注册时声明 `sync: bool`：

| sync | 语义 | 用法 |
|------|------|------|
| `true` | 阻塞型：Agent 本轮结束前等待结果 | `read_file`, `web_search`, `terminal`, `kb_delete` |
| `false` | Fire-and-forget：返回 task_id，后续收割 | `kb_query_async`, `kb_fill_gap_async` |

### 轮内并行规则

```
Agent Round:
  ┌─ 提交 web_search(sync=true)    ┐
  ├─ 提交 read_file(sync=true)     ├ 同时提交到线程池
  ├─ 提交 kb_query_async(false)    ┤ 互不阻塞
  └─ 提交 grep(sync=true)          ┘
  ↓
  [run_sync_batch: 等待所有 sync=true 完成，按 tool_call_id 匹配结果]
  ↓
  Agent 看到: web_search结果 + read_file结果 + grep结果 + {async_task_id}
```

**实现**: `_call_llm` 中将 `for tc in executable_calls` 逐条串行改为 `TaskRunner.run_sync_batch()` 批量并行提交 + 统一等待。结果通过 `tool_call_id` 匹配，顺序无关。

### 异步结果收割

```
Round N+1:
  kb_collect_tasks(["a1", "a2"]) → [result_a1, result_a2]
  
  如果某个 task 还在跑:
  kb_collect_tasks(["a3"]) → []   (空，还没完成)
  
  单查:
  kb_check_task("a3") → {status: "running"}
```

---

## 2. 组件设计

### TaskRunner (`core/task_runner.py`)

全局单例，管理线程池 + 任务生命周期。

```python
@dataclass
class TaskState:
    task_id: str
    tool_name: str
    status: str           # "running" | "done" | "error"
    created_at: float
    result: Any = None
    error: str = ""

class TaskRunner:
    _pool: ThreadPoolExecutor
    _tasks: dict[str, TaskState]           # 所有活跃/刚完成的任务
    _sync_futures: dict[str, Future]       # 当前轮 sync=true 的 futures
    _stats: dict[str, dict]                # 工具级统计
    
    submit(tool_name, fn, sync) → str | Any
        # sync=True: 提交到线程池, 记录 Future, 返回占位 (轮边界 resolve)
        # sync=False: 提交到线程池, 记录 TaskState, 返回 task_id

    wait_sync() → dict[str, Any]           # 等待所有 sync futures, 返回 {task_id: result}
    collect(task_ids) → list[TaskState]    # 收已完成 async 任务, 从 _tasks 删除
    check(task_id) → TaskState | None
    stats() → dict                         # 运行统计
```

### ToolRegistry 扩展 (`core/tools/registry.py`)

```python
@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    sync: bool = True              # ← 新增
    available_domains: list[str] = field(default_factory=lambda: ["general"])
```

注册时:
```python
registry.register("kb_query_async", schema, handler, toolset="core", sync=False)
```

### 工具注册 (`config/tools.yaml`)

```yaml
tools:
  kb_query:
    sync: true
    timeout: 60
    allowlist: [l1, l2, l3]

  kb_query_async:
    sync: false
    timeout: 5
    allowlist: [l1, l2, l3]

  kb_fill_gap_async:
    sync: false
    timeout: 5
    allowlist: [l1, l2, l3]

  kb_check_task:
    sync: true
    timeout: 5
    allowlist: [l1, l2, l3]

  kb_collect_tasks:
    sync: true
    timeout: 10
    allowlist: [l1, l2, l3]
```

### LayerAgent 调用循环 (`core/layers/base.py`)

`_call_llm` 方法的每轮迭代末尾:

```python
# After all tool calls executed in this turn:
if self._task_runner:
    sync_results = self._task_runner.wait_sync()
    # inject sync_results into next turn's user prompt
    ...

# Before next LLM call, format sync_results + pending async task_ids
```

### Agent 提示词注入

L1 system prompt 加:
```
工具调用规则:
- sync=true 的工具结果在本轮结束时返回给你
- sync=false 的工具会立即返回 task_id，你需要在下几轮调用
  kb_collect_tasks 来获取结果
- 同一轮的所有工具调用之间没有依赖关系，会同时执行
- 如果某轮没有 sync=true 的工具调用，本轮会立即进入下一轮
```

---

## 3. 任务生命周期

```
submit(sync=true):
  → 记录 Future → 本轮结束时 wait_sync() → 返回结果 → 清理 Future

submit(sync=false):
  → 创建 TaskState → 提交到线程池 →
    running → Agent 调用 check_task → 看到 "running"
    done    → Agent 调用 collect_tasks → 返回结果 → 从 _tasks 删除
    error   → Agent 调用 collect_tasks → 返回错误 → 从 _tasks 删除

  超时: 无自动超时。Agent 可以在多轮后放弃收集。
  内存: 任务结果被收集后立即删除。未收集的任务在进程退出时丢失。
  统计: 每个工具调用都记录 count/duration/errors 到 _stats，永久保留（内存）。
```

---

## 4. 文件清单

| 文件 | 角色 |
|------|------|
| `core/task_runner.py` | TaskRunner 类 — 线程池 + 任务状态 + 统计 |
| `core/tools/registry.py` | ToolEntry 加 `sync` 字段 |
| `core/tools/async_tools.py` | `kb_check_task`, `kb_collect_tasks` 工具注册 |
| `core/tools/kb_tools.py` | 加 `kb_query_async`, `kb_fill_gap_async` 注册 |
| `core/layers/base.py` | `_call_llm` 工具循环 → `run_sync_batch()` 并行 |
| `core/layers/l0_5_1/manager.py` | L1 prompt 加工具规则说明 |
| `core/layers/l2/manager.py` | L2 prompt 加工具规则说明 |
| `core/layers/l3/manager.py` | L3 prompt 加工具规则说明 |
| `config/tools.yaml` | 所有工具加 `sync` 字段 |
| `core/chain_factory.py` | 初始化 TaskRunner，注入到 agent |

---

## 5. 兼容性

- 所有现有工具 `sync` 默认 `true` — 行为不变
- ToolEntry 的 `sync` 字段不改变现有的 toolset/allowlist 逻辑
- KB 的子 agent 路径（SubAgentLoop, FillGapLoop）保持不变，只是外层调用方式从同步变异步
