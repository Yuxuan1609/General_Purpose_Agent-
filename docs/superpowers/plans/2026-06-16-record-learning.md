# Record Learning + Tool Registry Unification

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agent-driven learning proposal (record_learning) with RoundTree context + unified tool filtering per-context.

**Architecture:** RecordLearning replaces Executor auto-pending. Agent decides when to learn. Sub-agent fills L2/L3 details from RoundTree. ToolRegistry unified — AgentContext filters tools by name, replacing dual DictInjector/allowlist paths.

**Tech Stack:** Python 3.10+, dataclasses, deque, json

---

## File Map

| File | Role | Change |
|------|------|--------|
| `core/agent_context.py` | AgentContext — tool allow/deny + resolve | Create |
| `core/round_tree.py` | DecisionNode + RoundHistory queue | Create |
| `core/tools/record_learning_tool.py` | record_learning tool handler + LearningRecordSubAgent | Create |
| `core/types.py` | Add DecisionNode type | Modify |
| `core/layers/l0_5_1/manager.py` | Build DecisionNode after L1 done; L1 prompt + record_learning guidance | Modify |
| `core/layers/l2/manager.py` | Build DecisionNode after L2 done | Modify |
| `core/layers/l3/manager.py` | Build DecisionNode after L3 done | Modify |
| `core/layers/base.py` | Inject AgentContext into _call_llm / _get_tools | Modify |
| `core/executor.py` | Remove _write_pending auto-write | Modify |
| `core/chain_factory.py` | Wire AgentContext + RoundHistory | Modify |
| `core/tools/__init__.py` | Register record_learning | Modify |
| `config/tools.yaml` | Add record_learning entry | Modify |
| `scripts/test_record_learning.py` | Integration test | Create |

---

### Task 1: DecisionNode + RoundHistory

**Files:**
- Create: `core/round_tree.py`

```python
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
```

- [ ] **Step 1: Test**

```bash
python3 -c "from core.round_tree import RoundHistory, DecisionNode; h=RoundHistory(3); h.push(DecisionNode('l0_5_1','q','r','x')); assert len(h.snapshot())==1; print('PASS')"
```

- [ ] **Commit**: `git add core/round_tree.py && git commit -m "feat: DecisionNode + RoundHistory queue"`

---

### Task 2: Populate RoundTree in layer managers

**Files:** `core/layers/l0_5_1/manager.py`, `core/layers/l2/manager.py`, `core/layers/l3/manager.py`

In each manager's `query()`, after the layer's decision is made, build its DecisionNode.

- [ ] **Step 1: L0_5_1Manager — build L1 node + store child pointers**

In `L0_5_1Manager.query()`, after L1 decides (line ~522 where `self._l1_notify` is set):

```python
# Build L1 DecisionNode
l1_node = DecisionNode(
    layer="l0_5_1",
    query=meta,
    result=self._l1_notify.get("result", ""),
    reasoning=self._l1_notify.get("reasoning", ""),
)

# Attach L2 history as children
for h in self._l2_history:
    l2_data = h.get("l2_reply", {})
    l2_node = DecisionNode(
        layer="l2",
        query=h.get("query", ""),
        result=str(l2_data.get("reply", "")),
        reasoning=str(l2_data.get("reasoning", "")),
    )
    # L2's children (L3) are stored in l2_data if cascade was triggered
    l3_data = l2_data.get("_l3_children", [])
    for l3 in l3_data:
        l2_node.children.append(DecisionNode(
            layer="l3",
            query=l3.get("task", ""),
            result=l3.get("result", ""),
        ))
    l1_node.children.append(l2_node)

# Push to global history
from core.round_tree import get_round_history
get_round_history().push(l1_node)
self._l2_history.clear()
```

Add a global singleton to round_tree.py:
```python
_history: RoundHistory | None = None

def get_round_history() -> RoundHistory:
    global _history
    if _history is None:
        _history = RoundHistory()
    return _history
```

- [ ] **Step 2: L2Manager — pass L3 children upward**

In `L2Manager.query()`, after L3 cascade, build L3 child nodes and store them so L1 can attach:

```python
# After cascade_consolidation_to_l3 or normal L3 queries:
if self._l3_history:
    l3_children = []
    for h in self._l3_history:
        l3_children.append({"task": h.get("query", ""), "result": h.get("reply", "")})
    self._l2_notify["_l3_children"] = l3_children
```

- [ ] **Step 3: Test**

```bash
python3 -m pytest tests/test_capability.py -q
```

- [ ] **Commit**: `git add core/round_tree.py core/layers/l0_5_1/manager.py core/layers/l2/manager.py && git commit -m "feat: populate RoundTree in layer managers"`

---

### Task 3: record_learning tool

**Files:**
- Create: `core/tools/record_learning_tool.py`

```python
"""record_learning tool — Agent proposes learnable content, sub-agent fills details."""
import json, uuid
from datetime import datetime, timezone
from pathlib import Path


PENDING_DIR = "data/learning/pending"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_record_learning(registry, pending_dir: str = PENDING_DIR):
    registry.register("record_learning", {
        "type": "function",
        "function": {
            "name": "record_learning",
            "description": (
                "记录值得学习的内容（仅L1可用）。提供 domain + learning_target + importance + reasoning。"
                "L2/L3层的详细evidence由后台自动补充后写入pending文件夹。"
                "默认异步(sync=false)，返回task_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "学习域，如'interaction'"},
                    "learning_target": {"type": "string", "description": "这次要学什么（一句话）"},
                    "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                    "reasoning": {"type": "string", "description": "为什么认为这值得学习"},
                    "sync": {"type": "boolean", "description": "true=blocking(default), false=fire-and-forget"},
                },
                "required": ["domain", "learning_target", "importance", "reasoning"],
            },
        },
    }, _record_learning_handler, toolset="core", sync=False)


def _record_learning_handler(args=None):
    d = args or {}
    domain = d.get("domain", "")
    target = d.get("learning_target", "")
    importance = d.get("importance", "medium")
    reasoning = d.get("reasoning", "")
    if not domain or not target:
        return json.dumps({"error": "domain and learning_target required"})

    from core.task_runner import get_task_runner

    def _run():
        from core.round_tree import get_round_history
        tree_data = get_round_history().all_as_dict()
        # Build the record
        record = {
            "id": uuid.uuid4().hex,
            "domain": domain,
            "learning_target": target,
            "importance": importance,
            "reasoning": reasoning,
            "l1_observations": [],
            "l2_observations": [],
            "l3_observations": [],
            "source_rounds": [],
            "round_tree": tree_data,
            "recorded_at": _now(),
        }

        # Sub-agent fills L2/L3 observations from tree
        _fill_observations(record, tree_data)

        # Write to pending dir
        pending_path = Path(PENDING_DIR) / domain.replace("/", "_")
        pending_path.mkdir(parents=True, exist_ok=True)
        filepath = pending_path / f"{record['id']}_{_now().replace(':', '-')}.json"
        content = json.dumps(record, ensure_ascii=False, indent=2, default=str)
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=pending_path, suffix=".json")
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp).replace(filepath)

        return {"status": "ok", "file": str(filepath), "id": record["id"]}

    tid = get_task_runner().submit("record_learning", _run)
    return json.dumps({"task_id": tid, "status": "running"})


def _fill_observations(record: dict, tree_data: list[dict]):
    """Sub-agent logic: scan tree for L2/L3 evidence related to learning_target."""
    # For MVP: extract basic observations from tree nodes
    for round_node in tree_data:
        for child in round_node.get("children", []):
            if child["layer"] == "l2" and child.get("result"):
                # Simple heuristic: if L2 had a non-empty result, record it
                record["l2_observations"].append({
                    "finding": f"L2处理了查询: {child['query'][:200]}",
                    "evidence": child["result"][:500],
                    "implication": ""
                })
                record["source_rounds"].append(round_node.get("round_index", "?"))
            for grandchild in child.get("children", []):
                if grandchild["layer"] == "l3" and grandchild.get("result"):
                    record["l3_observations"].append({
                        "finding": f"L3执行了: {grandchild.get('query', '')[:100]}",
                        "evidence": grandchild["result"][:500],
                        "implication": ""
                    })
```

- [ ] **Step 2: Register in __init__.py**

```python
from core.tools.record_learning_tool import register_record_learning
register_record_learning(registry)
```

- [ ] **Step 3: Add to tools.yaml**

```yaml
  record_learning:
    sync: false
    timeout: 5
    allowlist: [l1]
    fallback:
      max_retries: 0
      degrade: []
```

- [ ] **Step 4: Test**

```bash
python3 -m pytest tests/test_capability.py -q
python3 scripts/test_e2e_full.py
```

- [ ] **Commit**: `git add core/tools/record_learning_tool.py core/tools/__init__.py config/tools.yaml && git commit -m "feat: record_learning tool + sub-agent observation filler"`

---

### Task 4: AgentContext — unified tool filtering

**Files:**
- Create: `core/agent_context.py`

```python
"""AgentContext — per-environment tool allow/deny."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AgentContext:
    allowed_tools: set[str] = field(default_factory=set)
    denied_tools: set[str] = field(default_factory=set)

    def resolve(self, registry) -> list:
        """Return tool schemas visible to this context."""
        if self.allowed_tools:
            return [t.schema for t in registry.all()
                    if t.name in self.allowed_tools]
        schemas = registry.all()
        if self.denied_tools:
            return [t.schema for t in schemas
                    if t.name not in self.denied_tools]
        return [t.schema for t in schemas]
```

- [ ] **Step 2: Update LayerAgent to use AgentContext**

Add `self._context: AgentContext | None = None` to LayerAgent.

In `_get_tools(layer)`:
```python
def _get_tools(self, layer: str) -> list[dict] | None:
    if self._injector is None:
        return None
    if self._context:
        return self._context.resolve(self._injector._registry)  # via ToolRegistry
    getter = getattr(self._injector, "get_tools_for_layer", None)
    if getter is None:
        return None
    return getter(layer)
```

- [ ] **Step 3: LearningEnv sets AgentContext on agents**

In LearningEnv (or chain_factory), set context:
```python
learn_ctx = AgentContext(allowed_tools={
    "query_domain", "create_domain", "deprecate_domain", "merge_domain",
    "deprecate_l1_rule", "create_l1_rule", "modify_l1_rule",
    "deprecate_l2_card", "create_l2_card", "modify_l2_card",
    "deprecate_l3_skill", "create_l3_skill", "modify_l3_skill",
    "record_learning",
    "kb_query", "ask_user", "l1_report",
})
```

- [ ] **Step 4: Test and commit**

```bash
python3 -m pytest tests/ -q
git add core/agent_context.py core/layers/base.py core/chain_factory.py
git commit -m "feat: AgentContext — unified tool filtering by context"
```

---

### Task 5: Remove Executor auto-pending-write

**Files:** `core/executor.py`

Comment out or remove `_write_pending` call in `execute()`:

```python
# _write_pending is deprecated — Agent uses record_learning instead
# if self._learning_dir and session.get("enable_learning", True):
#     self._write_pending(obs, notify_layers, result)
```

- [ ] **Commit**: `git add core/executor.py && git commit -m "refactor: remove Executor auto-pending-write (replaced by record_learning)"`

---

### Task 6: L1 prompt — record_learning guidance

**Files:** `core/layers/l0_5_1/manager.py`

In `_build_system_prompt()`, add after tool rules:

```python
learning_guidance = (
    "## 学习记录\n"
    "如果本轮产生了值得固化的知识，调用 record_learning。判断标准:\n"
    "- 完成了复杂任务且用到了可复用策略\n"
    "- 发现 L2知识缺口 / L3技能缺口\n"
    "- 用户给出明确的正向/负向反馈\n"
    "只需提供 domain, learning_target, importance, reasoning。\n"
    "L2/L3的详细evidence会由后台自动补充。\n"
)
```

- [ ] **Commit**: `git add core/layers/l0_5_1/manager.py && git commit -m "feat: L1 prompt — record_learning guidance"`

---

### Task 7: Integration test + full run

- [ ] **Step 1: Create test**

`scripts/test_record_learning.py`:
- Push 2 rounds of DecisionNodes to RoundHistory
- Call record_learning handler
- Verify JSON file written to pending dir
- Verify content has domain, learning_target, observations
- Clean up pending file

- [ ] **Step 2: Run all**

```bash
python3 -m pytest tests/ -q
python3 scripts/test_e2e_full.py
python3 scripts/test_record_learning.py
```

- [ ] **Commit**: `git add scripts/test_record_learning.py && git commit -m "test: record_learning integration test"`
