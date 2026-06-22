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
    tool_spec: str = "primary"
    semantic_description: str = ""
    sync: bool = True
    force_sync: bool = False
    check_fn: Callable | None = None
    toolset: str = "core"


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
                    cls._instance._enabled_secondary = threading.local()
        return cls._instance

    def __init__(self, domain_registry=None):
        self._registry = domain_registry

    def _get_enabled_secondary(self) -> set[str]:
        """Return current thread's enabled secondary set (lazy-init to empty set)."""
        s = getattr(self._enabled_secondary, "enabled", None)
        if s is None:
            s = set()
            self._enabled_secondary.enabled = s
        return s

    def enable_secondary(self, names: list[str]) -> int:
        """Add secondary tool names to current thread's enabled set.

        Returns count of names that correspond to actually-registered secondary tools.
        """
        with self._lock:
            valid = {n for n, e in self._entries.items() if e.tool_spec == "secondary"}
        wanted = set(names) & valid
        enabled = self._get_enabled_secondary()
        enabled |= wanted
        return len(wanted)

    def clear_secondary(self) -> None:
        """Clear current thread's enabled secondary set."""
        self._enabled_secondary.enabled = set()

    def register(self, name: str, schema: dict, handler: Callable,
                 check_fn: Callable | None = None, toolset: str = "core",
                 override: bool = False, sync: bool = True,
                 force_sync: bool = False,
                 tool_spec: str = "primary",
                 semantic_description: str = ""):
        with self._lock:
            existing = self._entries.get(name)
            if existing and existing.toolset != toolset and not override:
                raise ValueError(
                    f"Tool '{name}' already registered from toolset "
                    f"'{existing.toolset}' (attempted from '{toolset}')"
                )
            tool = ToolEntry(
                name=name, schema=schema, handler=handler,
                sync=sync, force_sync=force_sync, check_fn=check_fn, toolset=toolset,
                tool_spec=tool_spec,
                semantic_description=semantic_description,
            )
            self._entries[name] = tool

    def get_definitions(self, requested: set[str] | None = None) -> list[dict]:
        enabled = self._get_enabled_secondary()
        with self._lock:
            entries = self._entries.values()
            if requested:
                entries = [e for e in entries if e.name in requested]
            return [
                e.schema for e in entries
                if (e.check_fn is None or e.check_fn())
                and not (e.tool_spec == "secondary" and e.name not in enabled)
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

    def clear(self):
        """Reset all entries. For testing only."""
        with self._lock:
            self._entries.clear()
