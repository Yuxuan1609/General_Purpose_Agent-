from __future__ import annotations
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    check_fn: Callable | None = None
    toolset: str = "core"


class ToolRegistry:
    """Thread-safe singleton tool registry. Adapted from Hermes tools/registry.py."""
    _instance: ToolRegistry | None = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._entries: dict[str, ToolEntry] = {}
        return cls._instance

    def register(self, name: str, schema: dict, handler: Callable,
                 check_fn: Callable | None = None, toolset: str = "core",
                 override: bool = False):
        with self._lock:
            existing = self._entries.get(name)
            if existing and existing.toolset != toolset and not override:
                raise ValueError(
                    f"Tool '{name}' already registered from toolset "
                    f"'{existing.toolset}' (attempted from '{toolset}')"
                )
            self._entries[name] = ToolEntry(
                name=name, schema=schema, handler=handler,
                check_fn=check_fn, toolset=toolset,
            )

    def get_definitions(self, requested: set[str] | None = None) -> list[dict]:
        with self._lock:
            entries = self._entries.values()
            if requested:
                entries = [e for e in entries if e.name in requested]
            return [
                e.schema for e in entries
                if e.check_fn is None or e.check_fn()
            ]

    def dispatch(self, name: str, args: dict, context: dict | None = None) -> str:
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            return json.dumps({"error": f"Tool '{name}' not found"})
        try:
            result = entry.handler(args, context) if context else entry.handler(args)
            if isinstance(result, str):
                return result
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def deregister(self, name: str):
        with self._lock:
            self._entries.pop(name, None)

    def clear(self):
        """Reset all entries. For testing only."""
        with self._lock:
            self._entries.clear()
