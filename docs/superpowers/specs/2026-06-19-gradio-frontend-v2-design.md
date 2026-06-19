# Gradio Frontend v2 — Multi-Session + Parallel Task Tracking

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 用 Gradio 构造前端，支持多 session（持久化到本地）+ 单 session 内多 task 并行执行与监控。覆盖 L1/L2/L3 决策链 + sub-agent 任务（`record_learning`/`auto_learning`/`terminal(sync=false)`）。

**痛点根因：** 当前 dispatch-and-forget 任务实际不可追踪 — 6 个调用点用 `get_task_runner()`（每次新建临时 runner），提交的 task_id 返回给 agent 后 runner 失去引用、任务结果写进孤立 dict 立即被 GC。从 agent/前端视角"没有实际执行"。

**Architecture:** Gradio 作为独立前端层，复用现有 logging + RoundTree + executor.execute 返回值作为 trace 数据源，agent core 不加采集逻辑。顶层 task 共享 chain 并行跑；sub-agent task 走 shared `TaskRunner` 线程池。

**Tech Stack:** gradio, Python 3.10+, existing agent chain + SQLite WAL stores

---

## 架构边界

```
┌──────────────────────────────────────────────────────────────────────┐
│  Gradio UI (scripts/gradio_app.py)                                   │
│  ├─ Session 栏   ── SessionStore.list/create/switch/delete           │
│  ├─ 任务栏      ── monitor.task_list(session_id) + chat submit       │
│  └─ Trace 栏    ── monitor.snapshot + log_tail + decision_tree       │
├──────────────────────────────────────────────────────────────────────┤
│  core/setup.py (NEW)                                                 │
│  └─ setup_executor() → shared chain+executor init (CLI/Gradio 共用)  │
├──────────────────────────────────────────────────────────────────────┤
│  core/session.py (NEW)                                               │
│  └─ SessionStore(SQLite WAL) — session + task 元数据 CRUD            │
├──────────────────────────────────────────────────────────────────────┤
│  core/monitor.py (NEW — v1 plan 已登记，文件实际不存在)              │
│  ├─ snapshot(session_id) → tasks/capacity/learning                   │
│  ├─ log_tail(log_dir, layer, lines) → per-layer log 尾部             │
│  ├─ task_list(session_id) → SessionStore.list_tasks                  │
│  └─ decision_tree(task_id) → RoundTree.snapshot                      │
├──────────────────────────────────────────────────────────────────────┤
│  core/task_runner.py (MODIFIED)                                      │
│  ├─ 验证 get_shared_runner() 可用性                                  │
│  ├─ + progress 字段 / subscribe / list_tasks / cancel                │
│  └─ collect 保留历史（不再删除）                                     │
├──────────────────────────────────────────────────────────────────────┤
│  core/storage/*.py (MODIFIED — 并行支持必需)                         │
│  └─ 6 个 store: + check_same_thread=False + 写锁 (threading.Lock)    │
├──────────────────────────────────────────────────────────────────────┤
│  dispatch 调用点 6 处 (MODIFIED)                                      │
│  └─ get_task_runner() → get_shared_runner()                          │
│  ├─ core/tools/record_learning_tool.py:57 (record_learning handler)  │
│  ├─ core/tools/record_learning_tool.py:102 (auto_learning trigger)   │
│  ├─ core/tools/async_tools.py:48 (check_task handler)                │
│  ├─ core/tools/async_tools.py:63 (collect_tasks handler)             │
│  ├─ core/layers/base.py:102 (_drain_pending_async)                   │
│  └─ core/layers/base.py:292,313 (_call_llm sync/async dispatch)      │
├──────────────────────────────────────────────────────────────────────┤
│  Existing core (UNCHANGED — 复用，不加采集)                          │
│  ├─ logging_setup.py — per-layer log 文件 (l0_5_1/l2/l3/executor)    │
│  ├─ round_tree.py — RoundTree.snapshot()                             │
│  ├─ executor.execute() → {action_text, notify_layers}                │
│  └─ TaskRunner.get_shared_runner().status()                           │
└──────────────────────────────────────────────────────────────────────┘
```

**原则：**
- Agent core 零采集逻辑 — trace 全部复用现有 log 文件 + executor.execute 返回值 + RoundTree.snapshot
- Session/task 元数据走新 SessionStore(SQLite)；task 运行时状态走内存 TaskRunner（崩溃标 interrupted）
- 顶层 task 共享 chain 并行跑（依赖 thread-local RoundTree + SQLite WAL + 新增 store 写锁）
- sub-agent task 通过 shared TaskRunner 并行执行，dispatch 时登记到 SessionStore，前端可追踪

---

## 并发模型

### 顶层 task 并行
- 用户可在一个 session 内顺序提交多个 chat 查询；每个查询 = 一个顶层 task
- 多个顶层 task 共享 chain + executor 并行跑（gr.State session 隔离 env，chain/executor 进程级共享）
- 隔离保证：RoundTree 已 thread-local（`current_node`/`push_node`/`pop_node`）；LLMClient HTTP 无状态；ToolRegistry 构造后只读
- 写安全：SQLite store 加 `check_same_thread=False` + per-store 写锁（见 Task 2）

### sub-agent task 并行
- 覆盖范围：`record_learning`(sync=false) / `auto_learning`(auto-trigger) / `terminal`(sync=false)
- 不覆盖：`kb_query`/`kb_fill_gap`（同步阻塞，无 fire-and-forget）
- 通过 shared `TaskRunner` 线程池并行；dispatch 时 `SessionStore.register_task` 登记
- progress 由 handler 调 `TaskRunner.update_progress(task_id, pct)` 上报

---

## 文件清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `core/setup.py` | 新增 | `setup_executor(project_root=None) → (chain, executor)` |
| `core/session.py` | 新增 | `SessionStore` — session + task 元数据 CRUD + thread-local task context（`set/get/clear_task_context`） |
| `scripts/gradio_app.py` | 新增 | Gradio UI 入口 |
| `core/task_runner.py` | 修改 | 验证 shared runner + 增强 API |
| `core/monitor.py` | 新增 | `snapshot`/`log_tail`/`task_list`/`decision_tree` |
| `core/storage/l1_store.py` | 修改 | `check_same_thread=False` + 写锁 |
| `core/storage/l2_store.py` | 修改 | 同上 |
| `core/storage/l3_store.py` | 修改 | 同上 |
| `core/storage/domain_store.py` | 修改 | 同上 |
| `core/storage/kb_store.py` | 修改 | 同上 |
| `core/storage/__init__.py` | 修改 | `_connect` 加 `check_same_thread=False` |
| `core/tools/record_learning_tool.py` | 修改 | 2 处 `get_task_runner()` → `get_shared_runner()` |
| `core/tools/async_tools.py` | 修改 | 2 处同上 |
| `core/layers/base.py` | 修改 | 3 处同上 |
| `scripts/interactive_agent.py` | 修改 | `_setup_executor` → `from core.setup import setup_executor` |
| `MAINTAIN.md` | 修改 | 新增 setup.py/session.py/monitor.py/gradio_app.py 条目；更新 task_runner.py/store 条目 |

---

## Task 1: 修复 dispatch 调用点 + 验证 shared runner

**目标:** 统一所有 dispatch 到 `get_shared_runner()`，验证单进程并发可用。

### 1.1 调用点清单

| 文件:行 | 当前 | 改为 |
|---------|------|------|
| `core/tools/record_learning_tool.py:57` | `get_task_runner()` | `get_shared_runner()` |
| `core/tools/record_learning_tool.py:102` | `get_task_runner()` | `get_shared_runner()` |
| `core/tools/async_tools.py:48` | `get_task_runner()` | `get_shared_runner()` |
| `core/tools/async_tools.py:63` | `get_task_runner()` | `get_shared_runner()` |
| `core/layers/base.py:102` | `get_task_runner()` | `get_shared_runner()` |
| `core/layers/base.py:292` | `get_task_runner()` | `get_shared_runner()` |
| `core/layers/base.py:313` | `get_task_runner()` | `get_shared_runner()` |

### 1.2 验证步骤

`get_shared_runner()` 全局单例从未被并发场景真正测试过。修改后必须验证：

1. 跑现有测试套件：`python -m pytest tests/ -v` — 确认无回归
2. 跑 `scripts/test_async_dispatch.py` — 确认 async dispatch + collect 链路通
3. 新增并发测试：2 个线程同时 `submit` + `collect`，确认 task 不丢失、stats 正确
4. 若发现 shared runner 有问题，修 `TaskRunner` 本身（不加 workaround）

### 1.3 废弃 `get_task_runner()`

`get_task_runner()`（每次新建）是反模式，dispatch 后 runner 失去引用即孤立。修改后该函数标记 deprecated，仅保留给测试 fixture 用（测试需要独立 runner 实例时）。

---

## Task 2: SQLite Store 线程安全（并行支持必需）

**目标:** 让 6 个 store 支持跨线程访问，否则顶层 task 并行第一轮 consolidation 就崩。

### 2.1 问题诊断

当前 `sqlite3.connect()` 默认 `check_same_thread=True`。store 是 chain 构建时单例、`_conn` 单连接。顶层 task 并行跑时多线程访问同一 `_conn` → 抛 `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`。

WAL 模式只在"每线程独立连接指向同一 db 文件"时提供并发写序列化。共享单连接时 WAL 帮不上忙。

### 2.2 修复方案

每个 store `__init__` 加 `check_same_thread=False` + `threading.Lock`：

```python
# core/storage/l2_store.py (representative, same pattern for all 6)
import threading

class L2SQLiteStore:
    def __init__(self, db_path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._write_lock = threading.Lock()
        self._init_schema()

    def insert(self, card: dict) -> None:
        with self._write_lock:
            self._conn.execute(...)
            self._conn.commit()

    def update(self, card_id, **fields) -> bool:
        with self._write_lock:
            self._conn.execute(...)
            self._conn.commit()
            return self._conn.total_changes > 0

    def delete(self, card_id) -> bool:
        with self._write_lock:
            self._conn.execute(...)
            self._conn.commit()
            return self._conn.total_changes > 0
    # 读方法（get/list_all/list_by_domain/count）不加锁，WAL 允许并发读
```

### 2.3 改动文件

| 文件 | 改动 |
|------|------|
| `core/storage/__init__.py:15` | `_connect` 加 `check_same_thread=False` |
| `core/storage/l1_store.py:17` | 同上 + 写锁（insert/update/delete） |
| `core/storage/l2_store.py:18` | 同上 |
| `core/storage/l3_store.py:17` | 同上 |
| `core/storage/domain_store.py:12` | 同上 |
| `core/storage/kb_store.py:17` | 同上 |

### 2.4 验证

新增测试：2 线程并发 `insert` 同一 store，确认无异常、数据完整。跑现有 store 测试套件无回归。

---

## Task 3: TaskRunner 增强

**目标:** 让 TaskRunner 支持 progress/事件/历史/cancel，供前端追踪。

### 3.1 字段与方法变更

```python
@dataclass
class TaskState:
    task_id: str
    tool_name: str
    status: str          # "running" | "done" | "error" | "cancelled"
    created_at: float = field(default_factory=time.time)
    result: Any = None
    error: str = ""
    progress: float = 0.0    # NEW — 0-100, handler 通过 update_progress 上报
    metadata: dict = field(default_factory=dict)  # NEW — session_id/parent_task_id/trace_id 等

class TaskRunner:
    def submit(self, tool_name, fn, metadata=None) -> str:
        """新增 metadata 参数 — dispatch 时注入 session_id/parent_task_id 供前端关联"""

    def update_progress(self, task_id: str, progress: float) -> None:
        """NEW — handler 调用上报进度"""

    def subscribe(self, callback: Callable[[TaskState], None]) -> None:
        """NEW — task 状态变更事件流（前端轮询数据源）"""

    def unsubscribe(self, callback: Callable[[TaskState], None]) -> None:
        """NEW"""

    def list_tasks(self, status: str | None = None, tool_name: str | None = None,
                   session_id: str | None = None) -> list[TaskState]:
        """NEW — 按状态/工具名/session 过滤列出"""

    def cancel(self, task_id: str) -> bool:
        """NEW — 协作式取消（设 cancelled 标志，handler 自检 task.cancelled）"""

    def collect(self, task_ids: list[str], keep_history: bool = True) -> list[dict]:
        """CHANGED — keep_history 默认 True，不再删除已收集任务"""
```

### 3.2 事件触发点

`_on_async_done` 在状态变更后调所有 subscriber：
```python
def _on_async_done(self, task_id, future):
    with self._lock:
        task = self._tasks.get(task_id)
    if task is None: return
    try:
        task.result = future.result()
        task.status = "done"
    except Exception as e:
        task.status = "error"
        task.error = str(e)
    self._notify(task)  # NEW

def _notify(self, task):
    for cb in list(self._subscribers):
        try: cb(task)
        except Exception: pass
```

### 3.3 cancel 机制

`TaskState` 加 `cancelled: bool = False`。handler 在长操作循环中自检：
```python
def _long_running_handler(...):
    runner = get_shared_runner()
    task = runner.check(my_task_id)
    for chunk in work:
        if task and task.cancelled:
            return {"status": "cancelled"}
        runner.update_progress(my_task_id, pct)
        process(chunk)
```

`record_learning`/`auto_learning`/`terminal` 的 handler 在循环点加自检。

### 3.4 内存不持久化

第一版 task 运行时不持久化 — SessionStore 只存元数据 + 完成后的 result_summary。崩溃时进行中 task 标 `interrupted`（前端启动时扫描 `status="running"` 且 `updated_at` 超过阈值的 task 改 `interrupted`）。

---

## Task 4: SessionStore (`core/session.py`)

**目标:** 持久化 session + task 元数据到 SQLite，支持前端 session 列表 + task 追踪。

### 4.1 Schema

```sql
-- data/cognitive/sessions.db (WAL)
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | closed
    log_dir TEXT,                            -- logs/interaction/{ts} 路径
    last_active_at TEXT NOT NULL
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,                     -- = TaskRunner task_id (sub-agent) 或 UUID (顶层)
    session_id TEXT NOT NULL,
    parent_task_id TEXT,                     -- sub-agent 关联到顶层 task
    type TEXT NOT NULL,                      -- "top" | "record_learning" | "auto_learning" | "terminal" | ...
    tool_name TEXT,                          -- sub-agent 的工具名
    status TEXT NOT NULL,                    -- running | done | error | cancelled | interrupted
    progress REAL NOT NULL DEFAULT 0.0,
    trace_id TEXT,                           -- RoundTree 关联
    result_summary TEXT,                     -- 完成后的结果摘要（前 500 字）
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX idx_tasks_session ON tasks(session_id);
CREATE INDEX idx_tasks_parent ON tasks(parent_task_id);
```

### 4.2 API

```python
class SessionStore:
    def __init__(self, db_path: Path | str = "data/cognitive/sessions.db"): ...

    # Session
    def create_session(self, name: str, log_dir: str | None = None) -> dict: ...
    def list_sessions(self, include_closed: bool = False) -> list[dict]: ...
    def get_session(self, session_id: str) -> dict | None: ...
    def update_session(self, session_id: str, **fields) -> bool: ...
    def close_session(self, session_id: str) -> None: ...
    def delete_session(self, session_id: str) -> None: ...  # 级联删 tasks

    # Task
    def register_task(self, task_id: str, session_id: str, type: str,
                      parent_task_id: str | None = None, tool_name: str | None = None,
                      trace_id: str | None = None) -> None: ...
    def update_task(self, task_id: str, **fields) -> bool: ...
    def list_tasks(self, session_id: str, parent_task_id: str | None = None) -> list[dict]: ...
    def get_task(self, task_id: str) -> dict | None: ...

    # 维护
    def mark_interrupted_on_startup(self) -> int: ...
    """启动时扫描 status='running' 且 updated_at 超 1h 的 task 改 'interrupted'"""
```

### 4.3 与 TaskRunner 集成

Gradio 启动时：
1. `SessionStore` 单例
2. `TaskRunner.subscribe(callback)` — callback 收到 task 状态变更 → `SessionStore.update_task(task_id, status=..., progress=..., result_summary=...)`
3. dispatch 调用点在 `TaskRunner.submit(..., metadata={session_id, parent_task_id})` 后调 `SessionStore.register_task(...)`

**dispatch 调用点修改细节**（Task 1 的扩展）：

| 调用点 | 额外改动 |
|--------|---------|
| `record_learning_tool.py:57` | submit 后 `SessionStore.register_task(tid, session_id, "record_learning", parent_task_id=current_top_task_id)` |
| `record_learning_tool.py:102` | 同上，type="auto_learning" |
| `base.py:292` (async dispatch) | 同上，type=tool_name, parent_task_id=当前顶层 task |

**session_id/parent_task_id 来源：** 通过 thread-local context（新 `core/runtime_context.py` 或复用现有 thread-local 机制）传递。顶层 task 执行前 set，执行后 clear。sub-agent handler 读取。

```python
# core/runtime_context.py (NEW, 轻量)
import threading
_context = threading.local()

def set_task_context(session_id: str, task_id: str):
    _context.session_id = session_id
    _context.task_id = task_id

def get_task_context() -> tuple[str | None, str | None]:
    return getattr(_context, 'session_id', None), getattr(_context, 'task_id', None)

def clear_task_context():
    _context.session_id = None
    _context.task_id = None
```

> 注：thread-local context 放 `core/session.py` 内（与 SessionStore 同模块），不新建 `runtime_context.py`、不塞进 `runtime_registry.py`（后者是进程级全局，混入 thread-local 会混淆职责）。`session.py` 导出 `set_task_context`/`get_task_context`/`clear_task_context` 三个函数。

---

## Task 5: Monitor 模块 (`core/monitor.py`)

**目标:** 聚合 trace 数据源（全复用现有，agent core 不加采集）。

### 5.1 API

```python
def snapshot(session_id: str | None = None, chain=None, pending_dir="data/learning/pending") -> dict:
    """聚合静态状态 + 任务列表"""
    return {
        "tasks": _task_list(session_id),
        "capacity": _capacity_snapshot(chain),
        "learning": _learning_snapshot(pending_dir),
        "sessions": _session_summary(),
    }

def task_list(session_id: str, parent_task_id: str | None = None) -> list[dict]:
    """从 SessionStore 拉任务列表"""
    from core.session import get_session_store
    return get_session_store().list_tasks(session_id, parent_task_id)

def log_tail(log_dir: str, layer: str, lines: int = 50) -> str:
    """读 per-layer log 文件尾部"""
    # layer: "l0_5_1" | "l2" | "l3" | "executor"
    path = Path(log_dir) / f"{layer}.log"
    if not path.exists():
        return ""
    with open(path, encoding="utf-8") as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])

def decision_tree(task_id: str | None = None) -> list:
    """复用 RoundTree.snapshot()"""
    from core.round_tree import get_round_history
    return get_round_history().snapshot()

def task_detail(task_id: str) -> dict:
    """单 task 详情：SessionStore.get_task + 关联 trace"""
    from core.session import get_session_store
    return get_session_store().get_task(task_id)
```

### 5.2 子函数（复用 v1 plan 的实现）

`_task_snapshot`/`_learning_snapshot`/`_capacity_snapshot`/`_log_snapshot` 沿用 v1 plan 已验证的实现（见 v1 plan 1.2 节，API 已在 MAINTAIN 登记但文件未实际创建）。

### 5.3 Key API 验证

| Plan 引用 | 实际存在 | 备注 |
|-----------|---------|------|
| `TaskRunner.status()` | ✅ `core/task_runner.py:125` | |
| `get_shared_runner()` | ✅ `core/task_runner.py:171` | |
| `chain._downstream._knowledge.cards` | ✅ | chain→L2Manager→FlexibleKnowledge |
| `chain._downstream._downstream._skill_layer.list_all()` | ✅ | chain→L2Manager→L3Manager→SkillLayer |
| `RoundTree.snapshot()` | ✅ `core/round_tree.py` | thread-local |
| `executor.execute() → {action_text, notify_layers}` | ✅ `core/executor.py:39` | |
| `logs/interaction/{ts}/{l0_5_1,l2,l3,executor}.log` | ✅ `logging_setup.py` | 纯文本 DEBUG |

---

## Task 6: Gradio App (`scripts/gradio_app.py`)

**目标:** 三栏布局 — Session 栏 / 任务栏 / Trace 栏。

### 6.1 布局

```
┌─ Session 栏（左 25%）─┬─ 任务栏（中 30%）────┬─ Trace 栏（右 45%）─────┐
│ [+ 新建 session]    │ 当前 session 的任务   │ 选中 task 的详情         │
│ ─────────────────── │ ───────────────────  │ ─────────────────────── │
│ • 工作区A (active)  │ ▶ 用户查询 [running] │ ▶ 决策树 (L1→L2→L3)     │
│ • 实验1  (idle)     │   ▓▓▓▓░░ 60%         │   ├ L1: result/reasoning │
│ • 调试X  (closed)   │ ▶ record_learning    │   ├ L2: reply/reasoning  │
│   [持久化列表]      │   [done] ✓           │   └ L3: result/reasoning │
│                    │ ▶ auto_learning       │ ─────────────────────── │
│ [删除] [重命名]     │   [running] ▓░░░░ 20%│ 子任务 (sub-agent)       │
│                    │ ▶ terminal(sync=false)│   ├ record_learning tid  │
│                    │   [queued]            │   ├ auto_learning tid    │
│                    │ [刷新]                │   └ terminal tid         │
│                    │ ─── chat ───         │ ─────────────────────── │
│                    │ [输入框] [发送]       │ 层日志 (尾部 50 行)       │
│                    │                      │ [L1] [L2] [L3] [Exec]    │
└────────────────────┴──────────────────────┴──────────────────────────┘
```

### 6.2 核心组件

```python
# scripts/gradio_app.py (骨架)
import gradio as gr
from core.setup import setup_executor
from core.session import get_session_store
from core.monitor import snapshot, log_tail, task_list, decision_tree, task_detail
from core.session import get_session_store, set_task_context, clear_task_context

@dataclass
class SessionState:
    env: object = None
    session_id: str = ""
    current_task_id: str = ""  # trace 栏选中的 task

def main():
    chain, executor = setup_executor(PROJECT_ROOT)
    session_store = get_session_store()

    def create_session(name):
        s = session_store.create_session(name)
        env = _create_env()
        return SessionState(env=env, session_id=s["id"]), *_refresh(s["id"])

    def chat(user_input, state):
        env = state.env
        env.receive_input(user_input)
        obs = env.build_task_observation()
        # 注册顶层 task
        top_tid = str(uuid.uuid4())[:12]
        session_store.register_task(top_tid, state.session_id, "top")
        set_task_context(state.session_id, top_tid)
        try:
            result = executor.execute(obs)
            reply = result.get("action_text", "")
            session_store.update_task(top_tid, status="done",
                                       result_summary=reply[:500])
        except Exception as e:
            session_store.update_task(top_tid, status="error", result_summary=str(e))
            reply = f"[Error] {e}"
        finally:
            clear_task_context()
        env.step(reply)
        return state, *_refresh(state.session_id, top_tid)

    def _refresh(session_id, focus_task_id=None):
        snap = snapshot(session_id=session_id, chain=chain)
        tasks = snap["tasks"]
        # session 栏 / 任务栏 / trace 栏更新
        ...
        return (session_list_update, task_list_update, trace_update, ...)

    # Gradio Blocks 布局 + 定时刷新 every=2s
    with gr.Blocks() as app:
        session_state = gr.State()
        with gr.Row():
            with gr.Column(scale=1):  # Session 栏
                ...
            with gr.Column(scale=1):  # 任务栏
                ...
            with gr.Column(scale=2):  # Trace 栏
                ...
        # 定时刷新
        app.load(lambda s: _refresh(s.session_id), [session_state],
                 [outputs], every=2)
    app.launch(server_name="127.0.0.1", server_port=7860)
```

### 6.3 状态管理

| 问题 | 修复 |
|------|------|
| InteractionEnv 缺 system_prompt | 传 `DEFAULT_SYSTEM_PROMPT` |
| reset() 未调用 | `_create_env()` 中调 `env.reset()` |
| 多 session 共享 env | `gr.State` 每 session 独立 |
| LLM 同步阻塞 UI | Gradio 队列模式自动排队；定时刷新 every=2s 不阻塞 |
| session_id/parent_task_id 传递 | `runtime_context` thread-local，chat 入口 set / finally clear |
| TaskRunner 事件 → SessionStore | `TaskRunner.subscribe(callback)` callback 调 `session_store.update_task` |
| 进行中 task 崩溃恢复 | 启动时 `session_store.mark_interrupted_on_startup()` |

### 6.4 trace 栏数据源（全复用现有）

- 顶层 task NOTIFY：`executor.execute()` 返回值（chat callback 捕获）
- 决策树：`monitor.decision_tree()` → `RoundTree.snapshot()`
- sub-agent 子任务：`monitor.task_list(session_id, parent_task_id=top_tid)`
- 层日志：`monitor.log_tail(log_dir, layer, lines=50)` 读 `logs/interaction/{ts}/*.log` 尾部

---

## Task Dependency Graph

```
T1 (dispatch 修复 + shared runner 验证) ─┐
                                          ├─→ T3 (TaskRunner 增强) ─┐
T2 (store 线程安全) ──────────────────────┘                          │
                                                                     ├─→ T6 (Gradio App)
T4 (SessionStore) ──────────────────────────→ T5 (Monitor) ──────────┘
                                                                     │
T0 (core/setup.py) ───────────────────────────────────────────────────┘
```

执行顺序：T0 → T1 → T2 → T3 → T4 → T5 → T6（T1/T2 可并行，T4 可与 T1/T2 并行）

---

## 自检清单

### 并发正确性
- [ ] 6 个 store 加 `check_same_thread=False` + 写锁
- [ ] 7 处 `get_task_runner()` → `get_shared_runner()`
- [ ] `get_shared_runner()` 并发测试通过（2 线程 submit+collect 无丢失）
- [ ] 顶层 task 并行测试通过（2 个 executor.execute 并发跑，NOTIFY 不串）
- [ ] store 并发写测试通过（2 线程并发 insert 同一 store）

### SessionStore
- [ ] SQLite WAL + `check_same_thread=False` + 写锁
- [ ] session CRUD + task CRUD 完整
- [ ] `mark_interrupted_on_startup` 正确标记崩溃残留 task
- [ ] parent_task_id 关联正确（sub-agent → 顶层 task）

### TaskRunner
- [ ] `progress` 字段 + `update_progress` API
- [ ] `subscribe`/`unsubscribe` 事件流
- [ ] `list_tasks` 按状态/工具名/session 过滤
- [ ] `cancel` 协作式取消（handler 自检）
- [ ] `collect(keep_history=True)` 不删除任务

### runtime_context
- [ ] thread-local session_id/parent_task_id 传递
- [ ] chat 入口 set / finally clear
- [ ] sub-agent handler 读取并传给 `SessionStore.register_task`

### Monitor
- [ ] `snapshot`/`task_list`/`log_tail`/`decision_tree`/`task_detail` 实现
- [ ] 所有函数纯查询，不修改状态
- [ ] API 引用已验证存在（见 5.3 表）

### Gradio
- [ ] 三栏布局：Session 栏 / 任务栏 / Trace 栏
- [ ] `gr.State` 每 session 独立 env
- [ ] 定时刷新 `every=2s`
- [ ] trace 栏复用 log 文件 + RoundTree.snapshot + executor.execute 返回值
- [ ] sub-agent 子任务通过 `task_list(parent_task_id)` 展示
- [ ] 层日志 tab 切换（L1/L2/L3/Exec）

### 文件/纪律
- [ ] agent core 零采集逻辑（trace 全复用现有）
- [ ] `interactive_agent.py` 改用 `setup_executor`
- [ ] 无死导入
- [ ] `MAINTAIN.md` 新增条目：`setup.py`/`session.py`（含 thread-local context 函数）/`monitor.py`/`gradio_app.py`；更新 `task_runner.py`/6 个 store 条目
- [ ] v1 plan（2026-06-18）标记 superseded by v2

### 测试
- [ ] 新增并发测试：shared runner + store 并发写 + 顶层 task 并行
- [ ] 现有测试套件无回归
- [ ] Gradio 启动冒烟测试（手动）
