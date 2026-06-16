# Async Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sync/async tool dispatch with round-level parallel execution and task lifecycle management.

**Architecture:** TaskRunner thread pool + ToolEntry.sync flag + round-boundary wait_sync() + collect_tasks for async results. All existing tools sync=true by default.

**Tech Stack:** Python 3.10+, concurrent.futures.ThreadPoolExecutor, dataclasses

---

## File Map

| File | Role | Change |
|------|------|--------|
| `core/task_runner.py` | TaskRunner singleton — thread pool + task store + stats | Create |
| `core/tools/registry.py` | ToolEntry + register() | Add `sync` field |
| `core/tools/kb_tools.py` | KB tool registration | Add `kb_query_async`, `kb_fill_gap_async` |
| `core/tools/async_tools.py` | `kb_check_task`, `kb_collect_tasks` handlers | Create |
| `core/layers/base.py` | `_call_llm` round loop | Add `wait_sync()` at turn boundary |
| `core/layers/l0_5_1/manager.py` | L1 system prompt | Add tool rules description |
| `core/layers/l2/manager.py` | L2 system prompt | Add tool rules description |
| `core/layers/l3/manager.py` | L3 system prompt | Add tool rules description |
| `config/tools.yaml` | All tools | Add `sync` field |
| `tests/test_task_runner.py` | Unit tests for TaskRunner | Create |

---

### Task 1: TaskRunner — thread pool + task store

**Files:**
- Create: `core/task_runner.py`

- [ ] **Step 1: Implement TaskRunner**

```python
"""Async task runner — thread pool + task lifecycle + stats."""
from __future__ import annotations
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class TaskState:
    task_id: str
    tool_name: str
    status: str          # "running" | "done" | "error"
    created_at: float = field(default_factory=time.time)
    result: Any = None
    error: str = ""


class TaskRunner:
    def __init__(self, max_workers: int = 8):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._tasks: dict[str, TaskState] = {}
        self._sync_futures: dict[str, Future] = {}
        self._stats: dict[str, dict] = {}

    def submit(self, tool_name: str, fn: Callable, sync: bool = True) -> str | None:
        """Submit a task. sync=True returns None (result via wait_sync).
        sync=False returns task_id immediately."""
        task_id = uuid.uuid4().hex[:12]

        def _wrapper():
            start = time.time()
            try:
                result = fn()
                elapsed = time.time() - start
                self._record_stat(tool_name, "success", elapsed)
                return result
            except Exception as e:
                elapsed = time.time() - start
                self._record_stat(tool_name, "error", elapsed)
                raise e

        future = self._pool.submit(_wrapper)

        if sync:
            self._sync_futures[task_id] = future
            return None
        else:
            task = TaskState(task_id=task_id, tool_name=tool_name, status="running")
            self._tasks[task_id] = task
            future.add_done_callback(lambda f, tid=task_id: self._on_async_done(tid, f))
            return task_id

    def _on_async_done(self, task_id: str, future: Future):
        task = self._tasks.get(task_id)
        if task is None:
            return
        try:
            task.result = future.result()
            task.status = "done"
        except Exception as e:
            task.status = "error"
            task.error = str(e)

    def wait_sync(self) -> dict[str, Any]:
        """Block until all sync futures complete. Returns {task_id: result}."""
        results = {}
        for task_id, future in list(self._sync_futures.items()):
            try:
                results[task_id] = future.result()
            except Exception as e:
                results[task_id] = {"error": str(e)}
        self._sync_futures.clear()
        return results

    def check(self, task_id: str) -> TaskState | None:
        return self._tasks.get(task_id)

    def collect(self, task_ids: list[str]) -> list[dict]:
        """Collect completed async tasks. Removes from store after return."""
        results = []
        for tid in task_ids:
            task = self._tasks.pop(tid, None)
            if task is not None and task.status != "running":
                results.append({
                    "task_id": task.task_id,
                    "tool_name": task.tool_name,
                    "status": task.status,
                    "result": task.result if task.status == "done" else None,
                    "error": task.error if task.status == "error" else None,
                })
        return results

    def pending_tasks(self) -> list[str]:
        return [tid for tid, t in self._tasks.items() if t.status == "running"]

    def stats(self) -> dict:
        return dict(self._stats)

    def _record_stat(self, tool_name: str, outcome: str, elapsed: float):
        s = self._stats.setdefault(tool_name, {"count": 0, "success": 0, "error": 0, "total_ms": 0})
        s["count"] += 1
        s[outcome] += 1
        s["total_ms"] += elapsed * 1000

    def shutdown(self):
        self._pool.shutdown(wait=False)


# Global singleton
_runner: TaskRunner | None = None


def get_task_runner() -> TaskRunner:
    global _runner
    if _runner is None:
        _runner = TaskRunner()
    return _runner
```

- [ ] **Step 2: Test manually**

```bash
python3 -c "
from core.task_runner import get_task_runner
import time

r = get_task_runner()

# Test async
tid = r.submit('test', lambda: time.sleep(1) or 'hello', sync=False)
print(f'async_id: {tid}')
time.sleep(0.1)
print(f'check: {r.check(tid).status}')
time.sleep(1.1)
print(f'collect: {r.collect([tid])}')

# Test sync
r.submit('test_sync', lambda: 'world', sync=True)
results = r.wait_sync()
print(f'sync_results: {results}')

print(f'stats: {r.stats()}')
print('PASS')
"
```

- [ ] **Step 3: Commit**

```bash
git add core/task_runner.py
git commit -m "feat: TaskRunner — thread pool + async task lifecycle + stats"
```

---

### Task 2: ToolEntry.sync + ToolRegistry.register() update

**Files:**
- Modify: `core/tools/registry.py`

- [ ] **Step 1: Add sync field to ToolEntry**

```python
@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    sync: bool = True              # ← NEW
    available_domains: list[str] = field(default_factory=lambda: ["general"])
```

- [ ] **Step 2: Update register() method**

```python
def register(self, name: str, schema: dict, handler: Callable,
             toolset: str = "default", sync: bool = True):
    entry = ToolEntry(
        name=name, schema=schema, handler=handler,
        sync=sync,
        available_domains=list(self._domains.get(name, ["general"])),
    )
    self._tools[name] = entry
    if self._registry:
        for d in entry.available_domains:
            self._registry.index_item("tool", d, name)
```

- [ ] **Step 3: Run tests and commit**

```bash
python3 -m pytest tests/test_capability.py -q
git add core/tools/registry.py
git commit -m "feat: ToolEntry.sync field + register() sync param"
```

---

### Task 3: Async KB tools + check/collect tools

**Files:**
- Modify: `core/tools/kb_tools.py`
- Create: `core/tools/async_tools.py`

- [ ] **Step 1: Add kb_query_async and kb_fill_gap_async to kb_tools.py**

After the sync handler registrations, add:

```python
# In register_kb_tools():
registry.register("kb_query_async", _schema("kb_query"), _kb_query_async_handler,
                  toolset="core", sync=False)
registry.register("kb_fill_gap_async", _schema("kb_fill_gap"), _kb_fill_gap_async_handler,
                  toolset="core", sync=False)
```

Add handlers:
```python
def _kb_query_async_handler(args: dict | None = None) -> str:
    query = (args or {}).get("query", "")
    domain = (args or {}).get("domain")
    if not query:
        return json.dumps({"error": "No query provided"})

    def _run():
        from scripts.interactive_kb_agent import SubAgentLoop
        kb = _get_kb()
        kb.load()
        llm = _get_llm()
        agent = SubAgentLoop(llm, kb, trace=False)
        result = agent.run(query, domain)
        kb.close()
        return result

    from core.task_runner import get_task_runner
    tid = get_task_runner().submit("kb_query_async", _run, sync=False)
    return json.dumps({"task_id": tid, "status": "running"})


def _kb_fill_gap_async_handler(args: dict | None = None) -> str:
    suggestion = (args or {})
    domain = suggestion.get("domain", "")
    topic = suggestion.get("topic", "")
    if not domain or not topic:
        return json.dumps({"error": "domain and topic required"})

    def _run():
        from scripts.interactive_kb_agent import FillGapLoop
        kb = _get_kb()
        kb.load()
        llm = _get_llm()
        agent = FillGapLoop(llm, kb, trace=False)
        return agent.run(suggestion)

    from core.task_runner import get_task_runner
    tid = get_task_runner().submit("kb_fill_gap_async", _run, sync=False)
    return json.dumps({"task_id": tid, "status": "running"})
```

- [ ] **Step 2: Create core/tools/async_tools.py**

```python
"""Async task management tools: check_task, collect_tasks."""
import json


def register_async_tools(registry):
    registry.register("kb_check_task", {
        "type": "function",
        "function": {
            "name": "kb_check_task",
            "description": "Check status of an async KB task. Returns running/done/error.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            },
        },
    }, _check_task_handler, toolset="core", sync=True)

    registry.register("kb_collect_tasks", {
        "type": "function",
        "function": {
            "name": "kb_collect_tasks",
            "description": "Collect results of completed async KB tasks. Only returns done/error tasks. Running tasks are skipped.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of task IDs to collect",
                    },
                },
                "required": ["task_ids"],
            },
        },
    }, _collect_tasks_handler, toolset="core", sync=True)


def _check_task_handler(args: dict | None = None) -> str:
    task_id = (args or {}).get("task_id", "")
    if not task_id:
        return json.dumps({"error": "task_id required"})
    from core.task_runner import get_task_runner
    task = get_task_runner().check(task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {task_id}"})
    return json.dumps({
        "task_id": task.task_id,
        "tool_name": task.tool_name,
        "status": task.status,
    })


def _collect_tasks_handler(args: dict | None = None) -> str:
    task_ids = (args or {}).get("task_ids", [])
    if not task_ids:
        return json.dumps({"results": [], "pending": []})
    from core.task_runner import get_task_runner
    runner = get_task_runner()
    results = runner.collect(task_ids)
    pending = runner.pending_tasks()
    return json.dumps({"results": results, "pending": pending})
```

- [ ] **Step 3: Register in __init__.py**

In `core/tools/__init__.py`, add:
```python
from core.tools.async_tools import register_async_tools
register_async_tools(registry)
```

- [ ] **Step 4: Run tests and commit**

```bash
python3 -m pytest tests/ -q
git add core/tools/kb_tools.py core/tools/async_tools.py core/tools/__init__.py
git commit -m "feat: async KB tools + check_task/collect_tasks"
```

---

### Task 4: tools.yaml sync field

**Files:**
- Modify: `config/tools.yaml`

- [ ] **Step 1: Add sync: true to all existing tools**

```yaml
tools:
  terminal:
    sync: true
    timeout: 30
    allowlist: [l2, l3]
    ...

  web_search:
    sync: true
    ...

  # ... all existing tools ...

  # New async tools
  kb_query_async:
    sync: false
    timeout: 5
    allowlist: [l1, l2, l3]
    fallback:
      max_retries: 0
      degrade: []

  kb_fill_gap_async:
    sync: false
    timeout: 5
    allowlist: [l1, l2, l3]
    fallback:
      max_retries: 0
      degrade: []

  kb_check_task:
    sync: true
    timeout: 5
    allowlist: [l1, l2, l3]
    fallback:
      max_retries: 0
      degrade: []

  kb_collect_tasks:
    sync: true
    timeout: 10
    allowlist: [l1, l2, l3]
    fallback:
      max_retries: 0
      degrade: []
```

- [ ] **Step 2: Commit**

```bash
git add config/tools.yaml
git commit -m "feat: add sync field to all tools in tools.yaml"
```

---

### Task 5: _call_llm — 同轮内 sync 工具并行执行

**Files:**
- Modify: `core/layers/base.py` — the tool execution loop (~lines 163-189)
- Modify: `core/task_runner.py` — add `run_sync_batch()` helper

**原理:** `tool_call_id` 天然匹配结果，顺序无关。把 `for tc in executable_calls:` 从逐条串行改为批量提交 + 统一等待。

- [ ] **Step 1: Add run_sync_batch to TaskRunner**

```python
# In core/task_runner.py, add to TaskRunner class:
def run_sync_batch(self, calls: list[dict], timeout: float = 30) -> list[dict]:
    """Run multiple sync tool calls in parallel. Returns results in call order.
    
    Each call: {"id": tool_call_id, "tool": name, "exec": callable}
    Result: {"id": tool_call_id, "result": CapabilityResult-like}
    """
    futures: dict[str, Future] = {}
    for c in calls:
        futures[c["id"]] = self._pool.submit(c["exec"])

    results = []
    for c in calls:
        try:
            raw = futures[c["id"]].result(timeout=timeout)
            results.append({"id": c["id"], "success": True, "data": raw})
        except Exception as e:
            results.append({"id": c["id"], "success": False, "error": str(e),
                            "data": {"error": str(e)}})
    return results
```

- [ ] **Step 2: Rewrite tool execution loop in _call_llm**

**File:** `core/layers/base.py`

In `_call_llm`, find the tool execution loop (after `executable_calls = []` append, around line 168).

Replace the entire `for tc in executable_calls:` block:

```python
# ── OLD (sequential):
# for tc in executable_calls:
#     raw = self._injector.execute_tool_call(layer, tc.function.name, tc.function.arguments)
#     if raw.success:
#         ...
#     messages.append(...)

# ── NEW (parallel batch):
if executable_calls:
    from core.task_runner import get_task_runner
    runner = get_task_runner()
    batch = []
    for tc in executable_calls:
        inj = self._injector
        l = layer
        n = tc.function.name
        a = tc.function.arguments
        batch.append({
            "id": tc.id,
            "tool": n,
            "exec": lambda inj=inj, l=l, n=n, a=a: inj.execute_tool_call(l, n, a),
        })
    outcomes = runner.run_sync_batch(batch, timeout=30)
    for outcome in outcomes:
        tc_id = outcome["id"]
        if outcome["success"]:
            raw = outcome["data"]
            result_content = raw.data
            self._log.debug("  └─ result (success=%s, id=%s): %s",
                           raw.success, tc_id, str(result_content)[:800])
        else:
            result_content = outcome["data"]
            self._log.warning("  └─ result (error, id=%s): %s",
                             tc_id, outcome["error"])
        serialized = json.dumps(result_content, ensure_ascii=False)
        messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": serialized,
        })
```

Remove the old sequential `for tc in executable_calls:` block entirely.

- [ ] **Step 3: Run tests**

```bash
python3 -m pytest tests/test_capability.py tests/test_learning_env.py -q
```

- [ ] **Step 4: Commit**

```bash
git add core/layers/base.py core/task_runner.py
git commit -m "feat: parallel sync tool execution within a round via run_sync_batch"
```

---

### Task 6: Agent prompt — tool rules

**Files:**
- Modify: `core/layers/l0_5_1/manager.py`
- Modify: `core/layers/l2/manager.py`
- Modify: `core/layers/l3/manager.py`

- [ ] **Step 1: Add tool rules to L1 system prompt**

In `L1Agent._build_system_prompt()`, after the layer architecture section, add:

```python
# After "## 指令\n{instruction}\n\n":
tool_rules = (
    "## 工具调用规则\n"
    "- sync=true 的工具结果在本轮结束时返回给你\n"
    "- sync=false 的工具会立即返回 task_id，你需要在下几轮调用 "
    "kb_collect_tasks 来获取结果\n"
    "- kb_check_task(task_id) 可以查询单个任务的状态\n"
    "- 同一个决策轮中，先提交 sync=false 的任务，再提交 sync=true 的任务，"
    "然后等待本轮结果\n"
    "- 如果某轮没有 sync=true 的工具调用，直接进入下一轮\n"
)
```

Append to system prompt string.

- [ ] **Step 2: Same for L2, L3**

Copy the same block into L2Agent._build_system_prompt() and L3Agent._build_system_prompt().

- [ ] **Step 3: Run tests and commit**

```bash
python3 -m pytest tests/ -q
git add core/layers/l0_5_1/manager.py core/layers/l2/manager.py core/layers/l3/manager.py
git commit -m "feat: add async tool rules to agent prompts"
```

---

### Task 7: Integration test

**Files:**
- Create: `scripts/test_async_dispatch.py`

- [ ] **Step 1: Write integration test**

```python
"""Async dispatch integration test."""
from pathlib import Path
import sys, time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_async_submit_collect():
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    # Submit async tasks
    tids = []
    for i in range(3):
        def _work(n=i):
            time.sleep(0.5)
            return f"result_{n}"
        tid = runner.submit("test_async", _work, sync=False)
        tids.append(tid)

    # Check running
    for tid in tids:
        task = runner.check(tid)
        assert task is not None
        print(f"  task {tid}: {task.status}")

    # Wait for completion
    time.sleep(1)

    # Collect
    results = runner.collect(tids)
    assert len(results) == 3
    for r in results:
        assert r["status"] == "done"
    print(f"PASS: async submit → collect {len(results)} results")

    # Verify cleaned from store
    assert runner.check(tids[0]) is None
    print("PASS: tasks removed from store after collect")


def test_sync_wait():
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    for i in range(2):
        def _work(n=i):
            return f"sync_{n}"
        runner.submit("test_sync", _work, sync=True)

    results = runner.wait_sync()
    assert len(results) == 2
    print(f"PASS: sync wait → {len(results)} results")


def test_stats():
    from core.task_runner import get_task_runner
    runner = get_task_runner()

    stats = runner.stats()
    assert "test_async" in stats
    assert "test_sync" in stats
    print(f"PASS: stats tracked: {list(stats.keys())}")


if __name__ == "__main__":
    test_async_submit_collect()
    test_sync_wait()
    test_stats()
    print("\nAll async dispatch tests pass!")
```

- [ ] **Step 2: Run**

```bash
python3 scripts/test_async_dispatch.py
```

- [ ] **Step 3: Commit**

```bash
git add scripts/test_async_dispatch.py
git commit -m "test: async dispatch integration test"
```

---

### Task 8: Final test run + MAINTAIN.md

- [ ] **Step 1: Full test suite**

```bash
python3 -m pytest tests/ -q
python3 scripts/test_async_dispatch.py
python3 scripts/test_domain_e2e_pipeline.py
```

- [ ] **Step 2: Update MAINTAIN.md**

Add TaskRunner section + async tool entries.

- [ ] **Step 3: Commit**

```bash
git add MAINTAIN.md
git commit -m "docs: update MAINTAIN.md with async dispatch"
```
