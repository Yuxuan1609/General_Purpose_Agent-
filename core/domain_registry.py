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

    def save(self, filepath: Path) -> None:
        import json
        import tempfile
        data = {
            "nodes": {
                path: {
                    "parent": node.parent,
                    "description": node.description,
                    "correlations": node.correlations,
                    "relations": node.relations,
                }
                for path, node in self._nodes.items()
            },
            "reverse_index": self._reverse_index,
        }
        filepath.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=filepath.parent, suffix=".json")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            Path(tmp).replace(filepath)
        finally:
            Path(tmp).unlink(missing_ok=True)

    @classmethod
    def load(cls, filepath: Path) -> DomainRegistry:
        import json
        if not filepath.exists():
            return cls()
        data = json.loads(filepath.read_text(encoding="utf-8"))
        nodes = {}
        for path, raw in data.get("nodes", {}).items():
            nodes[path] = DomainNode(
                path=path,
                parent=raw.get("parent"),
                description=raw.get("description", ""),
                correlations=raw.get("correlations", {}),
                relations=raw.get("relations", ""),
            )
        reg = cls(nodes)
        reg._reverse_index = data.get("reverse_index", {"l2": {}, "l3": {}, "tool": {}})
        return reg

    def __len__(self):
        return len(self._nodes)
