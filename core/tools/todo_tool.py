"""Minimal todo tool for subtask tracking."""
import json


class TodoStore:
    def __init__(self):
        self._items: list[dict] = []

    def update(self, todos: list[dict]) -> list[dict]:
        for t in todos:
            t.setdefault("status", "pending")
            existing = next((i for i in self._items if i.get("id") == t.get("id")), None)
            if existing:
                existing.update(t)
            else:
                self._items.append(t)
        return self._items

    def active(self) -> list[dict]:
        return [t for t in self._items if t.get("status") in ("pending", "in_progress")]

    def format(self) -> str:
        active = self.active()
        if not active:
            return "No active tasks."
        return "\n".join(f"- [{t['status']}] {t.get('content', t.get('id', '?'))}" for t in active)


_store = TodoStore()


def register_todo_tool(registry):
    def handler(args=None, timeout=5):
        todos = (args or {}).get("todos")
        if todos:
            updated = _store.update(todos)
            return json.dumps({"success": True, "todos": updated})
        return json.dumps({"todos": _store.active()})

    registry.register("todo", {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "Create or view subtask tracking list",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]}
                            }
                        }
                    }
                }
            }
        }
    }, handler, toolset="core")
