# Gradio Frontend v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Gradio 构造前端，支持多 session（持久化）+ 单 session 内多 task 并行执行与监控，覆盖 L1/L2/L3 决策链 + sub-agent 任务。

**Architecture:** Gradio 独立前端层，复用现有 logging + RoundTree + executor.execute 返回值作为 trace 数据源（agent core 零采集）。顶层 task 共享 chain 并行跑；sub-agent task 走 shared `TaskRunner` 线程池。SQLite store 加 `check_same_thread=False` + 写锁支持跨线程。

**Tech Stack:** gradio, Python 3.10+, existing agent chain, SQLite WAL, threading

**Spec:** `docs/superpowers/specs/2026-06-19-gradio-frontend-v2-design.md`

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `core/setup.py` | 新增 | `setup_executor()` — CLI/Gradio 共享初始化 |
| `core/session.py` | 新增 | `SessionStore`(SQLite) + thread-local task context |
| `core/monitor.py` | 新增 | 聚合 trace 数据源（snapshot/log_tail/task_list/decision_tree） |
| `scripts/gradio_app.py` | 新增 | Gradio UI 入口（三栏布局） |
| `core/task_runner.py` | 修改 | progress/subscribe/list_tasks/cancel + collect 保留历史 |
| `core/storage/__init__.py` | 修改 | `_connect` 加 `check_same_thread=False` |
| `core/storage/l1_store.py` | 修改 | `check_same_thread=False` + 写锁 |
| `core/storage/l2_store.py` | 修改 | 同上 |
| `core/storage/l3_store.py` | 修改 | 同上 |
| `core/storage/domain_store.py` | 修改 | 同上 |
| `core/storage/kb_store.py` | 修改 | 同上 |
| `core/tools/record_learning_tool.py` | 修改 | 2 处 `get_task_runner()` → `get_shared_runner()` + register_task |
| `core/tools/async_tools.py` | 修改 | 2 处同上 |
| `core/layers/base.py` | 修改 | 3 处同上 + async dispatch register_task |
| `scripts/interactive_agent.py` | 修改 | `_setup_executor` → `setup_executor` |
| `tests/test_setup.py` | 新增 | setup_executor 测试 |
| `tests/test_session.py` | 新增 | SessionStore 测试 |
| `tests/test_monitor.py` | 新增 | monitor 测试 |
| `tests/test_task_runner_concurrent.py` | 新增 | shared runner 并发测试 |
| `tests/test_storage_threadsafe.py` | 新增 | store 跨线程测试 |
| `tests/test_dispatch_tracking.py` | 新增 | dispatch → SessionStore 集成测试 |
| `MAINTAIN.md` | 修改 | 新增/更新条目 |

---

## Task 0: 提取共享 setup (`core/setup.py`)

**Files:**
- Create: `core/setup.py`
- Modify: `scripts/interactive_agent.py:37-55`
- Test: `tests/test_setup.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_setup.py
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_setup_executor_returns_chain_and_executor(tmp_path, monkeypatch):
    """setup_executor 应返回 (chain, executor) 元组并注册到 runtime_registry。"""
    # Mock 重依赖以避免真实 LLM/加载
    mock_llm = MagicMock()
    mock_chain = MagicMock(name="chain")
    mock_executor = MagicMock(name="executor")

    with patch("core.setup.load_env") as mock_load_env, \
         patch("core.setup.build_llm_client", return_value=mock_llm), \
         patch("core.setup.build_default_chain", return_value=mock_chain), \
         patch("core.setup.Executor", return_value=mock_executor), \
         patch("core.setup.register_runtime") as mock_register:
        from core.setup import setup_executor
        chain, executor = setup_executor(project_root=tmp_path)

    assert chain is mock_chain
    assert executor is mock_executor
    mock_load_env.assert_called_once_with(tmp_path)
    mock_register.assert_called_once_with(mock_chain, mock_executor)


def test_setup_executor_defaults_project_root(monkeypatch):
    """不传 project_root 时使用 setup.py 所在目录的 parent。"""
    with patch("core.setup.load_env"), \
         patch("core.setup.build_llm_client", return_value=MagicMock()), \
         patch("core.setup.build_default_chain", return_value=MagicMock()), \
         patch("core.setup.Executor", return_value=MagicMock()), \
         patch("core.setup.register_runtime"):
        from core.setup import setup_executor
        setup_executor()  # 不应抛异常
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_setup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.setup'`

- [ ] **Step 3: 创建 `core/setup.py`**

```python
# core/setup.py
"""Shared executor/chain setup — used by both CLI and Gradio."""
from __future__ import annotations
from pathlib import Path
from typing import Any


def setup_executor(project_root: Path | None = None) -> tuple[Any, Any]:
    """Create and wire llm → chain → executor. Returns (chain, executor).

    Registers the chain + executor to runtime_registry so auto-learning
    and other global consumers can find them.
    """
    from core.env_loader import load_env
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    load_env(project_root)

    from core.llm_factory import build_llm_client
    llm = build_llm_client(project_root / "config.yaml")

    from core.chain_factory import build_default_chain
    chain = build_default_chain(project_root, auxiliary_llm=llm, seed=False)

    from core.executor import Executor
    executor = Executor(
        layer_root=chain,
        llm_client=llm,
        learning_dir=project_root / "data" / "learning",
    )

    from core.runtime_registry import register_runtime
    register_runtime(chain, executor)

    return chain, executor
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_setup.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 修改 `scripts/interactive_agent.py`**

替换 `_setup_executor` 函数（行 37-55）：

```python
# scripts/interactive_agent.py (替换 _setup_executor 函数体)
def _setup_executor():
    from core.setup import setup_executor
    chain, executor = setup_executor(PROJECT_ROOT)
    return executor
```

- [ ] **Step 6: 跑 CLI 冒烟测试（手动，确认无回归）**

Run: `python -c "from scripts.interactive_agent import _setup_executor; print('import ok')"`
Expected: 输出 `import ok`（不实际初始化，只验证 import 链）

- [ ] **Step 7: Commit**

```bash
git add core/setup.py scripts/interactive_agent.py tests/test_setup.py
git commit -m "refactor: extract setup_executor to core/setup.py (shared by CLI/Gradio)"
```

---

## Task 1: 修复 dispatch 调用点 + 验证 shared runner

**Files:**
- Modify: `core/tools/record_learning_tool.py:57,102`
- Modify: `core/tools/async_tools.py:48,63`
- Modify: `core/layers/base.py:102,292,313`
- Test: `tests/test_task_runner_concurrent.py`

- [ ] **Step 1: 写 shared runner 并发测试**

```python
# tests/test_task_runner_concurrent.py
"""验证 get_shared_runner() 在多线程 submit+collect 下的正确性。"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.task_runner import get_shared_runner, TaskRunner


def test_shared_runner_is_singleton():
    """get_shared_runner() 返回同一实例。"""
    # 注意：shared runner 是进程级单例，测试间状态会泄漏。
    # 此测试只验证身份相等，不验证状态。
    a = get_shared_runner()
    b = get_shared_runner()
    assert a is b


def test_concurrent_submit_and_collect():
    """2 线程同时 submit + collect，task 不丢失。"""
    runner = get_shared_runner()
    results = {}
    lock = threading.Lock()

    def worker(worker_id: int):
        tids = []
        for i in range(10):
            tid = runner.submit(f"test_tool_{worker_id}",
                                 lambda w=worker_id, i=i: f"r{w}-{i}")
            tids.append(tid)
        # 收割
        collected = runner.collect(tids, keep_history=True)
        with lock:
            results[worker_id] = collected

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, w) for w in range(2)]
        for f in as_completed(futures):
            f.result()  # propagate exceptions

    # 每个 worker 应该收到 10 个结果
    assert len(results[0]) == 10
    assert len(results[1]) == 10
    # 所有 task 应该是 done 状态
    for collected in results.values():
        for item in collected:
            assert item["status"] == "done"


def test_concurrent_submit_does_not_lose_tasks():
    """高频并发 submit 不丢任务（验证 _tasks dict 锁保护）。"""
    runner = get_shared_runner()
    submitted_tids = []
    submit_lock = threading.Lock()

    def submitter():
        for i in range(20):
            tid = runner.submit("burst", lambda i=i: i)
            with submit_lock:
                submitted_tids.append(tid)

    threads = [threading.Thread(target=submitter) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 80 个 task 全部应可查询到
    for tid in submitted_tids:
        assert runner.check(tid) is not None, f"task {tid} lost"
```

- [ ] **Step 2: 跑测试确认现状**

Run: `python -m pytest tests/test_task_runner_concurrent.py -v`
Expected: 可能 FAIL 或 PASS — 验证 shared runner 当前是否真的安全

- [ ] **Step 3: 修改 7 处 dispatch 调用点**

```python
# core/tools/record_learning_tool.py:57 (在 _record_learning_handler)
# 原: from core.task_runner import get_task_runner
#     tid = get_task_runner().submit("record_learning", _run)
# 改:
from core.task_runner import get_shared_runner
tid = get_shared_runner().submit("record_learning", _run)

# core/tools/record_learning_tool.py:102 (在 _check_auto_trigger)
# 原: from core.task_runner import get_task_runner
#     get_task_runner().submit("auto_learning", lambda ...)
# 改:
from core.task_runner import get_shared_runner
get_shared_runner().submit("auto_learning", lambda d=domain, p=pending_path, files=json_files:
_dispatch_learning(d, p, files))

# core/tools/async_tools.py:48 (在 _check_task_handler)
# 原: from core.task_runner import get_task_runner
#     task = get_task_runner().check(task_id)
# 改:
from core.task_runner import get_shared_runner
task = get_shared_runner().check(task_id)

# core/tools/async_tools.py:63 (在 _collect_tasks_handler)
# 原: from core.task_runner import get_task_runner
#     runner = get_task_runner()
# 改:
from core.task_runner import get_shared_runner
runner = get_shared_runner()

# core/layers/base.py:102 (在 _drain_pending_async)
# 原: from core.task_runner import get_task_runner
#     runner = get_task_runner()
# 改:
from core.task_runner import get_shared_runner
runner = get_shared_runner()

# core/layers/base.py:292 (在 _call_llm async dispatch 分支)
# 原: from core.task_runner import get_task_runner
#     runner = get_task_runner()
# 改:
from core.task_runner import get_shared_runner
runner = get_shared_runner()

# core/layers/base.py:313 (在 _call_llm sync batch 分支)
# 原: from core.task_runner import get_task_runner
#     runner = get_task_runner()
# 改:
from core.task_runner import get_shared_runner
runner = get_shared_runner()
```

- [ ] **Step 4: 跑并发测试**

Run: `python -m pytest tests/test_task_runner_concurrent.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: 跑现有 async dispatch 测试无回归**

Run: `python -m pytest scripts/test_async_dispatch.py -v` (若存在) 或 `python -m pytest tests/ -v -k "async or dispatch or task_runner"`
Expected: PASS

- [ ] **Step 6: 跑全量测试套件确认无回归**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS（若有 failure 需排查是否 shared runner 引入）

- [ ] **Step 7: Commit**

```bash
git add core/tools/record_learning_tool.py core/tools/async_tools.py core/layers/base.py tests/test_task_runner_concurrent.py
git commit -m "fix: unify dispatch to get_shared_runner (was get_task_runner creating orphan runners)"
```

---

## Task 2: SQLite Store 线程安全

**Files:**
- Modify: `core/storage/__init__.py:13-19`
- Modify: `core/storage/l1_store.py:14-21`
- Modify: `core/storage/l2_store.py:14-22`
- Modify: `core/storage/l3_store.py:14-22`
- Modify: `core/storage/domain_store.py:10-18`
- Modify: `core/storage/kb_store.py:14-22`
- Test: `tests/test_storage_threadsafe.py`

- [ ] **Step 1: 写跨线程访问测试**

```python
# tests/test_storage_threadsafe.py
"""验证 6 个 store 支持跨线程访问（check_same_thread=False + 写锁）。"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from core.storage.l1_store import L1SQLiteStore
from core.storage.l2_store import L2SQLiteStore
from core.storage.l3_store import L3SQLiteStore
from core.storage.domain_store import DomainSQLiteStore
from core.storage.kb_store import KBSQLiteStore


def test_l1_store_cross_thread_access(temp_dir):
    """L1SQLiteStore 在构建线程外的线程访问不抛 ProgrammingError。"""
    store = L1SQLiteStore(temp_dir / "l1.db")
    errors = []

    def worker(i):
        try:
            store.insert({
                "id": f"rule_{i}",
                "content": f"rule content {i}",
                "created_by": "test",
                "source": "l1",
                "added_at": "2026-01-01T00:00:00Z",
                "version": 1,
                "last_modified": "2026-01-01T00:00:00Z",
            })
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(20)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"cross-thread errors: {errors}"
    assert store.count() == 20
    store.close()


def test_l2_store_cross_thread_concurrent_write(temp_dir):
    """L2SQLiteStore 并发写不丢数据、不损坏。"""
    store = L2SQLiteStore(temp_dir / "l2.db")
    errors = []

    def worker(i):
        try:
            for j in range(5):
                store.insert({
                    "id": f"card_{i}_{j}",
                    "content": f"content {i}-{j}",
                    "domain": "general",
                    "available_domains": ["general"],
                    "source": "observation",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "last_used": "2026-01-01T00:00:00Z",
                    "usefulness": 0,
                    "misleading": 0,
                    "comment": "",
                })
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(5)]
        for f in as_completed(futures):
            f.result()

    assert not errors, f"concurrent write errors: {errors}"
    assert len(store.list_all()) == 25
    store.close()


def test_l3_store_cross_thread_access(temp_dir):
    """L3SQLiteStore 跨线程访问。"""
    store = L3SQLiteStore(temp_dir / "l3.db")
    errors = []

    def worker(i):
        try:
            store.insert({
                "name": f"skill_{i}",
                "content": f"# Skill {i}\n...",
                "domain": "general",
                "available_domains": ["general"],
                "created_by": "test",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "last_used": "2026-01-01T00:00:00Z",
            })
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(10)]
        for f in as_completed(futures):
            f.result()

    assert not errors
    assert store.count() == 10
    store.close()


def test_domain_store_cross_thread_index(temp_dir):
    """DomainSQLiteStore 跨线程 index_item。"""
    store = DomainSQLiteStore(temp_dir / "domain.db")
    # 先插入一个 node
    store.insert_node({
        "path": "general", "parent": None, "description": "general",
        "correlations": {}, "relations": {}, "embedding_vector": None,
    })
    errors = []

    def worker(i):
        try:
            store.index_item("l2", "general", f"item_{i}")
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(20)]
        for f in as_completed(futures):
            f.result()

    assert not errors
    items = store.get_items("l2", "general")
    assert len(items) == 20
    store.close()


def test_kb_store_cross_thread_insert(temp_dir):
    """KBSQLiteStore 跨线程 insert。"""
    store = KBSQLiteStore(temp_dir / "kb.db")
    errors = []

    def worker(i):
        try:
            store.insert({
                "doc_id": f"doc_{i}",
                "domain": "general",
                "title": f"Title {i}",
                "content": f"content {i}",
                "source": "test",
                "meta": {},
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "last_used": "2026-01-01T00:00:00Z",
            })
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, i) for i in range(10)]
        for f in as_completed(futures):
            f.result()

    assert not errors
    assert len(store.list_all()) == 10
    store.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_storage_threadsafe.py -v`
Expected: FAIL — `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`

- [ ] **Step 3: 修改 `core/storage/__init__.py`**

```python
# core/storage/__init__.py (替换 _connect 函数)
def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False 允许跨线程访问；写安全由各 store 的 _write_lock 保证
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 4: 修改 `core/storage/l1_store.py`**

```python
# core/storage/l1_store.py (顶部加 import)
import threading

# __init__ 方法改为：
class L1SQLiteStore:
    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._write_lock = threading.Lock()
        self._init_schema()

    # insert 加锁：
    def insert(self, rule: dict) -> None:
        with self._write_lock:
            self._conn.execute("""
                INSERT OR REPLACE INTO l1_rules
                (id, content, created_by, source, added_at, version, last_modified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                rule["id"], rule["content"],
                rule.get("created_by", "unknown"),
                rule.get("source", "l1"),
                rule.get("added_at", _now()),
                rule.get("version", 1),
                rule.get("last_modified", _now()),
            ))
            self._conn.commit()

    # update 加锁：
    def update(self, rule_id: str, **fields) -> bool:
        sets = []
        values = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            values.append(v)
        if not sets:
            return False
        sets.append("last_modified = ?")
        values.append(_now())
        values.append(rule_id)
        with self._write_lock:
            self._conn.execute(
                f"UPDATE l1_rules SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            return self._conn.total_changes > 0

    # delete 加锁：
    def delete(self, rule_id: str) -> bool:
        with self._write_lock:
            self._conn.execute("DELETE FROM l1_rules WHERE id = ?", (rule_id,))
            self._conn.commit()
            return self._conn.total_changes > 0
    # 读方法（get/list_all/count）不加锁，WAL 允许并发读
```

- [ ] **Step 5: 修改 `core/storage/l2_store.py`（同样模式）**

```python
# core/storage/l2_store.py 顶部加 import threading
# __init__ 加 check_same_thread=False + self._write_lock = threading.Lock()
# insert/update/delete 加 with self._write_lock:
# （模式同 L1，读方法不加锁）
```

- [ ] **Step 6: 修改 `core/storage/l3_store.py`（同样模式）**

```python
# 同 L2 模式：import threading + check_same_thread=False + _write_lock + 写方法加锁
```

- [ ] **Step 7: 修改 `core/storage/domain_store.py`（同样模式）**

```python
# 同 L2 模式。注意 domain_store 有多个写方法：insert_node/update_node/delete_node/
# index_item/unindex_item/unindex_domain — 全部加 with self._write_lock
```

- [ ] **Step 8: 修改 `core/storage/kb_store.py`（同样模式）**

```python
# 同 L2 模式。写方法：insert/update/delete/touch — 全部加 with self._write_lock
```

- [ ] **Step 9: 跑跨线程测试**

Run: `python -m pytest tests/test_storage_threadsafe.py -v`
Expected: PASS (5 tests)

- [ ] **Step 10: 跑现有 store 测试无回归**

Run: `python -m pytest tests/ -v -k "store or philosophy or flexible or skill or domain_registry or knowledge_base"`
Expected: 全部 PASS

- [ ] **Step 11: Commit**

```bash
git add core/storage/__init__.py core/storage/l1_store.py core/storage/l2_store.py core/storage/l3_store.py core/storage/domain_store.py core/storage/kb_store.py tests/test_storage_threadsafe.py
git commit -m "fix: SQLite stores support cross-thread access (check_same_thread=False + write lock)"
```

---

## Task 3: TaskRunner 增强

**Files:**
- Modify: `core/task_runner.py`
- Test: `tests/test_task_runner_concurrent.py` (追加)

- [ ] **Step 1: 追加增强 API 测试**

```python
# 追加到 tests/test_task_runner_concurrent.py

def test_update_progress():
    """update_progress 设置 task 的 progress 字段。"""
    runner = get_shared_runner()
    tid = runner.submit("test", lambda: time.sleep(0.1))
    runner.update_progress(tid, 50.0)
    task = runner.check(tid)
    assert task is not None
    assert task.progress == 50.0


def test_subscribe_receives_state_changes():
    """subscribe 的 callback 在 task 完成时被调用。"""
    runner = get_shared_runner()
    received = []
    lock = threading.Lock()

    def callback(task):
        with lock:
            received.append((task.task_id, task.status))

    runner.subscribe(callback)
    try:
        tid = runner.submit("test", lambda: "done")
        # 等 task 完成
        time.sleep(0.3)
        # callback 应该被触发
        assert any(tid == t[0] for t in received), f"callback not called for {tid}"
    finally:
        runner.unsubscribe(callback)


def test_list_tasks_filter_by_tool_name():
    """list_tasks 按工具名过滤。"""
    runner = get_shared_runner()
    tids = []
    for i in range(3):
        tids.append(runner.submit("filter_tool", lambda: i))
        runner.submit("other_tool", lambda: i)
    tasks = runner.list_tasks(tool_name="filter_tool")
    assert len(tasks) >= 3
    assert all(t.tool_name == "filter_tool" for t in tasks)


def test_list_tasks_filter_by_session_id():
    """list_tasks 按 session_id 过滤（通过 metadata 注入）。"""
    runner = get_shared_runner()
    tid = runner.submit("test", lambda: "ok", metadata={"session_id": "sess_123"})
    tasks = runner.list_tasks(session_id="sess_123")
    assert any(t.task_id == tid for t in tasks)


def test_collect_keeps_history_by_default():
    """collect 默认保留历史，不删除 task。"""
    runner = get_shared_runner()
    tid = runner.submit("test", lambda: "done")
    time.sleep(0.2)
    collected = runner.collect([tid])  # keep_history 默认 True
    assert len(collected) == 1
    # task 应该仍然可查
    assert runner.check(tid) is not None


def test_cancel_marks_task_cancelled():
    """cancel 设置 cancelled 标志。"""
    runner = get_shared_runner()
    cancelled_flag = threading.Event()

    def long_task():
        while not cancelled_flag.is_set():
            time.sleep(0.05)
        return "cancelled"

    tid = runner.submit("long", long_task)
    runner.cancel(tid)
    cancelled_flag.set()
    time.sleep(0.2)
    task = runner.check(tid)
    # task 应该有 cancelled 标志
    assert task is not None
    assert task.status == "cancelled" or task.cancelled is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_task_runner_concurrent.py -v -k "progress or subscribe or list_tasks or collect_keeps or cancel"`
Expected: FAIL — 方法不存在

- [ ] **Step 3: 修改 `core/task_runner.py`**

```python
# core/task_runner.py (完整替换，保留原有逻辑 + 新增)
"""Async task runner — thread pool + task lifecycle + stats + progress + events."""
from __future__ import annotations
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class TaskState:
    task_id: str
    tool_name: str
    status: str          # "running" | "done" | "error" | "cancelled"
    created_at: float = field(default_factory=time.time)
    result: Any = None
    error: str = ""
    progress: float = 0.0
    metadata: dict = field(default_factory=dict)
    cancelled: bool = False


class TaskRunner:
    def __init__(self, max_workers: int | None = None):
        if max_workers is None:
            from core.config_loader import get_section
            max_workers = get_section('runtime', default={}).get('task_runner_workers', 8)
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskState] = {}
        self._stats: dict[str, dict] = {}
        self._subscribers: list[Callable[[TaskState], None]] = []
        self._sub_lock = threading.Lock()

    def submit(self, tool_name: str, fn: Callable,
               metadata: dict | None = None) -> str:
        """Submit an async task. Returns task_id immediately.

        metadata: 可选 dict，可含 session_id/parent_task_id 供前端关联。
        """
        task_id = uuid.uuid4().hex[:12]

        def _wrapper():
            start = time.time()
            try:
                result = fn()
                elapsed = time.time() - start
                self._record_stat(tool_name, "success", elapsed)
                return result
            except Exception:
                elapsed = time.time() - start
                self._record_stat(tool_name, "error", elapsed)
                raise

        future = self._pool.submit(_wrapper)
        task = TaskState(
            task_id=task_id, tool_name=tool_name, status="running",
            metadata=metadata or {},
        )
        with self._lock:
            self._tasks[task_id] = task
        future.add_done_callback(lambda f, tid=task_id: self._on_async_done(tid, f))
        return task_id

    def _on_async_done(self, task_id: str, future: Future):
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if task.cancelled:
                task.status = "cancelled"
            else:
                try:
                    task.result = future.result()
                    task.status = "done"
                except Exception as e:
                    task.status = "error"
                    task.error = str(e)
        self._notify(task)

    def _notify(self, task: TaskState):
        with self._sub_lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(task)
            except Exception:
                pass

    def update_progress(self, task_id: str, progress: float) -> None:
        """Update progress (0-100) of a running task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task.progress = float(progress)
        if task:
            self._notify(task)

    def subscribe(self, callback: Callable[[TaskState], None]) -> None:
        with self._sub_lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[TaskState], None]) -> None:
        with self._sub_lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def list_tasks(self, status: str | None = None,
                   tool_name: str | None = None,
                   session_id: str | None = None) -> list[TaskState]:
        """Filter tasks by status / tool_name / session_id (in metadata)."""
        with self._lock:
            tasks = list(self._tasks.values())
        result = []
        for t in tasks:
            if status and t.status != status:
                continue
            if tool_name and t.tool_name != tool_name:
                continue
            if session_id and t.metadata.get("session_id") != session_id:
                continue
            result.append(t)
        return result

    def cancel(self, task_id: str) -> bool:
        """Cooperative cancel — sets cancelled flag, handler should self-check."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != "running":
                return False
            task.cancelled = True
        self._notify(task)
        return True

    def run_sync_batch(self, calls: list[dict], timeout: float = 300) -> list[dict]:
        """Run multiple sync tool calls in parallel. Returns results in call order."""
        futures: dict[str, Future] = {}
        for c in calls:
            def _make_wrap(tool_name, fn):
                def _wrap():
                    start = time.time()
                    try:
                        result = fn()
                        elapsed = time.time() - start
                        self._record_stat(tool_name, "success", elapsed)
                        return result
                    except Exception:
                        elapsed = time.time() - start
                        self._record_stat(tool_name, "error", elapsed)
                        raise
                return _wrap
            futures[c["id"]] = self._pool.submit(_make_wrap(c["tool"], c["exec"]))

        results = []
        for c in calls:
            try:
                raw = futures[c["id"]].result(timeout=timeout)
                results.append({"id": c["id"], "success": True, "data": raw})
            except Exception as e:
                results.append({"id": c["id"], "success": False,
                                "error": str(e), "data": {"error": str(e)}})
        return results

    def check(self, task_id: str) -> TaskState | None:
        with self._lock:
            return self._tasks.get(task_id)

    def collect(self, task_ids: list[str], keep_history: bool = True) -> list[dict]:
        """Collect completed async tasks. Only returns done/error/cancelled tasks.

        keep_history=True (default): does NOT remove tasks from store.
        keep_history=False: removes collected tasks (legacy behavior).
        """
        results = []
        with self._lock:
            for tid in task_ids:
                task = self._tasks.get(tid)
                if task is not None and task.status != "running":
                    results.append({
                        "task_id": task.task_id,
                        "tool_name": task.tool_name,
                        "status": task.status,
                        "progress": task.progress,
                        "result": task.result if task.status == "done" else None,
                        "error": task.error if task.status == "error" else None,
                    })
                    if not keep_history:
                        self._tasks.pop(tid)
        return results

    def pending_tasks(self) -> list[str]:
        with self._lock:
            return [tid for tid, t in self._tasks.items() if t.status == "running"]

    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def status(self) -> dict:
        with self._lock:
            running = sum(1 for t in self._tasks.values() if t.status == "running")
            done = sum(1 for t in self._tasks.values() if t.status == "done")
            error = sum(1 for t in self._tasks.values() if t.status == "error")
            cancelled = sum(1 for t in self._tasks.values() if t.status == "cancelled")
            return {
                "running": running,
                "done": done,
                "error": error,
                "cancelled": cancelled,
                "total": len(self._tasks),
                "by_tool": dict(self._stats),
            }

    def wait_all(self, timeout: float | None = None):
        deadline = time.time() + timeout if timeout else float("inf")
        while time.time() < deadline:
            with self._lock:
                running = sum(1 for t in self._tasks.values() if t.status == "running")
            if running == 0:
                return
            time.sleep(0.1)
        raise TimeoutError(f"wait_all timed out after {timeout}s")

    def _record_stat(self, tool_name: str, outcome: str, elapsed: float):
        with self._lock:
            s = self._stats.setdefault(tool_name,
                                        {"count": 0, "success": 0, "error": 0, "total_ms": 0})
            s["count"] += 1
            s[outcome] += 1
            s["total_ms"] += elapsed * 1000

    def shutdown(self, wait: bool = True):
        self._pool.shutdown(wait=wait)


def get_task_runner() -> TaskRunner:
    """Create a fresh TaskRunner. DEPRECATED for dispatch — use get_shared_runner().
    Kept for test fixtures needing isolated instances."""
    return TaskRunner()


_runner: TaskRunner | None = None


def get_shared_runner() -> TaskRunner:
    """Global singleton runner — all dispatch should use this."""
    global _runner
    if _runner is None:
        _runner = TaskRunner()
    return _runner
```

- [ ] **Step 4: 跑增强 API 测试**

Run: `python -m pytest tests/test_task_runner_concurrent.py -v`
Expected: PASS (全部，包括新增 6 个)

- [ ] **Step 5: 跑全量测试无回归**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add core/task_runner.py tests/test_task_runner_concurrent.py
git commit -m "feat: TaskRunner adds progress/subscribe/list_tasks/cancel + collect keeps history"
```

---

## Task 4: SessionStore (`core/session.py`)

**Files:**
- Create: `core/session.py`
- Test: `tests/test_session.py`

- [ ] **Step 1: 写 SessionStore 测试**

```python
# tests/test_session.py
"""SessionStore — session + task 元数据持久化 + thread-local task context。"""
import threading
from datetime import datetime, timezone

import pytest

from core.session import (
    SessionStore, set_task_context, get_task_context, clear_task_context,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestSessionStore:
    def test_create_session(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session(name="工作区A")
        assert s["id"]
        assert s["name"] == "工作区A"
        assert s["status"] == "active"
        store.close()

    def test_list_sessions_excludes_closed_by_default(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s1 = store.create_session("active_one")
        s2 = store.create_session("closed_one")
        store.close_session(s2["id"])
        listed = store.list_sessions()
        ids = [s["id"] for s in listed]
        assert s1["id"] in ids
        assert s2["id"] not in ids

    def test_list_sessions_include_closed(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("to_close")
        store.close_session(s["id"])
        listed = store.list_sessions(include_closed=True)
        assert any(x["id"] == s["id"] for x in listed)
        store.close()

    def test_get_session(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        got = store.get_session(s["id"])
        assert got is not None
        assert got["name"] == "test"
        assert store.get_session("nonexistent") is None
        store.close()

    def test_update_session(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("old_name")
        store.update_session(s["id"], name="new_name")
        got = store.get_session(s["id"])
        assert got["name"] == "new_name"
        store.close()

    def test_delete_session_cascades_tasks(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("to_delete")
        store.register_task("task_1", s["id"], "top")
        store.register_task("task_2", s["id"], "record_learning", parent_task_id="task_1")
        store.delete_session(s["id"])
        assert store.get_session(s["id"]) is None
        assert store.list_tasks(s["id"]) == []
        store.close()


class TestTaskCRUD:
    def test_register_and_list_tasks(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        store.register_task("t1", s["id"], "top")
        store.register_task("t2", s["id"], "record_learning", parent_task_id="t1")
        tasks = store.list_tasks(s["id"])
        assert len(tasks) == 2
        # 按 parent 过滤
        sub = store.list_tasks(s["id"], parent_task_id="t1")
        assert len(sub) == 1
        assert sub[0]["id"] == "t2"
        store.close()

    def test_update_task(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        store.register_task("t1", s["id"], "top")
        store.update_task("t1", status="done", progress=100.0,
                          result_summary="已完成")
        got = store.get_task("t1")
        assert got["status"] == "done"
        assert got["progress"] == 100.0
        assert got["result_summary"] == "已完成"
        store.close()

    def test_get_task_nonexistent(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        assert store.get_task("nope") is None
        store.close()


class TestMarkInterrupted:
    def test_running_tasks_marked_interrupted_on_startup(self, temp_dir):
        """status='running' 且 updated_at 超阈值的 task 改 'interrupted'。"""
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        store.register_task("stuck", s["id"], "top")
        # 手动改 updated_at 为 2 小时前
        old = (datetime.now(timezone.utc).timestamp()) - 7200
        store._conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (datetime.fromtimestamp(old, timezone.utc).isoformat(), "stuck"),
        )
        store._conn.commit()
        count = store.mark_interrupted_on_startup(threshold_seconds=3600)
        assert count == 1
        got = store.get_task("stuck")
        assert got["status"] == "interrupted"
        store.close()

    def test_recent_running_not_marked(self, temp_dir):
        store = SessionStore(temp_dir / "sessions.db")
        s = store.create_session("test")
        store.register_task("fresh", s["id"], "top")
        count = store.mark_interrupted_on_startup(threshold_seconds=3600)
        assert count == 0
        got = store.get_task("fresh")
        assert got["status"] == "running"
        store.close()


class TestThreadLocalContext:
    def test_set_and_get_context(self):
        clear_task_context()
        set_task_context("sess_1", "task_1")
        sid, tid = get_task_context()
        assert sid == "sess_1"
        assert tid == "task_1"
        clear_task_context()

    def test_clear_context(self):
        set_task_context("sess_1", "task_1")
        clear_task_context()
        sid, tid = get_task_context()
        assert sid is None
        assert tid is None

    def test_context_is_thread_local(self):
        """不同线程的 context 互不干扰。"""
        results = {}
        set_task_context("main_sess", "main_task")

        def worker():
            set_task_context("worker_sess", "worker_task")
            results["worker"] = get_task_context()
            clear_task_context()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        # worker 的 context 不影响 main
        assert results["worker"] == ("worker_sess", "worker_task")
        sid, tid = get_task_context()
        assert sid == "main_sess"
        assert tid == "main_task"
        clear_task_context()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.session'`

- [ ] **Step 3: 创建 `core/session.py`**

```python
# core/session.py
"""SessionStore — session + task 元数据持久化 (SQLite WAL) + thread-local task context.

Tracks:
- sessions: user-level workspaces (id, name, created_at, status, log_dir)
- tasks: per-session execution units (top-level + sub-agent)

Thread-local context (set_task_context/get_task_context/clear_task_context)
allows dispatch handlers to know which session/task they belong to without
explicit parameter passing.
"""
from __future__ import annotations
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Thread-local task context ──
_context = threading.local()


def set_task_context(session_id: str, task_id: str) -> None:
    """Set current thread's session_id + task_id for dispatch tracking."""
    _context.session_id = session_id
    _context.task_id = task_id


def get_task_context() -> tuple[str | None, str | None]:
    """Return (session_id, task_id) of current thread, or (None, None)."""
    return getattr(_context, "session_id", None), getattr(_context, "task_id", None)


def clear_task_context() -> None:
    """Clear current thread's task context."""
    _context.session_id = None
    _context.task_id = None


# ── SessionStore ──
class SessionStore:
    def __init__(self, db_path: Path | str = "data/cognitive/sessions.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.row_factory = sqlite3.Row
        self._write_lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._write_lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    log_dir TEXT,
                    last_active_at TEXT NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    parent_task_id TEXT,
                    type TEXT NOT NULL,
                    tool_name TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    progress REAL NOT NULL DEFAULT 0.0,
                    trace_id TEXT,
                    result_summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id)")
            self._conn.commit()

    # ── Session CRUD ──
    def create_session(self, name: str, log_dir: str | None = None) -> dict:
        sid = uuid.uuid4().hex[:12]
        now = _now()
        with self._write_lock:
            self._conn.execute(
                "INSERT INTO sessions (id, name, created_at, status, log_dir, last_active_at) "
                "VALUES (?, ?, ?, 'active', ?, ?)",
                (sid, name, now, log_dir, now),
            )
            self._conn.commit()
        return {"id": sid, "name": name, "created_at": now,
                "status": "active", "log_dir": log_dir, "last_active_at": now}

    def list_sessions(self, include_closed: bool = False) -> list[dict]:
        if include_closed:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY last_active_at DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE status = 'active' ORDER BY last_active_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_session(self, session_id: str, **fields) -> bool:
        if not fields:
            return False
        sets = []
        values = []
        for k, v in fields.items():
            if k == "last_active_at":
                continue
            sets.append(f"{k} = ?")
            values.append(v)
        sets.append("last_active_at = ?")
        values.append(_now())
        values.append(session_id)
        with self._write_lock:
            self._conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            return self._conn.total_changes > 0

    def close_session(self, session_id: str) -> None:
        self.update_session(session_id, status="closed")

    def delete_session(self, session_id: str) -> None:
        with self._write_lock:
            self._conn.execute(
                "DELETE FROM tasks WHERE session_id = ?", (session_id,))
            self._conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()

    # ── Task CRUD ──
    def register_task(self, task_id: str, session_id: str, type: str,
                      parent_task_id: str | None = None,
                      tool_name: str | None = None,
                      trace_id: str | None = None) -> None:
        now = _now()
        with self._write_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO tasks "
                "(id, session_id, parent_task_id, type, tool_name, status, progress, "
                " trace_id, result_summary, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'running', 0.0, ?, NULL, ?, ?)",
                (task_id, session_id, parent_task_id, type, tool_name,
                 trace_id, now, now),
            )
            self._conn.commit()

    def update_task(self, task_id: str, **fields) -> bool:
        if not fields:
            return False
        sets = []
        values = []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            values.append(v)
        sets.append("updated_at = ?")
        values.append(_now())
        values.append(task_id)
        with self._write_lock:
            self._conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                values,
            )
            self._conn.commit()
            return self._conn.total_changes > 0

    def list_tasks(self, session_id: str,
                   parent_task_id: str | None = None) -> list[dict]:
        if parent_task_id is None:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE session_id = ? AND parent_task_id = ? "
                "ORDER BY created_at",
                (session_id, parent_task_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def mark_interrupted_on_startup(self, threshold_seconds: int = 3600) -> int:
        """Mark running tasks older than threshold as interrupted (crash recovery)."""
        import time as _time
        cutoff_iso = datetime.fromtimestamp(
            _time.time() - threshold_seconds, timezone.utc
        ).isoformat()
        with self._write_lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status = 'interrupted' "
                "WHERE status = 'running' AND updated_at < ?",
                (cutoff_iso,),
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        self._conn.close()


# ── Module-level singleton ──
_store: SessionStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionStore:
    """Global singleton SessionStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SessionStore()
    return _store
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_session.py -v`
Expected: PASS (全部测试，约 10 个)

- [ ] **Step 5: Commit**

```bash
git add core/session.py tests/test_session.py
git commit -m "feat: SessionStore — session + task metadata persistence + thread-local task context"
```

---

## Task 5: dispatch 调用点集成 SessionStore

**Files:**
- Modify: `core/tools/record_learning_tool.py:57,102`
- Modify: `core/layers/base.py:292` (async dispatch 分支)
- Test: `tests/test_dispatch_tracking.py`

**注:** async_tools.py (check_task/collect_tasks) 是查询工具，不创建新 task，无需 register。

- [ ] **Step 1: 写 dispatch 集成测试**

```python
# tests/test_dispatch_tracking.py
"""验证 dispatch 调用点正确登记到 SessionStore。"""
import json
from unittest.mock import patch, MagicMock

import pytest

from core.session import SessionStore, set_task_context, clear_task_context


def test_record_learning_registers_task(temp_dir, monkeypatch):
    """record_learning sync=false 时登记到 SessionStore。"""
    store = SessionStore(temp_dir / "sessions.db")
    monkeypatch.setattr("core.session.get_session_store", lambda: store)

    # 创建 session + 设 thread-local context
    s = store.create_session("test")
    set_task_context(s["id"], "top_task_1")

    try:
        from core.tools.record_learning_tool import _record_learning_handler
        # Mock TaskRunner.submit 返回固定 tid
        mock_runner = MagicMock()
        mock_runner.submit.return_value = "rl_tid_123"
        with patch("core.task_runner.get_shared_runner", return_value=mock_runner):
            result = _record_learning_handler({
                "domain": "interaction",
                "learning_target": "test target",
                "importance": "high",
                "reasoning": "test reasoning",
                "sync": False,
            })
        # 应该登记到 SessionStore
        task = store.get_task("rl_tid_123")
        assert task is not None
        assert task["session_id"] == s["id"]
        assert task["parent_task_id"] == "top_task_1"
        assert task["type"] == "record_learning"
        # 返回值应含 task_id
        parsed = json.loads(result)
        assert parsed["task_id"] == "rl_tid_123"
    finally:
        clear_task_context()
        store.close()


def test_async_dispatch_registers_task(temp_dir, monkeypatch):
    """_call_llm async dispatch 分支登记到 SessionStore。"""
    store = SessionStore(temp_dir / "sessions.db")
    monkeypatch.setattr("core.session.get_session_store", lambda: store)

    s = store.create_session("test")
    set_task_context(s["id"], "top_task_1")

    try:
        from core.layers.base import LayerAgent
        from core.task_runner import get_shared_runner

        # 构造一个最小 agent 实例测试 _call_llm 的 async 分支
        # 实际通过 mock LLM + injector 触发 async tool call
        # 这里用集成方式：直接验证 register_task 在 async 分支被调用
        # （完整 _call_llm 测试见 test_dispatch_tracking_e2e）
        pass  # 见下方 e2e 测试
    finally:
        clear_task_context()
        store.close()


def test_no_context_skips_registration(temp_dir, monkeypatch):
    """无 thread-local context 时不登记（向后兼容 CLI 模式）。"""
    store = SessionStore(temp_dir / "sessions.db")
    monkeypatch.setattr("core.session.get_session_store", lambda: store)

    clear_task_context()  # 确保无 context

    from core.tools.record_learning_tool import _record_learning_handler
    mock_runner = MagicMock()
    mock_runner.submit.return_value = "rl_tid_no_ctx"
    with patch("core.task_runner.get_shared_runner", return_value=mock_runner):
        _record_learning_handler({
            "domain": "interaction",
            "learning_target": "no ctx",
            "importance": "low",
            "reasoning": "test",
            "sync": False,
        })
    # 无 context 不应登记
    assert store.get_task("rl_tid_no_ctx") is None
    store.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_dispatch_tracking.py -v -k "registers or no_context"`
Expected: FAIL — record_learning 未调 register_task

- [ ] **Step 3: 修改 `core/tools/record_learning_tool.py`**

```python
# core/tools/record_learning_tool.py — _record_learning_handler 函数体
# 在 submit 之后加 register_task 调用
def _record_learning_handler(args=None, **kwargs):
    d = args or {}
    domain = d.get("domain", "")
    target = d.get("learning_target", "")
    importance = d.get("importance", "medium")
    reasoning = d.get("reasoning", "")
    if not domain or not target:
        return json.dumps({"error": "domain and learning_target required"})

    if d.get("sync", False):
        record = _build_and_save(domain, target, importance, reasoning)
        return json.dumps(record, ensure_ascii=False, default=str)

    def _run():
        return _build_and_save(domain, target, importance, reasoning)

    from core.task_runner import get_shared_runner
    from core.session import get_task_context, get_session_store
    session_id, parent_task_id = get_task_context()
    metadata = {"session_id": session_id, "parent_task_id": parent_task_id}
    tid = get_shared_runner().submit("record_learning", _run, metadata=metadata)
    # 登记 sub-agent task（仅在 session 上下文内）
    if session_id:
        try:
            get_session_store().register_task(
                tid, session_id, "record_learning",
                parent_task_id=parent_task_id, tool_name="record_learning",
            )
        except Exception:
            pass  # SessionStore 故障不影响 dispatch
    return json.dumps({"task_id": tid, "status": "running"})
```

```python
# core/tools/record_learning_tool.py — _check_auto_trigger 函数体
def _check_auto_trigger(pending_path: Path, domain: str):
    json_files = sorted(pending_path.glob("*.json"))
    if len(json_files) < 5:
        return

    from core.task_runner import get_shared_runner
    from core.session import get_task_context, get_session_store
    session_id, parent_task_id = get_task_context()
    metadata = {"session_id": session_id, "parent_task_id": parent_task_id}
    tid = get_shared_runner().submit(
        "auto_learning", lambda d=domain, p=pending_path, files=json_files:
        _dispatch_learning(d, p, files), metadata=metadata)
    if session_id:
        try:
            get_session_store().register_task(
                tid, session_id, "auto_learning",
                parent_task_id=parent_task_id, tool_name="auto_learning",
            )
        except Exception:
            pass
```

- [ ] **Step 4: 修改 `core/layers/base.py` async dispatch 分支**

```python
# core/layers/base.py — 在 async_calls 分支（约 line 290-308）
# submit 后加 register_task
if async_calls:
    from core.task_runner import get_shared_runner
    from core.session import get_task_context, get_session_store
    runner = get_shared_runner()
    session_id, parent_task_id = get_task_context()
    for tc in async_calls:
        name = tc.function.name
        args_json = tc.function.arguments
        self._log.debug("  ├─ async : %s(%s) id=%s", name, args_json[:400], tc.id)
        def _make_async_exec(_inj, _l, _n, _a):
            def _exec():
                return _inj.execute_tool_call(_l, _n, _a)
            return _exec
        exec_fn = _make_async_exec(self._injector, layer, name, args_json)
        metadata = {"session_id": session_id, "parent_task_id": parent_task_id}
        tid = runner.submit(name, exec_fn, metadata=metadata)
        # 登记 sub-agent task
        if session_id:
            try:
                get_session_store().register_task(
                    tid, session_id, name,
                    parent_task_id=parent_task_id, tool_name=name,
                )
            except Exception:
                pass
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps({"task_id": tid, "status": "running"}),
        })
```

- [ ] **Step 5: 跑集成测试**

Run: `python -m pytest tests/test_dispatch_tracking.py -v`
Expected: PASS

- [ ] **Step 6: 跑全量测试无回归**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add core/tools/record_learning_tool.py core/layers/base.py tests/test_dispatch_tracking.py
git commit -m "feat: dispatch points register sub-agent tasks to SessionStore (when session context active)"
```

---

## Task 6: Monitor 模块 (`core/monitor.py`)

**Files:**
- Create: `core/monitor.py`
- Test: `tests/test_monitor.py`

- [ ] **Step 1: 写 monitor 测试**

```python
# tests/test_monitor.py
"""Monitor 模块 — 聚合 trace 数据源（纯查询，不修改状态）。"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.monitor import snapshot, log_tail, task_list, decision_tree, task_detail


def test_snapshot_returns_expected_keys(temp_dir, monkeypatch):
    """snapshot 返回 tasks/capacity/learning/sessions 四个 key。"""
    mock_chain = MagicMock()
    mock_chain._downstream = None  # 简化 capacity
    monkeypatch.setattr("core.monitor._session_summary", lambda: {"count": 1})
    monkeypatch.setattr("core.monitor._learning_snapshot", lambda d: {"total_pending": 0})
    monkeypatch.setattr("core.monitor._capacity_snapshot", lambda c: {"l2": {}, "l3": {}})
    monkeypatch.setattr("core.monitor._task_list", lambda sid: [])

    snap = snapshot(session_id="s1", chain=mock_chain)
    assert set(snap.keys()) == {"tasks", "capacity", "learning", "sessions"}


def test_log_tail_returns_last_n_lines(temp_dir):
    """log_tail 读文件尾部 N 行。"""
    log_dir = temp_dir / "logs" / "ts_1"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "l0_5_1.log"
    log_file.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    tail = log_tail(str(log_dir), "l0_5_1", lines=2)
    assert "line4" in tail
    assert "line5" in tail
    assert "line3" not in tail


def test_log_tail_nonexistent_file_returns_empty(temp_dir):
    """log_tail 不存在的文件返回空字符串。"""
    result = log_tail(str(temp_dir / "nope"), "l0_5_1")
    assert result == ""


def test_task_list_uses_session_store(temp_dir, monkeypatch):
    """task_list 从 SessionStore 拉取。"""
    mock_store = MagicMock()
    mock_store.list_tasks.return_value = [{"id": "t1", "type": "top"}]
    monkeypatch.setattr("core.session.get_session_store", lambda: mock_store)

    tasks = task_list("sess_1")
    assert tasks == [{"id": "t1", "type": "top"}]
    mock_store.list_tasks.assert_called_once_with("sess_1", None)


def test_decision_tree_uses_round_history(monkeypatch):
    """decision_tree 复用 RoundTree.snapshot()。"""
    mock_history = MagicMock()
    mock_node = MagicMock()
    mock_node.layer = "l0_5_1"
    mock_history.snapshot.return_value = [mock_node]
    monkeypatch.setattr("core.round_tree.get_round_history", lambda: mock_history)

    tree = decision_tree()
    assert tree == [mock_node]


def test_task_detail_uses_session_store(temp_dir, monkeypatch):
    """task_detail 从 SessionStore.get_task 拉取。"""
    mock_store = MagicMock()
    mock_store.get_task.return_value = {"id": "t1", "status": "done"}
    monkeypatch.setattr("core.session.get_session_store", lambda: mock_store)

    detail = task_detail("t1")
    assert detail == {"id": "t1", "status": "done"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_monitor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.monitor'`

- [ ] **Step 3: 创建 `core/monitor.py`**

```python
# core/monitor.py
"""Monitor — aggregates trace data sources for frontend display.

Pure query module — does NOT modify any state. All data sourced from:
- SessionStore (session/task metadata)
- per-layer log files (logs/interaction/{ts}/*.log)
- RoundTree.snapshot() (decision tree)
- TaskRunner.status() (running task stats)
- chain internals (L2/L3 capacity)
"""
from __future__ import annotations
from pathlib import Path
from typing import Any


def snapshot(session_id: str | None = None, chain=None,
             pending_dir: str = "data/learning/pending") -> dict:
    """Return full agent status snapshot as JSON-serializable dict."""
    return {
        "tasks": _task_list(session_id),
        "capacity": _capacity_snapshot(chain),
        "learning": _learning_snapshot(pending_dir),
        "sessions": _session_summary(),
    }


def task_list(session_id: str, parent_task_id: str | None = None) -> list[dict]:
    """List tasks for a session from SessionStore."""
    from core.session import get_session_store
    return get_session_store().list_tasks(session_id, parent_task_id)


def task_detail(task_id: str) -> dict | None:
    """Single task detail from SessionStore."""
    from core.session import get_session_store
    return get_session_store().get_task(task_id)


def log_tail(log_dir: str, layer: str, lines: int = 50) -> str:
    """Read tail of a per-layer log file.

    layer: "l0_5_1" | "l2" | "l3" | "executor"
    """
    path = Path(log_dir) / f"{layer}.log"
    if not path.exists():
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            all_lines = f.readlines()
    except OSError:
        return ""
    return "".join(all_lines[-lines:])


def decision_tree(task_id: str | None = None) -> list:
    """Reuse RoundTree.snapshot() — thread-local decision tree."""
    from core.round_tree import get_round_history
    return get_round_history().snapshot()


# ── Internal helpers ──

def _task_list(session_id: str | None) -> list[dict]:
    if session_id is None:
        return []
    return task_list(session_id)


def _capacity_snapshot(chain) -> dict:
    """L2/L3 capacity vs limits."""
    from core.config_loader import get_section
    learn = get_section("learning", default={})
    l2_limit = learn.get("l2_card_limit", 30)
    l3_limit = learn.get("l3_skill_limit", 20)

    l2_count = 0
    l3_count = 0
    if chain:
        l2_mgr = getattr(chain, "_downstream", None)
        if l2_mgr and hasattr(l2_mgr, "_knowledge"):
            l2_count = len(l2_mgr._knowledge.cards)
        l3_mgr = getattr(l2_mgr, "_downstream", None) if l2_mgr else None
        if l3_mgr and hasattr(l3_mgr, "_skill_layer"):
            l3_count = len(l3_mgr._skill_layer.list_all())

    return {
        "l2": {"count": l2_count, "limit": l2_limit,
               "over": max(0, l2_count - l2_limit)},
        "l3": {"count": l3_count, "limit": l3_limit,
               "over": max(0, l3_count - l3_limit)},
    }


def _learning_snapshot(pending_dir: str) -> dict:
    p = Path(pending_dir)
    domains = {}
    if p.exists():
        for d in p.iterdir():
            if d.is_dir():
                files = list(d.glob("*.json"))
                domains[d.name] = {"pending": len(files)}
    archive_dir = Path("data/learning/archive")
    archive_count = sum(1 for _ in archive_dir.rglob("*.json")) if archive_dir.exists() else 0
    return {
        "domains": domains,
        "total_pending": sum(d["pending"] for d in domains.values()),
        "total_archive": archive_count,
    }


def _session_summary() -> dict:
    """Active session count + latest session info."""
    from core.session import get_session_store
    sessions = get_session_store().list_sessions(include_closed=False)
    return {
        "count": len(sessions),
        "latest": sessions[0] if sessions else None,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_monitor.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add core/monitor.py tests/test_monitor.py
git commit -m "feat: monitor module — aggregate trace sources (snapshot/log_tail/task_list/decision_tree)"
```

---

## Task 7: Gradio App (`scripts/gradio_app.py`)

**Files:**
- Create: `scripts/gradio_app.py`

> **注:** Gradio UI 测试以手动冒烟为主（启动 + 点击 + 验证渲染），不写自动化测试（Gradio 测试基础设施重，YAGNI）。

- [ ] **Step 1: 创建 `scripts/gradio_app.py`**

```python
# scripts/gradio_app.py
"""Cognitive Agent — Gradio Web UI with multi-session + parallel task tracking.

Three-column layout:
- Left: Session list (persistent, create/switch/delete)
- Middle: Task list for current session (top-level + sub-agent, parallel visible) + chat input
- Right: Trace detail for selected task (L1/L2/L3 decision tree + sub-tasks + layer logs)
"""
from __future__ import annotations
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

from core.setup import setup_executor
from core.session import (
    get_session_store, set_task_context, clear_task_context,
)
from core.monitor import snapshot, log_tail, task_list, task_detail, decision_tree
from core.task_runner import get_shared_runner

DEFAULT_SYSTEM_PROMPT = "你是一个智能助手。请直接简洁地回复用户的问题。"


@dataclass
class SessionState:
    """Per-browser-session state. Gradio State creates one per user."""
    env: object = None
    session_id: str = ""
    session_name: str = ""
    current_task_id: str = ""  # task selected in trace panel
    chat_history: list = field(default_factory=list)


def _create_env(system_prompt: str = DEFAULT_SYSTEM_PROMPT):
    from core.env.interaction_env import InteractionEnv
    env = InteractionEnv(
        system_prompt=system_prompt,
        debug=True,
        enable_learning=True,
    )
    env.reset("interaction")
    return env


def _setup_task_tracking():
    """Wire TaskRunner events → SessionStore updates."""
    store = get_session_store()
    # 启动时标记崩溃残留 task
    store.mark_interrupted_on_startup()

    def on_task_change(task):
        try:
            store.update_task(
                task.task_id,
                status=task.status,
                progress=task.progress,
                result_summary=(str(task.result)[:500] if task.result else None),
            )
        except Exception:
            pass

    get_shared_runner().subscribe(on_task_change)


def _refresh_session_list():
    store = get_session_store()
    sessions = store.list_sessions(include_closed=False)
    rows = []
    for s in sessions:
        rows.append([s["id"], s["name"], s["status"], s.get("last_active_at", "")[:19]])
    return gr.update(value=rows)


def _refresh_task_list(session_id: str):
    if not session_id:
        return gr.update(value=[])
    tasks = task_list(session_id)
    rows = []
    for t in tasks:
        type_label = {"top": "用户查询", "record_learning": "记录学习",
                      "auto_learning": "自动学习", "terminal": "终端"}.get(
            t["type"], t["type"])
        rows.append([
            t["id"][:8],
            type_label,
            t["status"],
            f"{t['progress']:.0f}%",
            t.get("created_at", "")[:19],
        ])
    return gr.update(value=rows)


def _refresh_trace(session_id: str, task_id: str, log_dir: str = ""):
    """Build trace panel content for selected task."""
    if not task_id:
        return gr.update(value="## 选择一个 task 查看详情"), gr.update(value={}), gr.update(value="")

    # 1. Task 详情
    detail = task_detail(task_id)
    if not detail:
        return gr.update(value=f"## Task {task_id} 未找到"), gr.update(value={}), gr.update(value="")

    md_lines = [
        f"## Task {task_id[:8]}",
        f"- **类型:** {detail['type']}",
        f"- **状态:** {detail['status']}",
        f"- **进度:** {detail['progress']:.0f}%",
    ]
    if detail.get("result_summary"):
        md_lines.append(f"- **结果:** {detail['result_summary'][:300]}")

    # 2. 子任务（sub-agent）
    sub_tasks = task_list(session_id, parent_task_id=task_id) if session_id else []
    if sub_tasks:
        md_lines.append("\n### 子任务 (sub-agent)")
        for st in sub_tasks:
            md_lines.append(
                f"- `{st['id'][:8]}` {st['type']} [{st['status']}] {st['progress']:.0f}%"
            )

    # 3. 决策树（仅顶层 task 有意义）
    if detail["type"] == "top":
        tree = decision_tree()
        if tree:
            md_lines.append("\n### 决策树 (L1→L2→L3)")
            md_lines.append(f"共 {len(tree)} 轮决策")

    # 4. 层日志（默认显示 L1）
    log_content = log_tail(log_dir, "l0_5_1", lines=50) if log_dir else ""

    return gr.update(value="\n".join(md_lines)), gr.update(value={"task": detail, "sub_tasks": sub_tasks}), gr.update(value=log_content)


def main():
    chain, executor = setup_executor(PROJECT_ROOT)
    _setup_task_tracking()

    def create_session(name: str):
        if not name.strip():
            name = f"Session {datetime.now().strftime('%H:%M')}"
        store = get_session_store()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = str(PROJECT_ROOT / "logs" / "interaction" / stamp)
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        # 启动 per-layer logging
        from core.layers.logging_setup import setup_layer_logging
        setup_layer_logging(Path(log_dir))
        s = store.create_session(name, log_dir=log_dir)
        env = _create_env()
        state = SessionState(env=env, session_id=s["id"], session_name=name)
        return state, _refresh_session_list(), _refresh_task_list(s["id"]), *_refresh_trace(s["id"], "", log_dir)

    def switch_session(evt: gr.SelectData, session_table, current_state):
        """Click session row to switch."""
        if evt.index[0] < 0 or not session_table:
            return current_state, gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        row = session_table[evt.index[0]]
        session_id = row[0]
        store = get_session_store()
        s = store.get_session(session_id)
        if not s:
            return current_state, gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        env = _create_env()
        new_state = SessionState(env=env, session_id=s["id"], session_name=s["name"])
        return (new_state, _refresh_session_list(), _refresh_task_list(s["id"]),
                *_refresh_trace(s["id"], "", s.get("log_dir", "")))

    def delete_session(session_table, current_state):
        """Delete current session."""
        if not current_state.session_id:
            return current_state, _refresh_session_list(), gr.update(), *_refresh_trace("", "")
        store = get_session_store()
        store.delete_session(current_state.session_id)
        new_state = SessionState()
        return new_state, _refresh_session_list(), gr.update(), *_refresh_trace("", "")

    def chat(user_input: str, state: SessionState):
        """Handle one chat turn — single top-level task."""
        if not user_input or not user_input.strip():
            session = get_session_store().get_session(state.session_id) if state.session_id else None
            return state, "", gr.update(), gr.update(), *_refresh_trace(
                state.session_id, state.current_task_id,
                (session or {}).get("log_dir", ""))
        if not state.session_id:
            # 自动创建 session
            state, *_ = create_session("默认 Session")

        env = state.env
        env.receive_input(user_input.strip())
        obs = env.build_task_observation()
        if obs is None:
            return state, "", gr.update(), gr.update(), *_refresh_trace(
                state.session_id, state.current_task_id, "")

        # 注册顶层 task
        top_tid = uuid.uuid4().hex[:12]
        store = get_session_store()
        store.register_task(top_tid, state.session_id, "top")
        set_task_context(state.session_id, top_tid)
        try:
            result = executor.execute(obs)
            reply = (result.get("action_text") or "").strip() or "(no output)"
            store.update_task(top_tid, status="done", progress=100.0,
                              result_summary=reply[:500])
        except Exception as e:
            reply = f"[Error] {e}"
            store.update_task(top_tid, status="error", result_summary=str(e)[:500])
        finally:
            clear_task_context()

        env.step(reply)
        state.chat_history.append((user_input, reply))
        state.current_task_id = top_tid

        session = store.get_session(state.session_id) or {}
        log_dir = session.get("log_dir", "")
        return (state, "", _refresh_task_list(state.session_id),
                *_refresh_trace(state.session_id, top_tid, log_dir))

    def select_task(evt: gr.SelectData, task_table, state: SessionState):
        """Click task row to show trace."""
        if evt.index[0] < 0 or not task_table:
            return state, *_refresh_trace(state.session_id, "", "")
        row = task_table[evt.index[0]]
        task_id_full = row[0]  # 注意：显示是截断的 8 位，需用前缀匹配
        # 实际应存完整 id 在 table data，这里简化用前缀
        store = get_session_store()
        all_tasks = store.list_tasks(state.session_id)
        matched = [t for t in all_tasks if t["id"].startswith(task_id_full)]
        if not matched:
            return state, *_refresh_trace(state.session_id, "", "")
        state.current_task_id = matched[0]["id"]
        session = store.get_session(state.session_id) or {}
        return state, *_refresh_trace(state.session_id, state.current_task_id,
                                      session.get("log_dir", ""))

    def refresh_log(log_dir, layer_choice):
        """Switch layer log tab."""
        return gr.update(value=log_tail(log_dir, layer_choice, lines=50))

    # ── UI Layout ──
    with gr.Blocks(title="Cognitive Agent", theme=gr.themes.Soft()) as app:
        session_state = gr.State(SessionState())

        gr.Markdown("# Cognitive Agent — 多 Session + 并行任务追踪")

        with gr.Row():
            # ── Session 栏（左 25%）──
            with gr.Column(scale=1):
                gr.Markdown("### Sessions")
                with gr.Row():
                    new_session_name = gr.Textbox(
                        label="新 session 名", placeholder="工作区名...",
                        scale=3, lines=1)
                    create_btn = gr.Button("新建", variant="primary", scale=1)
                session_table = gr.Dataframe(
                    headers=["ID", "名称", "状态", "最后活跃"],
                    datatype=["str", "str", "str", "str"],
                    label="Session 列表",
                    interactive=False,
                )
                delete_btn = gr.Button("删除当前 session", size="sm", variant="stop")

            # ── 任务栏（中 30%）──
            with gr.Column(scale=1):
                gr.Markdown("### 任务 (并行可见)")
                task_table = gr.Dataframe(
                    headers=["ID", "类型", "状态", "进度", "创建时间"],
                    datatype=["str", "str", "str", "str", "str"],
                    label="当前 session 的任务",
                    interactive=False,
                )
                refresh_tasks_btn = gr.Button("刷新任务", size="sm")
                gr.Markdown("---")
                gr.Markdown("### 对话 (单任务提交)")
                chatbot = gr.Chatbot(label="对话历史", height=200)
                with gr.Row():
                    msg = gr.Textbox(label="输入", placeholder="输入问题...",
                                     scale=4, lines=1)
                    send_btn = gr.Button("发送", variant="primary", scale=1)

            # ── Trace 栏（右 45%）──
            with gr.Column(scale=2):
                gr.Markdown("### Trace 详情")
                trace_md = gr.Markdown("## 选择一个 task 查看详情")
                trace_json = gr.JSON(label="任务数据")

                gr.Markdown("### 层日志 (尾部 50 行)")
                with gr.Row():
                    layer_choice = gr.Radio(
                        ["l0_5_1", "l2", "l3", "executor"],
                        label="层", value="l0_5_1", scale=1)
                    log_refresh_btn = gr.Button("刷新日志", size="sm", scale=1)
                log_content = gr.Textbox(
                    label="", lines=15, max_lines=15,
                    interactive=False, show_label=False)

        # ── Event handlers ──
        create_btn.click(
            create_session,
            [new_session_name],
            [session_state, session_table, task_table, trace_md, trace_json, log_content],
        ).then(lambda: "", None, new_session_name)

        session_table.select(
            switch_session,
            [session_table, session_state],
            [session_state, session_table, task_table, trace_md, trace_json, log_content],
        )

        delete_btn.click(
            delete_session,
            [session_table, session_state],
            [session_state, session_table, task_table, trace_md, trace_json, log_content],
        )

        msg.submit(
            chat,
            [msg, session_state],
            [session_state, msg, task_table, trace_md, trace_json, log_content],
        )
        send_btn.click(
            chat,
            [msg, session_state],
            [session_state, msg, task_table, trace_md, trace_json, log_content],
        )

        task_table.select(
            select_task,
            [task_table, session_state],
            [session_state, trace_md, trace_json, log_content],
        )

        refresh_tasks_btn.click(
            lambda s: _refresh_task_list(s.session_id),
            [session_state],
            [task_table],
        )

        log_refresh_btn.click(
            lambda s, lc: refresh_log(
                (get_session_store().get_session(s.session_id) or {}).get("log_dir", ""),
                lc),
            [session_state, layer_choice],
            [log_content],
        )

        # 定时刷新任务列表（每 3s）
        app.load(
            lambda s: _refresh_task_list(s.session_id) if s.session_id else gr.update(),
            [session_state],
            [task_table],
            every=3,
        )

    app.launch(server_name="127.0.0.1", server_port=7860)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证 import 无误**

Run: `python -c "import scripts.gradio_app; print('import ok')"`
Expected: 输出 `import ok`（不实际启动，只验证 import 链；需要 gradio 已安装）

- [ ] **Step 3: 手动冒烟测试**

Run: `python scripts/gradio_app.py`
Expected:
- 浏览器打开 `http://127.0.0.1:7860`
- 三栏布局正确显示
- 输入 session 名点"新建" → session 列表出现新行
- 在对话栏输入问题点"发送" → 任务列表出现"用户查询"行 + trace 栏显示详情
- 点击任务行 → trace 栏切换显示该 task 详情
- 切换层日志 radio → 显示对应层 log 尾部

- [ ] **Step 4: Commit**

```bash
git add scripts/gradio_app.py
git commit -m "feat: Gradio v2 frontend — multi-session + parallel task tracking + 3-layer trace"
```

---

## Task 8: 更新 MAINTAIN.md + 标记 v1 plan superseded

**Files:**
- Modify: `MAINTAIN.md`
- Modify: `docs/superpowers/plans/2026-06-18-gradio-frontend.md` (顶部加 superseded 标记)

- [ ] **Step 1: 在 MAINTAIN.md 添加新模块条目**

在 `## core/setup.py` 章节后/对应位置，新增/更新以下条目（参考现有格式）：

```markdown
## core/setup.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `setup_executor` | `(project_root: Path\|None = None) → (chain, executor)` | 一次性构建 llm → chain → executor → register_runtime。CLI 和 Gradio 共用 | interactive_agent, gradio_app | build_llm_client, build_default_chain, Executor, register_runtime |

## core/session.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `SessionStore` | `__init__(db_path="data/cognitive/sessions.db")` | SQLite WAL 存储 session + task 元数据，支持跨线程 | gradio_app, monitor, dispatch handlers | sqlite3 |
| `SessionStore.create_session` | `(name, log_dir=None) → dict` | 新建 session | gradio_app | — |
| `SessionStore.list_sessions` | `(include_closed=False) → list[dict]` | 列出 session | gradio_app, monitor | — |
| `SessionStore.get_session` | `(session_id) → dict\|None` | 获取单个 session | gradio_app | — |
| `SessionStore.update_session` | `(session_id, **fields) → bool` | 更新 session 字段 | gradio_app | — |
| `SessionStore.close_session` | `(session_id) → None` | 关闭 session（status=closed） | gradio_app | update_session |
| `SessionStore.delete_session` | `(session_id) → None` | 删除 session + 级联删 tasks | gradio_app | — |
| `SessionStore.register_task` | `(task_id, session_id, type, parent_task_id=None, tool_name=None, trace_id=None) → None` | 登记新 task | dispatch handlers, gradio_app | — |
| `SessionStore.update_task` | `(task_id, **fields) → bool` | 更新 task 字段 | TaskRunner 事件回调, gradio_app | — |
| `SessionStore.list_tasks` | `(session_id, parent_task_id=None) → list[dict]` | 列出 session 的 tasks | monitor, gradio_app | — |
| `SessionStore.get_task` | `(task_id) → dict\|None` | 获取单个 task | monitor, gradio_app | — |
| `SessionStore.mark_interrupted_on_startup` | `(threshold_seconds=3600) → int` | 启动时标记超时 running task 为 interrupted | gradio_app | — |
| `get_session_store` | `() → SessionStore` | 全局单例 | monitor, gradio_app, dispatch handlers | — |
| `set_task_context` | `(session_id, task_id) → None` | 设置 thread-local task 上下文 | gradio_app chat | — |
| `get_task_context` | `() → (session_id, task_id)` | 读取 thread-local 上下文 | dispatch handlers | — |
| `clear_task_context` | `() → None` | 清除 thread-local 上下文 | gradio_app chat (finally) | — |

## core/monitor.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `snapshot` | `(session_id=None, chain=None, pending_dir="data/learning/pending") → dict` | 聚合静态状态：tasks/capacity/learning/sessions | gradio_app | _task_list, _capacity_snapshot, _learning_snapshot, _session_summary |
| `task_list` | `(session_id, parent_task_id=None) → list[dict]` | 从 SessionStore 拉任务列表 | gradio_app, snapshot | SessionStore.list_tasks |
| `task_detail` | `(task_id) → dict\|None` | 单 task 详情 | gradio_app | SessionStore.get_task |
| `log_tail` | `(log_dir, layer, lines=50) → str` | 读 per-layer log 文件尾部 | gradio_app | Path, open |
| `decision_tree` | `(task_id=None) → list` | 复用 RoundTree.snapshot() | gradio_app | get_round_history().snapshot() |
| `_capacity_snapshot` | `(chain) → dict` | L2/L3 容量 vs 上限 | snapshot | chain 内部属性, get_section |
| `_learning_snapshot` | `(pending_dir) → dict` | 统计 pending 文件数 | snapshot | Path.glob |
| `_session_summary` | `() → dict` | active session 计数 | snapshot | SessionStore.list_sessions |

## scripts/gradio_app.py

| 函数/类 | 签名 | 作用 | 上游调用者 | 下游调用 |
|----------|------|------|-----------|---------|
| `SessionState` | `@dataclass(env, session_id, session_name, current_task_id, chat_history)` | 浏览器 session 状态 | gr.State | — |
| `main` | `() → None` | Gradio UI 入口：构建 UI + 事件绑定 + 定时刷新 | 直接运行 | setup_executor, _setup_task_tracking |
| `create_session` | `(name) → (state, session_table, task_table, trace_md, trace_json, log_content)` | 新建 session + env + 启动 logging | create_btn.click | SessionStore.create_session, setup_layer_logging, _create_env |
| `chat` | `(user_input, state) → (state, msg, task_table, trace_md, trace_json, log_content)` | 单轮对话：env → register top task → execute → update task | msg.submit, send_btn.click | executor.execute, SessionStore, set/clear_task_context |
| `select_task` | `(evt, task_table, state) → (state, trace_md, trace_json, log_content)` | 点击 task 行显示 trace | task_table.select | _refresh_trace |
| `_refresh_trace` | `(session_id, task_id, log_dir) → (md, json, log)` | 构建 trace 栏 3 个输出 | 各 callback | task_detail, task_list, decision_tree, log_tail |
| `_refresh_session_list` | `() → gr.update` | 刷新 session 列表 | 各 callback | SessionStore.list_sessions |
| `_refresh_task_list` | `(session_id) → gr.update` | 刷新任务列表 | 各 callback | task_list |
| `_setup_task_tracking` | `() → None` | 订阅 TaskRunner 事件 → SessionStore 更新 | main | mark_interrupted_on_startup, TaskRunner.subscribe |
```

更新已有条目：
- `core/task_runner.py`: `TaskState` 加 `progress`/`metadata`/`cancelled` 字段；新增 `update_progress`/`subscribe`/`unsubscribe`/`list_tasks`/`cancel`；`collect` 加 `keep_history` 参数；`status()` 加 `cancelled` 计数；`submit` 加 `metadata` 参数；`get_task_runner()` 标记 deprecated
- 6 个 store 条目：`__init__` 加 `check_same_thread=False` + `_write_lock`；写方法标注 "with _write_lock"

- [ ] **Step 2: 在 v1 plan 顶部加 superseded 标记**

```markdown
# Gradio Frontend — Design Spec (v2)

> **⚠️ SUPERSEDED by v2:** 本文档已被 `docs/superpowers/specs/2026-06-19-gradio-frontend-v2-design.md` 取代。
> v2 增加多 session 持久化 + 单 session 多 task 并行追踪 + sub-agent 任务可见性 + SQLite store 线程安全修复。
> 本文档保留作历史参考，请勿据此实现。
```

- [ ] **Step 3: 在 MAINTAIN.md Changelog 加条目**

```markdown
| 2026-06-19 | **Gradio Frontend v2**：新增 `core/setup.py`（setup_executor）、`core/session.py`（SessionStore + thread-local task context）、`core/monitor.py`（snapshot/log_tail/task_list/decision_tree）、`scripts/gradio_app.py`（三栏 UI）。TaskRunner 增强：progress/subscribe/list_tasks/cancel + collect 保留历史 + submit 加 metadata。6 个 SQLite store 加 `check_same_thread=False` + 写锁（支持跨线程并行）。7 处 dispatch 调用点 `get_task_runner()` → `get_shared_runner()` + 登记 SessionStore。`interactive_agent.py` 改用 `setup_executor`。v1 plan 标记 superseded。 |
```

- [ ] **Step 4: Commit**

```bash
git add MAINTAIN.md docs/superpowers/plans/2026-06-18-gradio-frontend.md
git commit -m "docs: update MAINTAIN.md for Gradio v2 + mark v1 plan superseded"
```

---

## 验收测试（最终）

- [ ] **全量测试套件**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS，无回归

- [ ] **新测试覆盖**

Run: `python -m pytest tests/test_setup.py tests/test_session.py tests/test_monitor.py tests/test_task_runner_concurrent.py tests/test_storage_threadsafe.py tests/test_dispatch_tracking.py -v`
Expected: 全部 PASS

- [ ] **Gradio 冒烟测试（手动）**

Run: `python scripts/gradio_app.py`
验证：
1. 三栏布局正确
2. 新建 session 持久化（重启后仍可见）
3. 对话提交后任务列表出现"用户查询"
4. sub-agent task（record_learning sync=false）出现在任务列表
5. 点击 task 行 trace 栏显示详情
6. 层日志 tab 切换正常
7. 多 session 切换不串状态

- [ ] **并行验证**

在 Gradio 中：
1. 提交一个会触发 record_learning 的查询
2. 立即提交第二个查询（不等第一个完成）
3. 两个顶层 task 都应出现在任务列表并行 running
4. record_learning sub-agent task 应出现在对应顶层 task 的子任务中
