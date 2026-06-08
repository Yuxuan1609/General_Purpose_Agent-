# Domain System Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded domain strings with a centralized DomainRegistry that manages domain nodes, their relationships, and reverse-indexes all knowledge/skills/tools by domain.

**Architecture:** New `core/domain_registry.py` (DomainNode dataclass + DomainRegistry class) backed by `data/layers/domain_registry.json`. All searchable entities (KnowledgeCard, SkillMeta, ToolDefinition) gain `available_domains: list[str]` field. Registry provides dual-path retrieval: primary (exact domain match) + explore (correlated domains). L1/L2/L3 managers query registry instead of using hardcoded constants.

**Tech Stack:** Python dataclasses, JSON persistence (atomic write via tempfile.mkstemp + Path.replace), pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `core/domain_registry.py` | **Create** | DomainNode dataclass + DomainRegistry class |
| `data/layers/domain_registry.json` | **Create** | Persisted domain nodes + reverse index |
| `core/task.py` | Modify | Deprecate `Domain.level` field, keep `path` |
| `core/flexible_knowledge.py` | Modify | KnowledgeCard: `domain` → `available_domains`; sync reverse_index on add/remove |
| `core/skill_layer.py` | Modify | SkillMeta: `domain` → `available_domains`; `match()` → `get_skills_by_ids()` via registry |
| `core/tools/registry.py` | Modify | ToolDefinition: add `available_domains`; add `get_tools_for_domain()` |
| `core/seed_knowledge.py` | Modify | Init DomainRegistry nodes + index all seed items |
| `core/layers/__init__.py` | Modify | `build_chain()` accepts and passes `DomainRegistry` |
| `core/layers/l0_5_1/manager.py` | Modify | L1Agent: `L2_DOMAIN_NODES` → `registry.list_all()` |
| `core/layers/l2/manager.py` | Modify | L2Manager: dual-path retrieval via registry; remove `L2_DOMAIN_NODES` |
| `core/layers/l3/manager.py` | Modify | L3Manager: `skill_layer.match()` → `registry.get_primary_items("l3", domain)` |
| `core/chain_factory.py` | Modify | Build DomainRegistry in factory |
| `scripts/test_consolidation_real.py` | Modify | Wire registry into test setup |
| `scripts/smoke_test_consolidation.py` | Modify | Wire registry into smoke test setup |
| `tests/test_domain_registry.py` | **Create** | Test DomainRegistry CRUD, indexing, retrieval |
| `tests/conftest.py` | Modify | Add `domain_registry` fixture |

---

### Task 1: DomainNode dataclass + DomainRegistry skeleton

**Files:**
- Create: `core/domain_registry.py`
- Create: `tests/test_domain_registry.py`

- [ ] **Step 1: Write DomainNode and DomainRegistry skeleton**

```python
# core/domain_registry.py
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
```

- [ ] **Step 2: Write test for basic operations**

```python
# tests/test_domain_registry.py
from core.domain_registry import DomainNode, DomainRegistry


class TestDomainNode:
    def test_create_node(self):
        node = DomainNode(
            path="game/leduc",
            parent="game",
            description="Leduc Hold'em",
            correlations={"game/doudizhu": 0.6},
            relations="sister of doudizhu",
        )
        assert node.path == "game/leduc"
        assert node.parent == "game"
        assert node.correlations["game/doudizhu"] == 0.6


class TestDomainRegistry:
    def test_empty_registry(self):
        reg = DomainRegistry()
        assert len(reg) == 0
        assert reg.list_all() == []

    def test_add_and_get_node(self):
        reg = DomainRegistry()
        reg._nodes["game"] = DomainNode(
            path="game", parent=None,
            description="Games", relations="child: leduc"
        )
        node = reg.get_node("game")
        assert node is not None
        assert node.description == "Games"
        assert node.parent is None

    def test_get_nonexistent_returns_none(self):
        reg = DomainRegistry()
        assert reg.get_node("nonexistent") is None

    def test_list_all(self):
        reg = DomainRegistry()
        reg._nodes["a"] = DomainNode(path="a", parent=None, description="A")
        reg._nodes["b"] = DomainNode(path="b", parent="a", description="B")
        nodes = reg.list_all()
        assert len(nodes) == 2
        paths = {n.path for n in nodes}
        assert paths == {"a", "b"}

    def test_children_of(self):
        reg = DomainRegistry()
        reg._nodes["game"] = DomainNode(path="game", parent=None, description="G")
        reg._nodes["game/leduc"] = DomainNode(path="game/leduc", parent="game", description="L")
        reg._nodes["game/doudizhu"] = DomainNode(path="game/doudizhu", parent="game", description="D")
        reg._nodes["coding"] = DomainNode(path="coding", parent=None, description="C")
        children = reg.children_of("game")
        assert len(children) == 2
        assert {c.path for c in children} == {"game/leduc", "game/doudizhu"}
```

- [ ] **Step 3: Run tests to verify**

Run: `pytest tests/test_domain_registry.py -v`
Expected: 4 PASS

- [ ] **Step 4: Commit**

```bash
git add core/domain_registry.py tests/test_domain_registry.py
git commit -m "feat: DomainNode dataclass + DomainRegistry skeleton with basic CRUD"
```

---

### Task 2: DomainRegistry persistence (load/save JSON)

**Files:**
- Modify: `core/domain_registry.py`
- Create: `data/layers/domain_registry.json`
- Modify: `tests/test_domain_registry.py`

- [ ] **Step 1: Add save/load to DomainRegistry**

```python
# core/domain_registry.py — add to DomainRegistry class

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
```

- [ ] **Step 2: Write test for persistence round-trip**

```python
# tests/test_domain_registry.py — add to TestDomainRegistry

    def test_save_load_roundtrip(self, tmp_path):
        reg = DomainRegistry()
        reg._nodes["game"] = DomainNode(
            path="game", parent=None,
            description="Games", correlations={}, relations=""
        )
        reg._nodes["game/leduc"] = DomainNode(
            path="game/leduc", parent="game",
            description="Leduc", correlations={"game/doudizhu": 0.6}, relations="sib"
        )
        reg._reverse_index["l2"]["game/leduc"] = ["card_1", "card_2"]
        reg._reverse_index["l3"]["game/leduc"] = ["skill_a"]
        reg._reverse_index["tool"]["general"] = ["web_search"]

        fp = tmp_path / "registry.json"
        reg.save(fp)

        loaded = DomainRegistry.load(fp)
        assert len(loaded) == 2
        node = loaded.get_node("game/leduc")
        assert node.description == "Leduc"
        assert node.correlations == {"game/doudizhu": 0.6}
        assert loaded._reverse_index["l2"]["game/leduc"] == ["card_1", "card_2"]
        assert loaded._reverse_index["l3"]["game/leduc"] == ["skill_a"]
        assert loaded._reverse_index["tool"]["general"] == ["web_search"]

    def test_load_nonexistent_returns_empty(self, tmp_path):
        reg = DomainRegistry.load(tmp_path / "nonexistent.json")
        assert len(reg) == 0
```

- [ ] **Step 3: Create seed domain_registry.json**

```json
{
  "nodes": {
    "general": {
      "parent": null,
      "description": "通用领域，跨域知识的默认归属",
      "correlations": {},
      "relations": ""
    },
    "game": {
      "parent": "general",
      "description": "游戏策略领域的根节点，涵盖各类对抗性游戏的决策知识",
      "correlations": {"learning/reflect": 0.2},
      "relations": "子域: game/leduc, game/doudizhu"
    },
    "game/leduc": {
      "parent": "game",
      "description": "Leduc Hold'em 简化德州扑克，2人对局，K/Q/J各两种花色，翻牌前/翻牌后两轮下注",
      "correlations": {"game/doudizhu": 0.6},
      "relations": "姊妹域: game/doudizhu（同为扑克类游戏，部分策略可迁移）"
    },
    "game/doudizhu": {
      "parent": "game",
      "description": "斗地主3人卡牌游戏，54张牌含大小王，1地主vs2农民",
      "correlations": {"game/leduc": 0.6},
      "relations": "姊妹域: game/leduc（扑克类，顶牌/炸弹等策略部分互通）"
    },
    "learning/reflect": {
      "parent": "general",
      "description": "学习反思域，消费执行记录分析策略问题和改进机会",
      "correlations": {},
      "relations": "子域: learning/compile, learning/consolidate"
    },
    "learning/compile": {
      "parent": "learning/reflect",
      "description": "知识编译域，将高激活同域卡片编译为L3技能",
      "correlations": {"learning/consolidate": 0.8},
      "relations": "姊妹域: learning/consolidate"
    },
    "learning/consolidate": {
      "parent": "learning/reflect",
      "description": "知识整理域，管理知识库容量：合并相似条目、归档低活跃内容",
      "correlations": {"learning/compile": 0.8},
      "relations": "姊妹域: learning/compile"
    }
  },
  "reverse_index": {
    "l2": {},
    "l3": {},
    "tool": {}
  }
}
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest tests/test_domain_registry.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add core/domain_registry.py data/layers/domain_registry.json tests/test_domain_registry.py
git commit -m "feat: DomainRegistry JSON persistence (load/save) + seed registry.json"
```

---

### Task 3: DomainRegistry retrieval API (get_primary_items, get_explore_items, get_items_for_domains)

**Files:**
- Modify: `core/domain_registry.py`
- Modify: `tests/test_domain_registry.py`

- [ ] **Step 1: Add retrieval methods**

```python
# core/domain_registry.py — add to DomainRegistry class

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
        for neighbor_path, weight in node.correlations.items():
            if weight >= threshold:
                result.extend(idx.get(neighbor_path, []))
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
```

- [ ] **Step 2: Write tests for retrieval**

```python
# tests/test_domain_registry.py — add to TestDomainRegistry

    def _setup_registry_with_index(self):
        reg = DomainRegistry()
        reg._nodes["game/leduc"] = DomainNode(
            path="game/leduc", parent="game",
            description="Leduc", correlations={"game/doudizhu": 0.6}
        )
        reg._nodes["game/doudizhu"] = DomainNode(
            path="game/doudizhu", parent="game",
            description="Doudizhu", correlations={"game/leduc": 0.6}
        )
        reg._nodes["coding"] = DomainNode(
            path="coding", parent=None,
            description="Code", correlations={}
        )
        reg._reverse_index = {
            "l2": {
                "game/leduc": ["card_1", "card_2"],
                "game/doudizhu": ["card_3"],
                "coding": ["card_4"],
            },
            "l3": {
                "game/leduc": ["skill_a"],
            },
            "tool": {
                "general": ["web_search"],
                "game/leduc": ["poker_calc"],
            },
        }
        return reg

    def test_get_primary_items(self):
        reg = self._setup_registry_with_index()
        assert reg.get_primary_items("l2", "game/leduc") == ["card_1", "card_2"]
        assert reg.get_primary_items("l2", "nonexistent") == []

    def test_get_explore_items(self):
        reg = self._setup_registry_with_index()
        items = reg.get_explore_items("l2", "game/leduc", threshold=0.5)
        assert "card_3" in items
        assert "card_4" not in items

    def test_get_explore_items_below_threshold(self):
        reg = self._setup_registry_with_index()
        items = reg.get_explore_items("l2", "game/leduc", threshold=0.9)
        assert items == []

    def test_get_items_for_domains(self):
        reg = self._setup_registry_with_index()
        items = reg.get_items_for_domains("l2", ["game/leduc", "game/doudizhu"])
        assert sorted(items) == ["card_1", "card_2", "card_3"]
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_domain_registry.py -v`
Expected: 10 PASS

- [ ] **Step 4: Commit**

```bash
git add core/domain_registry.py tests/test_domain_registry.py
git commit -m "feat: DomainRegistry retrieval API (primary/explore/multi-domain)"
```

---

### Task 4: DomainRegistry mutation API (index management + graph management)

**Files:**
- Modify: `core/domain_registry.py`
- Modify: `tests/test_domain_registry.py`

- [ ] **Step 1: Add index and graph mutation methods**

```python
# core/domain_registry.py — add to DomainRegistry class

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
```

- [ ] **Step 2: Write tests for mutation**

```python
# tests/test_domain_registry.py — add to TestDomainRegistry

    def test_index_and_unindex(self):
        reg = DomainRegistry()
        reg.index_item("l2", "game/leduc", "card_1")
        assert reg.get_primary_items("l2", "game/leduc") == ["card_1"]
        reg.index_item("l2", "game/leduc", "card_2")
        assert reg.get_primary_items("l2", "game/leduc") == ["card_1", "card_2"]
        reg.index_item("l2", "game/leduc", "card_1")  # no dupe
        assert reg.get_primary_items("l2", "game/leduc") == ["card_1", "card_2"]
        reg.unindex_item("l2", "game/leduc", "card_1")
        assert reg.get_primary_items("l2", "game/leduc") == ["card_2"]

    def test_update_item_domains(self):
        reg = DomainRegistry()
        reg.index_item("l2", "game/leduc", "card_x")
        reg.index_item("l2", "game/doudizhu", "card_x")
        reg.update_item_domains("l2", "card_x", ["game/leduc", "coding"])
        assert reg.get_primary_items("l2", "game/leduc") == ["card_x"]
        assert reg.get_primary_items("l2", "game/doudizhu") == []
        assert reg.get_primary_items("l2", "coding") == ["card_x"]

    def test_add_node(self):
        reg = DomainRegistry()
        node = reg.add_node("coding/python", parent="coding",
                            description="Python stuff",
                            correlations={"coding": 0.9},
                            relations="sub of coding")
        retrieved = reg.get_node("coding/python")
        assert retrieved is node
        assert retrieved.description == "Python stuff"
        assert len(reg) == 1

    def test_update_correlation(self):
        reg = DomainRegistry()
        reg.add_node("a", None, "A")
        reg.add_node("b", None, "B", correlations={"a": 0.3})
        reg.update_correlation("a", "b", 0.7)
        assert reg.get_node("a").correlations == {"b": 0.7}
        assert reg.get_node("b").correlations == {"a": 0.7}

    def test_update_node(self):
        reg = DomainRegistry()
        reg.add_node("x", None, "old desc")
        result = reg.update_node("x", description="new desc", relations="hi")
        assert result is not None
        assert reg.get_node("x").description == "new desc"
        assert reg.get_node("x").relations == "hi"

    def test_update_node_nonexistent(self):
        reg = DomainRegistry()
        assert reg.update_node("nope", description="x") is None
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_domain_registry.py -v`
Expected: 16 PASS

- [ ] **Step 4: Commit**

```bash
git add core/domain_registry.py tests/test_domain_registry.py
git commit -m "feat: DomainRegistry mutation API (index + graph management)"
```

---

### Task 5: FlexibleKnowledge — KnowledgeCard.available_domains + index sync

**Files:**
- Modify: `core/flexible_knowledge.py`
- Modify: `tests/test_flexible_knowledge.py`
- Modify: `tests/test_domain_registry.py`

- [ ] **Step 1: Add available_domains to KnowledgeCard**

```python
# core/flexible_knowledge.py — modify KnowledgeCard dataclass

@dataclass
class KnowledgeCard:
    id: str
    content: str
    domain: "Domain"                     # keep for backward compat
    available_domains: list[str] = field(default_factory=list)
    confidence: float = 0.5
    activation: float = 0.5
    source: str = "manual"
    success_count: int = 0
    failure_count: int = 0
    last_used: str = ""
```

- [ ] **Step 2: Add registry parameter + index sync to FlexibleKnowledge**

```python
# core/flexible_knowledge.py — modify FlexibleKnowledge.__init__

    def __init__(self, knowledge_dir, index_path, domain_registry=None):
        self.knowledge_dir = Path(knowledge_dir)
        self.index_path = Path(index_path)
        self._registry = domain_registry
        self.cards: list[KnowledgeCard] = []
```

```python
# core/flexible_knowledge.py — modify add_card to init available_domains + sync index

    def add_card(self, content, domain, confidence=0.5, source="manual",
                 available_domains=None) -> KnowledgeCard:
        card_id = uuid.uuid4().hex[:8]
        card = KnowledgeCard(
            id=card_id, content=content, domain=domain,
            available_domains=available_domains or [domain.path],
            confidence=confidence, source=source,
        )
        self.cards.append(card)
        self._sync_card_index(card)
        return card

    def _sync_card_index(self, card: KnowledgeCard) -> None:
        if self._registry is None:
            return
        for d in card.available_domains:
            self._registry.index_item("l2", d, card.id)

    def _unsync_card_index(self, card_id: str) -> None:
        if self._registry is None:
            return
        for d, ids in list(self._registry._reverse_index.get("l2", {}).items()):
            if card_id in ids:
                ids.remove(card_id)
```

```python
# core/flexible_knowledge.py — modify remove_card to unsync index

    def remove_card(self, card_id: str) -> bool:
        self._unsync_card_index(card_id)
        for i, c in enumerate(self.cards):
            if c.id == card_id:
                self.cards.pop(i)
                return True
        return False
```

- [ ] **Step 3: Write test for available_domains + index sync**

```python
# tests/test_flexible_knowledge.py — add test

    def test_card_available_domains_indexed(self, tmp_path):
        from core.domain_registry import DomainRegistry
        reg = DomainRegistry()
        reg.add_node("game/leduc", "game", "Leduc")
        reg.add_node("game", None, "Game")
        fk = FlexibleKnowledge(tmp_path / "k", tmp_path / "index.json",
                               domain_registry=reg)
        card = fk.add_card(content="test", domain=Domain("game/leduc", "specific"))
        assert card.available_domains == ["game/leduc"]
        items = reg.get_primary_items("l2", "game/leduc")
        assert card.id in items

    def test_card_remove_unsyncs_index(self, tmp_path):
        from core.domain_registry import DomainRegistry
        reg = DomainRegistry()
        reg.add_node("game/leduc", "game", "Leduc")
        fk = FlexibleKnowledge(tmp_path / "k", tmp_path / "index.json",
                               domain_registry=reg)
        card = fk.add_card(content="test", domain=Domain("game/leduc", "specific"))
        assert card.id in reg.get_primary_items("l2", "game/leduc")
        fk.remove_card(card.id)
        assert card.id not in reg.get_primary_items("l2", "game/leduc")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_flexible_knowledge.py tests/test_domain_registry.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/flexible_knowledge.py tests/test_flexible_knowledge.py
git commit -m "feat: KnowledgeCard.available_domains + FlexibleKnowledge index sync"
```

---

### Task 6: SkillLayer — SkillMeta.available_domains + registry-based matching

**Files:**
- Modify: `core/skill_layer.py`
- Modify: `tests/test_skill_layer.py`

- [ ] **Step 1: Add available_domains to SkillMeta, registry parameter to SkillLayer**

```python
# core/skill_layer.py — modify SkillMeta

@dataclass
class SkillMeta:
    name: str
    description: str
    domain: "Domain"                    # keep for backward compat
    available_domains: list[str] = field(default_factory=list)
    cross_domain: bool = False          # keep for backward compat
    skill_dir: Path | None = None
    created_by: str = "manual"
    source_card_ids: list[str] = field(default_factory=list)
```

```python
# core/skill_layer.py — modify SkillLayer.__init__

    def __init__(self, skills_dir, tool_registry, domain_registry=None):
        self.skills_dir = Path(skills_dir)
        self.tool_registry = tool_registry
        self._registry = domain_registry
        self._skills: dict[str, SkillMeta] = {}
```

```python
# core/skill_layer.py — modify create_skill

    def create_skill(self, name, content, domain, created_by="manual",
                     available_domains=None) -> SkillMeta:
        meta = SkillMeta(
            name=name, description=content.split("\n")[0][:200],
            domain=domain,
            available_domains=available_domains or [domain.path],
            skill_dir=None, created_by=created_by,
        )
        self._skills[name] = meta
        if self._registry:
            for d in meta.available_domains:
                self._registry.index_item("l3", d, name)
        # write SKILL.md file ... (existing logic)
        return meta
```

- [ ] **Step 2: Add registry-based query method, deprecate old match()**

```python
# core/skill_layer.py — add to SkillLayer

    def get_skills_by_ids(self, ids: list[str]) -> list[dict]:
        result = []
        for name in ids:
            skill = self._skills.get(name)
            if skill is None:
                continue
            content = ""
            if skill.skill_dir:
                skf = skill.skill_dir / "SKILL.md"
                if skf.exists():
                    content = skf.read_text(encoding="utf-8")
            result.append({
                "name": skill.name,
                "description": skill.description,
                "domain": skill.domain.path,
                "content": content,
            })
        return result

    # match() kept for backward compat but marked for removal
    def match(self, task_domain) -> list[SkillMeta]:
        if self._registry:
            ids = self._registry.get_primary_items("l3", task_domain.path)
            return [self._skills[n] for n in ids if n in self._skills]
        # fallback to old match logic (unchanged)
        ...
```

- [ ] **Step 3: Write test**

```python
# tests/test_skill_layer.py — add test

    def test_get_skills_by_ids_from_registry(self):
        from core.domain_registry import DomainRegistry
        reg = DomainRegistry()
        reg.add_node("game/leduc", "game", "Leduc")
        sl = SkillLayer(self.tmp_dir / "skills", ToolRegistry(),
                        domain_registry=reg)
        sl.create_skill("test-skill", "desc\ncontent", Domain("game/leduc", "specific"))
        ids = reg.get_primary_items("l3", "game/leduc")
        assert "test-skill" in ids
        skills = sl.get_skills_by_ids(ids)
        assert len(skills) == 1
        assert skills[0]["name"] == "test-skill"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_skill_layer.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add core/skill_layer.py tests/test_skill_layer.py
git commit -m "feat: SkillMeta.available_domains + registry-based get_skills_by_ids"
```

---

### Task 7: ToolRegistry — ToolDefinition.available_domains + domain filtering

**Files:**
- Modify: `core/tools/registry.py`
- Modify: `tests/test_tool_registry.py`

- [ ] **Step 1: Add available_domains to ToolDefinition, registry parameter**

```python
# core/tools/registry.py — modify ToolDefinition

@dataclass
class ToolDefinition:
    name: str
    description: str
    schema: dict
    handler: callable
    available_domains: list[str] = field(default_factory=list)
```

```python
# core/tools/registry.py — modify ToolRegistry

    def __init__(self, domain_registry=None):
        self._tools: dict[str, ToolDefinition] = {}
        self._registry = domain_registry

    def register(self, schema, handler, available_domains=None):
        name = schema.get("name", "")
        desc = schema.get("description", "")
        tool = ToolDefinition(
            name=name, description=desc, schema=schema,
            handler=handler,
            available_domains=available_domains or ["general"],
        )
        self._tools[name] = tool
        if self._registry:
            for d in tool.available_domains:
                self._registry.index_item("tool", d, name)

    def get_tools_for_domain(self, domain: str) -> list[ToolDefinition]:
        if self._registry:
            ids = self._registry.get_primary_items("tool", domain)
            return [t for t in self._tools.values() if t.name in ids]
        return list(self._tools.values())
```

- [ ] **Step 2: Write test**

```python
# tests/test_tool_registry.py — add test

    def test_tool_domain_filtering(self):
        from core.domain_registry import DomainRegistry
        reg = DomainRegistry()
        reg.add_node("game/leduc", "game", "Leduc")
        reg.add_node("general", None, "General")
        tr = ToolRegistry(domain_registry=reg)
        tr.register({"name": "web_search", "description": "search"},
                    lambda: None, available_domains=["general"])
        tr.register({"name": "poker_calc", "description": "odds"},
                    lambda: None, available_domains=["game/leduc"])
        tools = tr.get_tools_for_domain("game/leduc")
        names = [t.name for t in tools]
        assert "poker_calc" in names
        assert "web_search" not in names
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_tool_registry.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add core/tools/registry.py tests/test_tool_registry.py
git commit -m "feat: ToolDefinition.available_domains + get_tools_for_domain filtering"
```

---

### Task 8: seed_knowledge.py — init DomainRegistry + index all seed items

**Files:**
- Modify: `core/seed_knowledge.py`

- [ ] **Step 1: Add registry init + indexing to seed_knowledge**

```python
# core/seed_knowledge.py — new function

def init_registry(registry_path: Path) -> DomainRegistry:
    from core.domain_registry import DomainRegistry
    reg = DomainRegistry.load(registry_path)
    if len(reg) == 0:
        # first-time init: load from seed
        reg = _seed_domain_nodes()
        reg.save(registry_path)
    return reg


def _seed_domain_nodes() -> DomainRegistry:
    from core.domain_registry import DomainRegistry, DomainNode
    reg = DomainRegistry()
    nodes = [
        ("general", None, "通用领域，跨域知识的默认归属", {}, ""),
        ("game", "general", "游戏策略领域的根节点", {"learning/reflect": 0.2}, "子域: game/leduc, game/doudizhu"),
        ("game/leduc", "game", "Leduc Hold'em 简化德州扑克", {"game/doudizhu": 0.6}, "姊妹域: game/doudizhu"),
        ("game/doudizhu", "game", "斗地主3人卡牌游戏", {"game/leduc": 0.6}, "姊妹域: game/leduc"),
        ("learning/reflect", "general", "学习反思域", {}, "子域: learning/compile, learning/consolidate"),
        ("learning/compile", "learning/reflect", "知识编译域", {"learning/consolidate": 0.8}, "姊妹域: learning/consolidate"),
        ("learning/consolidate", "learning/reflect", "知识整理域", {"learning/compile": 0.8}, "姊妹域: learning/compile"),
    ]
    for path, parent, desc, corr, rels in nodes:
        reg.add_node(path, parent, desc, corr, rels)
    return reg
```

- [ ] **Step 2: Modify seed functions to index items**

```python
# core/seed_knowledge.py — modify seed_knowledge to accept + use registry

def seed_knowledge(fk, phil, sl=None, domain_registry=None):
    _seed_leduc_cards(fk, domain_registry)
    _seed_doudizhu_cards(fk, domain_registry)
    _seed_consolidation_cards(fk, domain_registry)
    if sl:
        _seed_l3_skills(sl, domain_registry)


def _seed_leduc_cards(fk, registry=None):
    domain = Domain("game/leduc", "specific")
    cards = [...]
    for content, conf in cards:
        card = fk.add_card(content=content, domain=domain, confidence=conf,
                           source="seed", available_domains=["game/leduc"])
    # FlexibleKnowledge.add_card already syncs with registry
```

- [ ] **Step 3: Run existing tests to verify no breakage**

Run: `pytest tests/test_flexible_knowledge.py tests/test_skill_layer.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add core/seed_knowledge.py
git commit -m "feat: seed_knowledge — init DomainRegistry + index all seed items"
```

---

### Task 9: L1/L2/L3 managers — wire DomainRegistry

**Files:**
- Modify: `core/layers/__init__.py`
- Modify: `core/layers/l0_5_1/manager.py`
- Modify: `core/layers/l2/manager.py`
- Modify: `core/layers/l3/manager.py`

- [ ] **Step 1: build_chain accepts DomainRegistry, passes to managers**

```python
# core/layers/__init__.py

def build_chain(meta_driver, philosophy, flexible_knowledge, skill_layer,
                auxiliary_llm=None, domain_registry=None) -> L0_5_1Manager:
    ...
    l3 = L3Manager(skill_layer, upward=L3Upward(), downward=L3Downward(),
                   auxiliary_llm=auxiliary_llm, domain_registry=domain_registry)
    l2 = L2Manager(flexible_knowledge, downstream=l3,
                   upward=L2Upward(), downward=L2Downward(),
                   auxiliary_llm=auxiliary_llm, domain_registry=domain_registry)
    l1 = L0_5_1Manager(meta_driver, philosophy, auxiliary_llm=auxiliary_llm,
                        downstream=l2, upward=L1Upward(), downward=L1Downward(),
                        domain_registry=domain_registry)
    return l1
```

- [ ] **Step 2: L1 — replace L2_DOMAIN_NODES with registry.list_all()**

```python
# core/layers/l0_5_1/manager.py

class L0_5_1Manager(LayerManager):
    def __init__(self, meta_driver, philosophy, auxiliary_llm=None,
                 downstream=None, upward=None, downward=None,
                 domain_registry=None):
        super().__init__(...)
        self._registry = domain_registry
        self._agent = L1Agent(auxiliary_llm, philosophy) if auxiliary_llm else None

    def query(self, msg, trace_id=""):
        ...
        domain_nodes = self._registry.list_all() if self._registry else L2_DOMAIN_NODES
        stage1_result = self._agent.stage1(meta, obs.state,
                                           domain_nodes=domain_nodes)
        ...
```

```python
# core/layers/l0_5_1/manager.py — L1Agent.stage1, adapt node format

    def stage1(self, meta, state, domain_nodes=None):
        nodes = domain_nodes or []
        nodes_text = "\n".join(
            f"{i + 1}. {n.path if hasattr(n, 'path') else n['name']}\n"
            f"   {n.description if hasattr(n, 'description') else n.get('description','')}"
            for i, n in enumerate(nodes)
        )
        ...
```

- [ ] **Step 3: L2 — dual-path retrieval via registry**

```python
# core/layers/l2/manager.py

class L2Manager(LayerManager):
    def __init__(self, knowledge, downstream=None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None):
        ...
        self._registry = domain_registry

    def query(self, msg, trace_id=""):
        ...
        # Primary + Explore retrieval
        if self._registry and obs:
            session = obs.session or {}
            task_domain = session.get("domain", "general")
            primary_ids = self._registry.get_primary_items("l2", task_domain)
            explore_ids = self._registry.get_explore_items("l2", task_domain, threshold=0.5)
            all_ids = list(dict.fromkeys(primary_ids + explore_ids))
            self._cards = self._build_cards_from_ids(all_ids)
        else:
            self._cards = self._build_cards(selected_nodes)
        ...

    def _build_cards_from_ids(self, card_ids):
        cards = []
        for cid in card_ids:
            for c in self._knowledge.cards:
                if c.id == cid:
                    cards.append({
                        "content": c.content,
                        "confidence": c.confidence,
                        "activation": c.activation,
                        "domain": c.domain.path,
                    })
                    break
        return cards
```

- [ ] **Step 4: L3 — registry-based skill matching**

```python
# core/layers/l3/manager.py

class L3Manager(LayerManager):
    def __init__(self, skill_layer, downstream=None,
                 upward=None, downward=None, auxiliary_llm=None,
                 domain_registry=None):
        ...
        self._registry = domain_registry

    def query(self, msg, trace_id=""):
        ...
        session = obs.session if obs else {}
        domain_path = session.get("domain", "general")

        if self._registry:
            skill_ids = self._registry.get_primary_items("l3", domain_path)
            self._matched_skills = self._skill_layer.get_skills_by_ids(skill_ids)
            self._matched = [s["name"] for s in self._matched_skills]
        else:
            # fallback to old match logic
            domain = Domain(domain_path, "specific")
            matched = self._skill_layer.match(domain)
            ...
```

- [ ] **Step 5: Run existing layer tests to verify**

Run: `pytest tests/test_layers.py -v`
Expected: all PASS (may need fixture updates for domain_registry)

- [ ] **Step 6: Commit**

```bash
git add core/layers/__init__.py core/layers/l0_5_1/manager.py core/layers/l2/manager.py core/layers/l3/manager.py
git commit -m "feat: wire DomainRegistry into L1/L2/L3 managers — dual-path retrieval + skill matching"
```

---

### Task 10: Integration — build_chain, scripts, deprecate Domain.level, remove L2_DOMAIN_NODES

**Files:**
- Modify: `core/chain_factory.py`
- Modify: `core/task.py`
- Modify: `core/layers/l2/manager.py`
- Modify: `scripts/test_consolidation_real.py`
- Modify: `scripts/smoke_test_consolidation.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: chain_factory builds registry**

```python
# core/chain_factory.py

def build_chain_with_registry(meta_driver, philosophy, fk, sl,
                               auxiliary_llm=None, registry_path=None):
    from core.seed_knowledge import init_registry
    reg = init_registry(registry_path) if registry_path else None
    return build_chain(meta_driver, philosophy, fk, sl,
                       auxiliary_llm=auxiliary_llm, domain_registry=reg)
```

- [ ] **Step 2: Deprecate Domain.level**

```python
# core/task.py — add deprecation comment

@dataclass(frozen=True)
class Domain:
    path: str
    level: str = "specific"  # DEPRECATED: will be removed in Phase 2
```

- [ ] **Step 3: Remove L2_DOMAIN_NODES from l2/manager.py imports**

```python
# core/layers/l2/manager.py — remove L2_DOMAIN_NODES from __all__ export
```

- [ ] **Step 4: Update scripts to pass registry**

```python
# scripts/test_consolidation_real.py — wire registry

from core.seed_knowledge import init_registry
reg_path = PROJECT_ROOT / "data" / "layers" / "domain_registry.json"
reg = init_registry(reg_path)
# pass reg to build_chain and knowledge stores
fk = FlexibleKnowledge(..., domain_registry=reg)
sl = SkillLayer(..., domain_registry=reg)
chain = _build_chain(..., domain_registry=reg)
```

- [ ] **Step 5: Update conftest fixtures**

```python
# tests/conftest.py — add domain_registry fixture

@pytest.fixture
def domain_registry():
    from core.domain_registry import DomainRegistry, DomainNode
    reg = DomainRegistry()
    reg.add_node("general", None, "通用")
    reg.add_node("game/leduc", "game", "Leduc")
    reg.add_node("game/doudizhu", "game", "Doudizhu")
    reg.add_node("learning/reflect", "general", "Reflect")
    reg.add_node("learning/consolidate", "learning/reflect", "Consolidate")
    return reg
```

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: all PASS

- [ ] **Step 7: Run consolidation test with real LLM**

Run: `python scripts/test_consolidation_real.py`
Expected: completes successfully (may need domain_registry.json in place)

- [ ] **Step 8: Commit**

```bash
git add core/chain_factory.py core/task.py core/layers/l2/manager.py scripts/test_consolidation_real.py scripts/smoke_test_consolidation.py tests/conftest.py
git commit -m "feat: integration — DomainRegistry wired through full chain, deprecate Domain.level"
```

---

### Task 11: Update MAINTAIN.md

**Files:**
- Modify: `MAINTAIN.md`

- [ ] **Step 1: Append DomainRegistry entries to MAINTAIN.md**

Add changelog entry and new section for `core/domain_registry.py` with DomainNode + DomainRegistry API table.

- [ ] **Step 2: Commit**

```bash
git add MAINTAIN.md
git commit -m "docs: MAINTAIN — DomainRegistry + DomainNode entries"
```
