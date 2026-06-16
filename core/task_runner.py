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
        self._stats: dict[str, dict] = {}

    def submit(self, tool_name: str, fn: Callable, sync: bool = True) -> str | None:
        """Submit a task. sync=True returns None (result via run_sync_batch).
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
            return None  # sync tasks are handled by run_sync_batch
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

    def run_sync_batch(self, calls: list[dict], timeout: float = 30) -> list[dict]:
        """Run multiple sync tool calls in parallel. Returns results in call order.

        Each call: {"id": tool_call_id, "tool": name, "exec": callable}
        Result: {"id": tool_call_id, "success": bool, "data": Any, "error": str}
        """
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
                    except Exception as e:
                        elapsed = time.time() - start
                        self._record_stat(tool_name, "error", elapsed)
                        raise e
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
        s = self._stats.setdefault(tool_name,
                                    {"count": 0, "success": 0, "error": 0, "total_ms": 0})
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
