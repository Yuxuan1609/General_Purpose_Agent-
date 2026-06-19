# core/task_runner.py
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

        metadata: optional dict, may contain session_id/parent_task_id for frontend association.
        """
        task_id = uuid.uuid4().hex[:12]

        def _wrapper():
            _ctx_session_id = (metadata or {}).get("session_id")
            _ctx_parent_task_id = (metadata or {}).get("parent_task_id")
            if _ctx_session_id:
                from core.session import set_task_context, clear_task_context
                set_task_context(_ctx_session_id, _ctx_parent_task_id or "")
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
            finally:
                if _ctx_session_id:
                    clear_task_context()

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
