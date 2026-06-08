from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DomainNode:
    path: str
    parent: str | None
    description: str
    correlations: dict[str, float] = field(default_factory=dict)
    relations: str = ""


class DomainRegistry:
    def __init__(self, nodes: dict[str, DomainNode] | None = None):
        self._nodes: dict[str, DomainNode] = nodes or {}
        self._reverse_index: dict[str, dict[str, list[str]]] = {
            "l2": {}, "l3": {}, "tool": {},
        }

    def get_node(self, path: str) -> DomainNode | None:
        return self._nodes.get(path)

    def list_all(self) -> list[DomainNode]:
        return list(self._nodes.values())

    def children_of(self, path: str) -> list[DomainNode]:
        return [n for n in self._nodes.values() if n.parent == path]

    def __len__(self):
        return len(self._nodes)
