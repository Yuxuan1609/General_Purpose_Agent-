"""Round tree — records L1→L2→L3 decision chain per round."""
from __future__ import annotations
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class DecisionNode:
    layer: str            # "l0_5_1" | "l2" | "l3"
    query: str            # query/task received
    result: str           # decision result
    reasoning: str        # why
    children: list[DecisionNode] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "layer": self.layer,
            "query": self.query[:1000],
            "result": self.result[:2000],
            "reasoning": self.reasoning[:2000],
            "children": [c.to_dict() for c in self.children],
        }


class RoundHistory:
    def __init__(self, max_rounds: int = 5):
        self._queue: deque[DecisionNode] = deque(maxlen=max_rounds)

    def push(self, l1_node: DecisionNode) -> None:
        self._queue.append(l1_node)

    def snapshot(self, count: int | None = None) -> list[DecisionNode]:
        items = list(self._queue)
        if count is not None:
            items = items[-count:]
        return items

    def all_as_dict(self) -> list[dict]:
        return [n.to_dict() for n in self._queue]

    def __len__(self) -> int:
        return len(self._queue)


# Global singleton
_history: RoundHistory | None = None


def get_round_history() -> RoundHistory:
    global _history
    if _history is None:
        _history = RoundHistory()
    return _history


# ── Thread-local node stack for RoundTree construction ──

import threading

_current_node_stack = threading.local()


def current_node() -> DecisionNode | None:
    stack = getattr(_current_node_stack, "stack", None)
    return stack[-1] if stack else None


def push_node(node: DecisionNode) -> None:
    stack = getattr(_current_node_stack, "stack", None)
    if stack is None:
        stack = []
        _current_node_stack.stack = stack
    stack.append(node)


def pop_node() -> DecisionNode | None:
    stack = getattr(_current_node_stack, "stack", None)
    if not stack:
        return None
    return stack.pop()
