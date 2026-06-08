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

    # ── index management ──

    def index_item(self, layer: str, domain: str, item_id: str) -> None:
        idx = self._reverse_index.setdefault(layer, {})
        lst = idx.setdefault(domain, [])
        if item_id not in lst:
            lst.append(item_id)

    def unindex_item(self, layer: str, domain: str, item_id: str) -> None:
        idx = self._reverse_index.get(layer, {})
        lst = idx.get(domain, [])
        if item_id in lst:
            lst.remove(item_id)

    def update_item_domains(self, layer: str, item_id: str,
                            domains: list[str]) -> None:
        idx = self._reverse_index.get(layer, {})
        for d, lst in idx.items():
            if item_id in lst:
                lst.remove(item_id)
        for d in domains:
            self.index_item(layer, d, item_id)

    # ── graph management ──

    def add_node(self, path: str, parent: str | None,
                 description: str = "",
                 correlations: dict[str, float] | None = None,
                 relations: str = "") -> DomainNode:
        node = DomainNode(
            path=path, parent=parent, description=description,
            correlations=correlations or {}, relations=relations,
        )
        self._nodes[path] = node
        return node

    def update_correlation(self, a: str, b: str, weight: float) -> None:
        node_a = self._nodes.get(a)
        if node_a:
            node_a.correlations[b] = weight
        node_b = self._nodes.get(b)
        if node_b:
            node_b.correlations[a] = weight

    def update_node(self, path: str, **fields) -> DomainNode | None:
        node = self._nodes.get(path)
        if node is None:
            return None
        for key, val in fields.items():
            if hasattr(node, key):
                object.__setattr__(node, key, val)
        return node

    def get_primary_items(self, layer: str, domain: str) -> list[str]:
        idx = self._reverse_index.get(layer, {})
        items = idx.get(domain, [])
        return list(items)

    def get_explore_items(self, layer: str, domain: str,
                          threshold: float = 0.5) -> list[str]:
        node = self._nodes.get(domain)
        if not node:
            return []
        idx = self._reverse_index.get(layer, {})
        result: list[str] = []
        seen: set[str] = set()
        for neighbor_path, weight in node.correlations.items():
            if weight >= threshold:
                for item_id in idx.get(neighbor_path, []):
                    if item_id not in seen:
                        seen.add(item_id)
                        result.append(item_id)
        return result

    def get_items_for_domains(self, layer: str, domains: list[str]) -> list[str]:
        idx = self._reverse_index.get(layer, {})
        seen: set[str] = set()
        result: list[str] = []
        for d in domains:
            for item_id in idx.get(d, []):
                if item_id not in seen:
                    seen.add(item_id)
                    result.append(item_id)
        return result

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
