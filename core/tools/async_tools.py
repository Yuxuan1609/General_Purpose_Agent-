"""Generic async task management tools: check_task, collect_tasks."""
from __future__ import annotations
import json


def register_async_tools(registry):
    registry.register("check_task", {
        "type": "function",
        "function": {
            "name": "check_task",
            "description": "Check status of an async task. Returns running/done/error.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "sync": {"type": "boolean", "description": "Sync mode (default true)"},
                },
                "required": ["task_id"],
            },
        },
    }, _check_task_handler, toolset="core", sync=True)

    registry.register("collect_tasks", {
        "type": "function",
        "function": {
            "name": "collect_tasks",
            "description": "Collect results of completed async tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of task IDs to collect",
                    },
                    "sync": {"type": "boolean", "description": "Sync mode (default true)"},
                },
                "required": ["task_ids"],
            },
        },
    }, _collect_tasks_handler, toolset="core", sync=True)


def _check_task_handler(args: dict | None = None, **kwargs) -> str:
    task_id = (args or {}).get("task_id", "")
    if not task_id:
        return json.dumps({"error": "task_id required"})
    from core.task_runner import get_shared_runner
    task = get_shared_runner().check(task_id)
    if task is None:
        return json.dumps({"error": f"Task not found: {task_id}"})
    return json.dumps({
        "task_id": task.task_id,
        "tool_name": task.tool_name,
        "status": task.status,
    })


def _collect_tasks_handler(args: dict | None = None, **kwargs) -> str:
    task_ids = (args or {}).get("task_ids", [])
    if not task_ids:
        return json.dumps({"results": [], "pending": []})
    from core.task_runner import get_shared_runner
    runner = get_shared_runner()
    results = runner.collect(task_ids)
    pending = runner.pending_tasks()
    return json.dumps({"results": results, "pending": pending})
