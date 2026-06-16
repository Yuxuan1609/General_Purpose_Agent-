from __future__ import annotations
import json
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolEntry:
    name: str
    schema: dict
    handler: Callable
    sync: bool = True
    check_fn: Callable | None = None
    toolset: str = "core"
    available_domains: list[str] = field(default_factory=list)


class ToolRegistry:
    """Thread-safe singleton tool registry. Adapted from Hermes tools/registry.py."""
    _instance: ToolRegistry | None = None
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._entries: dict[str, ToolEntry] = {}
        return cls._instance

    def __init__(self, domain_registry=None):
        self._registry = domain_registry

    def register(self, name: str, schema: dict, handler: Callable,
                 check_fn: Callable | None = None, toolset: str = "core",
                 available_domains: list[str] | None = None,
                 override: bool = False, sync: bool = True):
        if available_domains is None:
            available_domains = ["general"]
        with self._lock:
            existing = self._entries.get(name)
            if existing and existing.toolset != toolset and not override:
                raise ValueError(
                    f"Tool '{name}' already registered from toolset "
                    f"'{existing.toolset}' (attempted from '{toolset}')"
                )
            tool = ToolEntry(
                name=name, schema=schema, handler=handler,
                sync=sync, check_fn=check_fn, toolset=toolset,
                available_domains=available_domains,
            )
            self._entries[name] = tool
            if self._registry:
                for d in tool.available_domains:
                    self._registry.index_item("tool", d, name)

    def get_definitions(self, requested: set[str] | None = None) -> list[dict]:
        with self._lock:
            entries = self._entries.values()
            if requested:
                entries = [e for e in entries if e.name in requested]
            return [
                e.schema for e in entries
                if e.check_fn is None or e.check_fn()
            ]

    def dispatch(self, name: str, args: dict, context: dict | None = None,
                 timeout: int | None = None) -> str:
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            return json.dumps({"error": f"Tool '{name}' not found"})
        try:
            kwargs = {"args": args}
            if context is not None:
                kwargs["context"] = context
            if timeout is not None:
                kwargs["timeout"] = timeout
            result = entry.handler(**kwargs)
            if isinstance(result, str):
                return result
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def deregister(self, name: str):
        with self._lock:
            self._entries.pop(name, None)

    def get_tools_for_domain(self, domain: str) -> list[ToolEntry]:
        if self._registry:
            ids = self._registry.get_primary_items("tool", domain)
            return [t for t in self._entries.values() if t.name in ids]
        return list(self._entries.values())

    def clear(self):
        """Reset all entries. For testing only."""
        with self._lock:
            self._entries.clear()
