"""Async task management tools: check_task, collect_tasks."""
from __future__ import annotations
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
