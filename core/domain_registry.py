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
    embedding_vector: list[float] | None = None


class DomainRegistry:
    def __init__(self, nodes: dict[str, DomainNode] | None = None,
                 embedding_model_path: str | None = None,
                 db_path: Path | str | None = None):
        self._nodes: dict[str, DomainNode] = nodes or {}
        self._reverse_index: dict[str, dict[str, list[str]]] = {
            "l2": {}, "l3": {}, "tool": {},
        }
        self._embedding_model_path = embedding_model_path
        self._db = None
        if db_path:
            from core.storage.domain_store import DomainSQLiteStore
            self._db = DomainSQLiteStore(db_path)
            self._load_from_db()

    def _load_from_db(self):
        for n in self._db.list_nodes():
            self._nodes[n["path"]] = DomainNode(
                path=n["path"],
                parent=n.get("parent"),
                description=n.get("description", ""),
                correlations=n.get("correlations", {}),
                relations=n.get("relations", ""),
                embedding_vector=n.get("embedding_vector"),
            )
        self._reverse_index = self._db.get_all_index()

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
        if self._db:
            self._db.index_item(layer, domain, item_id)

    def unindex_item(self, layer: str, domain: str, item_id: str) -> None:
        idx = self._reverse_index.get(layer, {})
        lst = idx.get(domain, [])
        if item_id in lst:
            lst.remove(item_id)
        if self._db:
            self._db.unindex_item(layer, domain, item_id)

    def update_item_domains(self, layer: str, item_id: str,
                            domains: list[str]) -> None:
        idx = self._reverse_index.get(layer, {})
        for d, lst in idx.items():
            if item_id in lst:
                lst.remove(item_id)
                if self._db:
                    self._db.unindex_item(layer, d, item_id)
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
        if self._db:
            self._db.insert_node({
                "path": path,
                "parent": parent,
                "description": description,
                "correlations": correlations or {},
                "relations": relations,
            })
        return node

    def update_correlation(self, a: str, b: str, weight: float) -> None:
        node_a = self._nodes.get(a)
        if node_a:
            node_a.correlations[b] = weight
            if self._db:
                self._db.update_node(a, correlations=node_a.correlations)
        node_b = self._nodes.get(b)
        if node_b:
            node_b.correlations[a] = weight
            if self._db:
                self._db.update_node(b, correlations=node_b.correlations)

    def update_node(self, path: str, **fields) -> DomainNode | None:
        node = self._nodes.get(path)
        if node is None:
            return None
        for key, val in fields.items():
            if hasattr(node, key):
                object.__setattr__(node, key, val)
        if self._db and fields:
            self._db.update_node(path, **fields)
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

    # ── embedding & correlation ──

    def compute_embedding(self, path: str, content_getter=None) -> bool:
        node = self._nodes.get(path)
        if node is None:
            return False
        if content_getter is None:
            return False

        parts = [node.description]
        for layer in ("l2", "l3"):
            items = content_getter(layer, path) or []
            parts.extend(items)

        text = " | ".join(p for p in parts if p)
        if not text.strip():
            return False

        try:
            from core.model_manager import get_embedding_model
            model = get_embedding_model()
            import numpy as np
            vec = model.batchtransform([text])[0]
            node.embedding_vector = vec.tolist()
            if self._db:
                self._db.update_node(path, embedding_vector=node.embedding_vector)
            return True
        except Exception:
            return False

    def compute_correlation(self, a: str, b: str) -> float:
        node_a = self._nodes.get(a)
        node_b = self._nodes.get(b)
        if not node_a or not node_b:
            return 0.0

        emb_score = 0.0
        if node_a.embedding_vector and node_b.embedding_vector:
            import numpy as np
            va = np.array(node_a.embedding_vector)
            vb = np.array(node_b.embedding_vector)
            emb_score = float(np.dot(va, vb))
            emb_score = max(0.0, emb_score)

        idx = self._reverse_index
        items_a = set()
        items_b = set()
        for layer in ("l2", "l3"):
            for did in idx.get(layer, {}).get(a, []):
                items_a.add((layer, did))
            for did in idx.get(layer, {}).get(b, []):
                items_b.add((layer, did))
        union = len(items_a | items_b)
        jaccard = len(items_a & items_b) / union if union > 0 else 0.0

        return round(0.5 * emb_score + 0.5 * jaccard, 4)

    def refresh_embeddings_for(self, domains: list[str],
                               content_getter=None) -> int:
        count = 0
        for path in domains:
            if self.compute_embedding(path, content_getter):
                count += 1
        return count

    def compute_all_correlations(self) -> int:
        """Recompute all domain-to-domain correlations.
        Preserves existing correlations when computed value is 0.0
        (empty domains with no content to compare).
        """
        paths = list(self._nodes.keys())
        count = 0
        for i, a in enumerate(paths):
            for b in paths[i+1:]:
                corr = self.compute_correlation(a, b)
                if corr > 0.0 or self._nodes[a].correlations.get(b) or self._nodes[b].correlations.get(a):
                    self.update_correlation(a, b, corr)
                    count += 1
        return count

    # ── deprecate & merge ──

    def _remove_domain(self, path: str) -> None:
        for layer in ("l2", "l3", "tool"):
            self._reverse_index.get(layer, {}).pop(path, None)
            if self._db:
                self._db.unindex_domain(layer, path)
        self._nodes.pop(path, None)
        if self._db:
            self._db.delete_node(path)

    def deprecate_domain(self, path: str) -> None:
        node = self._nodes.get(path)
        if node is None:
            raise ValueError(f"Domain not found: {path}")

        orphaned = 0
        for layer in ("l2", "l3"):
            idx = self._reverse_index.get(layer, {})
            items_in_domain = set(idx.get(path, []))
            if not items_in_domain:
                continue
            items_in_others = set()
            for domain_name, item_list in idx.items():
                if domain_name != path:
                    items_in_others.update(item_list)
            orphans = items_in_domain - items_in_others
            orphaned += len(orphans)

        if orphaned > 0:
            raise ValueError(
                f"Domain '{path}' still has {orphaned} items with no other domain. "
                f"Migrate items before deprecating."
            )

        for layer in ("l2", "l3", "tool"):
            self._reverse_index.get(layer, {}).pop(path, None)
            if self._db:
                self._db.unindex_domain(layer, path)
        self._nodes.pop(path, None)
        if self._db:
            self._db.delete_node(path)

    def merge_domain(self, source: str, target: str,
                     content_getter=None) -> dict:
        if source not in self._nodes:
            raise ValueError(f"Source domain not found: {source}")
        if target not in self._nodes:
            raise ValueError(f"Target domain not found: {target}")

        source_node = self._nodes[source]
        target_node = self._nodes[target]

        moved = 0
        for layer in ("l2", "l3", "tool"):
            idx = self._reverse_index.get(layer, {})
            items = idx.pop(source, [])
            target_items = idx.setdefault(target, [])
            for item_id in items:
                if item_id not in target_items:
                    target_items.append(item_id)
                    moved += 1
                    if self._db:
                        self._db.index_item(layer, target, item_id)

        for k, v in source_node.correlations.items():
            if k in target_node.correlations:
                target_node.correlations[k] = max(target_node.correlations[k], v)
            else:
                target_node.correlations[k] = v
        target_node.correlations.pop(source, None)
        target_node.correlations.pop(target, None)

        for n in self._nodes.values():
            if source in n.correlations:
                v = n.correlations.pop(source)
                n.correlations[target] = max(n.correlations.get(target, 0), v)
                if self._db:
                    self._db.update_node(n.path, correlations=n.correlations)

        if self._db:
            self._db.update_node(target, correlations=target_node.correlations)

        self._remove_domain(source)

        if content_getter:
            self.compute_embedding(target, content_getter)

        return {"moved_items": moved}

    def save(self, filepath: Path) -> None:
        if self._db:
            return
        import json
        import tempfile
        data = {
            "nodes": {
                path: {
                    "parent": node.parent,
                    "description": node.description,
                    "correlations": node.correlations,
                    "relations": node.relations,
                    "embedding_vector": node.embedding_vector,
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
                embedding_vector=raw.get("embedding_vector"),
            )
        reg = cls(nodes)
        reg._reverse_index = data.get("reverse_index", {"l2": {}, "l3": {}, "tool": {}})
        return reg

    def __len__(self):
        return len(self._nodes)
