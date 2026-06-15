# Domain Optimization V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make domain an index derived from L2/L3 content; add time system, auto-correlation, and Agent-driven split/merge operations.

**Architecture:** Domain is no longer hand-managed — its definition comes from the L2/L3 items assigned to it. Correlation is computed deterministically from content similarity with time decay weighting. Agent tools for domain management (create/query/deprecate/merge) are consolidation-only, injected via DictInjector.

**Tech Stack:** Python 3.10+, dataclasses, yaml, txtai embeddings (vendor)

---

## File Map

| File | Role | Change |
|------|------|------|
| `core/skill_layer.py` | SkillMeta + edit_skill + _parse_skill_meta | Add time fields (not actively used yet) |
| `core/knowledge/models.py` | KnowledgeDoc | Add `last_used` |
| `core/flexible_knowledge.py` | KnowledgeCard | No change (already has time fields) |
| `core/domain_registry.py` | DomainNode + DomainRegistry | Add embedding_vector, compute_embedding, compute_correlation, deprecate_domain, merge_domain |
| `core/layers/l2/manager.py` | L2 consolidation tools | Add `domain` to modify_l2_card |
| `core/layers/l3/manager.py` | L3 consolidation tools | Add `domain` to modify_l3_skill |
| `core/layers/l0_5_1/manager.py` | L1Agent + L0_5_1Manager | Add query_domain, deprecate_domain, merge_domain; enhance create_domain |
| `core/env/learning_env.py` | LearningEnv._apply_l2/_apply_l3 | Handle domain field in modify |
| `core/env/threshold_scorer.py` | ThresholdScorer | Domain health report |
| `core/chain_factory.py` | build_chain | Pass knowledge_stores to L0_5_1Manager |

---

### Task 1: Add time fields to SkillMeta

**Files:**
- Modify: `core/skill_layer.py:16-29`

- [ ] **Step 1: Add time fields to SkillMeta dataclass**

```python
@dataclass
class SkillMeta:
    name: str
    description: str
    domain: "Domain"
    available_domains: list[str] = field(default_factory=list)
    cross_domain: bool = False
    version: str = "1.0.0"
    created_by: str = "agent"
    source_cards: list[str] = field(default_factory=list)
    skill_dir: Path | None = None
    usefulness: int = 0
    misleading: int = 0
    comment: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    last_used: datetime = field(default_factory=_now)
```

Add import at top of file if missing:
```python
from datetime import datetime, timezone

def _now():
    return datetime.now(timezone.utc)
```

- [ ] **Step 2: Update create_skill to set created_at/updated_at**

In `create_skill()` (line ~74), after creating SkillMeta:
```python
meta = SkillMeta(
    name=name, description=description, domain=domain,
    available_domains=available_domains,
    cross_domain=cross_domain, created_by=created_by,
    source_cards=source_cards or [],
    skill_dir=skill_dir,
)
```
No change needed — `field(default_factory=_now)` handles it.

- [ ] **Step 3: Update _parse_skill_meta to read time fields from YAML**

In `_parse_skill_meta()` (line ~224), add time field reading:

```python
def _parse_skill_meta(self, skill_file: Path) -> SkillMeta | None:
    from core.task import Domain
    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    domain_path = fm.get("domain", "general")
    domain_level = "general" if domain_path == "general" else "specific"

    def _parse_time(key: str) -> datetime:
        v = fm.get(key, "")
        if not v:
            return _now()
        try:
            return datetime.fromisoformat(str(v))
        except (ValueError, TypeError):
            return _now()

    return SkillMeta(
        name=fm.get("name", skill_file.parent.name),
        description=fm.get("description", ""),
        domain=Domain(domain_path, domain_level),
        cross_domain=fm.get("cross_domain", False),
        version=str(fm.get("version", "1.0.0")),
        created_by=str(fm.get("created_by", "agent")),
        source_cards=fm.get("source_cards", []),
        skill_dir=skill_file.parent,
        usefulness=int(fm.get("usefulness", 0)),
        misleading=int(fm.get("misleading", 0)),
        comment=str(fm.get("comment", "")),
        created_at=_parse_time("created_at"),
        updated_at=_parse_time("updated_at"),
        last_used=_parse_time("last_used"),
    )
```

- [ ] **Step 4: Update edit_skill to bump updated_at**

In `edit_skill()` (after the content/quality logic, before return):
```python
    meta.updated_at = _now()
    return meta
```

- [ ] **Step 5: Add touch_skill for last_used**

New method on SkillLayer:
```python
def touch_skill(self, name: str) -> None:
    """Mark a skill as recently used."""
    meta = self._skills.get(name)
    if meta:
        meta.last_used = _now()
```

Call `touch_skill` in L3Manager when a skill is matched (in `query()` after `get_skills_by_ids`).

- [ ] **Step 6: Run tests and commit**

```bash
python3 -m pytest tests/test_skill_layer.py -q
python3 -m pytest tests/test_learning_env.py -q
git add core/skill_layer.py
git commit -m "feat: add time fields to SkillMeta (created_at, updated_at, last_used)"
```

---

### Task 2: Add last_used to KnowledgeDoc

**Files:**
- Modify: `core/knowledge/models.py:33-43`
- Modify: `core/knowledge/knowledge_base.py:42-62`

- [ ] **Step 1: Add last_used to KnowledgeDoc**

```python
@dataclass
class KnowledgeDoc:
    id: str = field(default_factory=_uid)
    domain: str = ""
    title: str = ""
    content: str = ""
    content_type: str = "markdown"
    source: str = "manual"
    meta: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_used: str = field(default_factory=_now)
```

Update `to_dict()`:
```python
def to_dict(self) -> dict:
    return {
        "id": self.id, "domain": self.domain, "title": self.title,
        "content": self.content, "content_type": self.content_type,
        "source": self.source, "meta": self.meta,
        "created_at": self.created_at, "updated_at": self.updated_at,
        "last_used": self.last_used,
    }
```

- [ ] **Step 2: Touch last_used on KB query**

In `knowledge_base.py`, find the search method. Add after returning results:
```python
for doc in results:
    doc.last_used = _now_static()
```

If the search method returns dicts not objects, update `self._docs[id].last_used = _now_static()` instead.

- [ ] **Step 3: Run tests and commit**

```bash
python3 -m pytest tests/test_knowledge_base.py -q
git add core/knowledge/models.py core/knowledge/knowledge_base.py
git commit -m "feat: add last_used to KnowledgeDoc, touch on query"
```

---

### Task 3: Time fields — data structure only (not actively used yet)

**(Replaces original Task 3 — time decay logic deferred)**

**Files:**
- No additional changes beyond Task 1 + 2.

Time fields (`created_at`, `updated_at`, `last_used`) are now present on all three models:
- `KnowledgeCard` — already has them ✓
- `SkillMeta` — added in Task 1 ✓
- `KnowledgeDoc` — added in Task 2 ✓

Usage (correlation weighting, decay, staleness detection) is deferred until time system design is finalized.

- [ ] **Step 1: Verify all three models have time fields**

```bash
python3 -c "
from core.flexible_knowledge import KnowledgeCard; print('Card:', [f for f in KnowledgeCard.__dataclass_fields__ if 'time' in f.lower() or 'used' in f.lower() or 'created' in f.lower() or 'updated' in f.lower()])
from core.skill_layer import SkillMeta; print('Skill:', [f for f in SkillMeta.__dataclass_fields__ if 'time' in f.lower() or 'used' in f.lower() or 'created' in f.lower() or 'updated' in f.lower()])
from core.knowledge.models import KnowledgeDoc; print('Doc:', [f for f in KnowledgeDoc.__dataclass_fields__ if 'time' in f.lower() or 'used' in f.lower() or 'created' in f.lower() or 'updated' in f.lower()])
"
```

Expected output showing `created_at`, `updated_at`, `last_used` on all three.

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "feat: add time fields to all models (SkillMeta, KnowledgeDoc) — not yet actively used"
```

---

### Task 4: Add domain field to modify_l2_card / modify_l3_skill

**Files:**
- Modify: `core/layers/l2/manager.py:86-97` (schema), `:118-128` (handler)
- Modify: `core/layers/l3/manager.py:70-80` (schema), `:101-111` (handler)
- Modify: `core/env/learning_env.py:693-710` (_apply_l2), `:712-726` (_apply_l3)

- [ ] **Step 1: Add domain to modify_l2_card schema**

In `_L2_CONSOLIDATION_TOOLS`, update `modify_l2_card`:

```python
{"type": "function", "function": {
    "name": "modify_l2_card",
    "description": "Modify an existing L2 card. Use content to update card text, domain to change domain assignment, or pass only quality fields for feedback.\n\nQuality fields (both range -5 to +5):\n  usefulness: +5=critical help, ... \n  misleading: +5=severely misleading, ...\n  comment: natural language quality note, max 100 chars.",
    "parameters": {"type": "object", "properties": {
        "card_id": {"type": "string", "description": "Card id to modify, e.g. card_xxxxxxxx"},
        "content": {"type": "string", "description": "Full modified card content. Omit if only recording quality feedback."},
        "domain": {"type": "string", "description": "New domain path for this card. Use to move card to a different/sub domain during split/merge."},
        "reason": {"type": "string", "description": "Reason for modification"},
        "usefulness": {"type": "integer", "description": "How useful. Range -5 to +5."},
        "misleading": {"type": "integer", "description": "How misleading. Range -5 to +5."},
        "comment": {"type": "string", "description": "Quality note, max 100 chars."},
    }, "required": ["card_id", "reason"], "additionalProperties": False},
}},
```

- [ ] **Step 2: Add domain to modify_l2_card handler**

In `_setup_l2_consolidation`, update handler:

```python
def modify_l2_card(args: dict) -> str:
    mod = {"type": "update", "target": args["card_id"], "layer": "l2",
           "content": args.get("content", ""), "reason": args["reason"]}
    if "domain" in args and args["domain"]:
        mod["domain"] = args["domain"]
    if "usefulness" in args:
        mod["usefulness"] = args["usefulness"]
    if "misleading" in args:
        mod["misleading"] = args["misleading"]
    if "comment" in args:
        mod["comment"] = args["comment"]
    agent._pending_mods.append(mod)
    return f"已记录: 修改 {args['card_id']}"
```

- [ ] **Step 3: Same for modify_l3_skill**

In `core/layers/l3/manager.py`, add `domain` property to the schema and handler with identical pattern.

- [ ] **Step 4: Update LearningEnv._apply_l2 to handle domain change**

```python
elif mod_type == "update":
    kwargs = _quality_kwargs(payload)
    result = store.modify_card(card_id, content or None, **kwargs)
    if result is None:
        raise ValueError(f"Card not found: {card_id}")
    if "domain" in payload:
        new_domain = payload["domain"]
        if new_domain and new_domain != result.domain.path:
            result.domain = Domain(new_domain, "specific")
            result.available_domains = [new_domain]
```

- [ ] **Step 5: Same for _apply_l3 domain change**

```python
elif mod_type == "update":
    kwargs = _quality_kwargs(payload)
    store.edit_skill(skill_name, content or None, **kwargs)
    if "domain" in payload:
        new_domain = payload["domain"]
        if new_domain:
            meta = store._skills.get(skill_name)
            if meta:
                meta.domain = Domain(new_domain, "specific")
                meta.available_domains = [new_domain]
```

- [ ] **Step 6: Run tests and commit**

```bash
python3 -m pytest tests/test_learning_env.py tests/test_capability.py -q
git add core/layers/l2/manager.py core/layers/l3/manager.py core/env/learning_env.py
git commit -m "feat: add domain field to modify_l2_card/modify_l3_skill tools"
```

---

### Task 5: DomainRegistry — embedding vectors + correlation + deprecate/merge

**Files:**
- Modify: `core/domain_registry.py`

**Correlation algorithm (deterministic, no Agent involved):**

```
domain_text = description + " | " + " ".join(所有L2卡片content) + " | " + " ".join(所有L3技能description)
embedding_vector = embeddinggemma.encode(domain_text)  # 缓存到 DomainNode
correlation(a, b) = 0.5 × cosine(emb_a, emb_b) + 0.5 × jaccard(reverse_index共引)
```

Embedding vector 只在该域 L2/L3 条目变更时重算（add_card/create_skill/modify_card/edit_skill → 标记 dirty → 下次 consolidation 或 dispatch 时重算）。

- [ ] **Step 1: Add embedding_vector to DomainNode**

```python
@dataclass
class DomainNode:
    path: str
    parent: str | None
    description: str
    correlations: dict[str, float] = field(default_factory=dict)
    relations: str = ""
    embedding_vector: list[float] | None = None  # cached
```

- [ ] **Step 2: Add compute_embedding method to DomainRegistry**

```python
def compute_embedding(self, path: str, content_getter=None) -> bool:
    """Compute and cache embedding vector for a domain.
    
    content_getter(layer, domain) -> list[str] of item contents.
    Returns True if embedding was computed, False if no content available.
    """
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
        from vendor.txtai_core.embeddings import HFVectors
        model = HFVectors("C:/Users/micha/PycharmProjects/cognitive-agent/embeddinggemma")
        vec = model.encode(text)[0]
        import numpy as np
        v = np.array(vec)
        v = v / (np.linalg.norm(v) + 1e-8)
        node.embedding_vector = v.tolist()
        return True
    except Exception:
        return False
```

- [ ] **Step 3: Add compute_correlation method**

```python
def compute_correlation(self, a: str, b: str) -> float:
    """Compute correlation between two domains.
    
    50% embedding cosine similarity + 50% reverse_index Jaccard overlap.
    Embeddings must already be fresh (caller ensures compute_embedding was
    run for both domains before calling this).
    
    Returns float in [0, 1].
    """
    node_a = self._nodes.get(a)
    node_b = self._nodes.get(b)
    if not node_a or not node_b:
        return 0.0

    emb_score = 0.0
    if node_a.embedding_vector and node_b.embedding_vector:
        import numpy as np
        va = np.array(node_a.embedding_vector)
        vb = np.array(node_b.embedding_vector)
        emb_score = float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-8))
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
```

- [ ] **Step 4: Add refresh_embeddings_for and compute_all_correlations**

Called at the end of each learning round, after all L2/L3 modifications are applied:

```python
def refresh_embeddings_for(self, domains: list[str],
                           content_getter=None) -> int:
    """Recompute embeddings for given domains. Returns count of successful recomputes."""
    count = 0
    for path in domains:
        if self.compute_embedding(path, content_getter):
            count += 1
    return count


def compute_all_correlations(self) -> int:
    """Recompute all domain-to-domain correlations.
    Assumes embeddings are already fresh.
    Returns count of correlation pairs updated.
    """
    paths = list(self._nodes.keys())
    count = 0
    for i, a in enumerate(paths):
        for b in paths[i+1:]:
            corr = self.compute_correlation(a, b)
            self.update_correlation(a, b, corr)
            count += 1
    return count
```

- [ ] **Step 4: Add deprecate_domain with orphan check**

```python
def deprecate_domain(self, path: str) -> int:
    """Remove a domain node. Fails if items still reference this domain as their only domain.
    
    Returns 0 on success.
    """
    node = self._nodes.get(path)
    if node is None:
        raise ValueError(f"Domain not found: {path}")

    orphaned = 0
    for layer in ("l2", "l3", "tool"):
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
    self._nodes.pop(path, None)
    return 0
```

- [ ] **Step 5: Add merge_domain with auto-embedding**

```python
def merge_domain(self, source: str, target: str,
                 content_getter=None) -> dict:
    """Merge source domain into target: move all items, merge correlations, deprecate source.
    Auto-computes target embedding after merge.
    
    Returns: {"moved_items": int}
    """
    if source not in self._nodes:
        raise ValueError(f"Source domain not found: {source}")
    if target not in self._nodes:
        raise ValueError(f"Target domain not found: {target}")

    source_node = self._nodes[source]
    target_node = self._nodes[target]

    moved = 0
    for layer in ("l2", "l3"):
        idx = self._reverse_index.get(layer, {})
        items = idx.pop(source, [])
        target_items = idx.setdefault(target, [])
        for item_id in items:
            if item_id not in target_items:
                target_items.append(item_id)
                moved += 1

    # Merge correlations
    for k, v in source_node.correlations.items():
        if k in target_node.correlations:
            target_node.correlations[k] = max(target_node.correlations[k], v)
        else:
            target_node.correlations[k] = v
    target_node.correlations.pop(source, None)
    target_node.correlations.pop(target, None)

    # Update other nodes' correlations pointing to source → target
    for n in self._nodes.values():
        if source in n.correlations:
            v = n.correlations.pop(source)
            n.correlations[target] = max(n.correlations.get(target, 0), v)

    # Deprecate source
    self.deprecate_domain(source)

    # Auto-recompute target embedding
    if content_getter:
        self.compute_embedding(target, content_getter)

    return {"moved_items": moved}
```

- [ ] **Step 7: LearningEnv._apply_parsed_mods — auto refresh embeddings after round**

In `LearningEnv._apply_parsed_mods()`, after all modifications are applied and before `self._done = True`, collect all affected domains and refresh embeddings + correlations:

```python
# In _apply_parsed_mods, after the for-loop over layers:
if not self._dry_run:
    affected_domains: set[str] = set()
    for layer_key in ("l1", "l2", "l3"):
        mods = parsed.get(f"{layer_key}_modifications", [])
        for mod in mods:
            # Collect domains from create/update/deprecate
            domain = mod.get("domain")
            if domain:
                affected_domains.add(domain)
    if affected_domains and self._registry and content_getter:
        self._registry.refresh_embeddings_for(
            list(affected_domains), content_getter)
        self._registry.compute_all_correlations()
```

Note: `content_getter` needs to be available. Pass it to LearningEnv constructor or from knowledge_stores.

- [ ] **Step 8: Run tests and commit**

```bash
python3 -m pytest tests/ -q -k "domain or knowledge"
git add core/domain_registry.py core/flexible_knowledge.py core/skill_layer.py
git commit -m "feat: embedding vectors + 50/50 correlation + deprecate/merge on DomainRegistry"
```

---

### Task 6: Consolidation tools for domain management

**Files:**
- Modify: `core/layers/l0_5_1/manager.py` (L1Agent consolidation tools + L0_5_1Manager)

- [ ] **Step 1: Add query_domain tool**

```python
# In _L1_CONSOLIDATION_TOOLS:
{"type": "function", "function": {
    "name": "query_domain",
    "description": "List all L2 cards and L3 skills in a domain. Use to inspect domain contents before splitting or merging.",
    "parameters": {"type": "object", "properties": {
        "domain": {"type": "string", "description": "Domain path to query, e.g. 'game/doudizhu'"},
    }, "required": ["domain"], "additionalProperties": False},
}},
```

Handler in `_setup_l1_consolidation`:
```python
def query_domain(args: dict) -> str:
    domain = args["domain"]
    if agent._registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    l2_ids = agent._registry._reverse_index.get("l2", {}).get(domain, [])
    l3_ids = agent._registry._reverse_index.get("l3", {}).get(domain, [])
    # Get card/skill details from knowledge stores
    cards = []
    for c in agent._cards_store.cards if hasattr(agent, '_cards_store') else []:
        if c.id in l2_ids:
            cards.append({"id": c.id, "content": c.content[:200],
                          "usefulness": c.usefulness, "last_used": str(c.last_used)[:10]})
    skills = []
    for name, m in (agent._skills_store._skills.items() if hasattr(agent, '_skills_store') else {}):
        if name in l3_ids:
            skills.append({"name": name, "description": m.description,
                           "usefulness": m.usefulness, "last_used": str(m.last_used)[:10]})
    return json.dumps({
        "domain": domain,
        "l2_cards": cards,
        "l3_skills": skills,
    }, ensure_ascii=False, default=str)
```

Wait — L1Agent doesn't have direct access to `_cards_store` or `_skills_store`. The manager has them. Need to pass them or use a different approach.

The manager (`L0_5_1Manager`) has `self._knowledge` for FlexibleKnowledge (L2) but not directly for SkillLayer. Let me check... Actually, in chain_factory, the chain levels are built with `phil, fk, sl` (Philosophy, FlexibleKnowledge, SkillLayer). L0_5_1Manager takes `philosophy` and `domain_registry`. It does NOT have access to `fk` or `sl`.

The simplest fix: pass `fk` and `sl` to L1Agent (or at least to the DictInjector handler via closure).

Better approach: the `query_domain` handler can be defined in L0_5_1Manager.query() where `self` has access to both `self._registry` AND `self._chain` (or we pass additional stores).

Actually, the cleanest: store knowledge stores on L0_5_1Manager. Currently it only has `_philosophy` and `_registry`. Add `_fk` and `_sl` fields, then the agent's consolidation handler can access them via a closure.

Let me revise — in L0_5_1Manager.__init__, save knowledge stores, and in query(), when setting up consolidation, pass them to the agent.

Actually, even simpler: L1Agent already takes `philosophy` and `domain_registry`. Add optional `knowledge_stores` dict.

Let me redesign:

```python
class L1Agent(LayerAgent):
    def __init__(self, llm_client, philosophy, domain_registry=None,
                 knowledge_stores: dict | None = None):
        super().__init__(llm_client, logger)
        self._philosophy = philosophy
        self._registry = domain_registry
        self._l2_store = knowledge_stores.get("l2") if knowledge_stores else None
        self._l3_store = knowledge_stores.get("l3") if knowledge_stores else None
```

Then the handler can use `agent._l2_store` and `agent._l3_store`.

Actually, let me keep this simpler. The query_domain handler can work without accessing stores directly — it queries the domain from registry which has the reverse_index. But it still needs content for listing. Let me just leave content listing to the DictInjector handler which has access to the stores via closure.

Let me restructure. The handler in `_setup_l1_consolidation` can capture references:

```python
def query_domain(args: dict) -> str:
    domain = args["domain"]
    if agent._registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    l2_ids = set(agent._registry._reverse_index.get("l2", {}).get(domain, []))
    l3_ids = set(agent._registry._reverse_index.get("l3", {}).get(domain, []))
    cards = []
    if agent._l2_store:
        for c in agent._l2_store.cards:
            if c.id in l2_ids:
                cards.append({"id": c.id, "content": c.content[:150],
                              "usefulness": c.usefulness, "last_used": str(c.last_used.isoformat())[:10]})
    skills = []
    if agent._l3_store:
        for name, m in agent._l3_store._skills.items():
            if name in l3_ids:
                skills.append({"name": name, "description": m.description[:150],
                               "usefulness": m.usefulness, "last_used": str(m.last_used.isoformat())[:10]})
    return json.dumps({"domain": domain, "l2_cards": cards, "l3_skills": skills},
                      ensure_ascii=False, default=str)
```

This works. Let me keep this approach.

- [ ] **Step 2: Add deprecate_domain tool**

```python
# In _L1_CONSOLIDATION_TOOLS:
{"type": "function", "function": {
    "name": "deprecate_domain",
    "description": "Remove a domain. Before calling, ensure all L2/L3 items have been migrated to other domains. Will fail if items still reference this domain.",
    "parameters": {"type": "object", "properties": {
        "domain": {"type": "string", "description": "Domain path to deprecate"},
        "reason": {"type": "string", "description": "Why this domain is being removed"},
    }, "required": ["domain", "reason"], "additionalProperties": False},
}},
```

Handler:
```python
def deprecate_domain(args: dict) -> str:
    domain = args["domain"]
    if agent._registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    try:
        removed = agent._registry.deprecate_domain(domain)
        return json.dumps({"success": True, "message": f"Domain '{domain}' removed, {removed} orphaned items cleaned"})
    except ValueError as e:
        return json.dumps({"error": str(e)})
```

- [ ] **Step 3: Add merge_domain tool**

```python
# In _L1_CONSOLIDATION_TOOLS:
{"type": "function", "function": {
    "name": "merge_domain",
    "description": "Merge source domain into target: moves all items, merges correlations, deprecates source. One-click operation — Agent only provides two domain names.",
    "parameters": {"type": "object", "properties": {
        "source": {"type": "string", "description": "Domain to merge FROM (will be removed)"},
        "target": {"type": "string", "description": "Domain to merge INTO (survives)"},
        "reason": {"type": "string", "description": "Why merging"},
    }, "required": ["source", "target", "reason"], "additionalProperties": False},
}},
```

Handler:
```python
def merge_domain(args: dict) -> str:
    source = args["source"]
    target = args["target"]
    if agent._registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    try:
        result = agent._registry.merge_domain(source, target)
        return json.dumps({"success": True, "message": f"Merged '{source}' → '{target}', {result['moved_items']} items moved"})
    except ValueError as e:
        return json.dumps({"error": str(e)})
```

- [ ] **Step 4: Enhance create_domain to require initial content**

Update create_domain schema to add `initial_cards` and `initial_skills`:

```python
{"type": "function", "function": {
    "name": "create_domain",
    "description": "Create a new domain. Must provide at least one L2 card or L3 skill as initial content — empty domains are not allowed.",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "Domain path, e.g. 'interaction'"},
        "parent": {"type": "string", "description": "Parent domain. Default: 'general'."},
        "description": {"type": "string", "description": "Brief description (1-2 sentences)"},
        "relations": {"type": "string", "description": "Related domains or notes. Optional."},
        "initial_cards": {
            "type": "array", "items": {
                "type": "object", "properties": {
                    "content": {"type": "string"},
                    "domain": {"type": "string"},
                }, "required": ["content"]
            },
            "description": "Initial L2 knowledge cards for this domain"
        },
        "initial_skills": {
            "type": "array", "items": {
                "type": "object", "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                    "domain": {"type": "string"},
                }, "required": ["name", "content"]
            },
            "description": "Initial L3 skills for this domain"
        },
    }, "required": ["path", "description"], "additionalProperties": False},
}},
```

Handler:
```python
def create_domain(args: dict) -> str:
    path = args.get("path", "")
    parent = args.get("parent", "general")
    description = args.get("description", "")
    relations = args.get("relations", "")
    initial_cards = args.get("initial_cards", [])
    initial_skills = args.get("initial_skills", [])
    if not path or not description:
        return json.dumps({"error": "path and description are required"})
    if not initial_cards and not initial_skills:
        return json.dumps({"error": "Domain must have at least one initial card or skill. Empty domains are not allowed."})
    if agent._registry is None:
        return json.dumps({"error": "DomainRegistry not connected"})
    try:
        agent._registry.add_node(path, parent, description, {}, relations)
        created_cards = 0
        if agent._l2_store:
            from core.task import Domain
            for card_data in initial_cards:
                card_domain = card_data.get("domain", path)
                agent._l2_store.add_card(
                    content=card_data["content"],
                    domain=Domain(card_domain, "specific"),
                    source="learning_env",
                )
                created_cards += 1
        created_skills = 0
        if agent._l3_store:
            from core.task import Domain
            for skill_data in initial_skills:
                skill_domain = skill_data.get("domain", path)
                agent._l3_store.create_skill(
                    name=skill_data["name"],
                    content=skill_data["content"],
                    domain=Domain(skill_domain, "specific"),
                    created_by="learning_env",
                )
                created_skills += 1
        return json.dumps({
            "success": True,
            "message": f"Domain '{path}' created under '{parent}'. Cards: {created_cards}, Skills: {created_skills}",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})
```

- [ ] **Step 5: Update L1Agent.__init__ to accept knowledge stores**

```python
def __init__(self, llm_client, philosophy, domain_registry=None,
             knowledge_stores: dict | None = None):
    super().__init__(llm_client, logger)
    self._philosophy = philosophy
    self._registry = domain_registry
    stores = knowledge_stores or {}
    self._l2_store = stores.get("l2")
    self._l3_store = stores.get("l3")
```

- [ ] **Step 6: Update L0_5_1Manager to pass knowledge stores**

```python
# In __init__:
self._agent = L1Agent(auxiliary_llm, philosophy, domain_registry,
                      knowledge_stores={"l2": self._knowledge.get("l2"),
                                        "l3": self._knowledge.get("l3")}) if auxiliary_llm else None
```

Wait — L0_5_1Manager doesn't currently have `self._knowledge`. Let me check... No, only L2Manager has `self._knowledge`. The chain is built in chain_factory. Let me check how L0_5_1Manager is constructed.

Actually, L0_5_1Manager receives `philosophy` and `domain_registry`. The knowledge stores are passed separately. I need to add them to the constructor.

Let me add `knowledge_stores` parameter to L0_5_1Manager.__init__:

```python
def __init__(self, meta_driver, philosophy, auxiliary_llm=None,
             downstream: LayerManager | None = None,
             upward=None, downward=None,
             domain_registry=None, max_rounds=3,
             knowledge_stores: dict | None = None):
    ...
    self._knowledge_stores = knowledge_stores or {}
    self._agent = L1Agent(auxiliary_llm, philosophy, domain_registry,
                          knowledge_stores=self._knowledge_stores) if auxiliary_llm else None
```

And in chain_factory, pass `{"l2": fk, "l3": sl}` to L0_5_1Manager.

- [ ] **Step 7: Update DictInjector, register all 4 new tools**

In `_setup_l1_consolidation`:
```python
self._injector = DictInjector({
    "create_domain": create_domain,
    "query_domain": query_domain,
    "deprecate_domain": deprecate_domain,
    "merge_domain": merge_domain,
    "deprecate_l1_rule": deprecate_l1_rule,
    "create_l1_rule": create_l1_rule,
    "modify_l1_rule": modify_l1_rule,
})
```

- [ ] **Step 8: Also allow L2 consolidation to call these**

Per user request: `query_domain` available to L1/L2/L3, `deprecate_domain`/`merge_domain`/`create_domain` to L1/L2.

For L2: add the same tools to `_L2_CONSOLIDATION_TOOLS` + `_setup_l2_consolidation`.

But wait — L2Agent doesn't have access to domain_registry or knowledge stores. Need to pass them similarly.

For now, since L2 consolidation is a separate agent, I'll add the same pattern: pass `knowledge_stores` and `domain_registry` to L2Agent.

Actually, L2Agent already receives `knowledge` (FlexibleKnowledge) and `domain_registry` in its constructor. Let me check:

```python
class L2Agent(LayerAgent):
    def __init__(self, llm_client, knowledge, domain_nodes=None, domain_registry=None):
```

It has `self._knowledge` and `self._registry`. But it doesn't have L3 store. Let me add `knowledge_stores` to L2Agent too.

Actually, for scope control, let me add tools only to L1 for now. L2 getting domain tools is a future addition. The user said "L1 L2" for deprecate/merge/create and "L1 L2 L3" for query. But the consolidation tools live in the layer-specific managers. Adding them to L2 requires duplicating handlers.

For now, let me add all 4 tools to L1 only. The user can request L2/L3 additions later if needed.

Wait, re-reading: "query_domain L1 L2 L3都行 deprecate_domain / merge_domain L1 L2 此外create domain也是L1 L2"

OK, they want these tools available to these layers. But since these are consolidation tools (DictInjector), they're layer-specific. Adding to L1 is the primary case. L2/L3 would need separate implementations.

Let me focus on L1 for now and note L2/L3 as follow-up.

- [ ] **Step 9: Validate constraint: deprecate_domain checks for orphaned items**

Update `deprecate_domain` in DomainRegistry:

```python
def deprecate_domain(self, path: str) -> int:
    """Remove a domain node. Fails if items still reference this domain.
    Returns count of items that would be orphaned (0 = safe to deprecate).
    """
    node = self._nodes.get(path)
    if node is None:
        raise ValueError(f"Domain not found: {path}")

    # Check for items still referencing this domain
    orphaned = 0
    for layer in ("l2", "l3", "tool"):
        idx = self._reverse_index.get(layer, {})
        items_in_domain = set(idx.get(path, []))
        if not items_in_domain:
            continue
        # Check if any of these items are ONLY in this domain
        for layer2, domains in self._reverse_index.items():
            for domain_name, item_list in domains.items():
                if domain_name != path:
                    items_in_domain -= set(item_list)
        orphaned += len(items_in_domain)

    if orphaned > 0:
        raise ValueError(
            f"Domain '{path}' still has {orphaned} items with no other domain. "
            f"Migrate items to another domain before deprecating."
        )

    # Remove from reverse_index
    for layer in ("l2", "l3", "tool"):
        self._reverse_index.get(layer, {}).pop(path, None)

    # Remove node
    self._nodes.pop(path, None)
    return 0
```

- [ ] **Step 10: Run tests and commit**

```bash
python3 -m pytest tests/test_capability.py -q
git add core/layers/l0_5_1/manager.py core/layers/l2/manager.py core/domain_registry.py core/chain_factory.py
git commit -m "feat: add query_domain, deprecate_domain, merge_domain, enhanced create_domain tools"
```

---

### Task 7: Wire chain_factory with knowledge_stores and content_getter

**Files:**
- Modify: `core/chain_factory.py`

- [ ] **Step 1: Pass knowledge_stores to L0_5_1Manager**

In `build_chain()`, where L0_5_1Manager is constructed:
```python
knowledge_stores = {"l2": fk, "l3": sl}
l0_5_1 = L0_5_1Manager(meta_driver, philosophy, auxiliary_llm=auxiliary_llm,
                       domain_registry=domain_registry,
                       knowledge_stores=knowledge_stores)
```

Update `L0_5_1Manager.__init__` to accept and store `knowledge_stores`:
```python
def __init__(self, meta_driver, philosophy, auxiliary_llm=None,
             downstream=None, upward=None, downward=None,
             domain_registry=None, max_rounds=3,
             knowledge_stores: dict | None = None):
    ...
    self._knowledge_stores = knowledge_stores or {}
    self._agent = L1Agent(auxiliary_llm, philosophy, domain_registry,
                          knowledge_stores=self._knowledge_stores) if auxiliary_llm else None
```

- [ ] **Step 2: Wire content_getter for auto-correlation and embedding**

Provide a `content_getter` closure for DomainRegistry operations:
```python
def _make_content_getter(fk, sl):
    def getter(layer: str, domain: str) -> list[str]:
        if layer == "l2":
            return [c.content for c in fk.cards if domain in c.available_domains]
        elif layer == "l3":
            return [m.description for n, m in sl._skills.items()
                    if domain in m.available_domains]
        return []
    return getter
```

Call `reg.compute_all_correlations(content_getter)` during consolidation trigger in LearningEnv or chain initialization (one-time startup seed). On each new consolidation, correlation auto-updates because `mark_dirty` triggers recompute.

- [ ] **Step 3: Commit**

```bash
git add core/chain_factory.py core/layers/l0_5_1/manager.py
git commit -m "feat: wire knowledge_stores and content_getter into chain factory"
```

---

### Task 8: Domain health report in consolidation

**Files:**
- Modify: `core/env/threshold_scorer.py`
- Modify: `core/env/learning_env.py:342-531` (build_consolidation_task)

- [ ] **Step 1: Add domain_health_report to ThresholdScorer**

```python
def domain_health_report(self, registry, l2_store, l3_store) -> str:
    """Build a domain health report for consolidation task meta."""
    lines = ["### Domain Health Report", ""]
    for node in registry.list_all():
        path = node.path
        l2_count = len(registry._reverse_index.get("l2", {}).get(path, []))
        l3_count = len(registry._reverse_index.get("l3", {}).get(path, []))
        corr = node.correlations
        status = []
        if l2_count >= 25:
            status.append("L2_OVER_LIMIT")
        if l3_count >= 20:
            status.append("L3_OVER_LIMIT")
        if not status:
            status.append("OK")
        corr_str = ", ".join(f"{k}={v:.2f}" for k, v in sorted(corr.items()))
        lines.append(f"| {path} | {l2_count} | {l3_count} | {', '.join(status)} | {corr_str} |")
    return "\n".join(lines)
```

- [ ] **Step 2: Inject health report into build_consolidation_task meta**

In `LearningEnv.build_consolidation_task()`, after building meta, append:
```python
if self._registry:
    health = self._scorer.domain_health_report(self._registry,
                                                self._knowledge.get("l2"),
                                                self._knowledge.get("l3"))
    meta += f"\n\n{health}"
```

- [ ] **Step 3: Build merge candidates section**

Add to health report:
```
### Merge Candidates
| source | target | correlation | source_cards | target_cards | suggestion |
```

Populated from correlation data: if corr > 0.7 and both domains have < 10 cards, suggest merge.

- [ ] **Step 4: Commit**

```bash
git add core/env/threshold_scorer.py core/env/learning_env.py
git commit -m "feat: domain health report + merge candidates in consolidation task"
```

---

### Task 9: End-to-end integration test

**Files:**
- Create: `scripts/test_domain_optimization_e2e.py`

- [ ] **Step 1: Write E2E test**

Integration test that:
1. Seeds game/doudizhu with 30 cards (triggers split)
2. Creates game/doudizhu_v2 with similar content (triggers merge)
3. Runs consolidation
4. Verifies Agent sees health report and can take action

```python
"""E2E domain optimization test."""
from __future__ import annotations
import json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def main():
    from core.env_loader import load_env
    load_env(PROJECT_ROOT)

    from core.domain_registry import DomainRegistry
    reg = DomainRegistry()

    # Seed domains
    reg.add_node("game/doudizhu", "game", "斗地主",
                 {"game/leduc": 0.6}, "")
    reg.add_node("game/doudizhu_v2", "game", "斗地主变体",
                 {"game/doudizhu": 0.85}, "高度重叠")

    # Test merge
    result = reg.merge_domain("game/doudizhu_v2", "game/doudizhu")
    assert result["moved_items"] == 0  # no items yet
    assert "game/doudizhu_v2" not in reg._nodes
    print("PASS: merge_domain removes source node")

    # Test deprecate with orphaned items
    from core.task import Domain
    from core.flexible_knowledge import FlexibleKnowledge
    fk = FlexibleKnowledge(Path("data/layers/knowledge"),
                           Path("data/layers/knowledge/l2_index.json"),
                           domain_registry=reg)
    fk.add_card("test card", Domain("game/doudizhu", "specific"))
    try:
        reg.deprecate_domain("game/doudizhu")
        print("FAIL: should have raised")
    except ValueError as e:
        print(f"PASS: deprecate blocks orphaned items: {e}")

    # Clean up
    fk.remove_card(fk.cards[0].id)
    reg.deprecate_domain("game/doudizhu")
    print("PASS: deprecate succeeds after item removal")

    print("\nAll domain optimization tests pass!")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run and commit**

```bash
python3 scripts/test_domain_optimization_e2e.py
git add scripts/test_domain_optimization_e2e.py
git commit -m "test: domain optimization E2E test (merge, deprecate guard)"
```

---

### Task 10: Final test run + MAINTAIN.md update

- [ ] **Step 1: Full test suite**

```bash
python3 -m pytest tests/ -q
```

- [ ] **Step 2: Update MAINTAIN.md**

Add time system section, domain tool section, correlation section.

- [ ] **Step 3: Commit**

```bash
git add MAINTAIN.md
git commit -m "docs: update MAINTAIN.md with domain optimization v2"
```
