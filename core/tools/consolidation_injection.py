"""Consolidation injection — store DI for consolidation tool handlers.

Replaces ConsolidationContext. Handlers read stores + registry via module-level
getters, set once in chain_factory._mount_tools.
"""
from __future__ import annotations
from typing import Any

_stores: dict[str, Any] = {}
_registry: Any = None


def set_consolidation_stores(stores: dict[str, Any], registry: Any = None) -> None:
    global _stores, _registry
    _stores.clear()
    _stores.update(stores)
    if registry is not None:
        _registry = registry


def set_registry(registry: Any) -> None:
    global _registry
    _registry = registry


def get_store(layer: str) -> Any:
    return _stores.get(layer)


def get_registry() -> Any:
    return _registry
