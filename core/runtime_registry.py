"""Runtime registry — global access to chain + executor for auto-learning.

Replaces the ConsolidationContext.executor side-channel. Scripts register
chain+executor once after construction; _dispatch_learning calls get_executor().
"""
from __future__ import annotations
from typing import Any

_chain: Any = None
_executor: Any = None


def register_runtime(chain: Any, executor: Any) -> None:
    global _chain, _executor
    _chain = chain
    _executor = executor


def get_executor() -> Any:
    return _executor


def get_chain() -> Any:
    return _chain
